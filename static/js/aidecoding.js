// Aide code: pi coding chats in folders on the machine that hosts alles.
// projects and their chats sit in the rail, the open chat fills the rest.
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
import { toast, mdToHtml } from './util.js';
import { wireAutosizeTextarea, autosizeTextarea } from './text_entry.js';
import { createMenuController } from './kokuen.js';

const $ = id => document.getElementById(id);
const icons = {
  back: '<path d="m14 6-6 6 6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chevron: '<path d="m8 10 4 4 4-4"/>',
  folder: '<path d="M3.5 7.5V6h6l2 2h9v10.5h-17Z"/>',
  more: '<path d="M6 12h.01M12 12h.01M18 12h.01"/>',
  up: '<path d="M12 19V5m-6 6 6-6 6 6"/>',
  stop: '<path d="M8 8h8v8H8Z"/>',
  file: '<path d="M6 3.5h8l4 4v13H6Z"/><path d="M14 3.5v4h4"/>',
  pencil: '<path d="m4 20 1-4L16 5l3 3L8 19Z"/><path d="m14 7 3 3"/>',
  plusfile: '<path d="M6 3.5h8l4 4v13H6Z"/><path d="M12 11v6m-3-3h6"/>',
  terminal: '<path d="M3.5 5.5h17v13h-17Z"/><path d="m7 10 2.5 2L7 14m4.5 0H15"/>',
  search: '<path d="M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13Zm4.5-1.5 5 5"/>',
  list: '<path d="M8 7h12M8 12h12M8 17h12M4 7h.01M4 12h.01M4 17h.01"/>',
  tool: '<path d="M14.5 6.5a4 4 0 0 0-5.4 5.1L4 16.7 7.3 20l5.1-5.1a4 4 0 0 0 5.1-5.4l-2.4 2.4-2.6-.6-.6-2.6Z"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  cross: '<path d="m6.5 6.5 11 11m0-11-11 11"/>',
  down: '<path d="M12 5v14m-6-6 6 6 6-6"/>',
};
const icon = name => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (icons[name] || '') + '</svg>';

let host = null, opening = null;
let projects = [], chats = new Map(), expanded = new Set();
let current = { projectId: '', chatId: '' };
let models = [], model = null, pi = { state: 'missing' };
let live = null, liveSeq = 0, busy = false, sending = false, installTimer = null;
let streaming = null, toolRows = new Map(), version = 0;
let menu = null, projectMenu = null, menuProject = '';
// the harness new chats use (a setting), the one the open chat runs on, and its own models
let harness = 'pi', approval = 'auto', native = [], catalogRows = [], chatHarness = '', harnessModels = null;
let harnessMenu = null;
// pi's effort: the running chat's level and the levels its model takes, and what new chats use
let thinking = { level: '', levels: [] }, thinkingPref = '', effortMenu = null, goal = '';
let piCommands = [], slashItems = [], slashIndex = 0;
const LEVELS = ['off', 'minimal', 'low', 'medium', 'high'];
const levelName = level => ({ xhigh: 'extra high' }[level] || level);
// alles's own commands; the rest come from pi (extensions, prompt templates)
const BUILTINS = [
  { name: 'new', description: 'start a new chat in this project' },
  { name: 'model', description: 'pick the model pi uses' },
  { name: 'effort', args: '[level]', description: 'how hard pi thinks before it answers' },
  { name: 'context', description: 'show what fills the context window', live: true },
  { name: 'compact', args: '[focus]', description: 'summarize the chat so far to free up context', live: true },
  { name: 'goal', args: '[goal | clear]', description: 'set a goal pi keeps working toward' },
  { name: 'stop', description: 'stop what pi is doing', live: true },
  { name: 'whats-new', description: 'show what changed lately' },
];
const harnessName = id => native.find(h => h.harness === id)?.name || catalogRows.find(h => h.id === id)?.name || id;
const isNative = id => native.some(h => h.harness === id);

async function ownerFetch(input, init = {}) {
  const response = await fetch(input, init);
  if (response.status !== 403) return response;
  const error = await response.clone().json().catch(() => ({}));
  if (error.code !== 'recent_auth_required') return response;
  const me = await fetch('/api/auth/me').then(result => result.json()).catch(() => null);
  if (me?.enabled === false) return response;
  const password = await dlgPrompt('enter your Alles password to let pi work on this machine', '', { secret: true });
  if (password == null) return response;
  const confirmed = await fetch('/api/auth/reauth', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password }),
  });
  if (!confirmed.ok) { toast('password confirmation failed', 'error'); return response; }
  return fetch(input, init);
}
async function api(path, init = {}) {
  const response = await ownerFetch(path, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.message || data.detail || 'pi request failed');
    error.code = data.code || '';
    throw error;
  }
  return data;
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) });
const chatPath = (projectId, chatId = '') => `/api/aide/code/projects/${encodeURIComponent(projectId)}/chats${chatId ? `/${encodeURIComponent(chatId)}` : ''}`;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
function setError(text = '') { const node = $('aide-code-error'); node.textContent = text; node.hidden = !text; }
function project(id = current.projectId) { return projects.find(row => row.id === id) || null; }

// ── rail ──

function piLine() {
  const line = $('aide-code-pi');
  const name = pi.name || 'pi';
  const copy = {
    installing: `installing ${name} on this machine…`,
    needs_node: pi.error || `${name} needs node 22.19 or newer on this machine`,
    failed: `${name} could not install: ${pi.error || 'unknown error'}`,
    missing: `${name} is not installed yet`,
  }[pi.state] || '';
  line.textContent = copy;
  line.hidden = !copy;
  $('aide-code-pi-retry').hidden = pi.state !== 'failed';
}

function renderRail() {
  const list = $('aide-code-projects');
  list.replaceChildren();
  if (!projects.length) {
    list.append(el('p', 'acw-rail-empty', 'add a folder on this machine to start'));
    return;
  }
  for (const row of projects) {
    const group = el('div', 'acw-project');
    const head = el('div', 'acw-project-head');
    const toggle = el('button', 'acw-project-toggle');
    toggle.type = 'button';
    toggle.dataset.projectId = row.id;
    toggle.setAttribute('aria-expanded', String(expanded.has(row.id)));
    toggle.innerHTML = icon('chevron');
    toggle.append(el('span', 'acw-project-name', row.name));
    toggle.title = row.path;
    const more = el('button', 'acw-icon acw-project-more');
    more.type = 'button';
    more.dataset.projectMenu = row.id;
    more.setAttribute('aria-label', `${row.name} actions`);
    more.setAttribute('aria-haspopup', 'menu');
    more.innerHTML = icon('more');
    head.append(toggle, more);
    group.append(head);
    if (expanded.has(row.id)) {
      const items = el('div', 'acw-chat-list');
      const fresh = el('button', 'acw-chat acw-chat-new');
      fresh.type = 'button';
      fresh.dataset.newChat = row.id;
      fresh.innerHTML = icon('plus');
      fresh.append(el('span', '', 'new chat'));
      if (current.projectId === row.id && !current.chatId) fresh.setAttribute('aria-current', 'true');
      items.append(fresh);
      for (const chat of chats.get(row.id) || []) {
        const button = el('button', 'acw-chat');
        button.type = 'button';
        button.dataset.chatId = chat.id;
        button.dataset.projectId = row.id;
        button.append(el('span', 'acw-chat-title', chat.title));
        if (chat.running) button.append(el('span', 'acw-chat-state', 'working'));
        if (current.chatId === chat.id) button.setAttribute('aria-current', 'true');
        items.append(button);
      }
      group.append(items);
    }
    list.append(group);
  }
}

async function loadProjects() {
  projects = (await api('/api/aide/code/projects')).items || [];
  if (projects.length && !expanded.size) expanded.add(projects[0].id);
  await Promise.all([...expanded].map(loadChats));
  renderRail();
}

async function loadChats(projectId) {
  try { chats.set(projectId, (await api(chatPath(projectId))).items || []); }
  catch { chats.set(projectId, []); }
}

