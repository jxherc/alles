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
};
const icon = name => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (icons[name] || '') + '</svg>';

let host = null, opening = null;
let projects = [], chats = new Map(), expanded = new Set();
let current = { projectId: '', chatId: '' };
let models = [], model = null, pi = { state: 'missing' };
let live = null, liveSeq = 0, busy = false, sending = false, installTimer = null;
let streaming = null, toolRows = new Map(), version = 0;
let menu = null, projectMenu = null, menuProject = '';

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
  const copy = {
    installing: 'installing pi on this machine…',
    needs_node: pi.error || 'pi needs node 22.19 or newer on this machine',
    failed: `pi could not install: ${pi.error || 'unknown error'}`,
    missing: 'pi is not installed yet',
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
}

function toolSummary(name, rawArgs) {
  let args = {};
  try { args = JSON.parse(rawArgs || '{}'); } catch { /* cut off by the server; show the name only */ }
  const detail = args.command || args.path || args.pattern || args.file_path || '';
  return detail ? `${name} ${String(detail).split('\n')[0]}` : name;
}

function toolRow(id, name, args) {
  if (id && toolRows.has(id)) return toolRows.get(id);
  const row = el('details', 'acw-tool');
  const summary = el('summary');
  summary.append(el('span', 'acw-tool-name', toolSummary(name || 'tool', args)), el('span', 'acw-tool-state', 'running'));
  const output = el('pre', 'acw-tool-output');
  output.hidden = true;
  row.append(summary, output);
  row.dataset.state = 'running';
  if (id) toolRows.set(id, row);
  $('aide-code-log').append(row);
  return row;
}

function finishTool(id, ok, output) {
  const row = toolRows.get(id) || toolRow(id, 'tool', '');
  row.dataset.state = ok ? 'done' : 'failed';
  row.querySelector('.acw-tool-state').textContent = ok ? '' : 'failed';
  const pre = row.querySelector('.acw-tool-output');
  pre.textContent = output || (ok ? 'no output' : 'failed with no output');
  pre.hidden = false;
}

function assistantBlock(text, error = '') {
  const block = el('div', 'acw-msg acw-assistant');
  if (text) block.innerHTML = mdToHtml(text);
  if (error) block.append(el('p', 'acw-msg-error', error));
  return block;
}

function render(item) {
  const log = $('aide-code-log');
  if (item.kind === 'user') {
    const bubble = el('div', 'acw-msg acw-user');
    bubble.textContent = item.text;
    log.append(bubble);
  } else if (item.kind === 'delta') {
    if (!streaming) { streaming = assistantBlock(''); streaming.dataset.text = ''; log.append(streaming); }
    streaming.dataset.text += item.text;
    streaming.innerHTML = mdToHtml(streaming.dataset.text);
  } else if (item.kind === 'assistant') {
    const block = assistantBlock(item.text, item.error);
    if (streaming) { streaming.replaceWith(block); streaming = null; }
    else if (item.text || item.error) log.append(block);
    for (const tool of item.tools || []) toolRow(tool.id, tool.name, tool.args);
  } else if (item.kind === 'tool') {
    toolRow(item.id, item.name, item.args);
  } else if (item.kind === 'tool_done') {
    finishTool(item.id, item.ok, item.output);
  } else if (item.kind === 'error') {
    log.append(el('p', 'acw-msg-error', item.text));
  } else if (item.kind === 'note') {
    log.append(el('p', 'acw-note', item.text));
  }
}

function setBusy(value) {
  busy = value;
  $('aide-code-stop').hidden = !busy;
  $('aide-code-status').textContent = busy ? 'pi is working…' : '';
  host.dataset.busy = String(busy);
}

