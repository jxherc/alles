import { toast } from './util.js';
import { confirm as _dlgConfirm, prompt as _dlgPrompt } from './dialog.js';
import { renderProjectFolders, loadProjects, getProjects, createProject, assignSession } from './projects.js';
import { applyResponsePrivacy, stripEmojis, welcomeEnabled } from './privacy.js';
import { renderAgentSteps } from './agentview.js';
import { isIncognitoMode } from './modes.js';
import { getCurrentEndpoint, getSelected } from './models.js';

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
// ── per-conversation composer drafts ───────────────────────────────────────
// unsent text stays with the convo you typed it in — switch away + back, it's
// still there. keyed by session id (or 'new' for the not-yet-created chat).
const _draftKey = id => 'aide-draft-' + (id || 'new');
export function saveDraft() {
  const ta = document.getElementById('composer-ta');
  if (!ta) return;
  const k = _draftKey(_activeId);
  if (ta.value.trim()) localStorage.setItem(k, ta.value);
  else localStorage.removeItem(k);
}
export function restoreDraft(id) {
  const ta = document.getElementById('composer-ta');
  if (!ta) return;
  ta.value = localStorage.getItem(_draftKey(id)) || '';
  ta.style.height = 'auto';
  ta.dispatchEvent(new Event('input', { bubbles: true }));   // autosize + send-btn state
}
export function clearDraft(id) {
  localStorage.removeItem(_draftKey(id === undefined ? _activeId : id));
}

export function newChat() {
  saveDraft();              // keep whatever was half-typed in the outgoing convo
  _activeId = null;
  window._currentSession = null;
  window._pendingPersona = null;       // fresh chat starts with no persona pre-picked
  window._refreshPersonaBtn?.();        // keep the persona button visible + pickable pre-send
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  document.getElementById('messages').innerHTML = '';
  document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
  showWelcome();
  const ta = document.getElementById('composer-ta');
  if (ta) { ta.style.height = 'auto'; ta.focus(); }
  restoreDraft(null);       // bring back the 'new chat' draft if any
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
  if (!fl) renderProjectFolders(_allSessions, id => selectSession(id), () => loadSessions());

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
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
    e.dataTransfer?.setData('text/plain', el.dataset.id);     // reorder
    e.dataTransfer?.setData('text/session', el.dataset.id);   // drop-into-project
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
  if (id !== _activeId) saveDraft();   // stash the outgoing convo's unsent text
  _activeId = id;
  location.hash = id;
  restoreDraft(id);                    // and bring up this convo's draft

  // if we're sitting on a tools page (models/memory/etc), get back to chat first
  // — otherwise the messages render behind the still-open tool view
  window._enterChatView?.();

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
      import('./models.js').then(m => {
        document.getElementById('model-label').textContent = m.prettyModel(data.session.model);
      });
    }
    updateSessionHeader(data.session);
    window._setMode?.(data.session.mode || 'chat');   // restore this convo's last mode
    // refresh persona button
    try {
      window._refreshPersonaBtn?.();
    } catch (e) {}
    // 10b — if a background agent run is still going for this session, reattach to it
    import('./bgrun.js').then(m => m.reattach(id)).catch(() => {});
  } catch (e) {
    console.error('selectSession', e);
  }
}

