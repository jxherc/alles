import { toast } from './util.js';
import { formatDateTime, resolvedTimeZone } from './i18n.js';
import { initAideNews } from './aidenews.js';

let initialized = false;
let scheduleKind = 'schedule';
let intervalUnit = 'minutes';
let selectedProject = '';
let editingWorkflowId = '';
let projects = [];
let workflows = [];
let triggersByWorkflow = new Map();
let loadSequence = 0;
const SUPPORTED_SCHEDULE_KINDS = new Set(['schedule', 'once', 'interval', 'heartbeat']);

const byId = id => document.getElementById(id);

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function safeMessage(value) {
  return String(value || 'something went wrong').replace(/jarvis/gi, 'Aide');
}

async function requestJson(url, options = {}, fetcher = fetch) {
  const response = await fetcher(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(safeMessage(typeof detail === 'string' ? detail : detail?.message || payload?.message));
  }
  return payload;
}

function jsonOptions(method, body) {
  return { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) };
}

function localZone() {
  return resolvedTimeZone();
}

function formatDate(value) {
  if (!value) return '';
  const raw = String(value).trim();
  const parsed = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`);
  if (Number.isNaN(parsed.getTime())) return '';
  return formatDateTime(parsed, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function formatWallTime(value) {
  if (!value) return '';
  const match = String(value).replace(' ', 'T').match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/,
  );
  if (!match) return '';
  const [, year, month, day, hour, minute] = match;
  const parsed = new Date(Date.UTC(+year, +month - 1, +day, +hour, +minute));
  return formatDateTime(parsed, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC',
  });
}

function projectName(id) {
  return projects.find(project => project.id === id)?.name || 'tasks';
}

function triggerSummary(trigger) {
  if (!trigger) return 'manual';
  const config = trigger.config || {};
  if (trigger.kind === 'schedule') return `daily at ${config.time || '—'}`;
  if (trigger.kind === 'once') return `once · ${formatWallTime(config.at) || config.at || '—'}`;
  if (trigger.kind === 'interval' || trigger.kind === 'heartbeat') {
    const seconds = Number(config.every_seconds || 0);
    const amount = seconds % 86400 === 0 ? `${seconds / 86400}d`
      : seconds % 3600 === 0 ? `${seconds / 3600}h`
        : `${Math.max(1, seconds / 60)}m`;
    return `${trigger.kind} · every ${amount}`;
  }
  return trigger.kind;
}

function setStatus(message = '', error = false) {
  const status = byId('aide-schedule-form-status');
  if (!status) return;
  status.textContent = message ? safeMessage(message) : '';
  status.dataset.error = error ? 'true' : 'false';
}

function renderTiming() {
  const host = byId('aide-schedule-timing');
  if (!host) return;
  host.replaceChildren();
  const label = el('label');
  const name = el('span', '', scheduleKind === 'once' ? 'date and time' : 'timing');
  label.append(name);

  if (scheduleKind === 'schedule') {
    const input = el('input');
    input.id = 'aide-schedule-value';
    input.type = 'text';
    input.inputMode = 'numeric';
    input.placeholder = '09:00';
    input.setAttribute('aria-label', 'daily time in 24 hour format');
    label.append(input);
  } else if (scheduleKind === 'once') {
    const input = el('input');
    input.id = 'aide-schedule-value';
    input.type = 'text';
    input.placeholder = '2026-07-15 09:00';
    input.setAttribute('aria-label', 'date and time');
    label.append(input);
  } else {
    const row = el('div', 'aide-schedule-interval');
    const input = el('input');
    input.id = 'aide-schedule-value';
    input.type = 'text';
    input.inputMode = 'numeric';
    input.placeholder = scheduleKind === 'heartbeat' ? '30' : '60';
    input.setAttribute('aria-label', 'repeat amount');
    const choices = el('div', 'aide-schedule-unit-choices');
    choices.setAttribute('role', 'radiogroup');
    choices.setAttribute('aria-label', 'repeat unit');
    for (const [value, text] of [['minutes', 'min'], ['hours', 'hours'], ['days', 'days']]) {
      const button = el('button', '', text);
      button.type = 'button';
      button.dataset.scheduleUnit = value;
      button.setAttribute('role', 'radio');
      button.setAttribute('aria-checked', String(intervalUnit === value));
      button.tabIndex = intervalUnit === value ? 0 : -1;
      button.addEventListener('click', () => {
        intervalUnit = value;
        choices.querySelectorAll('[data-schedule-unit]').forEach(item => {
          const selected = item.dataset.scheduleUnit === value;
          item.setAttribute('aria-checked', String(selected));
          item.tabIndex = selected ? 0 : -1;
        });
      });
      choices.append(button);
    }
    choices.addEventListener('keydown', event =>
      moveRadio(event, '[data-schedule-unit]', target => target.click()));
    row.append(input, choices);
    label.append(row);
  }
  host.append(label);
}

function setKind(kind) {
  scheduleKind = kind;
  document.querySelectorAll('[data-schedule-kind]').forEach(button => {
    const selected = button.dataset.scheduleKind === kind;
    button.setAttribute('aria-checked', String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  renderTiming();
}

function moveRadio(event, selector, choose) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
  event.preventDefault();
  const buttons = [...event.currentTarget.querySelectorAll(selector)];
  const current = buttons.indexOf(document.activeElement);
  const direction = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
  const target = buttons[(current + direction + buttons.length) % buttons.length];
  if (!target) return;
  choose(target);
  target.focus();
}

function renderProjectMenu() {
  const menu = byId('aide-schedule-project-menu');
  if (!menu) return;
  menu.replaceChildren();
  const entries = [{ id: '', name: 'tasks' }, ...projects];
  for (const project of entries) {
    const button = el('button', '', project.name);
    button.type = 'button';
    button.setAttribute('role', 'menuitemradio');
    button.setAttribute('aria-checked', String(project.id === selectedProject));
    button.dataset.projectId = project.id;
    button.addEventListener('click', () => selectProject(project.id));
    menu.append(button);
  }
}

function selectProject(id) {
  selectedProject = id || '';
  byId('aide-schedule-project').textContent = projectName(selectedProject);
  closeProjectMenu();
  renderProjectMenu();
}

function openProjectMenu() {
  const button = byId('aide-schedule-project');
  const menu = byId('aide-schedule-project-menu');
  if (!button || !menu) return;
  renderProjectMenu();
  menu.hidden = false;
  button.setAttribute('aria-expanded', 'true');
  menu.querySelector('[aria-checked="true"]')?.focus();
}

function closeProjectMenu() {
  const button = byId('aide-schedule-project');
  const menu = byId('aide-schedule-project-menu');
  if (!button || !menu) return;
  menu.hidden = true;
  button.setAttribute('aria-expanded', 'false');
}

function timingValues(trigger) {
  const config = trigger?.config || {};
  if (trigger?.kind === 'schedule') return { value: config.time || '', unit: 'minutes' };
  if (trigger?.kind === 'once') {
    const value = String(config.at || '')
      .replace('T', ' ')
      .replace(/Z$/, '')
      .replace(/(\d{2}:\d{2}):\d{2}(?:\.\d+)?$/, '$1');
    return { value, unit: 'minutes' };
  }
  const seconds = Number(config.every_seconds || 0);
  if (seconds > 0 && seconds % 86400 === 0) return { value: String(seconds / 86400), unit: 'days' };
  if (seconds > 0 && seconds % 3600 === 0) return { value: String(seconds / 3600), unit: 'hours' };
  return { value: String(Math.max(1, seconds / 60 || 1)), unit: 'minutes' };
}

function openForm(workflow = null) {
  const form = byId('aide-schedule-form');
  if (!form) return;
  form.reset();
  editingWorkflowId = workflow?.id || '';
  const trigger = workflow ? triggersByWorkflow.get(workflow.id)?.[0] : null;
  const timing = timingValues(trigger);
  intervalUnit = timing.unit;
  form.hidden = false;
  setStatus();
  byId('aide-schedule-form-title').textContent = workflow ? 'edit schedule' : 'new schedule';
  byId('aide-schedule-submit').textContent = workflow ? 'save changes' : 'save schedule';
  if (workflow) {
    byId('aide-schedule-name').value = workflow.name || '';
    byId('aide-schedule-prompt').value = workflow.prompt || workflow.purpose || '';
    selectProject(workflow.project_id || '');
  } else {
    selectProject('');
  }
  setKind(trigger?.kind || 'schedule');
  const value = byId('aide-schedule-value');
  if (value) value.value = workflow ? timing.value : '';
  byId('aide-schedule-name')?.focus();
}

function closeForm() {
  const form = byId('aide-schedule-form');
  if (!form) return;
  form.hidden = true;
  form.reset();
  editingWorkflowId = '';
  byId('aide-schedule-form-title').textContent = 'new schedule';
  byId('aide-schedule-submit').textContent = 'save schedule';
  selectProject('');
  setStatus();
}

function makeConfig() {
  const raw = byId('aide-schedule-value')?.value.trim() || '';
  if (scheduleKind === 'schedule') {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(raw)) throw new Error('use a 24-hour time like 09:00');
    return { time: raw, weekdays: [0, 1, 2, 3, 4, 5, 6] };
  }
  if (scheduleKind === 'once') {
    const value = raw.replace(' ', 'T');
    if (!/^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d$/.test(value)) {
      throw new Error('use a date and time like 2026-07-15 09:00');
    }
    return { at: value };
  }
  const amount = Number(raw);
  if (!Number.isFinite(amount) || amount <= 0) throw new Error('enter a repeat amount');
  const multiplier = intervalUnit === 'days' ? 86400 : intervalUnit === 'hours' ? 3600 : 60;
  return { every_seconds: amount * multiplier };
}

async function saveSchedule(event) {
  event.preventDefault();
  const name = byId('aide-schedule-name')?.value.trim() || '';
  const prompt = byId('aide-schedule-prompt')?.value.trim() || '';
  if (!name || !prompt) { setStatus('add a name and what Aide should do', true); return; }
  let config;
  try { config = makeConfig(); }
  catch (error) { setStatus(error.message, true); return; }

  const submit = event.currentTarget.querySelector('[type="submit"]');
  submit.disabled = true;
  setStatus('saving…');
  try {
    const url = editingWorkflowId
      ? `/api/jarvis/aide-schedules/${editingWorkflowId}`
      : '/api/jarvis/aide-schedules';
    await requestJson(url, jsonOptions(editingWorkflowId ? 'PATCH' : 'POST', {
      name, prompt, project_id: selectedProject,
      kind: scheduleKind, config, timezone: localZone(),
    }));
    closeForm();
    await loadScheduled();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    submit.disabled = false;
  }
}

function scheduleRow(workflow) {
  const trigger = triggersByWorkflow.get(workflow.id)?.[0];
  const row = el('article', 'aide-schedule-row');
  const main = el('div', 'aide-schedule-row-main');
  main.append(el('strong', '', workflow.name));
  const meta = el('div', 'aide-schedule-meta');
  meta.append(
    el('span', '', triggerSummary(trigger)),
    el('span', '', projectName(workflow.project_id)),
  );
  if (trigger?.next_run_at && workflow.enabled && trigger.enabled) {
    meta.append(el('span', '', `next ${formatDate(trigger.next_run_at)}`));
  }
  main.append(meta);

  const state = el('span', `aide-schedule-state ${workflow.enabled && trigger?.enabled ? 'on' : ''}`,
    workflow.enabled && trigger?.enabled ? 'active' : 'paused');
  const actions = el('div', 'aide-schedule-actions');
  const edit = el('button', '', 'edit');
  edit.type = 'button';
  edit.dataset.scheduleAction = 'edit';
  edit.dataset.workflowId = workflow.id;
  const toggle = el('button', '', workflow.enabled && trigger?.enabled ? 'pause' : 'resume');
  toggle.type = 'button';
  toggle.dataset.scheduleAction = 'toggle';
  toggle.dataset.workflowId = workflow.id;
  const run = el('button', '', 'run now');
  run.type = 'button';
  run.dataset.scheduleAction = 'run';
  run.dataset.workflowId = workflow.id;
  if (!workflow.enabled) run.disabled = true;
  actions.append(edit, toggle, run);
  row.append(main, state, actions);
  return row;
}

function renderSchedules() {
  const host = byId('aide-schedule-list');
  if (!host) return;
  host.replaceChildren();
  if (!workflows.length) {
    const empty = el('div', 'aide-scheduled-empty');
    empty.append(el('strong', '', 'nothing scheduled'), el('p', '', 'Add work Aide should start later or check on a rhythm.'));
    host.append(empty);
    return;
  }
  workflows.forEach(workflow => host.append(scheduleRow(workflow)));
}

function renderRuns(runs, partial = false) {
  const host = byId('aide-run-list');
  if (!host) return;
  host.replaceChildren();
  if (partial) {
    const notice = el('p', 'aide-schedule-meta', 'some recent runs could not be loaded');
    notice.setAttribute('role', 'status');
    host.append(notice);
  }
  if (!runs.length) {
    const empty = el('div', 'aide-scheduled-empty');
    empty.append(
      el('strong', '', partial ? 'recent runs unavailable' : 'no runs yet'),
      el('p', '', partial
        ? 'Schedules are still available. Try the run history again shortly.'
        : 'Finished and active background work will appear here.'),
    );
    host.append(empty);
    return;
  }
  for (const run of runs) {
    const workflow = workflows.find(item => item.id === run.workflow_id);
    const row = el('article', 'aide-run-row');
    const main = el('div', 'aide-schedule-row-main');
    main.append(el('strong', '', workflow?.name || 'Aide work'));
    const summary = run.result_summary || run.safe_error || formatDate(run.created_at);
    main.append(el('div', 'aide-schedule-meta', summary));
    const state = el('span', `aide-run-state state-${run.state}`, run.state);
    const actions = el('div', 'aide-schedule-actions');
    if (['queued', 'running'].includes(run.state)) {
      const cancel = el('button', '', 'cancel');
      cancel.type = 'button';
      cancel.dataset.runAction = 'cancel';
      cancel.dataset.runId = run.id;
      actions.append(cancel);
    } else if (['failed', 'cancelled', 'interrupted'].includes(run.state)) {
      const retry = el('button', '', 'retry');
      retry.type = 'button';
      retry.dataset.runAction = 'retry';
      retry.dataset.runId = run.id;
      actions.append(retry);
    }
    row.append(main, state, actions);
    host.append(row);
  }
}

async function loadScheduled(fetcher = fetch) {
  const sequence = ++loadSequence;
  const scheduleHost = byId('aide-schedule-list');
  if (scheduleHost) scheduleHost.textContent = 'loading…';
  try {
    const [loadedWorkflows, loadedProjects] = await Promise.all([
      requestJson('/api/jarvis/workflows', {}, fetcher),
      requestJson('/api/projects', {}, fetcher).catch(() => []),
    ]);
    if (sequence !== loadSequence) return;
    projects = loadedProjects;
    const candidates = loadedWorkflows.filter(
      workflow => workflow.deterministic_action === 'aide_handoff'
        && workflow.delivery_policy?.aide_schedule_owner === 'aide_scheduled_v1');
    const loadedTriggers = new Map(await Promise.all(candidates.map(async workflow => [
      workflow.id,
      await requestJson(`/api/jarvis/workflows/${workflow.id}/triggers`, {}, fetcher).catch(() => []),
    ])));
    if (sequence !== loadSequence) return;
    triggersByWorkflow = loadedTriggers;
    workflows = candidates.filter(workflow => {
      const triggers = triggersByWorkflow.get(workflow.id) || [];
      return triggers.length === 1 && SUPPORTED_SCHEDULE_KINDS.has(triggers[0].kind);
    });
    renderProjectMenu();
    renderSchedules();
    let runHistoryPartial = false;
    const runGroups = await Promise.all(workflows.map(workflow => requestJson(
      `/api/jarvis/runs?workflow_id=${encodeURIComponent(workflow.id)}&limit=30`,
      {},
      fetcher,
    ).catch(() => {
      runHistoryPartial = true;
      return [];
    })));
    if (sequence !== loadSequence) return;
    const runs = runGroups.flat().sort(
      (left, right) => String(right.created_at || '').localeCompare(String(left.created_at || '')),
    );
    renderRuns(runs, runHistoryPartial);
  } catch (error) {
    if (sequence === loadSequence && scheduleHost) scheduleHost.textContent = safeMessage(error.message);
    throw error;
  }
}

async function handleScheduleAction(event) {
  const button = event.target.closest('[data-schedule-action]');
  if (!button) return;
  const workflow = workflows.find(item => item.id === button.dataset.workflowId);
  const trigger = triggersByWorkflow.get(workflow?.id)?.[0];
  if (!workflow) return;
  if (button.dataset.scheduleAction === 'edit') {
    openForm(workflow);
    return;
  }
  button.disabled = true;
  try {
    if (button.dataset.scheduleAction === 'run') {
      await requestJson(`/api/jarvis/workflows/${workflow.id}/runs`, { method: 'POST' });
    } else {
      const turnOn = !(workflow.enabled && trigger?.enabled);
      await requestJson(`/api/jarvis/aide-schedules/${workflow.id}/state`,
        jsonOptions('PATCH', { enabled: turnOn }));
    }
    await loadScheduled();
  } catch (error) {
    button.disabled = false;
    toast(safeMessage(error.message), 'error');
  }
}

async function handleRunAction(event) {
  const button = event.target.closest('[data-run-action]');
  if (!button) return;
  button.disabled = true;
  try {
    await requestJson(`/api/jarvis/runs/${button.dataset.runId}/${button.dataset.runAction}`, { method: 'POST' });
    await loadScheduled();
  } catch (error) {
    button.disabled = false;
    toast(safeMessage(error.message), 'error');
  }
}

async function selectTab(button) {
  document.querySelectorAll('[data-scheduled-tab]').forEach(tab =>
    {
      const selected = tab === button;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
  const section = button.dataset.scheduledTab;
  const schedules = section === 'schedules';
  byId('aide-schedule-list').hidden = !schedules;
  byId('aide-news-workbench').hidden = section !== 'news';
  byId('aide-run-list').hidden = section !== 'runs';
  byId('aide-scheduled-new').hidden = !schedules;
  if (!schedules) closeForm();
  if (section === 'news') await initAideNews();
}

function wireOnce() {
  byId('aide-scheduled-new')?.addEventListener('click', () => openForm());
  byId('aide-schedule-cancel')?.addEventListener('click', closeForm);
  byId('aide-schedule-form')?.addEventListener('submit', saveSchedule);
  document.querySelectorAll('[data-schedule-kind]').forEach(button =>
    button.addEventListener('click', () => setKind(button.dataset.scheduleKind)));
  document.querySelector('.aide-schedule-choices')?.addEventListener('keydown', event =>
    moveRadio(event, '[data-schedule-kind]', target => setKind(target.dataset.scheduleKind)));
  document.querySelectorAll('[data-scheduled-tab]').forEach(button => {
    button.addEventListener('click', () => { selectTab(button).catch(error => toast(safeMessage(error.message), 'error')); });
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...document.querySelectorAll('[data-scheduled-tab]')];
      const target = event.key === 'Home' ? tabs[0]
        : event.key === 'End' ? tabs.at(-1)
          : tabs[(tabs.indexOf(button) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
      target.focus();
      selectTab(target).catch(error => toast(safeMessage(error.message), 'error'));
    });
  });
  byId('aide-schedule-project')?.addEventListener('click', event => {
    event.stopPropagation();
    if (byId('aide-schedule-project-menu')?.hidden) openProjectMenu();
    else closeProjectMenu();
  });
  byId('aide-schedule-project-menu')?.addEventListener('keydown', event => {
    const items = [...event.currentTarget.querySelectorAll('[role="menuitemradio"]')];
    const index = items.indexOf(document.activeElement);
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    } else if (event.key === 'Escape') {
      closeProjectMenu();
      byId('aide-schedule-project')?.focus();
    }
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.aide-schedule-project-wrap')) closeProjectMenu();
  });
  byId('aide-schedule-list')?.addEventListener('click', handleScheduleAction);
  byId('aide-run-list')?.addEventListener('click', handleRunAction);
}

export async function initAideScheduled(fetcher = fetch) {
  if (!initialized) {
    initialized = true;
    wireOnce();
    renderTiming();
  }
  await loadScheduled(fetcher);
}

export async function activateAideScheduledTab(name = 'schedules') {
  const tab = document.querySelector(`[data-scheduled-tab="${name}"]`);
  if (!tab) return false;
  await selectTab(tab);
  tab.focus();
  return true;
}