// ── the open chat ──

function setPane(pane) { host.dataset.pane = pane; }
// rtl keeps the end of a long path (the project name) visible; the bdi stops it flipping the text
function showPath(path = '') {
  const node = $('aide-code-path');
  node.replaceChildren();
  if (path) { const bdi = document.createElement('bdi'); bdi.textContent = path; node.append(bdi); node.title = path; }
}

function showView(view) {
  $('aide-code-chat').hidden = view !== 'chat';
  $('aide-code-add-view').hidden = view !== 'add';
  $('aide-code-start').hidden = view !== 'start';
  $('aide-code-harness-view').hidden = view !== 'harnesses';
}

const TOOL_KINDS = {
  read: ['file', 'read'], edit: ['pencil', 'edit'], write: ['plusfile', 'write'], bash: ['terminal', 'run'],
  grep: ['search', 'search'], find: ['search', 'find'], ls: ['list', 'list'],
};
const parseArgs = raw => { try { return JSON.parse(raw || '{}'); } catch { return {}; } };
const since = start => { const s = Math.max(0, (Date.now() - start) / 1000); return s < 10 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`; };

function toolTitle(name, args) {
  const [, verb] = TOOL_KINDS[name] || ['tool', name || 'tool'];
  const target = args.command || args.path || args.pattern || args.file_path || '';
  return { verb, target: String(target).split('\n')[0] };
}

// lines of a and b as same / del / add, by longest common run (edits are small)
export function lineDiff(a, b) {
  const x = a.split('\n'), y = b.split('\n');
  if (x.length * y.length > 250000) return [...x.map(t => ['del', t]), ...y.map(t => ['add', t])];
  const dp = Array.from({ length: x.length + 1 }, () => new Uint32Array(y.length + 1));
  for (let i = x.length - 1; i >= 0; i--) for (let j = y.length - 1; j >= 0; j--) {
    dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const out = [];
  let i = 0, j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { out.push(['same', x[i]]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(['del', x[i++]]);
    else out.push(['add', y[j++]]);
  }
  while (i < x.length) out.push(['del', x[i++]]);
  while (j < y.length) out.push(['add', y[j++]]);
  return out;
}

// an edit as a diff: changed lines in red and green, two lines of context, long same stretches folded
function diffView(args) {
  const box = el('div', 'acw-diff');
  for (const change of (args.edits || [{ oldText: args.oldText, newText: args.newText }]).slice(0, 6)) {
    const rows = lineDiff(String(change.oldText ?? ''), String(change.newText ?? ''));
    const near = rows.map((_, n) => rows.slice(Math.max(0, n - 2), n + 3).some(([kind]) => kind !== 'same'));
    let folded = 0;
    const flush = () => { if (folded) { box.append(el('div', 'acw-diff-fold', `${folded} unchanged line${folded > 1 ? 's' : ''}`)); folded = 0; } };
    rows.forEach(([kind, text], n) => {
      if (kind === 'same' && !near[n]) { folded++; return; }
      flush();
      box.append(el('div', `acw-diff-line ${kind}`, text || ' '));
    });
    flush();
    box.append(el('div', 'acw-diff-gap'));
  }
  box.lastChild?.remove();
  return box;
}

function toolRow(id, name, rawArgs) {
  if (id && toolRows.has(id)) return toolRows.get(id);
  const args = parseArgs(rawArgs);
  const { verb, target } = toolTitle(name, args);
  const card = el('details', 'acw-tool');
  card.dataset.kind = name || 'tool';
  card.dataset.state = 'running';
  card.dataset.start = String(Date.now());
  const summary = el('summary');
  const mark = el('span', 'acw-tool-mark');
  mark.innerHTML = icon((TOOL_KINDS[name] || ['tool'])[0]);
  const label = el('span', 'acw-tool-label');
  label.append(el('span', 'acw-tool-verb', verb), el('span', 'acw-tool-target', target));
  const state = el('span', 'acw-tool-state');
  state.innerHTML = '<span class="acw-spin" aria-hidden="true"></span><span class="acw-tool-time">0.0s</span>';
  summary.append(mark, label, state);
  const body = el('div', 'acw-tool-body');
  if (name === 'bash' && args.command) body.append(el('pre', 'acw-term acw-term-cmd', `$ ${args.command}`));
  if (name === 'edit' && (args.edits || args.oldText != null)) { body.append(diffView(args)); card.open = true; }
  if (name === 'write' && args.content) body.append(el('pre', 'acw-tool-output acw-new-file', String(args.content).slice(0, 4000)));
  const output = el('pre', 'acw-tool-output');
  output.hidden = true;
  body.append(output);
  card.append(summary, body);
  if (id) toolRows.set(id, card);
  $('aide-code-log').append(card);
  card._timer = setInterval(() => {
    if (!card.isConnected || card.dataset.state !== 'running') { clearInterval(card._timer); return; }
    card.querySelector('.acw-tool-time').textContent = since(+card.dataset.start);
  }, 100);
  return card;
}

function finishTool(id, ok, output) {
  const card = toolRows.get(id) || toolRow(id, 'tool', '');
  clearInterval(card._timer);
  card.dataset.state = ok ? 'done' : 'failed';
  const state = card.querySelector('.acw-tool-state');
  const took = card.dataset.start ? since(+card.dataset.start) : '';
  state.innerHTML = `${icon(ok ? 'check' : 'cross')}<span class="acw-tool-time">${ok ? took : 'failed'}</span>`;
  const pre = card.querySelector('.acw-tool-output:not(.acw-new-file)');
  const text = output || (ok ? '' : 'failed with no output');
  pre.textContent = text;
  pre.hidden = !text;
  pre.classList.toggle('acw-term', card.dataset.kind === 'bash');
  // a failed step says why on its own line; pi usually tries again, so it stays shut
  if (!ok) {
    const why = text.split('\n').map(line => line.trim()).filter(Boolean).pop() || 'failed';
    card.querySelector('.acw-tool-why')?.remove();
    card.querySelector('summary').after(el('p', 'acw-tool-why', why.slice(0, 160)));
  }
}

// a run of steps folds into one line once pi moves on: how many, how many failed, how long
function groupSteps() {
  const log = $('aide-code-log');
  let run = [];
  const fold = () => {
    if (run.length >= 4) {
      const group = el('details', 'acw-steps');
      const failed = run.filter(card => card.dataset.state === 'failed').length;
      const summary = el('summary');
      const dots = el('span', 'acw-steps-dots');
      dots.setAttribute('aria-hidden', 'true');
      for (const card of run.slice(-24)) dots.append(el('span', card.dataset.state));
      summary.append(el('span', 'acw-steps-label', `${run.length} steps${failed ? ` · ${failed} failed` : ''}`), dots);
      run[0].before(group);
      group.append(summary, ...run);
    }
    run = [];
  };
  for (const node of [...log.children]) {
    // edits and new files stay in view: they're what changed
    if (node.matches('.acw-tool') && node.dataset.state !== 'running' && !['edit', 'write'].includes(node.dataset.kind)) run.push(node);
    else fold();
  }
  fold();
}

function assistantBlock(text, error = '') {
  const block = el('div', 'acw-msg acw-assistant');
  if (text) block.innerHTML = mdToHtml(text);
  if (error) block.append(el('p', 'acw-msg-error', error));
  return block;
}

function render(item) {
  const log = $('aide-code-log');
  if (item.kind === 'user' && /^Goal: [^]*\n\nWork toward this goal/.test(item.text || '')) {
    // a /goal from before a reload: show the card, not the instructions alles sent with it
    render({ kind: 'goal', state: 'set', text: item.text.slice(6).split('\n\nWork toward this goal')[0] });
  } else if (item.kind === 'user') {
    const bubble = el('div', 'acw-msg acw-user');
    bubble.textContent = item.text;
    log.append(bubble);
  } else if (item.kind === 'thinking') {
    showWorking(false);
    thinkingBlock(item.text);
  } else if (item.kind === 'delta') {
    showWorking(false);
    closeThinking();
    if (!streaming) { streaming = assistantBlock(''); streaming.dataset.text = ''; streaming.classList.add('is-streaming'); log.append(streaming); }
    streaming.dataset.text += item.text;
    streaming.innerHTML = mdToHtml(streaming.dataset.text);
  } else if (item.kind === 'assistant') {
    closeThinking();
    if (item.text) groupSteps();
    const block = assistantBlock(item.text, item.error);
    if (streaming) { streaming.replaceWith(block); streaming = null; }
    else if (item.text || item.error) log.append(block);
    for (const tool of item.tools || []) toolRow(tool.id, tool.name, tool.args);
  } else if (item.kind === 'tool') {
    showWorking(false);
    toolRow(item.id, item.name, item.args);
  } else if (item.kind === 'tool_done') {
    finishTool(item.id, item.ok, item.output);
  } else if (item.kind === 'error') {
    log.append(el('p', 'acw-msg-error', item.text));
  } else if (item.kind === 'note') {
    log.append(el('p', 'acw-note', item.text));
  } else if (item.kind === 'context') {
    log.append(contextCard(item));
  } else if (item.kind === 'compacted') {
    log.append(compactCard(item));
  } else if (item.kind === 'goal') {
    goal = item.state === 'cleared' ? '' : (item.text || goal);
    log.append(goalCard(item));
    renderGoal();
  }
}

// pi's reasoning, live: a shimmering line with a timer, open to read along
let thinking_ = null;
function thinkingBlock(text) {
  if (!thinking_) {
    thinking_ = el('details', 'acw-thinking');
    thinking_.dataset.start = String(Date.now());
    const summary = el('summary');
    summary.append(el('span', 'acw-thinking-label', 'thinking'), el('span', 'acw-tool-time', '0s'));
    thinking_.append(summary, el('div', 'acw-thinking-text'));
    $('aide-code-log').append(thinking_);
    const node = thinking_;
    node._timer = setInterval(() => {
      if (!node.isConnected || node.dataset.done) { clearInterval(node._timer); return; }
      node.querySelector('.acw-tool-time').textContent = since(+node.dataset.start);
    }, 100);
  }
  const box = thinking_.querySelector('.acw-thinking-text');
  box.textContent += text;
  if (thinking_.open) box.scrollTop = box.scrollHeight;
}
function closeThinking() {
  if (!thinking_) return;
  thinking_.dataset.done = '1';
  clearInterval(thinking_._timer);
  thinking_.querySelector('.acw-thinking-label').textContent = 'thought for';
  thinking_ = null;
}

// ── cards for /context, /compact and /goal ──

const fmt = n => n == null ? '?' : n >= 1e6 ? `${(n / 1e6).toFixed(1)}m` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n);

function cells(used, total, count = 50) {
  // one cell per 2% of the window; filled ones are what's in context now
  const grid = el('div', 'acw-cells');
  grid.setAttribute('aria-hidden', 'true');
  const filled = total ? Math.min(count, Math.round((used / total) * count)) : 0;
  for (let i = 0; i < count; i++) grid.append(el('span', i < filled ? 'on' : ''));
  return grid;
}

function contextCard(item) {
  const card = el('section', 'acw-card acw-context');
  card.setAttribute('aria-label', 'context');
  const head = el('div', 'acw-card-head');
  const pct = item.percent != null ? Math.round(item.percent) : null;
  head.append(el('strong', '', 'context'), el('span', 'acw-muted', `${fmt(item.tokens)} of ${fmt(item.window)} tokens${pct != null ? ` · ${pct}%` : ''}`));
  const rows = el('dl', 'acw-card-rows');
  const add = (label, value) => { if (value == null || value === '') return; rows.append(el('dt', '', label), el('dd', '', String(value))); };
  add('model', item.model);
  add('effort', item.thinking ? levelName(item.thinking) : '');
  add('messages', item.userMessages != null ? `${item.userMessages} from you, ${item.assistantMessages} from pi` : '');
  add('tool calls', item.toolCalls);
  add('tokens in', fmt(item.input));
  add('tokens out', fmt(item.output));
  add('read from cache', fmt(item.cache_read));
  if (item.cost) add('cost', `$${Number(item.cost).toFixed(item.cost < 1 ? 3 : 2)}`);
  card.append(head, cells(item.tokens || 0, item.window || 0), rows);
  return card;
}

function compactCard(item) {
  const card = el('section', 'acw-card acw-compacted');
  card.setAttribute('aria-label', 'context compacted');
  const head = el('div', 'acw-card-head');
  head.append(el('strong', '', 'compacted'), el('span', 'acw-muted', `${fmt(item.before)} → ${fmt(item.after)} tokens`));
  const bars = el('div', 'acw-compact-bars');
  bars.setAttribute('aria-hidden', 'true');
  const top = Math.max(item.before || 0, item.window || 0, 1);
  for (const [label, value] of [['before', item.before], ['after', item.after]]) {
    const bar = el('div', 'acw-bar');
    const fill = el('span');
    fill.style.width = `${Math.max(1, Math.round(((value || 0) / top) * 100))}%`;
    bar.append(el('small', '', label), fill);
    bars.append(bar);
  }
  card.append(head, bars);
  if (item.summary) {
    const more = el('details', 'acw-card-more');
    more.append(el('summary', '', 'what pi kept'), el('p', '', item.summary));
    card.append(more);
  }
  return card;
}

function goalCard(item) {
  const card = el('section', 'acw-card acw-goal-card');
  card.setAttribute('aria-label', 'goal');
  const words = { set: 'goal set', cleared: 'goal cleared', none: 'no goal yet', shown: 'goal' }[item.state] || 'goal';
  card.append(el('strong', '', words));
  if (item.text) card.append(el('p', '', item.text));
  else if (item.state === 'none') card.append(el('p', 'acw-muted', 'type /goal and what you want done'));
  return card;
}

function renderGoal() {
  const bar = $('aide-code-goal');
  bar.hidden = !goal;
  $('aide-code-goal-text').textContent = goal;
}

// ── effort ──

function effortLevels() {
  const using = current.chatId ? (chatHarness || harness) : harness;
  if (using !== 'pi') return [];
  if (current.chatId && thinking.levels.length) return thinking.levels;
  return model?.thinks ? LEVELS : [];
}
const currentLevel = () => (current.chatId && thinking.level) || thinkingPref || '';

function renderEffortMenu() {
  const list = $('aide-code-effort-menu');
  list.replaceChildren();
  for (const level of effortLevels()) {
    const item = el('button', 'acw-menu-item');
    item.type = 'button';
    item.setAttribute('role', 'menuitemradio');
    item.setAttribute('aria-checked', String(level === currentLevel()));
    item.append(el('span', '', levelName(level)));
    item.addEventListener('click', () => { effortMenu.close(); void setEffort(level); });
    list.append(item);
  }
}

async function setEffort(level) {
  if (!effortLevels().includes(level)) { setError(`pi can't use "${level}" with this model`); return; }
  try {
    const data = await send_('PUT', '/api/aide/code/thinking', { level, project_id: current.projectId, chat_id: current.chatId });
    thinkingPref = level;
    if (data.live) thinking = { level: data.level, levels: data.levels || thinking.levels };
    updateComposer();
  } catch (error) { setError(error.message); }
}

