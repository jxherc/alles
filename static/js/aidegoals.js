// standing goals: things Aide keeps working on and only speaks up about when there's news.
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { toast } from './util.js';
import { formatDateTime, t, tp } from './i18n.js';

const $ = id => document.getElementById(id);
const EVERY = () => [['hour', t('aide.goal_rhythm_hour')], ['six_hours', t('aide.goal_rhythm_six_hours')], ['day', t('aide.goal_rhythm_day')], ['week', t('aide.goal_rhythm_week')]];
const MODES = () => [['ask', t('aide.goal_mode_ask')], ['act', t('aide.goal_mode_act')]];
const WAKES = () => [['rhythm', t('aide.goal_wake_rhythm')], ['mail', t('aide.goal_wake_mail')], ['webhook', t('aide.goal_wake_webhook')]];
const EVERY_LINE = {
  hour: () => t('aide.goal_every_hour'),
  six_hours: () => t('aide.sched_every_six_hours'),
  day: () => t('aide.goal_every_day'),
  week: () => t('aide.goal_every_week'),
};
const STATES = {
  waiting: () => t('home.needs_you'),
  running: () => t('aide.goal_checking_now'),
  done: () => t('aide.goal_status_done'),
  finished: () => t('aide.goal_status_finished'),
  paused: () => t('aide.sched_state_paused'),
  active: () => t('aide.sched_state_active'),
};
let wired = false, goals = [], editing = '', every = 'day', mode = 'ask', wake = 'rhythm', poll = 0, loadTicket = 0;

function el(tag, className = '', text = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

async function ownerFetch(url, init = {}) {
  const response = await fetch(url, init);
  if (response.status !== 403) return response;
  const error = await response.clone().json().catch(() => ({}));
  if (error.code !== 'recent_auth_required') return response;
  const password = await dlgPrompt(t('aide.goal_reauth_prompt'), '', { secret: true });
  if (password == null) return response;
  const ok = await fetch('/api/auth/reauth', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password }) });
  return ok.ok ? fetch(url, init) : response;
}
async function api(url, init = {}) {
  const response = await ownerFetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || data.detail || t('aide.goal_request_failed'));
  return data;
}
const send = (method, url, body) => api(url, { method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });

