import { toast } from './util.js';
import { confirm as _dlgConfirm, prompt as _dlgPrompt } from './dialog.js';
import { renderProjectFolders, loadProjects, getProjects } from './projects.js';
import { applyResponsePrivacy, stripEmojis, welcomeEnabled } from './privacy.js';

let _sessions = { today: [], yesterday: [], earlier: [] };
let _activeId = null;
let _allSessions = [];  // flat list for search
const SESSION_ORDER_KEY = 'aide-session-order';

export function getActiveId() { return _activeId; }

// just fetch + render the sidebar. no navigation — safe to call after any mutation.
export async function loadSessions() {
  try {
    const r = await fetch('/api/sessions');
    _sessions = await r.json();
    _allSessions = [..._sessions.today, ..._sessions.yesterday, ..._sessions.earlier];
    _applySessionOrder();
    renderSidebar(document.getElementById('session-search')?.value || '');
    // active session got deleted/archived elsewhere → drop the stale highlight
    if (_activeId && !_allSessions.find(s => s.id === _activeId)) _activeId = null;
  } catch (e) {
    console.error('loadSessions', e);
  }
}

// called once on boot. only restore a session from a deep-link hash —
// a bare localhost:8000 always opens a fresh chat (like claude.ai/new).
export async function initSessions() {
  await loadSessions();
  const hash = location.hash.slice(1);
  if (hash && _allSessions.find(s => s.id === hash)) {
    await selectSession(hash);
  } else {
    newChat();
  }
}

// fresh empty chat — does NOT create a db row. the session is created
// lazily on the first send (see chat.js), so empty chats never persist.
export function newChat() {
  _activeId = null;
  window._currentSession = null;
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  document.getElementById('messages').innerHTML = '';
  document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
  showWelcome();
  const ta = document.getElementById('composer-ta');
  if (ta) { ta.value = ''; ta.style.height = 'auto'; ta.focus(); }
}

// mark a session active without re-fetching/re-rendering its messages.
// used after lazy-create so the in-flight stream isn't wiped.
export function markActive(id) {
  _activeId = id;
  if (id) location.hash = id;
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });
}


export function renderSidebar(filter = '') {
  const list = document.getElementById('session-list');
  const fl = filter.toLowerCase();

  let src = _allSessions;
  if (fl) {
    src = _allSessions.filter(s => s.name.toLowerCase().includes(fl));
  }

  if (!src.length) {
    list.innerHTML = '<div class="empty-sessions">no chats yet</div>';
    return;
  }

  let html = '';

  if (!fl) {
    if (_sessions.today.length)     html += renderGroup('today', _sessions.today);
    if (_sessions.yesterday.length) html += renderGroup('yesterday', _sessions.yesterday);
    if (_sessions.earlier.length)   html += renderGroup('earlier', _sessions.earlier);
  } else {
    html = src.map(s => renderItem(s)).join('');
  }

  list.innerHTML = html;

  // inject project folders above the session groups
  if (!fl) renderProjectFolders(_allSessions, id => selectSession(id));

  list.querySelectorAll('.session-item').forEach(el => {
    const sid = el.dataset.id;
    if (sid === _activeId) el.classList.add('active');
    el.addEventListener('click', () => selectSession(sid));
    el.addEventListener('contextmenu', e => { e.preventDefault(); openCtxMenu(e, sid); });
    el.querySelector('.star')?.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      toggleSessionStar(sid);
    });
    _bindSessionDrag(el);
    // double-click to rename
    el.querySelector('.session-name')?.addEventListener('dblclick', e => {
      e.stopPropagation();
      startRename(el, sid);
    });
  });
}

function renderGroup(label, items) {
  return `<span class="section-label">${label}</span>` + items.map(s => renderItem(s)).join('');
}