async function loadChatState() {
  // effort levels and pi's own commands for the running chat
  if (!current.chatId) return;
  const { projectId, chatId } = current;
  try {
    const data = await api(chatPath(projectId, chatId));
    if (current.chatId !== chatId) return;
    thinking = data.thinking?.levels ? data.thinking : thinking;
    const items = data.live ? (await api(`${chatPath(projectId, chatId)}/commands`)).items || [] : [];
    if (current.chatId === chatId) piCommands = items;
  } catch { /* the menu still has alles's own commands */ }
  updateComposer();
}

// ── / menu ──

function slashMatches(query) {
  const all = [...BUILTINS, ...piCommands.filter(c => !BUILTINS.some(b => b.name === c.name))];
  const q = query.toLowerCase();
  const hits = all.filter(c => !q || c.name.toLowerCase().includes(q) || (c.description || '').toLowerCase().includes(q));
  return hits.sort((a, b) => Number(!a.name.toLowerCase().startsWith(q)) - Number(!b.name.toLowerCase().startsWith(q)));
}

function slashQuery() {
  const input = $('aide-code-input');
  const value = input.value;
  if (!value.startsWith('/') || /\s/.test(value) || input.selectionStart !== value.length) return null;
  return value.slice(1);
}

function renderSlash() {
  const box = $('aide-code-slash');
  const input = $('aide-code-input');
  const query = slashQuery();
  slashItems = query == null ? [] : slashMatches(query);
  if (!slashItems.length) { closeSlash(); return; }
  slashIndex = Math.min(slashIndex, slashItems.length - 1);
  box.replaceChildren(...slashItems.map((command, index) => {
    const row = el('div', 'slash-item acw-slash-item');
    row.id = `aide-code-slash-${index}`;
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(index === slashIndex));
    row.classList.toggle('selected', index === slashIndex);
    const name = el('span', 'slash-cmd');
    name.append(el('span', 'slash-name', `/${command.name}`));
    if (command.args) name.append(el('span', 'slash-args', command.args));
    row.append(name, el('span', 'slash-desc', command.description || ''));
    if (command.source) row.append(el('span', 'acw-slash-source', command.source === 'prompt' ? 'template' : command.source));
    row.addEventListener('mousedown', event => { event.preventDefault(); slashIndex = index; pickSlash(true); });
    return row;
  }));
  box.hidden = false;
  input.setAttribute('aria-expanded', 'true');
  input.setAttribute('aria-activedescendant', `aide-code-slash-${slashIndex}`);
  box.querySelector('.selected')?.scrollIntoView({ block: 'nearest' });
}