function renderStats(stats = {}) {
  const parts = [];
  if (stats.tokens_per_second) parts.push([`${stats.tokens_per_second} tok/s`, '']);
  if (stats.cache_hit_rate != null) parts.push([`cache ${Math.round(stats.cache_hit_rate * 100)}%`, '']);
  // context is the first thing to go on a phone
  if (stats.context_percent != null) parts.push([`context ${Math.round(stats.context_percent)}%`, 'acw-stats-context']);
  $('aide-code-stats').replaceChildren(...parts.map(([text, className], index) => el('span', className, (index ? ' · ' : '') + text)));
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

function scrollLog() {
  const scroller = $('aide-code-scroll');
  if (scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160) scroller.scrollTop = scroller.scrollHeight;
}

async function refreshChats(projectId) { await loadChats(projectId); renderRail(); }

function resetLog() {
  $('aide-code-log').replaceChildren();
  streaming = null; toolRows = new Map();
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
  try {
    const data = await api(chatPath(projectId, chatId));
    if (ticket !== version) return;
    resetLog();
    for (const item of data.items) render(item);
    if (data.partial) render({ kind: 'delta', text: data.partial });
    if (data.model?.model) pickModel(models.find(m => m.model === data.model.model && (!data.model.endpoint_id || m.endpoint_id === data.model.endpoint_id)) || model, { remote: false });
    renderStats(data.stats);
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
  expanded.add(projectId);
  renderRail();
  resetLog();
  const row = project(projectId);
  $('aide-code-title').textContent = 'new chat';
  showPath(row?.path);
  $('aide-code-delete').hidden = true;
  showView('chat'); setPane('main');
  updateComposer();
  $('aide-code-input').focus();
}

function updateComposer() {
  const row = project();
  const input = $('aide-code-input');
  const ready = pi.state === 'ready' && !!model && !!row;
  input.disabled = !row;
  input.placeholder = row ? `ask pi to work in ${row.name}` : 'pick a project first';
  $('aide-code-send').disabled = !ready || sending || !input.value.trim();
  $('aide-code-model-label').textContent = model ? model.model : 'no coding model';
  $('aide-code-model').disabled = !models.length;
  const hint = !models.length ? 'add a model with an api key in settings → models to code with pi'
    : pi.state !== 'ready' ? 'pi will be ready once it finishes installing' : '';
  $('aide-code-hint').textContent = hint;
  $('aide-code-hint').hidden = !hint;
}

async function send(event) {
  event.preventDefault();
  const input = $('aide-code-input');
  const text = input.value.trim();
  if (!text || sending || $('aide-code-send').disabled) return;
  sending = true; updateComposer(); setError();
  const { projectId, chatId } = current;
  const choice = model ? { endpoint_id: model.endpoint_id, model: model.model } : {};
  try {
    if (!chatId) {
      const made = await post(chatPath(projectId), { text, ...choice });
      input.value = ''; autosizeTextarea(input);
      current = { projectId, chatId: made.chat_id };
      await refreshChats(projectId);
      $('aide-code-title').textContent = text.slice(0, 80);
      $('aide-code-delete').hidden = false;
      follow(projectId, made.chat_id, made.seq - 1);
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
    .catch(error => setError(error.message));
}

function renderModelMenu() {
  const list = $('aide-code-model-menu');
  list.replaceChildren();
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
  pi = data.pi; models = data.models || [];
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
        <section id="aide-code-start" class="acw-content acw-start" hidden>
          <p>pi reads, edits and runs code in a folder on the machine that runs alles. it does not ask before each command, so give it a project folder you're happy for it to change.</p>
          <button type="button" id="aide-code-start-add" class="acw-action acw-primary">add a project folder</button>
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
          <div id="aide-code-scroll" class="acw-scroll"><div id="aide-code-log" class="acw-log" role="log" aria-label="chat with pi"></div></div>
          <form id="aide-code-form" class="acw-composer">
            <div id="aide-code-question" class="acw-question" role="group" aria-label="pi is asking" hidden></div>
            <p id="aide-code-hint" class="acw-muted" hidden></p>
            <div class="acw-entry">
              <textarea id="aide-code-input" rows="1" maxlength="50000" data-kokuen-entry="autogrow" aria-label="message pi"></textarea>
              <div class="acw-entry-foot">
                <div class="acw-model">
                  <button type="button" id="aide-code-model" class="acw-action" aria-haspopup="menu" aria-expanded="false" aria-controls="aide-code-model-menu"><span id="aide-code-model-label">no coding model</span>${icon('chevron')}</button>
                  <div id="aide-code-model-menu" class="acw-menu acw-menu-up" role="menu" aria-label="coding model" hidden></div>
                </div>
                <span id="aide-code-stats" class="acw-stats"></span>
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
  input.addEventListener('input', updateComposer);
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('aide-code-form').requestSubmit(); }
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
    opening = (async () => {
      try {
        await loadStatus();
        await loadProjects();
        if (current.chatId) await openChat(current.projectId, current.chatId);
        else if (current.projectId) startChat(current.projectId);
        else showFirst();
      } catch (error) { setError(error.message); }
    })().finally(() => { opening = null; });
  }
  return opening;
}

export function closeAideCodingWorkspace() {
  ++version; if (host) host.hidden = true;
  closeLive(); clearTimeout(installTimer);
  menu?.close({ restoreFocus: false }); projectMenu?.close({ restoreFocus: false });
}

// older entry points from the Aide task tools
export const initAideCoding = initAideCodingWorkspace;
export const openAideCoding = openAideCodingWorkspace;
export const mountAideCodingPanel = initAideCodingWorkspace;