function when(value) {
  return value ? formatDateTime(value, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';
}

// a state code, not text, so the 'on' check below holds in every language
function stateOf(goal) {
  if (goal.waiting) return 'waiting';
  if (goal.running) return 'running';
  if (['done', 'finished', 'paused'].includes(goal.status)) return goal.status;
  return goal.enabled ? 'active' : 'paused';
}

function choiceGroup(label, options, value, onPick) {
  const field = el('div', 'aide-schedule-field');
  field.append(el('span', '', label));
  const group = el('div', 'aide-schedule-choices');
  group.setAttribute('role', 'radiogroup');
  group.setAttribute('aria-label', label);
  for (const [key, text] of options) {
    const button = el('button', '', text);
    button.type = 'button';
    button.setAttribute('role', 'radio');
    button.dataset.value = key;
    button.setAttribute('aria-checked', String(key === value));
    button.tabIndex = key === value ? 0 : -1;
    button.addEventListener('click', () => pick(key));
    group.append(button);
  }
  function pick(key) {
    onPick(key);
    for (const button of group.children) {
      const on = button.dataset.value === key;
      button.setAttribute('aria-checked', String(on));
      button.tabIndex = on ? 0 : -1;
    }
  }
  group.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const buttons = [...group.children];
    const at = buttons.indexOf(document.activeElement);
    const next = buttons[(at + (['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1) + buttons.length) % buttons.length];
    next.focus();
    pick(next.dataset.value);
  });
  field.append(group);
  return field;
}

function closeForm() {
  $('aide-goal-form')?.remove();
  editing = '';
}

function openForm(goal = null) {
  closeForm();
  editing = goal?.id || '';
  every = goal?.every || 'day';
  mode = goal?.mode || 'ask';
  wake = goal?.wake || 'rhythm';
  const form = el('form', 'aide-schedule-form aide-goal-form');
  form.id = 'aide-goal-form';
  const head = el('div', 'aide-schedule-form-head');
  head.append(el('strong', '', goal ? t('aide.goal_edit_title') : t('aide.goal_new')));
  const cancel = el('button', '', t('common.cancel'));
  cancel.type = 'button';
  cancel.addEventListener('click', () => { closeForm(); $('aide-scheduled-new')?.focus(); });
  head.append(cancel);
  const aimLabel = el('label');
  aimLabel.append(el('span', '', t('aide.goal_aim_label')));
  const aim = el('textarea');
  aim.id = 'aide-goal-aim';
  aim.rows = 3;
  aim.maxLength = 4000;
  aim.placeholder = t('aide.goal_aim_placeholder');
  aim.value = goal?.aim || '';
  aimLabel.append(aim);
  const untilLabel = el('label');
  untilLabel.append(el('span', '', t('aide.goal_until_label')));
  const until = el('input');
  until.id = 'aide-goal-until';
  until.type = 'text';
  until.inputMode = 'numeric';
  until.placeholder = '2026-12-31';
  until.autocomplete = 'off';
  until.value = goal?.until ? goal.until.slice(0, 10) : '';
  untilLabel.append(until);
  const rhythm = choiceGroup(t('aide.goal_check_every'), EVERY(), every, key => { every = key; });
  const filterLabel = el('label');
  filterLabel.append(el('span', '', t('aide.goal_mail_filter_label')));
  const filter = el('input');
  filter.id = 'aide-goal-mail-filter';
  filter.type = 'text';
  filter.maxLength = 200;
  filter.autocomplete = 'off';
  filter.placeholder = t('aide.goal_mail_filter_placeholder');
  filter.value = goal?.mail_filter || '';
  filterLabel.append(filter);
  // sits in the field grid so it lines up with the inputs
  const hookNote = el('div', 'aide-schedule-field');
  hookNote.append(el('span'), el('p', 'aide-goal-note', goal?.has_hook
    ? t('aide.goal_hook_kept')
    : t('aide.goal_hook_after_save')));
  const showWake = () => {
    rhythm.hidden = wake !== 'rhythm';
    filterLabel.hidden = wake !== 'mail';
    hookNote.hidden = wake !== 'webhook';
  };
  const wakeGroup = choiceGroup(t('aide.goal_wake_on'), WAKES(), wake, key => { wake = key; showWake(); });
  showWake();
  const actions = el('div', 'aide-schedule-form-actions');
  const status = el('span', '', t('aide.goal_form_hint'));
  status.id = 'aide-goal-status';
  status.setAttribute('role', 'status');
  const save = el('button', '', goal ? t('aide.goal_save') : t('aide.goal_start'));
  save.type = 'submit';
  actions.append(status, save);
  form.append(
    head,
    aimLabel,
    wakeGroup,
    rhythm,
    filterLabel,
    hookNote,
    choiceGroup(t('aide.goal_mode_label'), MODES(), mode, key => { mode = key; }),
    untilLabel,
    actions,
  );
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!aim.value.trim()) { status.textContent = t('aide.goal_aim_required'); aim.focus(); return; }
    save.disabled = true;
    try {
      const body = { aim: aim.value.trim(), every, mode, wake, mail_filter: filter.value.trim(), until: until.value.trim() };
      let saved;
      if (editing) saved = await send('PATCH', `/api/jarvis/aide-goals/${editing}`, body);
      else saved = await send('POST', '/api/jarvis/aide-goals', body);
      if (!saved.hook_token && wake === 'webhook' && !saved.has_hook) {
        saved = { ...saved, ...await send('POST', `/api/jarvis/aide-goals/${saved.id}/hook`) };
        saved.hook_token = saved.token;
      }
      closeForm();
      await loadGoals();
      if (saved.hook_token) showHook(saved.id, saved.hook_token);
      else $('aide-goal-list').querySelector('.aide-goal-row strong')?.focus();
    } catch (error) {
      status.textContent = error.message;
      status.dataset.error = 'true';
      save.disabled = false;
    }
  });
  $('aide-goal-list').prepend(form);
  aim.focus();
}