function closeSlash() {
  const box = $('aide-code-slash');
  box.hidden = true; box.replaceChildren(); slashItems = []; slashIndex = 0;
  $('aide-code-input').setAttribute('aria-expanded', 'false');
  $('aide-code-input').removeAttribute('aria-activedescendant');
}

function pickSlash(run) {
  const command = slashItems[slashIndex];
  if (!command) return;
  const input = $('aide-code-input');
  closeSlash();
  if (run && !command.args) { input.value = `/${command.name}`; $('aide-code-form').requestSubmit(); return; }
  input.value = `/${command.name} `;
  autosizeTextarea(input); input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  updateComposer();
}

function onSlashKey(event) {
  if ($('aide-code-slash').hidden) return false;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    slashIndex = (slashIndex + (event.key === 'ArrowDown' ? 1 : -1) + slashItems.length) % slashItems.length;
    renderSlash();
  } else if (event.key === 'Tab') { event.preventDefault(); pickSlash(false); }
  else if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); pickSlash(true); }
  else if (event.key === 'Escape') { event.preventDefault(); closeSlash(); }
  else return false;
  return true;
}

// commands alles runs in the browser; true when the text was one
function localCommand(text) {
  const [name, ...rest] = text.split(/\s+/);
  const arg = rest.join(' ').trim();
  const needsChat = BUILTINS.find(b => `/${b.name}` === name)?.live;
  if (needsChat && !current.chatId) { setError(`${name} works once a chat has started`); return true; }
  if (name === '/new') { startChat(current.projectId); return true; }
  if (name === '/model') { $('aide-code-model').click(); return true; }
  if (name === '/stop') { $('aide-code-stop').click(); return true; }
  if (name === '/whats-new') { import('./whatsnew.js').then(m => m.openWhatsNew()); return true; }
  if (name === '/effort') {
    if (arg) void setEffort(arg.toLowerCase().replace(/\s+/g, '') === 'extrahigh' ? 'xhigh' : arg.toLowerCase());
    else if (!$('aide-code-effort').hidden) $('aide-code-effort').click();
    else setError('this model has no effort levels');
    return true;
  }
  return false;
}

// between "send" and pi's first step: a live line so the wait never looks dead
let working = null;
function showWorking(on) {
  if (!on) { if (working) { clearInterval(working._timer); working.remove(); working = null; } return; }
  if (working || !host) return;
  working = el('div', 'acw-working');
  working.setAttribute('role', 'status');
  working.dataset.start = String(Date.now());
  working.innerHTML = '<span class="acw-spin" aria-hidden="true"></span><span class="acw-working-label">working</span><span class="acw-tool-time">0.0s</span>';
  $('aide-code-log').append(working);
  const node = working;
  node._timer = setInterval(() => { if (!node.isConnected) { clearInterval(node._timer); return; } node.querySelector('.acw-tool-time').textContent = since(+node.dataset.start); }, 100);
  scrollLog();
}

function setBusy(value) {
  const was = busy;
  busy = value;
  showWorking(busy && !was);
  $('aide-code-status').textContent = busy ? 'pi is working…' : '';
  sendOrStop();
  host.dataset.busy = String(busy);
  if (!busy) { showWorking(false); closeThinking(); streaming?.classList.remove('is-streaming'); groupSteps(); }
  // a short pulse on the box when pi finishes, so the end of a long run is noticed
  if (was && !busy) { const entry = host.querySelector('.acw-entry'); entry?.classList.remove('is-done'); void entry?.offsetWidth; entry?.classList.add('is-done'); }
}

function renderStats(stats = {}) {
  const parts = [];
  if (stats.tokens_per_second) parts.push([`${stats.tokens_per_second} tok/s`, '']);
  if (stats.cache_hit_rate != null) parts.push([`cache ${Math.round(stats.cache_hit_rate * 100)}%`, '']);
  $('aide-code-stats').replaceChildren(...parts.map(([text, className], index) => el('span', className, (index ? ' · ' : '') + text)));
  // context as a ring that fills; it opens /context
  const ring = $('aide-code-context');
  const pct = stats.context_percent;
  ring.hidden = pct == null;
  if (pct != null) {
    const value = Math.max(0, Math.min(100, Math.round(pct)));
    ring.style.setProperty('--pct', value);
    ring.dataset.level = value >= 85 ? 'high' : value >= 60 ? 'mid' : 'low';
    ring.querySelector('.acw-ring-text').textContent = `${value}%`;
    ring.setAttribute('aria-label', `context ${value}% full; show what fills it`);
    ring.title = `context ${value}% full`;
  }
}

function renderQuestion(question) {
  const box = $('aide-code-question');
  box.replaceChildren();
  if (!question) { box.hidden = true; return; }
  box.dataset.questionId = question.id;
  box.append(el('p', 'acw-question-title', question.title));
  const actions = el('div', 'acw-question-actions');
  const choices = question.method === 'confirm' ? [['yes', true], ['no', false]] : question.options.map(option => [option, option]);
  for (const [label, value] of [...choices, ['skip', null]]) {
    const button = el('button', 'acw-action', label);
    button.type = 'button';
    button.addEventListener('click', () => answer(question.id, value, button));
    actions.append(button);
  }
  box.append(actions);
  box.hidden = false;
  actions.querySelector('button')?.focus();
}

async function answer(questionId, value, button) {
  button.disabled = true;
  try { await post(`${chatPath(current.projectId, current.chatId)}/answer`, { question_id: questionId, value }); renderQuestion(null); }
  catch (error) { setError(error.message); button.disabled = false; }
}

function closeLive() { live?.close(); live = null; }

function follow(projectId, chatId, after) {
  closeLive();
  liveSeq = after;
  const source = new EventSource(`${chatPath(projectId, chatId)}/live?after=${after}`);
  live = source;
  source.onmessage = message => {
    if (live !== source) return;
    const event = JSON.parse(message.data);
    if (event.seq <= liveSeq) return;
    liveSeq = event.seq;
    if (event.kind === 'busy') setBusy(true);
    else if (event.kind === 'idle') { setBusy(false); void refreshChats(projectId); }
    else if (event.kind === 'stats') renderStats(event);
    else if (event.kind === 'question') renderQuestion(event);
    else if (event.kind === 'answered') renderQuestion(null);
    else render(event);
    scrollLog();
  };
  source.addEventListener('closed', () => { if (live === source) { closeLive(); setBusy(false); } });
  source.onerror = () => {
    if (live !== source) return;
    // the server ends the stream when pi stops; reload once to show where things are
    closeLive();
    if (current.chatId === chatId) void openChat(projectId, chatId, { keepScroll: true });
  };
}