// let bgrun.js refresh the conversation once a background run finishes
window._reloadActiveSession = () => { if (_activeId) selectSession(_activeId); };


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
      const { row, wrap } = appendAiMsg(m.content, m.meta?.thinking, m.meta?.tool_steps);
      row.dataset.msgId = m.id;
      const actions = wrap.querySelector('.msg-actions');
      // re-open artifact button from history
      if (m.meta?.artifacts?.length) {
        wrap.dataset.artifacts = JSON.stringify(m.meta.artifacts);
        if (actions) {
          const btn = document.createElement('button');
          btn.className = 'act-btn';
          btn.textContent = 'open artifact';
          btn.setAttribute('onclick', 'openArtifactFromMsg(this)');
          actions.appendChild(btn);
        }
      }
      // branch: fork the chat from this reply into a new session, non-destructively
      if (actions) {
        const bb = document.createElement('button');
        bb.className = 'act-btn msg-branch-btn';
        bb.textContent = 'branch';
        bb.title = 'fork a new chat from here (keeps this one)';
        bb.dataset.msgId = m.id;
        actions.appendChild(bb);
      }
    }
  }
  // wire edit + branch buttons after all messages are rendered
  _wireEditButtons(container);
  _wireBranchButtons(container);
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


export function appendAiMsg(text, thinking, toolSteps) {
  const { row, wrap, body } = _makeAiRow();
  // re-show the agent run (tool calls + diffs) inline, collapsed, above the reply
  if (toolSteps?.length) {
    const holder = document.createElement('div');
    holder.innerHTML = renderAgentSteps(toolSteps, false);
    if (holder.firstElementChild) body.appendChild(holder.firstElementChild);
  }
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
    <button class="msg-regen-btn act-btn" title="regenerate">regen</button>
    <button class="msg-rewrite-btn act-btn" data-style="shorter" title="rewrite shorter">shorter</button>
    <button class="msg-rewrite-btn act-btn" data-style="simpler" title="rewrite simpler">simpler</button>`;
  wrap.appendChild(actions);
  wireRewriteButtons(actions);

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


function _wireBranchButtons(container) {
  container.querySelectorAll('.msg-branch-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const msgId = btn.dataset.msgId;
      if (!msgId || !_activeId) return;
      btn.disabled = true;
      try {
        const r = await fetch(`/api/sessions/${_activeId}/fork`, {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ msg_id: msgId }),
        });
        if (!r.ok) throw new Error('fork failed');
        const ns = await r.json();
        await loadSessions();      // surface the new branch in the sidebar
        await selectSession(ns.id);  // and open it
      } catch {
        btn.disabled = false;
        const { toast } = await import('./util.js');
        toast('couldn\'t branch this chat', 'error');
      }
    });
  });
}

export function wireRewriteButtons(scope) {
  scope.querySelectorAll('.msg-rewrite-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const row = btn.closest('.msg-row');
      const content = row?.querySelector('.ai-content');
      if (!content || !_activeId) return;
      const style = btn.dataset.style;
      const siblings = row.querySelectorAll('.msg-rewrite-btn');
      siblings.forEach(b => b.disabled = true);
      const old = btn.textContent; btn.textContent = '…';
      try {
        const r = await fetch('/api/chat/rewrite', {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ session_id: _activeId, style, msg_id: row.dataset.msgId || '' }),
        });
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'rewrite failed');
        const { content: text } = await r.json();
        content.innerHTML = _md(text);
        toast(`rewritten ${style}`, 'success');
      } catch (err) {
        toast(String(err.message || err), 'error');
      } finally {
        siblings.forEach(b => b.disabled = false);
        btn.textContent = old;
      }
    });
  });
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
function _escName(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function greetingHtml() {
  const h = new Date().getHours();
  const name = (localStorage.getItem('alles-name') || '').trim();
  let pool;
  if (h < 5)        pool = ['still up?', 'burning the midnight oil?', 'the world\'s asleep, perfect',
                            'night owl mode?', 'quiet hours, big ideas', 'one more thing?', 'can\'t sleep?',
                            'late-night session?'];
  else if (h < 12)  pool = ['good morning', 'morning', 'rise and shine', 'top of the morning',
                            'fresh start', 'let\'s make today count', 'the day is yours', 'coffee first?'];
  else if (h < 18)  pool = ['good afternoon', 'afternoon', 'good to see you', 'back at it?',
                            'midday momentum', 'what are we shipping today?', 'let\'s keep rolling', 'ready when you are?'];
  else              pool = ['good evening', 'evening', 'welcome back', 'the night is young',
                            'what are we building tonight?', 'prime hours', 'let\'s get into it', 'golden hour for ideas'];
  const pick = pool[Math.floor(Math.random() * pool.length)];
  return _withName(pick, name);
}

// incognito hero title — same dynamic, time-of-day idea as the welcome greeting but
// with an off-the-record flavor. changes every time you open / refresh.
function incognitoTitle() {
  const h = new Date().getHours();
  let pool;
  if (h < 5)        pool = ['off the record, after hours', 'ghost mode, late night', 'no traces tonight',
                            'midnight, no memory', 'the quiet, unlogged hours', 'this stays between us'];
  else if (h < 12)  pool = ['a clean, private start', 'off the record this morning', 'no history today',
                            'incognito, fresh', 'quietly, just us', 'nothing written down'];
  else if (h < 18)  pool = ['off the books', 'a private session', 'nothing saved here',
                            'between you and me', 'no memory, no trace', 'speak freely'];
  else              pool = ['off the record tonight', 'a private evening', 'no traces this evening',
                            'just between us', 'quiet and unlogged', 'the night, off the books'];
  return pool[Math.floor(Math.random() * pool.length)];
}

// drop the name in before any trailing ? . ! so "one more thing?" → "one more thing, eric?"
function _withName(g, name) {
  if (!name) return _escName(g);
  const punct = /[?.!]$/.test(g) ? g.slice(-1) : '';
  const base = punct ? g.slice(0, -1) : g;
  return `${_escName(base)}, <span class="accent">${_escName(name)}</span>${punct}`;
}

export function showWelcome() {
  const g = document.getElementById('welcome-greeting');
  if (isIncognitoMode()) {
    // dedicated incognito hero — always shown off the record (à la Claude)
    if (g) g.innerHTML = `
      <div class="incognito-hero">
        <svg class="incognito-hero-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07"/></svg>
        <div class="incognito-hero-title">${incognitoTitle()}</div>
        <div class="incognito-hero-note">incognito chats aren't saved, added to memory, or used to train models.</div>
      </div>`;
    document.getElementById('welcome').style.display = 'flex';
    document.getElementById('messages').style.display = 'none';
  } else if (welcomeEnabled()) {
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

// download the active chat in any format — the server builds md/json/txt/html
export function downloadSession(fmt = 'md') {
  if (!_activeId) { toast('no active chat', 'error'); return; }
  const a = Object.assign(document.createElement('a'), {
    href: `/api/sessions/${_activeId}/export?fmt=${fmt}`,
    download: '',   // let the content-disposition filename win
  });
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// kept for the /export slash command + older callers
export async function exportActiveSessionMarkdown() { downloadSession('md'); }


export async function createSession(model = '', endpointId = '', options = {}) {
  const r = await fetch('/api/sessions', {
    method: 'POST',
    headers: {'content-type':'application/json'},
    body: JSON.stringify({ model, endpoint_id: endpointId, incognito: !!options.incognito, mode: options.mode || 'chat' }),
  });
  if (!r.ok) return null;
  const s = await r.json();
  await loadSessions();
  return s;
}


// return the active session id, or lazily create one (so research/docs-ask work on a
// fresh chat exactly like a normal first message does).
export async function ensureSession(options = {}) {
  const existing = getActiveId();
  if (existing) return existing;
  const ep = getCurrentEndpoint();
  if (!ep) { toast('no endpoint configured — add one via the model picker', 'error'); return null; }
  const model = getSelected()?.model || ep.models?.[0] || '';
  const s = await createSession(model, ep.id, options);
  if (!s) { toast('failed to create session', 'error'); return null; }
  markActive(s.id);
  return s.id;
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
        const p = await createProject(name.trim());
        if (p) {
          await assignSession(p.id, id);   // file this chat into the new project
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