// the webhook link is shown once, right after it's made; alles keeps only a hash of it
function showHook(goalId, token) {
  $('aide-goal-hook')?.remove();
  const box = el('section', 'aide-goal-hook');
  box.id = 'aide-goal-hook';
  box.setAttribute('aria-labelledby', 'aide-goal-hook-title');
  const title = el('strong', '', t('aide.goal_webhook_link'));
  title.id = 'aide-goal-hook-title';
  title.tabIndex = -1;
  const link = el('input');
  link.id = 'aide-goal-hook-url';
  link.readOnly = true;
  link.value = `${location.origin}/hooks/goal/${goalId}?token=${token}`;
  link.setAttribute('aria-label', t('aide.goal_webhook_link'));
  link.addEventListener('focus', () => link.select());
  const copy = el('button', '', t('common.copy'));
  copy.type = 'button';
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(link.value); copy.textContent = t('common.copied'); }
    catch { link.select(); copy.textContent = t('aide.goal_press_shortcut', { shortcut: '⌘C' }); }
  });
  const close = el('button', '', t('common.done'));
  close.type = 'button';
  close.addEventListener('click', () => { box.remove(); $('aide-goal-list').querySelector(`[data-goal-id="${goalId}"] strong`)?.focus(); });
  const row = el('div', 'aide-goal-hook-row');
  row.append(link, copy, close);
  box.append(
    title,
    el('p', '', t('aide.goal_hook_help')),
    row,
  );
  $('aide-goal-list').prepend(box);
  title.focus();
}

function action(label, name, goal, disabled = false) {
  const button = el('button', '', label);
  button.type = 'button';
  button.dataset.goalAction = name;
  button.dataset.goalId = goal.id;
  button.disabled = disabled;
  return button;
}

function row(goal) {
  const item = el('article', 'aide-schedule-row aide-goal-row');
  item.dataset.goalId = goal.id;
  const main = el('div', 'aide-schedule-row-main');
  const name = el('strong', '', goal.name);
  name.tabIndex = -1;
  const failed = !goal.running && goal.last_run?.state === 'failed';
  const headline = failed ? t('aide.goal_last_check_failed', { error: goal.last_run.error || t('aide.goal_could_not_finish') })
    : goal.headline || (goal.checks ? t('aide.goal_no_news') : t('aide.goal_first_check'));
  const line = el('p', 'aide-goal-headline', headline);
  if (failed) line.dataset.failed = 'true';
  main.append(name, line);
  const rhythm = EVERY_LINE[goal.every]?.() || t('aide.goal_every_other', { rhythm: `${goal.every}` });
  const woken = goal.wake === 'mail'
    ? (goal.mail_filter ? t('aide.goal_wakes_on_mail_with', { filter: goal.mail_filter }) : t('aide.goal_wakes_on_mail'))
    : goal.wake === 'webhook' ? t('aide.goal_wakes_on_webhook') : rhythm;
  const facts = [woken, tp('aide.goal_checks', goal.checks)];
  if (goal.enabled && goal.next_check_at) facts.push(t('aide.sched_next', { when: when(goal.next_check_at) }));
  if (goal.mode === 'act') facts.push(t('aide.goal_acts_alone'));
  // one line of text, so a wrap never starts with a lone dot
  main.append(el('p', 'aide-goal-meta', facts.join(' · ')));
  if (goal.notes || goal.last_run?.summary) {
    const memory = el('details', 'aide-goal-memory');
    memory.append(el('summary', '', t('aide.goal_memory')));
    if (goal.notes) memory.append(el('p', '', goal.notes));
    if (goal.last_run?.summary) {
      memory.append(el('p', 'aide-goal-last-label', goal.last_checked_at
        ? t('aide.goal_last_check_at', { when: when(goal.last_checked_at) })
        : t('aide.goal_last_check')));
      memory.append(el('p', 'aide-goal-last', goal.last_run.summary));
    }
    main.append(memory);
  }
  const state = stateOf(goal);
  const badge = el('span', `aide-schedule-state ${['active', 'running', 'waiting'].includes(state) ? 'on' : ''}`, STATES[state]());
  if (goal.waiting) badge.dataset.waiting = 'true';
  const actions = el('div', 'aide-schedule-actions');
  if (goal.waiting) actions.append(action(t('aide.goal_answer'), 'answer', goal));
  actions.append(
    action(t('aide.goal_check_now'), 'run', goal, !goal.enabled || goal.running),
    action(goal.enabled ? t('common.pause') : t('common.resume'), 'toggle', goal),
    action(t('common.edit'), 'edit', goal),
    ...(goal.wake === 'webhook' ? [action(t('aide.goal_new_link'), 'hook', goal)] : []),
    action(t('common.delete'), 'delete', goal, goal.running),
  );
  item.append(main, badge, actions);
  return item;
}