function nearBottom() { const sc = $('aide-code-scroll'); return sc.scrollHeight - sc.scrollTop - sc.clientHeight < 160; }
function scrollLog() {
  const scroller = $('aide-code-scroll');
  if (nearBottom()) scroller.scrollTop = scroller.scrollHeight;
  else $('aide-code-jump').hidden = false;  // something new arrived below where you're reading
}

async function refreshChats(projectId) { await loadChats(projectId); renderRail(); }

function resetLog() {
  for (const card of toolRows.values()) clearInterval(card._timer);
  showWorking(false);
  $('aide-code-log').replaceChildren();
  streaming = null; toolRows = new Map(); thinking_ = null;
  renderQuestion(null); renderStats(); setBusy(false); setError();
}

async function openChat(projectId, chatId, { keepScroll = false } = {}) {
  const ticket = ++version;
  closeLive();
  current = { projectId, chatId };
  expanded.add(projectId);
  renderRail();
  showView('chat'); setPane('main');
  const row = project(projectId);
  $('aide-code-title').textContent = (chats.get(projectId) || []).find(chat => chat.id === chatId)?.title || 'chat';
  showPath(row?.path);
  $('aide-code-delete').hidden = false;
  showIntro(false);
  try {
    const data = await api(chatPath(projectId, chatId));
    if (ticket !== version) return;
    resetLog();
    for (const item of data.items) render(item);
    if (!data.busy) groupSteps();
    if (data.partial) render({ kind: 'delta', text: data.partial });
    chatHarness = data.harness || harness;
    harnessModels = data.harness_models ? data.harness_models.map(m => ({ ...m, selected: m.model === data.model?.model })) : null;
    if (data.model?.model && isNative(chatHarness)) pickModel(models.find(m => m.model === data.model.model && (!data.model.endpoint_id || m.endpoint_id === data.model.endpoint_id)) || model, { remote: false });
    renderStats(data.stats);
    thinking = data.thinking?.levels ? data.thinking : { level: '', levels: [] };
    goal = data.goal || '';
    piCommands = [];
    if (data.live) void loadChatState();
    setBusy(data.busy);
    renderQuestion(data.questions?.[0] || null);
    if (data.live) follow(projectId, chatId, data.seq);
    if (!keepScroll) $('aide-code-scroll').scrollTop = $('aide-code-scroll').scrollHeight;
  } catch (error) { if (ticket === version) setError(error.message); }
  updateComposer();
}

function startChat(projectId) {
  ++version;
  closeLive();
  current = { projectId, chatId: '' };
  chatHarness = ''; harnessModels = null;
  thinking = { level: '', levels: [] }; goal = ''; piCommands = [];
  expanded.add(projectId);
  renderRail();
  resetLog();
  const row = project(projectId);
  $('aide-code-title').textContent = 'new chat';
  showPath(row?.path);
  $('aide-code-delete').hidden = true;
  showView('chat'); setPane('main');
  showIntro(true);
  updateComposer();
  $('aide-code-input').focus();
}

// while pi works: stop when the box is empty, send (it steers pi) once there's text
function sendOrStop() {
  const typed = !!$('aide-code-input').value.trim();
  $('aide-code-stop').hidden = !busy || typed;
  $('aide-code-send').hidden = busy && !typed;
}

const SUGGESTIONS = [
  ['explain this project', 'explain what this project does and how it is laid out'],
  ['find and fix a bug', 'look for a bug in this project, fix it, and show me how you checked'],
  ['write tests', 'write tests for the most important code here and run them'],
  ['work toward a goal', '/goal '],
];
function showIntro(on) {
  const intro = $('aide-code-intro');
  intro.hidden = !on;
  if (!on) return;
  const list = intro.querySelector('.acw-suggest');
  if (list.childElementCount) return;
  SUGGESTIONS.forEach(([label, text], n) => {
    const chip = el('button', 'acw-suggestion', label);
    chip.type = 'button';
    chip.setAttribute('role', 'listitem');
    chip.style.setProperty('--n', n);
    chip.addEventListener('click', () => {
      const input = $('aide-code-input');
      input.value = text; autosizeTextarea(input); input.focus();
      input.setSelectionRange(text.length, text.length);
      updateComposer(); renderSlash();
    });
    list.append(chip);
  });
}

function updateComposer() {
  const row = project();
  const input = $('aide-code-input');
  const using = current.chatId ? (chatHarness || harness) : harness;
  const nativeUse = isNative(using);
  const state = nativeUse ? native.find(h => h.harness === using)?.state : 'ready';
  const ready = state === 'ready' && (!nativeUse || !!model) && !!row;
  input.disabled = !row;
  input.placeholder = row ? `ask ${harnessName(using)} to work in ${row.name}` : 'pick a project first';
  $('aide-code-send').disabled = !ready || sending || !input.value.trim();
  sendOrStop();
  // omp and pi use alles's models; an ACP harness brings its own list, if it shares one
  const acpModels = !nativeUse ? harnessModels || [] : null;
  $('aide-code-model-label').textContent = nativeUse ? (model ? model.model : 'no coding model')
    : (acpModels.find(m => m.selected)?.name || (acpModels.length ? 'model' : 'its own model'));
  $('aide-code-model').disabled = nativeUse ? !models.length : !acpModels.length;
  $('aide-code-harness-label').textContent = harnessName(using);
  const levels = effortLevels();
  $('aide-code-effort').hidden = levels.length < 2;
  $('aide-code-effort-label').textContent = levelName(currentLevel()) || 'effort';
  $('aide-code-effort').title = 'how hard pi thinks';
  renderGoal();
  $('aide-code-harness').title = current.chatId ? 'start a new chat to use another harness' : 'harness for new chats';
  $('aide-code-harness').disabled = !!current.chatId;
  const hint = nativeUse && !models.length ? `add a model with an api key in settings → models to code with ${harnessName(using)}`
    : state !== 'ready' ? `${harnessName(using)} will be ready once it finishes installing` : '';
  $('aide-code-hint').textContent = hint;
  $('aide-code-hint').hidden = !hint;
}

async function send(event) {
  event.preventDefault();
  const input = $('aide-code-input');
  const text = input.value.trim();
  if (!text || sending || $('aide-code-send').disabled) return;
  setError();
  if (text.startsWith('/') && localCommand(text)) { input.value = ''; autosizeTextarea(input); closeSlash(); updateComposer(); return; }
  sending = true; updateComposer(); showIntro(false);
  const { projectId, chatId } = current;
  const choice = model && isNative(chatId ? chatHarness : harness) ? { endpoint_id: model.endpoint_id, model: model.model } : {};
  try {
    if (!chatId) {
      const made = await post(chatPath(projectId), { text, harness, ...choice });
      chatHarness = harness;
      input.value = ''; autosizeTextarea(input);
      current = { projectId, chatId: made.chat_id };
      await refreshChats(projectId);
      // the server's title is masked; what was typed may hold a secret
      $('aide-code-title').textContent = (chats.get(projectId) || []).find(chat => chat.id === made.chat_id)?.title || 'chat';
      $('aide-code-delete').hidden = false;
      follow(projectId, made.chat_id, made.seq - 1);
      void loadChatState();
    } else {
      const sent = await post(`${chatPath(projectId, chatId)}/messages`, { text, ...choice });
      input.value = ''; autosizeTextarea(input);
      if (!live) follow(projectId, chatId, sent.seq - 1);
    }
  } catch (error) {
    setError(error.code === 'pi_not_ready' ? 'pi is still installing; try again in a moment' : error.message);
  } finally { sending = false; updateComposer(); }
}