function renderItem(s) {
  const starred  = s.starred   ? ' starred'   : '';
  const incog    = s.incognito ? ' incognito' : '';
  const icon     = s.incognito ? '<span class="incognito-icon" title="incognito" aria-hidden="true"></span>' : '';
  return `<div class="session-item${starred}${incog}" data-id="${s.id}" draggable="true">
  <div class="session-dot"></div>
  ${icon}<span class="session-name">${escHtml(s.name)}</span>
  <button class="star" title="${s.starred ? 'unstar' : 'star'}" aria-label="${s.starred ? 'unstar session' : 'star session'}"></button>
</div>`;
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _loadSessionOrder() {
  try {
    const arr = JSON.parse(localStorage.getItem(SESSION_ORDER_KEY) || '[]');
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function _saveSessionOrder(order) {
  localStorage.setItem(SESSION_ORDER_KEY, JSON.stringify(order));
}

function _applySessionOrder() {
  const order = _loadSessionOrder();
  if (!order.length) return;
  const pos = new Map(order.map((id, idx) => [id, idx]));
  const sorter = (a, b) => (pos.get(a.id) ?? 999999) - (pos.get(b.id) ?? 999999);
  _allSessions.sort(sorter);
  ['today', 'yesterday', 'earlier'].forEach(k => _sessions[k]?.sort(sorter));
}

function _bindSessionDrag(el) {
  el.addEventListener('dragstart', e => {
    e.dataTransfer?.setData('text/plain', el.dataset.id);
    e.dataTransfer?.setDragImage?.(el, 12, 12);
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', () => el.classList.remove('dragging'));
  el.addEventListener('dragover', e => e.preventDefault());
  el.addEventListener('drop', e => {
    e.preventDefault();
    const fromId = e.dataTransfer?.getData('text/plain');
    const toId = el.dataset.id;
    if (!fromId || !toId || fromId === toId) return;
    _moveSessionBefore(fromId, toId);
  });
}

function _moveSessionBefore(fromId, toId) {
  const ids = _allSessions.map(s => s.id);
  const order = _loadSessionOrder().filter(id => ids.includes(id));
  ids.forEach(id => { if (!order.includes(id)) order.push(id); });
  const fromIdx = order.indexOf(fromId);
  const toIdx = order.indexOf(toId);
  if (fromIdx < 0 || toIdx < 0) return;
  order.splice(fromIdx, 1);
  order.splice(order.indexOf(toId), 0, fromId);
  _saveSessionOrder(order);
  _applySessionOrder();
  renderSidebar(document.getElementById('session-search')?.value || '');
}

async function toggleSessionStar(id) {
  const s = _allSessions.find(x => x.id === id);
  if (!s) return;
  const next = !s.starred;
  const r = await fetch(`/api/sessions/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ starred: next }),
  });
  if (!r.ok) { toast('star failed', 'error'); return; }
  s.starred = next;
  const grouped = [..._sessions.today, ..._sessions.yesterday, ..._sessions.earlier].find(x => x.id === id);
  if (grouped) grouped.starred = next;
  renderSidebar(document.getElementById('session-search')?.value || '');
}


export async function selectSession(id) {
  _activeId = id;
  location.hash = id;

  // update active class
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });

  try {
    const r = await fetch(`/api/sessions/${id}/history`);
    const data = await r.json();
    window._currentSession = data.session;
    renderMessages(data.messages);
    showMessages();

    // update topbar model label if session has a model
    if (data.session.model) {
      document.getElementById('model-label').textContent = data.session.model;
    }
    updateSessionHeader(data.session);
    // refresh persona button
    try {
      window._refreshPersonaBtn?.();
    } catch (e) {}
  } catch (e) {
    console.error('selectSession', e);
  }
}


function renderMessages(msgs) {
  const container = document.getElementById('messages');
  container.innerHTML = '';
  for (const m of msgs) {
    if (m.role === 'user') {
      const row = appendUserMsg(m.content);
      row.dataset.msgId = m.id;
    } else if (m.role === 'system' && m.content?.startsWith('[conversation summary]')) {
      // compact divider
      const div = document.createElement('div');
      div.className = 'compact-divider';
      div.innerHTML = '<span>context compacted</span>';
      container.appendChild(div);
    } else if (m.role === 'assistant') {
      const { row, wrap } = appendAiMsg(m.content, m.meta?.thinking);
      row.dataset.msgId = m.id;
      // re-open artifact button from history
      if (m.meta?.artifacts?.length) {
        wrap.dataset.artifacts = JSON.stringify(m.meta.artifacts);
        const actions = wrap.querySelector('.msg-actions');
        if (actions) {
          const btn = document.createElement('button');
          btn.className = 'act-btn';
          btn.textContent = 'open artifact';
          btn.setAttribute('onclick', 'openArtifactFromMsg(this)');
          actions.appendChild(btn);
        }
      }
    }
  }
  // wire edit buttons after all messages are rendered
  _wireEditButtons(container);
  container.scrollTop = container.scrollHeight;
}


export function appendUserMsg(text) {
  const { row } = _makeRow('user');
  row.innerHTML = `<div class="user-wrap">
    <div class="user-bubble">${escHtml(text)}</div>
    <button class="msg-edit-btn" title="edit"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3a2.8 2.8 0 0 1 4 4L7 21l-4 1 1-4Z"></path><path d="m15 5 4 4"></path></svg></button>
  </div>`;
  document.getElementById('messages').appendChild(row);
  scrollDown();
  return row;
}


export function appendAiMsg(text, thinking) {
  const { row, wrap, body } = _makeAiRow();
  if (thinking) {
    const tb = document.createElement('details');
    tb.className = 'thinking-block';
    tb.innerHTML = '<summary>thinking</summary><div class="thinking-content"></div>';
    tb.querySelector('.thinking-content').textContent = thinking;
    body.appendChild(tb);
  }
  // strip artifact tags from display
  const displayText = text ? text.replace(/<aide-artifact[^>]*>[\s\S]*?<\/aide-artifact>/g, '').trim() : '';
  const content = document.createElement('div');
  content.className = 'ai-content';
  content.innerHTML = displayText ? _md(stripEmojis(displayText)) : '';
  applyResponsePrivacy(content);
  body.appendChild(content);
  body.classList.add('done');

  const actions = document.createElement('div');
  actions.className = 'msg-actions';
  actions.innerHTML = `<button class="act-btn" onclick="copyMsg(this)">copy</button>
    <button class="msg-regen-btn act-btn" title="regenerate">regen</button>`;
  wrap.appendChild(actions);

  document.getElementById('messages').appendChild(row);
  scrollDown();
  return { row, wrap, body, content };
}


export function createStreamingAiRow() {
  const { row, wrap, body } = _makeAiRow();
  document.getElementById('messages').appendChild(row);
  scrollDown();
  return { row, body };
}


function _makeRow(type) {
  const row = document.createElement('div');
  row.className = 'msg-row';
  return { row };
}

function _makeAiRow() {
  const row = document.createElement('div');
  row.className = 'msg-row';
  const wrap = document.createElement('div');
  wrap.className = 'ai-wrap';
  const body = document.createElement('div');
  body.className = 'ai-body';
  wrap.appendChild(body);
  row.appendChild(wrap);
  return { row, wrap, body };
}


function _wireEditButtons(container) {
  container.querySelectorAll('.msg-edit-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const wrap = btn.closest('.user-wrap');
      const bubble = wrap?.querySelector('.user-bubble');
      const row = btn.closest('.msg-row');
      if (!bubble) return;
      const original = bubble.innerText;
      const ta = document.createElement('textarea');
      ta.className = 'edit-inline';
      ta.value = original;
      bubble.replaceWith(ta);
      ta.focus();

      const save = async () => {
        const newText = ta.value.trim() || original;
        const msgId = row?.dataset.msgId;
        const sid = _activeId;
        if (msgId && sid) {
          await fetch(`/api/sessions/${sid}/messages/${msgId}/edit`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ content: newText }),
          });
        }
        // remove all subsequent rows from DOM
        let next = row?.nextElementSibling;
        while (next) { const n = next.nextElementSibling; next.remove(); next = n; }
        // replace textarea with bubble
        const newBubble = document.createElement('div');
        newBubble.className = 'user-bubble';
        newBubble.textContent = newText;
        ta.replaceWith(newBubble);
        // re-send
        const { sendMessage } = await import('./chat.js');
        sendMessage(newText);
      };

      ta.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save(); }
        if (e.key === 'Escape') {
          const b = document.createElement('div');
          b.className = 'user-bubble'; b.textContent = original;
          ta.replaceWith(b);
        }
      });
      ta.addEventListener('blur', () => {
        // only save if still in DOM
        if (ta.isConnected) save();
      });
    });
  });

  container.querySelectorAll('.msg-regen-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const aiRow = btn.closest('.msg-row');
      // find the preceding user row
      let prev = aiRow?.previousElementSibling;
      while (prev && !prev.querySelector('.user-bubble')) {
        prev = prev.previousElementSibling;
      }
      const userText = prev?.querySelector('.user-bubble')?.innerText;
      const userMsgId = prev?.dataset.msgId;
      if (!userText) return;

      const sid = _activeId;
      if (userMsgId && sid) {
        // edit user msg with same content — backend deletes everything after it
        await fetch(`/api/sessions/${sid}/messages/${userMsgId}/edit`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ content: userText }),
        }).catch(() => {});
      }
      // remove AI row + anything after from DOM
      let next = aiRow?.nextElementSibling;
      while (next) { const n = next.nextElementSibling; next.remove(); next = n; }
      aiRow?.remove();

      const { sendMessage } = await import('./chat.js');
      sendMessage(userText);
    });
  });
}

// lazy md render — avoids import cycle with chat.js
function _md(text) {
  // pull from window if util.js already loaded it
  if (window._mdToHtml) return window._mdToHtml(text);
  // basic fallback
  return `<p>${text.replace(/\n\n/g,'</p><p>').replace(/\n/g,'<br>')}</p>`;
}


export function scrollDown() {
  const chat = document.getElementById('chat');
  chat.scrollTop = chat.scrollHeight;
}


// claude-style greeting: time-of-day, your name, and a little variety per refresh
function _escName(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function greetingHtml() {
  const h = new Date().getHours();
  const name = (localStorage.getItem('alles-name') || '').trim();
  let pool;
  if (h < 5)        pool = ['still up?', 'burning the midnight oil', 'the world\'s asleep, perfect',
                            'night owl mode', 'quiet hours, big ideas', 'one more thing?', 'can\'t sleep?',
                            'late-night session'];
  else if (h < 12)  pool = ['good morning', 'morning', 'rise and shine', 'top of the morning',
                            'fresh start', 'let\'s make today count', 'the day is yours', 'coffee first?'];
  else if (h < 18)  pool = ['good afternoon', 'afternoon', 'good to see you', 'back at it',
                            'midday momentum', 'what are we shipping today?', 'let\'s keep rolling', 'ready when you are'];
  else              pool = ['good evening', 'evening', 'welcome back', 'the night is young',
                            'what are we building tonight?', 'prime hours', 'let\'s get into it', 'golden hour for ideas'];
  const pick = pool[Math.floor(Math.random() * pool.length)];
  return _withName(pick, name);
}

// drop the name in before any trailing ? . ! so "one more thing?" → "one more thing, eric?"
function _withName(g, name) {
  if (!name) return _escName(g);
  const punct = /[?.!]$/.test(g) ? g.slice(-1) : '';
  const base = punct ? g.slice(0, -1) : g;
  return `${_escName(base)}, <span class="accent">${_escName(name)}</span>${punct}`;
}

export function showWelcome() {
  if (welcomeEnabled()) {
    const g = document.getElementById('welcome-greeting');
    if (g) g.innerHTML = greetingHtml();
    document.getElementById('welcome').style.display = 'flex';
    document.getElementById('messages').style.display = 'none';
  } else {
    document.getElementById('welcome').style.display = 'none';
    document.getElementById('messages').style.display = 'flex';
  }
  updateSessionHeader(window._currentSession || null);
}

export function showMessages() {
  document.getElementById('welcome').style.display = 'none';
  document.getElementById('messages').style.display = 'flex';
  updateSessionHeader(window._currentSession || null);
}

export function updateSessionHeader(session) {
  const actBtn   = document.getElementById('session-actions-btn');
  const tokCount = document.getElementById('session-token-count');
  if (!session) {
    if (actBtn)   actBtn.style.display   = 'none';
    if (tokCount) { tokCount.style.display = 'none'; tokCount.textContent = ''; }
    return;
  }
  if (actBtn)   actBtn.style.display   = '';
  // token count stays hidden until chat.js populates it
}

export async function exportActiveSessionMarkdown() {
  if (!_activeId) { toast('no active chat', 'error'); return; }
  const r = await fetch(`/api/sessions/${_activeId}/history`);
  if (!r.ok) { toast('export failed', 'error'); return; }
  const { session, messages } = await r.json();
  const md = messages
    .map(m => `**${m.role}:**\n\n${m.content}`)
    .join('\n\n---\n\n');
  const blob = new Blob([md], { type: 'text/markdown' });
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(blob),
    download: `${(session?.name || 'chat').replace(/[^a-z0-9]/gi, '-')}.md`,
  });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}


export async function createSession(model = '', endpointId = '', options = {}) {
  const r = await fetch('/api/sessions', {
    method: 'POST',
    headers: {'content-type':'application/json'},
    body: JSON.stringify({ model, endpoint_id: endpointId, incognito: !!options.incognito }),
  });
  if (!r.ok) return null;
  const s = await r.json();
  await loadSessions();
  return s;
}


export function updateSessionName(id, name) {
  _allSessions.forEach(s => { if (s.id === id) s.name = name; });
  // flash the active item
  const el = document.querySelector(`.session-item[data-id="${id}"] .session-name`);
  if (el) {
    el.textContent = name;
    el.classList.add('flashing');
    el.addEventListener('animationend', () => el.classList.remove('flashing'), { once: true });
  }
}


function startRename(el, id) {
  const nameEl = el.querySelector('.session-name');
  const current = nameEl.textContent;
  const inp = document.createElement('input');
  inp.value = current;
  inp.style.cssText = 'background:none;border:none;border-bottom:1px solid var(--muted);color:var(--text);font:inherit;font-size:0.8rem;width:100%;outline:none;padding:0';
  nameEl.replaceWith(inp);
  inp.focus(); inp.select();

  const commit = async () => {
    const name = inp.value.trim() || current;
    await fetch(`/api/sessions/${id}`, {
      method:'PATCH', headers:{'content-type':'application/json'},
      body: JSON.stringify({ name }),
    });
    inp.replaceWith(Object.assign(document.createElement('span'), { className:'session-name', textContent:name }));
    updateSessionName(id, name);
  };
  inp.addEventListener('blur', commit);
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
    if (e.key === 'Escape') { inp.value = current; inp.blur(); }
  });
}


function openCtxMenu(e, id) {
  const menu = document.getElementById('ctx-menu');
  const s = _allSessions.find(x => x.id === id);
  if (!s) return;

  const projects = getProjects();
  const projectItems = projects.map(p =>
    `<div class="ctx-item" data-action="move-project" data-pid="${p.id}">→ ${p.name}</div>`
  ).join('');
  menu.innerHTML = `
    <div class="ctx-item" data-action="rename">rename</div>
    <div class="ctx-item" data-action="star">${s.starred ? 'unstar' : 'star'}</div>
    <div class="ctx-item" data-action="archive">archive</div>
    ${projectItems}
    <div class="ctx-item" data-action="new-project">+ new project</div>
    <div class="ctx-item danger" data-action="delete">delete</div>
  `;
  menu.style.display = 'block';
  menu.style.left = e.clientX + 'px';
  menu.style.top = e.clientY + 'px';

  const hide = () => menu.style.display = 'none';
  document.addEventListener('click', hide, { once: true });

  menu.querySelectorAll('.ctx-item').forEach(item => {
    item.addEventListener('click', async () => {
      const action = item.dataset.action;
      if (action === 'rename') {
        const el = document.querySelector(`.session-item[data-id="${id}"]`);
        if (el) startRename(el, id);
      } else if (action === 'star') {
        await fetch(`/api/sessions/${id}`, {
          method:'PATCH', headers:{'content-type':'application/json'},
          body: JSON.stringify({ starred: !s.starred }),
        });
        await loadSessions();
      } else if (action === 'archive') {
        await fetch(`/api/sessions/${id}/archive`, { method: 'POST' });
        await loadSessions();
        if (id === _activeId || _activeId === null) newChat();
      } else if (action === 'move-project') {
        const pid = item.dataset.pid;
        await fetch(`/api/projects/${pid}/sessions/${id}`, { method: 'POST' });
        await loadProjects();
        await loadSessions();
        toast('moved to project', 'success');
      } else if (action === 'new-project') {
        const name = await _dlgPrompt('project name:');
        if (!name?.trim()) return;
        const r = await fetch('/api/projects', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ name: name.trim() }),
        });
        if (r.ok) {
          const p = await r.json();
          await fetch(`/api/projects/${p.id}/sessions/${id}`, { method: 'POST' });
          await loadProjects();
          await loadSessions();
          toast(`project "${name}" created`, 'success');
        }
      } else if (action === 'delete') {
        if (!await _dlgConfirm('delete this session?')) return;
        const res = await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
        if (!res.ok) { toast('unstar before deleting', 'error'); return; }
        const wasActive = id === _activeId;
        await loadSessions();
        if (wasActive) newChat();
      }
    });
  });
}
