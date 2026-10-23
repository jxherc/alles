// standing goals: things Aide keeps working on and only speaks up about when there's news.
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { toast } from './util.js';
import { formatDateTime } from './i18n.js';

const $ = id => document.getElementById(id);
const EVERY = [['hour', 'hour'], ['six_hours', '6 hours'], ['day', 'day'], ['week', 'week']];
const MODES = [['ask', 'ask me first'], ['act', 'just do it']];
const WAKES = [['rhythm', 'on a rhythm'], ['mail', 'new mail'], ['webhook', 'a webhook']];
const STATUS = { done: 'done', finished: 'finished', paused: 'paused' };
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
  const password = await dlgPrompt('enter your Alles password to change goals', '', { secret: true });
  if (password == null) return response;
  const ok = await fetch('/api/auth/reauth', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password }) });
  return ok.ok ? fetch(url, init) : response;
}
async function api(url, init = {}) {
  const response = await ownerFetch(url, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || data.detail || 'goal request failed');
  return data;
}
const send = (method, url, body) => api(url, { method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });

function when(value) {
  return value ? formatDateTime(value, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '';
}

function stateText(goal) {
  if (goal.waiting) return 'needs you';
  if (goal.running) return 'checking now';
  return STATUS[goal.status] || (goal.enabled ? 'active' : 'paused');
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
  head.append(el('strong', '', goal ? 'edit goal' : 'new goal'));
  const cancel = el('button', '', 'cancel');
  cancel.type = 'button';
  cancel.addEventListener('click', () => { closeForm(); $('aide-scheduled-new')?.focus(); });
  head.append(cancel);
  const aimLabel = el('label');
  aimLabel.append(el('span', '', 'what should Aide keep working on?'));
  const aim = el('textarea');
  aim.id = 'aide-goal-aim';
  aim.rows = 3;
  aim.maxLength = 4000;
  aim.placeholder = 'watch flights to lisbon in december and tell me when one is under 300 eur';
  aim.value = goal?.aim || '';
  aimLabel.append(aim);
  const untilLabel = el('label');
  untilLabel.append(el('span', '', 'stop on (optional)'));
  const until = el('input');
  until.id = 'aide-goal-until';
  until.type = 'text';
  until.inputMode = 'numeric';
  until.placeholder = '2026-12-31';
  until.autocomplete = 'off';
  until.value = goal?.until ? goal.until.slice(0, 10) : '';
  untilLabel.append(until);
  const rhythm = choiceGroup('check every', EVERY, every, key => { every = key; });
  const filterLabel = el('label');
  filterLabel.append(el('span', '', 'only mail with (optional)'));
  const filter = el('input');
  filter.id = 'aide-goal-mail-filter';
  filter.type = 'text';
  filter.maxLength = 200;
  filter.autocomplete = 'off';
  filter.placeholder = 'a sender or a word in the subject';
  filter.value = goal?.mail_filter || '';
  filterLabel.append(filter);
  // sits in the field grid so it lines up with the inputs
  const hookNote = el('div', 'aide-schedule-field');
  hookNote.append(el('span'), el('p', 'aide-goal-note', goal?.has_hook
    ? 'this goal keeps its webhook link; use "new link" on the goal to replace it.'
    : 'you get a private link after saving. anything that calls it wakes this goal.'));
  const showWake = () => {
    rhythm.hidden = wake !== 'rhythm';
    filterLabel.hidden = wake !== 'mail';
    hookNote.hidden = wake !== 'webhook';
  };
  const wakeGroup = choiceGroup('wake it on', WAKES, wake, key => { wake = key; showWake(); });
  showWake();
  const actions = el('div', 'aide-schedule-form-actions');
  const status = el('span', '', 'Aide only pings you for news, a question or an approval');
  status.id = 'aide-goal-status';
  status.setAttribute('role', 'status');
  const save = el('button', '', goal ? 'save goal' : 'start goal');
  save.type = 'submit';
  actions.append(status, save);
  form.append(
    head,
    aimLabel,
    wakeGroup,
    rhythm,
    filterLabel,
    hookNote,
    choiceGroup('when it wants to change something', MODES, mode, key => { mode = key; }),
    untilLabel,
    actions,
  );
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!aim.value.trim()) { status.textContent = 'say what the goal is'; aim.focus(); return; }
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
  const title = el('strong', '', 'webhook link');
  title.id = 'aide-goal-hook-title';
  title.tabIndex = -1;
  const link = el('input');
  link.id = 'aide-goal-hook-url';
  link.readOnly = true;
  link.value = `${location.origin}/hooks/goal/${goalId}?token=${token}`;
  link.setAttribute('aria-label', 'webhook link');
  link.addEventListener('focus', () => link.select());
  const copy = el('button', '', 'copy');
  copy.type = 'button';
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(link.value); copy.textContent = 'copied'; }
    catch { link.select(); copy.textContent = 'press ⌘C'; }
  });
  const close = el('button', '', 'done');
  close.type = 'button';
  close.addEventListener('click', () => { box.remove(); $('aide-goal-list').querySelector(`[data-goal-id="${goalId}"] strong`)?.focus(); });
  const row = el('div', 'aide-goal-hook-row');
  row.append(link, copy, close);
  box.append(
    title,
    el('p', '', 'POST to this link to wake the goal; the body becomes what woke it. it is shown only now, and anyone with it can wake this goal.'),
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
  const headline = failed ? `last check failed: ${goal.last_run.error || 'Aide could not finish it'}`
    : goal.headline || (goal.checks ? 'no news yet' : 'first check on its way');
  const line = el('p', 'aide-goal-headline', headline);
  if (failed) line.dataset.failed = 'true';
  main.append(name, line);
  const rhythm = EVERY.find(([key]) => key === goal.every)?.[1] || goal.every;
  const woken = goal.wake === 'mail' ? `wakes on new mail${goal.mail_filter ? ` with "${goal.mail_filter}"` : ''}`
    : goal.wake === 'webhook' ? 'wakes on its webhook' : `every ${rhythm}`;
  const facts = [woken, `${goal.checks} ${goal.checks === 1 ? 'check' : 'checks'}`];
  if (goal.enabled && goal.next_check_at) facts.push(`next ${when(goal.next_check_at)}`);
  if (goal.mode === 'act') facts.push('acts on its own');
  // one line of text, so a wrap never starts with a lone dot
  main.append(el('p', 'aide-goal-meta', facts.join(' · ')));
  if (goal.notes || goal.last_run?.summary) {
    const memory = el('details', 'aide-goal-memory');
    memory.append(el('summary', '', 'what it remembers'));
    if (goal.notes) memory.append(el('p', '', goal.notes));
    if (goal.last_run?.summary) {
      memory.append(el('p', 'aide-goal-last-label', `last check${goal.last_checked_at ? `, ${when(goal.last_checked_at)}` : ''}`));
      memory.append(el('p', 'aide-goal-last', goal.last_run.summary));
    }
    main.append(memory);
  }
  const state = stateText(goal);
  const badge = el('span', `aide-schedule-state ${['active', 'checking now', 'needs you'].includes(state) ? 'on' : ''}`, state);
  if (goal.waiting) badge.dataset.waiting = 'true';
  const actions = el('div', 'aide-schedule-actions');
  if (goal.waiting) actions.append(action('answer', 'answer', goal));
  actions.append(
    action('check now', 'run', goal, !goal.enabled || goal.running),
    action(goal.enabled ? 'pause' : 'resume', 'toggle', goal),
    action('edit', 'edit', goal),
    ...(goal.wake === 'webhook' ? [action('new link', 'hook', goal)] : []),
    action('delete', 'delete', goal, goal.running),
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
      el('strong', '', 'no goals yet'),
      el('p', '', 'Give Aide something to keep working on, like watching a price or keeping an inbox tidy. You can also just ask in conversation: "keep an eye on…".'),
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
    if (goal.has_hook && !await dlgConfirm('make a new webhook link? the old one stops working.', { confirmLabel: 'new link', danger: false })) return;
    try {
      const made = await send('POST', `/api/jarvis/aide-goals/${goal.id}/hook`);
      await loadGoals();
      showHook(goal.id, made.token);
    } catch (error) { toast(error.message, 'error'); }
    return;
  }
  if (name === 'delete' && !await dlgConfirm(`delete the goal "${goal.name}"? its past checks stay in recent runs.`, { confirmLabel: 'delete' })) return;
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