// ── model picker ──

function pickModel(choice, { remote = true } = {}) {
  model = choice || null;
  updateComposer();
  if (!remote || !current.chatId || !model) return;
  post(`${chatPath(current.projectId, current.chatId)}/model`, { endpoint_id: model.endpoint_id, model: model.model })
    .then(() => loadChatState())
    .catch(error => setError(error.message));
}

function pickHarnessModel(choice) {
  harnessModels = (harnessModels || []).map(m => ({ ...m, selected: m.model === choice.model }));
  updateComposer();
  post(`${chatPath(current.projectId, current.chatId)}/model`, { model: choice.model }).catch(error => setError(error.message));
}

function renderModelMenu() {
  const list = $('aide-code-model-menu');
  list.replaceChildren();
  if (current.chatId && !isNative(chatHarness)) {
    for (const choice of harnessModels || []) {
      const item = el('button', 'acw-menu-item');
      item.type = 'button';
      item.setAttribute('role', 'menuitemradio');
      item.setAttribute('aria-checked', String(!!choice.selected));
      item.append(el('span', '', choice.name || choice.model), el('small', '', harnessName(chatHarness)));
      item.addEventListener('click', () => { menu.close(); pickHarnessModel(choice); });
      list.append(item);
    }
    return;
  }
  for (const choice of models) {
    const item = el('button', 'acw-menu-item');
    item.type = 'button';
    item.setAttribute('role', 'menuitemradio');
    item.setAttribute('aria-checked', String(model?.endpoint_id === choice.endpoint_id && model?.model === choice.model));
    item.append(el('span', '', choice.model), el('small', '', choice.endpoint));
    item.addEventListener('click', () => { menu.close(); pickModel(choice); });
    list.append(item);
  }
}

// ── harnesses ──

async function loadCatalog() {
  try { catalogRows = (await api('/api/aide/code/harnesses')).items || []; } catch { catalogRows = catalogRows || []; }
}