function render() {
  const host = $('aide-goal-list');
  const kept = [$('aide-goal-hook'), $('aide-goal-form')].filter(Boolean);
  host.replaceChildren(...kept);
  if (!goals.length) {
    const empty = el('div', 'aide-scheduled-empty');
    empty.append(
      el('strong', '', t('aide.goal_empty_title')),
      el('p', '', t('aide.goal_empty_body')),
    );
    host.append(empty);
    return;
  }
  for (const goal of goals) host.append(row(goal));
}

export async function loadGoals() {
  const ticket = ++loadTicket;
  const data = await api('/api/jarvis/aide-goals');
  if (ticket !== loadTicket) return;
  goals = data.items || [];
  render();
  clearTimeout(poll);
  // while a check runs, follow it; otherwise the list stays still
  if (goals.some(goal => goal.running) && !$('aide-goal-list').hidden) poll = setTimeout(() => loadGoals().catch(() => {}), 4000);
}

async function onAction(event) {
  const button = event.target.closest('[data-goal-action]');
  if (!button) return;
  const goal = goals.find(item => item.id === button.dataset.goalId);
  if (!goal) return;
  const name = button.dataset.goalAction;
  if (name === 'edit') { openForm(goal); return; }
  if (name === 'answer') {
    // questions and approvals live with the run, in recent runs
    document.querySelector('[data-scheduled-tab="runs"]')?.click();
    return;
  }
  if (name === 'hook') {
    if (goal.has_hook && !await dlgConfirm(t('aide.goal_new_link_confirm'), { confirmLabel: t('aide.goal_new_link'), danger: false })) return;
    try {
      const made = await send('POST', `/api/jarvis/aide-goals/${goal.id}/hook`);
      await loadGoals();
      showHook(goal.id, made.token);
    } catch (error) { toast(error.message, 'error'); }
    return;
  }
  if (name === 'delete' && !await dlgConfirm(t('aide.goal_delete_confirm', { name: goal.name }), { confirmLabel: t('common.delete') })) return;
  button.disabled = true;
  try {
    if (name === 'run') await send('POST', `/api/jarvis/workflows/${goal.id}/runs`);
    else if (name === 'toggle') await send('PATCH', `/api/jarvis/aide-goals/${goal.id}/state`, { enabled: !goal.enabled });
    else if (name === 'delete') await send('DELETE', `/api/jarvis/aide-goals/${goal.id}`);
    await loadGoals();
    $('aide-goal-list').querySelector(`[data-goal-action="${name}"][data-goal-id="${goal.id}"]`)?.focus();
  } catch (error) {
    button.disabled = false;
    toast(error.message, 'error');
  }
}

export async function initAideGoals() {
  if (!wired) {
    wired = true;
    $('aide-goal-list').addEventListener('click', onAction);
  }
  await loadGoals();
}

export function newGoal() { openForm(); }

export function stopGoalPolling() { clearTimeout(poll); }