async function useHarness(id, nextApproval = approval) {
  const saved = await send_('PUT', '/api/aide/code/settings', { harness: id, approval: nextApproval });
  harness = saved.harness; approval = saved.approval;
  await loadStatus();
}
const send_ = (method, url, body) => api(url, { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

function renderHarnessMenu() {
  const list = $('aide-code-harness-menu');
  list.replaceChildren();
  const ready = catalogRows.filter(h => h.state === 'ready' || isNative(h.id));
  for (const row of ready) {
    const item = el('button', 'acw-menu-item');
    item.type = 'button';
    item.setAttribute('role', 'menuitemradio');
    item.setAttribute('aria-checked', String(row.id === harness));
    const state = isNative(row.id) ? native.find(h => h.harness === row.id)?.state : row.state;
    item.append(el('span', '', row.name), el('small', '', state === 'ready' ? (row.open_source ? 'open source' : row.license) : state.replace('_', ' ')));
    item.addEventListener('click', async () => {
      harnessMenu.close();
      try { await useHarness(row.id); } catch (error) { setError(error.message); }
    });
    list.append(item);
  }
  const more = el('button', 'acw-menu-item', 'more harnesses…');
  more.type = 'button';
  more.setAttribute('role', 'menuitem');
  more.addEventListener('click', () => { harnessMenu.close({ restoreFocus: false }); void openHarnesses(); });
  list.append(more);
}

async function openHarnesses() {
  ++version; closeLive();
  showView('harnesses'); setPane('main');
  $('aide-code-title').textContent = 'harnesses';
  showPath('');
  $('aide-code-delete').hidden = true;
  $('aide-code-harness-list').textContent = 'loading…';
  await loadCatalog();
  renderHarnessList();
  $('aide-code-title').focus();
}

function renderHarnessList() {
  const host = $('aide-code-harness-list');
  host.replaceChildren();
  for (const row of catalogRows) {
    const item = el('article', 'acw-harness-row');
    const main = el('div', 'acw-harness-main');
    const nameLine = el('div', 'acw-harness-name');
    nameLine.append(el('strong', '', row.name));
    if (row.id === harness) nameLine.append(el('span', 'acw-harness-default', 'default'));
    main.append(nameLine);
    if (row.description) main.append(el('p', 'acw-muted', row.description));
    const facts = [row.open_source ? `open source · ${row.license}` : `closed source · ${row.license}`];
    if (row.version) facts.push(row.version);
    const state = isNative(row.id) ? native.find(h => h.harness === row.id)?.state || row.state : row.state;
    facts.push({ ready: 'installed', missing: 'not installed', installing: 'installing…', failed: 'install failed', manual: 'install it yourself', unavailable: 'not for this machine', needs_node: 'needs node 22.19+' }[state] || state);
    main.append(el('p', 'acw-harness-facts', facts.join(' · ')));
    if (row.error) main.append(el('p', 'acw-msg-error', row.error));
    if (state === 'manual' && row.install_hint) main.append(el('code', 'acw-harness-hint', row.install_hint));
    const actions = el('div', 'acw-harness-actions');
    if (['missing', 'failed'].includes(state)) actions.append(harnessAction('install', row.id, 'install'));
    if (state === 'ready' && row.id !== harness) actions.append(harnessAction('use as default', row.id, 'use'));
    item.append(main, actions);
    if (row.id === 'omp' && state === 'ready') {
      // omp can ask before it runs a command; pi has no such switch
      const group = el('div', 'acw-harness-approval');
      group.setAttribute('role', 'radiogroup');
      group.setAttribute('aria-label', 'when omp wants to run a command');
      for (const [key, label] of [['auto', 'just do it'], ['ask', 'ask me first']]) {
        const button = el('button', 'acw-action', label);
        button.type = 'button';
        button.setAttribute('role', 'radio');
        button.setAttribute('aria-checked', String(approval === key));
        button.addEventListener('click', async () => {
          try { await useHarness(harness, key); renderHarnessList(); } catch (error) { setError(error.message); }
        });
        group.append(button);
      }
      main.append(group);
    }
    host.append(item);
  }
}

function harnessAction(label, id, name) {
  const button = el('button', 'acw-action', label);
  button.type = 'button';
  button.dataset.harnessAction = name;
  button.dataset.harnessId = id;
  return button;
}

async function onHarnessAction(event) {
  const button = event.target.closest('[data-harness-action]');
  if (!button) return;
  button.disabled = true;
  const id = button.dataset.harnessId;
  try {
    if (button.dataset.harnessAction === 'install') {
      await post(`/api/aide/code/harnesses/${encodeURIComponent(id)}/install`);
      // follow the install until it settles
      for (let i = 0; i < 300; i++) {
        await loadCatalog(); await loadStatus(); renderHarnessList();
        const row = catalogRows.find(h => h.id === id);
        const state = isNative(id) ? native.find(h => h.harness === id)?.state : row?.state;
        if (state !== 'installing' || $('aide-code-harness-view').hidden) break;
        await new Promise(resolve => setTimeout(resolve, 3000));
      }
    } else {
      await useHarness(id);
      renderHarnessList();
    }
  } catch (error) { setError(error.message); button.disabled = false; }
}

// ── adding a project ──

let browseTicket = 0;
async function browse(path) {
  const list = $('aide-code-folders');
  const ticket = ++browseTicket;
  try {
    const data = await api(`/api/aide/code/folders?path=${encodeURIComponent(path || '')}`);
    if (ticket !== browseTicket) return;  // a newer folder was asked for meanwhile
    $('aide-code-folder-path').value = data.path;
    $('aide-code-folder-up').disabled = !data.parent;
    $('aide-code-folder-up').dataset.path = data.parent || '';
    list.replaceChildren();
    if (!data.folders.length) list.append(el('p', 'acw-rail-empty', 'no folders inside this one'));
    for (const name of data.folders) {
      const button = el('button', 'acw-folder');
      button.type = 'button';
      button.innerHTML = icon('folder');
      button.append(el('span', '', name));
      button.addEventListener('click', () => browse(`${data.path.replace(/\/$/, '')}/${name}`));
      list.append(button);
    }
    setError();
  } catch (error) { if (ticket === browseTicket) setError(error.message); }
}

function openAdd() {
  ++version; closeLive();
  showView('add'); setPane('main');
  $('aide-code-title').textContent = 'add a project';
  $('aide-code-path').textContent = 'pick a folder on the machine that runs alles';
  $('aide-code-delete').hidden = true;
  void browse($('aide-code-folder-path').value || '');
  $('aide-code-folder-path').focus();
}

async function addProject() {
  const button = $('aide-code-folder-use');
  button.disabled = true;
  try {
    const row = await post('/api/aide/code/projects', { path: $('aide-code-folder-path').value });
    expanded.add(row.id);
    await loadProjects();
    startChat(row.id);
  } catch (error) { setError(error.message); }
  finally { button.disabled = false; }
}

async function forgetProject(projectId) {
  const row = project(projectId);
  if (!row) return;
  const ok = await dlgConfirm(`forget ${row.name}? its pi chats are set aside in alles's data folder. the folder itself is not touched.`, { confirmLabel: 'forget' });
  if (!ok) return;
  try {
    await api(`/api/aide/code/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' });
    expanded.delete(projectId); chats.delete(projectId);
    if (current.projectId === projectId) { current = { projectId: '', chatId: '' }; closeLive(); }
    await loadProjects();
    showFirst();
  } catch (error) { setError(error.message); }
}

async function deleteChat() {
  const { projectId, chatId } = current;
  if (!chatId) return;
  if (!await dlgConfirm('delete this chat? pi\'s record of it is removed. files it changed stay as they are.', { confirmLabel: 'delete' })) return;
  try {
    await api(chatPath(projectId, chatId), { method: 'DELETE' });
    await refreshChats(projectId);
    startChat(projectId);
  } catch (error) { setError(error.message); }
}

function showFirst() {
  const first = projects[0];
  if (!first) { showView('start'); $('aide-code-title').textContent = 'code with pi'; $('aide-code-path').textContent = ''; $('aide-code-delete').hidden = true; setPane('main'); updateComposer(); return; }
  const recent = (chats.get(first.id) || [])[0];
  if (recent) void openChat(first.id, recent.id);
  else startChat(first.id);
}

// ── status ──

async function loadStatus() {
  const data = await api('/api/aide/code/status');
  pi = data.pi; models = data.models || []; native = data.native || [];
  harness = data.settings?.harness || 'pi'; approval = data.settings?.approval || 'auto';
  thinkingPref = data.settings?.thinking || '';
  if (!model || !models.some(m => m.endpoint_id === model.endpoint_id && m.model === model.model)) model = data.default || models[0] || null;
  piLine(); renderModelMenu(); updateComposer();
  clearTimeout(installTimer);
  if (pi.state === 'installing') installTimer = setTimeout(() => { if (!host.hidden) void loadStatus(); }, 3000);
}

function markup() {
  return `
    <div class="acw-body">
      <aside class="acw-rail" aria-label="projects">
        <div class="acw-rail-head"><h2>projects</h2><button type="button" id="aide-code-add" class="acw-icon" aria-label="add a project" title="add a project">${icon('plus')}</button></div>
        <nav id="aide-code-projects" class="acw-projects" aria-label="projects and chats"></nav>
        <div class="acw-pi"><p id="aide-code-pi" role="status" hidden></p><button type="button" id="aide-code-pi-retry" class="acw-action" hidden>try again</button></div>
        <div id="aide-code-project-menu" class="acw-menu" role="menu" aria-label="project actions" hidden>
          <button type="button" role="menuitem" data-project-action="new">new chat</button>
          <button type="button" role="menuitem" data-project-action="forget">forget project</button>
        </div>
      </aside>
      <div class="acw-main">
        <header class="acw-head">
          <button type="button" id="aide-code-rail-back" class="acw-icon acw-mobile-back" aria-label="projects">${icon('back')}</button>
          <div class="acw-head-text"><h2 id="aide-code-title" tabindex="-1">code with pi</h2><p id="aide-code-path" class="acw-path"></p></div>
          <button type="button" id="aide-code-delete" class="acw-action" hidden>delete chat</button>
        </header>
        <p id="aide-code-error" class="acw-error" role="alert" hidden></p>
        <div id="aide-code-loading" class="acw-loading" role="status" aria-label="loading" hidden><span></span><span></span><span></span></div>
        <section id="aide-code-start" class="acw-content acw-start" hidden>
          <p>pi reads, edits and runs code in a folder on the machine that runs alles. it does not ask before each command, so give it a project folder you're happy for it to change.</p>
          <button type="button" id="aide-code-start-add" class="acw-action acw-primary">add a project folder</button>
        </section>
        <section id="aide-code-harness-view" class="acw-content acw-harnesses" hidden>
          <p class="acw-muted">pi is the default. omp and pi run natively; the rest connect through ACP and use their own sign-in and models. installs go into this machine's cache.</p>
          <div id="aide-code-harness-list" class="acw-harness-list"></div>
        </section>
        <section id="aide-code-add-view" class="acw-content acw-add" hidden>
          <form id="aide-code-folder-form" class="acw-folder-bar">
            <button type="button" id="aide-code-folder-up" class="acw-icon" aria-label="up one folder">${icon('back')}</button>
            <input id="aide-code-folder-path" type="text" spellcheck="false" autocomplete="off" aria-label="folder path">
            <button type="submit" class="acw-action">open</button>
          </form>
          <div id="aide-code-folders" class="acw-folders"></div>
          <div class="acw-add-foot"><button type="button" id="aide-code-folder-use" class="acw-action acw-primary">use this folder</button></div>
        </section>
        <section id="aide-code-chat" class="acw-chat-view" hidden>
          <div id="aide-code-scroll" class="acw-scroll">
            <div id="aide-code-intro" class="acw-intro" hidden>
              <h3>what should pi do here?</h3>
              <p>pi reads the files in this folder, edits them and runs commands, then tells you what it did. type / to see every command.</p>
              <div class="acw-suggest" role="list"></div>
            </div>
            <div id="aide-code-log" class="acw-log" role="log" aria-label="chat with pi"></div>
          </div>
          <button type="button" id="aide-code-jump" class="acw-jump" aria-label="jump to the latest" hidden>${icon('down')}</button>
          <form id="aide-code-form" class="acw-composer">
            <div id="aide-code-question" class="acw-question" role="group" aria-label="pi is asking" hidden></div>
            <p id="aide-code-hint" class="acw-muted" hidden></p>
            <div id="aide-code-goal" class="acw-goal" hidden><span class="acw-goal-label">goal</span><span id="aide-code-goal-text"></span><button type="button" id="aide-code-goal-clear" class="acw-action">clear</button></div>
            <div id="aide-code-slash" class="slash-popup acw-slash" role="listbox" aria-label="commands" hidden></div>
            <div class="acw-entry">
              <textarea id="aide-code-input" rows="1" maxlength="50000" data-kokuen-entry="autogrow" aria-label="message pi" role="combobox" aria-autocomplete="list" aria-controls="aide-code-slash" aria-expanded="false"></textarea>
              <div class="acw-entry-foot">
                <div class="acw-model acw-harness">
                  <button type="button" id="aide-code-harness" class="acw-action" aria-haspopup="menu" aria-expanded="false" aria-controls="aide-code-harness-menu"><span id="aide-code-harness-label">pi</span>${icon('chevron')}</button>
                  <div id="aide-code-harness-menu" class="acw-menu acw-menu-up" role="menu" aria-label="harness for new chats" hidden></div>
                </div>
                <div class="acw-model">
                  <button type="button" id="aide-code-model" class="acw-action" aria-haspopup="menu" aria-expanded="false" aria-controls="aide-code-model-menu"><span id="aide-code-model-label">no coding model</span>${icon('chevron')}</button>
                  <div id="aide-code-model-menu" class="acw-menu acw-menu-up" role="menu" aria-label="coding model" hidden></div>
                </div>
                <div class="acw-model">
                  <button type="button" id="aide-code-effort" class="acw-action" aria-haspopup="menu" aria-expanded="false" aria-controls="aide-code-effort-menu" hidden><span id="aide-code-effort-label">effort</span>${icon('chevron')}</button>
                  <div id="aide-code-effort-menu" class="acw-menu acw-menu-up" role="menu" aria-label="effort" hidden></div>
                </div>
                <span id="aide-code-stats" class="acw-stats"></span>
                <button type="button" id="aide-code-context" class="acw-ring" hidden><svg viewBox="0 0 36 36" aria-hidden="true"><circle class="acw-ring-track" cx="18" cy="18" r="15"/><circle class="acw-ring-fill" cx="18" cy="18" r="15" pathLength="100"/></svg><span class="acw-ring-text"></span></button>
                <span id="aide-code-status" class="acw-muted" role="status"></span>
                <button type="button" id="aide-code-stop" class="acw-icon" aria-label="stop pi" hidden>${icon('stop')}</button>
                <button type="submit" id="aide-code-send" class="acw-icon acw-send" aria-label="send" disabled>${icon('up')}</button>
              </div>
            </div>
          </form>
        </section>
      </div>
    </div>`;
}

export function initAideCodingWorkspace() {
  const target = $('aide-coding-workspace');
  if (!target || target.tagName === 'BUTTON' || host === target) return;
  host = target; host.classList.add('aide-coding-workspace'); host.setAttribute('aria-label', 'code with pi'); host.dataset.pane = 'main';
  host.innerHTML = markup();
  const input = $('aide-code-input');
  wireAutosizeTextarea(input);
  input.addEventListener('input', () => { slashIndex = 0; renderSlash(); updateComposer(); });
  input.addEventListener('blur', () => setTimeout(() => { if (document.activeElement !== input) closeSlash(); }, 0));
  input.addEventListener('keydown', event => {
    if (event.isComposing || onSlashKey(event)) return;
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('aide-code-form').requestSubmit(); }
  });
  effortMenu = createMenuController($('aide-code-effort-menu'), { onClose: () => $('aide-code-effort').setAttribute('aria-expanded', 'false') });
  $('aide-code-effort').addEventListener('click', event => {
    if (!$('aide-code-effort-menu').hidden) { effortMenu.close(); return; }
    renderEffortMenu();
    $('aide-code-effort').setAttribute('aria-expanded', 'true');
    effortMenu.open({ source: event.currentTarget });
  });
  $('aide-code-goal-clear').addEventListener('click', () => { input.value = '/goal clear'; $('aide-code-form').requestSubmit(); });
  $('aide-code-context').addEventListener('click', () => { input.value = '/context'; $('aide-code-form').requestSubmit(); });
  $('aide-code-scroll').addEventListener('scroll', () => { if (nearBottom()) $('aide-code-jump').hidden = true; }, { passive: true });
  $('aide-code-jump').addEventListener('click', () => {
    const scroller = $('aide-code-scroll');
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    $('aide-code-jump').hidden = true;
  });
  $('aide-code-form').addEventListener('submit', send);
  $('aide-code-stop').addEventListener('click', async () => {
    try { await post(`${chatPath(current.projectId, current.chatId)}/stop`); } catch (error) { setError(error.message); }
  });
  $('aide-code-delete').addEventListener('click', deleteChat);
  $('aide-code-add').addEventListener('click', openAdd);
  $('aide-code-start-add').addEventListener('click', openAdd);
  $('aide-code-rail-back').addEventListener('click', () => { setPane('rail'); $('aide-code-add').focus(); });
  $('aide-code-pi-retry').addEventListener('click', async () => {
    try { pi = (await post('/api/aide/code/install')).pi || pi; } catch (error) { setError(error.message); }
    void loadStatus();
  });
  $('aide-code-folder-form').addEventListener('submit', event => { event.preventDefault(); void browse($('aide-code-folder-path').value); });
  // typing a path wins over a listing still on its way
  $('aide-code-folder-path').addEventListener('input', () => { browseTicket++; });
  $('aide-code-folder-up').addEventListener('click', event => browse(event.currentTarget.dataset.path));
  $('aide-code-folder-use').addEventListener('click', addProject);

  harnessMenu = createMenuController($('aide-code-harness-menu'), { onClose: () => $('aide-code-harness').setAttribute('aria-expanded', 'false') });
  $('aide-code-harness').addEventListener('click', async event => {
    if (!$('aide-code-harness-menu').hidden) { harnessMenu.close(); return; }
    const source = event.currentTarget;
    if (!catalogRows.length) await loadCatalog();
    renderHarnessMenu();
    source.setAttribute('aria-expanded', 'true');
    harnessMenu.open({ source });
  });
  $('aide-code-harness-list').addEventListener('click', onHarnessAction);
  menu = createMenuController($('aide-code-model-menu'), { onClose: () => $('aide-code-model').setAttribute('aria-expanded', 'false') });
  $('aide-code-model').addEventListener('click', event => {
    if (!$('aide-code-model-menu').hidden) { menu.close(); return; }
    renderModelMenu();
    $('aide-code-model').setAttribute('aria-expanded', 'true');
    menu.open({ source: event.currentTarget });
  });
  projectMenu = createMenuController($('aide-code-project-menu'));
  $('aide-code-project-menu').addEventListener('click', event => {
    const action = event.target.closest('[data-project-action]')?.dataset.projectAction;
    if (!action) return;
    projectMenu.close({ restoreFocus: action === 'new' ? false : true });
    if (action === 'new') startChat(menuProject);
    else void forgetProject(menuProject);
  });

  $('aide-code-projects').addEventListener('click', async event => {
    const toggle = event.target.closest('[data-project-id].acw-project-toggle');
    const more = event.target.closest('[data-project-menu]');
    const chat = event.target.closest('[data-chat-id]');
    const fresh = event.target.closest('[data-new-chat]');
    if (more) {
      menuProject = more.dataset.projectMenu;
      const box = $('aide-code-project-menu');
      box.style.top = `${more.offsetTop + more.offsetHeight}px`;
      projectMenu.open({ source: more });
    } else if (toggle) {
      const id = toggle.dataset.projectId;
      if (expanded.has(id)) expanded.delete(id);
      else { expanded.add(id); await loadChats(id); }
      renderRail();
      $('aide-code-projects').querySelector(`.acw-project-toggle[data-project-id="${CSS.escape(id)}"]`)?.focus();
    } else if (chat) void openChat(chat.dataset.projectId, chat.dataset.chatId);
    else if (fresh) startChat(fresh.dataset.newChat);
  });
}

export async function openAideCodingWorkspace({ refresh = true } = {}) {
  initAideCodingWorkspace(); if (!host) return;
  host.hidden = false;
  if (!refresh && (current.projectId || projects.length)) {
    if (current.chatId) void openChat(current.projectId, current.chatId, { keepScroll: true });
    return;
  }
  if (!opening) {
    const slow = setTimeout(() => { $('aide-code-loading').hidden = false; }, 150);
    opening = (async () => {
      try {
        await loadStatus();
        await loadProjects();
        if (current.chatId) await openChat(current.projectId, current.chatId);
        else if (current.projectId) startChat(current.projectId);
        else showFirst();
      } catch (error) { setError(error.message); }
    })().finally(() => { opening = null; clearTimeout(slow); $('aide-code-loading').hidden = true; });
  }
  return opening;
}

export function closeAideCodingWorkspace() {
  ++version; if (host) host.hidden = true;
  closeLive(); clearTimeout(installTimer);
  menu?.close({ restoreFocus: false }); projectMenu?.close({ restoreFocus: false });
  effortMenu?.close({ restoreFocus: false }); closeSlash();
}

// older entry points from the Aide task tools
export const initAideCoding = initAideCodingWorkspace;
export const openAideCoding = openAideCodingWorkspace;
export const mountAideCodingPanel = initAideCodingWorkspace;
