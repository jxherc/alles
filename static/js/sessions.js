import { plainError, toast } from './util.js';
import { confirm as _dlgConfirm, prompt as _dlgPrompt } from './dialog.js';
import { renderProjectFolders, loadProjects, getProjects, createProject, assignSession } from './projects.js';
import { applyResponsePrivacy, stripEmojis, welcomeEnabled } from './privacy.js';
import { renderAgentSteps, wireAgentRunControls } from './agentview.js';
import { isIncognitoMode } from './modes.js?v=257';
import { scrollToLatest } from './scrollfollow.js';
import {
  modelOverrideForNewSession,
  restoreSessionModel,
  selectAideDefault,
} from './models.js?v=214';
import { t, tp } from './i18n.js';
import { contextProvenanceElement, sourceCitationStatus } from './memoryactions.js';
import { loadAnswerNoteRecovery, reconcileAnswerNote } from './answer_note.js';
import { loadAnswerTaskRecovery } from './answer_task.js';
import { createMenuController } from './kokuen.js?v=4';
import { pushRouteUrl, replaceRouteUrl, routeHistoryPosition } from './route_history.js';
import { compactResponseActions } from './response_actions.js?v=3';
const _si = n => (globalThis.window?.icon ? globalThis.window.icon(n) : '');   // the shared svg icon set

let _sessions = { today: [], yesterday: [], earlier: [] };
let _activeId = null;
let _composerGeneration = 0;
let _sessionSelectionRequest = 0;
let _allSessions = [];  // flat list for search
let _sessionsLoaded = false;
let _sessionLoadGeneration = 0;
let _sessionLoadState = 'loading';
const SESSION_ORDER_KEY = 'aide-session-order';
let _contextMenuController = null;

export function getActiveId() { return _activeId; }
export function getComposerGeneration() { return _composerGeneration; }

export function setPrimaryConversationUnavailable(unavailable) {
  window._aidePrimaryUnavailable = unavailable;
  const composer = document.getElementById('composer-outer');
  if (composer) composer.inert = unavailable;
  if (unavailable) document.dispatchEvent(new CustomEvent('alles:aide-primary-unavailable'));
}

function syncSessionRowState(row, active) {
  row.classList.toggle('active', active);
  row.querySelector('.session-open')?.setAttribute('aria-current', active ? 'true' : 'false');
}

// just fetch + render the sidebar. no navigation — safe to call after any mutation.
export async function loadSessions() {
  const generation = ++_sessionLoadGeneration;
  _sessionLoadState = 'loading';
  renderSessionLoadState();
  try {
    const r = await fetch('/api/sessions');
    if (!r.ok) throw new Error('could not load aide tasks');
    const sessions = await r.json();
    if (!['today', 'yesterday', 'earlier'].every(group => Array.isArray(sessions?.[group])
      && sessions[group].every(item => item && typeof item.id === 'string' && typeof item.name === 'string'))) {
      throw new Error('could not read the aide task list');
    }
    if (generation !== _sessionLoadGeneration) return false;
    _sessions = sessions;
    _allSessions = [..._sessions.today, ..._sessions.yesterday, ..._sessions.earlier];
    _sessionsLoaded = true;
    _applySessionOrder();
    // active session got deleted/archived elsewhere → drop the stale highlight
    if (_activeId && !_allSessions.find(s => s.id === _activeId)) _activeId = null;
    _sessionLoadState = 'ready';
    renderSidebar(document.getElementById('session-search')?.value || '');
    renderSessionLoadState();
    return true;
  } catch (e) {
    if (generation !== _sessionLoadGeneration) return false;
    _sessionLoadState = 'error';
    renderSessionLoadState();
    if (globalThis.navigator?.onLine !== false) console.error('loadSessions', e);
    return false;
  }
}
window._reloadAideSessions = loadSessions;

function renderSessionLoadState() {
  const state = document.getElementById('session-list-state');
  const message = document.getElementById('session-list-message');
  const retry = document.getElementById('session-list-retry');
  if (!state || !message || !retry) return;
  document.getElementById('session-list')?.setAttribute('aria-busy', String(_sessionLoadState === 'loading'));
  state.hidden = _sessionLoadState === 'ready';
  if (_sessionLoadState === 'ready') {
    if (document.activeElement === retry) document.getElementById('session-search')?.focus();
    retry.hidden = true;
    return;
  }
  message.textContent = _sessionLoadState === 'loading'
    ? (_sessionsLoaded ? t('aide.tasks_refreshing') : t('aide.tasks_loading'))
    : (_sessionsLoaded ? t('aide.tasks_refresh_failed') : t('aide.tasks_load_failed'));
  if (_sessionLoadState === 'error') retry.hidden = false;
  retry.setAttribute('aria-disabled', String(_sessionLoadState === 'loading'));
  retry.onclick = () => { if (_sessionLoadState !== 'loading') void loadSessions(); };
}

// called once on boot. Deep links still restore exact historical tasks; a bare
// Aide route opens the one permanent primary conversation.
export async function initSessions({ hashOwner = 'session' } = {}) {
  await loadSessions();
  void loadAnswerNoteRecovery();
  void loadAnswerTaskRecovery();
  // Session restoration owns only the Aide conversation route. Resolving the
  // canonical thread must never pull Home or a specialist app into Aide after
  // that route has already rendered.
  if (hashOwner !== 'session') return;
  const hash = location.hash.slice(1);
  const sourceMessage = new URLSearchParams(location.search).get('message') || '';
  if (hashOwner === 'session' && hash && (!_sessionsLoaded || _allSessions.find(s => s.id === hash))) {
    await selectSession(hash, sourceMessage, { skipDraft: true, preserveRecord: true });
  } else {
    try {
      let primary = _allSessions.find(item => item.primary);
      if (!primary) {
        const response = await fetch('/api/aide/conversation');
        if (!response.ok) throw new Error('primary conversation unavailable');
        primary = await response.json();
      }
      if (!primary?.id) throw new Error('primary conversation unavailable');
      if (!_allSessions.some(item => item.id === primary.id)) await loadSessions();
      const opened = await selectSession(primary.id, '', {
        skipDraft: true,
        preserveRecord: true,
        preserveHash: hashOwner !== 'session' || Boolean(sourceMessage),
        preserveMessage: Boolean(sourceMessage),
      });
      if (!opened) throw new Error('primary conversation unavailable');
    } catch (error) {
      console.error('initSessions', error);
      setPrimaryConversationUnavailable(true);
    }
  }
}

// fresh empty chat — does NOT create a db row. the session is created
// lazily on the first send (see chat.js), so empty chats never persist.
// ── per-conversation composer drafts ───────────────────────────────────────
// unsent text stays with the convo you typed it in — switch away + back, it's
// still there. keyed by session id (or 'new' for the not-yet-created chat).
const _legacyDraftKey = id => 'aide-draft-' + (id || 'new');
const _draftKey = id => 'aide-draft-v2-' + (id || 'new');
let _draftStorageWarned = false;
function writeDraft(id, text, scope, reportFailure = true) {
  try {
    // Keep text and source identity in one write, including an explicit empty
    // draft so a leftover legacy value cannot revive an already-sent question.
    localStorage.setItem(_draftKey(id), JSON.stringify({ text, document_scope: scope }));
    _draftStorageWarned = false;
    try { localStorage.removeItem(_legacyDraftKey(id)); } catch {}
    return true;
  } catch {
    if (reportFailure && !_draftStorageWarned) toast(t('aide.draft_keep_failed'), 'error');
    if (reportFailure) _draftStorageWarned = true;
    return false;
  }
}
export function saveDraft() {
  const ta = document.getElementById('composer-ta');
  if (!ta) return;
  if (isIncognitoMode()) return;
  const text = ta.value.trim() ? ta.value : '';
  const scope = window._pendingDocumentScope || null;
  if (!text && !scope) return clearDraft(_activeId);
  return writeDraft(_activeId, text, scope);
}
export function restoreDraft(id) {
  const ta = document.getElementById('composer-ta');
  if (!ta) return;
  if (isIncognitoMode()) {
    ta.value = '';
    window._setAideDocumentScope?.(null);
    ta.style.height = 'auto';
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    return;
  }
  let draft = { text: '', document_scope: null };
  try {
    const stored = localStorage.getItem(_draftKey(id));
    draft = stored === null
      ? { text: localStorage.getItem(_legacyDraftKey(id)) || '', document_scope: null }
      : JSON.parse(stored);
    if (!draft || typeof draft.text !== 'string') throw new Error('invalid draft');
  } catch {
    draft = { text: '', document_scope: null };
    toast(t('aide.draft_restore_failed'), 'error');
  }
  ta.value = draft.text;
  window._setAideDocumentScope?.(draft.document_scope || null);
  ta.style.height = 'auto';
  ta.dispatchEvent(new Event('input', { bubbles: true }));   // autosize + send-btn state
}
export function clearDraft(id) {
  if (isIncognitoMode()) return;
  return clearStoredDraft(id === undefined ? _activeId : id);
}

export function getDraftSnapshot(id) {
  try {
    const stored = localStorage.getItem(_draftKey(id));
    return stored === null
      ? { text: localStorage.getItem(_legacyDraftKey(id)) || '', document_scope: null }
      : JSON.parse(stored);
  } catch { return null; }
}

// A late acceptance may belong to a task that is no longer on screen. Only
// consume its submitted draft; a newer saved question still belongs to the user.
export function consumeDraft(id, expected, remainingText = '', remainingScope = null) {
  try {
    const stored = localStorage.getItem(_draftKey(id));
    if (stored === null) {
      // At quota, a scoped send may still own an unmigrated text-only draft.
      if (localStorage.getItem(_legacyDraftKey(id)) !== expected.text) return false;
    } else {
      const draft = JSON.parse(stored);
      if (!draft || draft.text !== expected.text
        || JSON.stringify(draft.document_scope) !== JSON.stringify(expected.document_scope)) return false;
    }
  } catch { return false; }
  return remainingText || remainingScope ? writeDraft(id, remainingText, remainingScope) : clearStoredDraft(id);
}

function clearStoredDraft(owner) {
  if (writeDraft(owner, '', null, false)) return true;
  // Removing consumed drafts needs no free storage, unlike migration to an
  // empty v2 record. Do not use this fallback for unsent edits.
  try {
    localStorage.removeItem(_legacyDraftKey(owner));
    localStorage.removeItem(_draftKey(owner));
    _draftStorageWarned = false;
    return true;
  } catch {
    toast(t('aide.draft_clear_failed'), 'error');
    return false;
  }
}

export function newChat(options = {}) {
  if (!options.skipDraft && saveDraft() === false) return false;
  setPrimaryConversationUnavailable(false);
  ++_composerGeneration;
  document.getElementById('composer-send-recovery')?.setAttribute('hidden', '');
  _activeId = null;
  window._currentSession = null;
  const requestedProject = options.projectId ?? new URLSearchParams(location.search).get('project_id') ?? '';
  window._pendingProjectId = getProjects().some(project => project.id === requestedProject) ? requestedProject : '';
  window._pendingWorkingDir = '';
  window._pendingPersona = null;       // fresh chat starts with no persona pre-picked
  window._pendingChatBehavior = '';
  window._refreshPersonaBtn?.();        // keep the persona button visible + pickable pre-send
  selectAideDefault();                  // new chats follow the effective Aide Chat role
  if (!options.preserveHash) {
    const target = new URL(location.href);
    target.hash = '';
    target.searchParams.delete('message');
    replaceRouteUrl(target);
  }
  document.getElementById('messages').innerHTML = '';
  document.querySelectorAll('.session-item').forEach(el => syncSessionRowState(el, false));
  showWelcome();
  const ta = document.getElementById('composer-ta');
  if (ta) { ta.style.height = 'auto'; ta.focus(); }
  restoreDraft(null);       // bring back the 'new chat' draft if any
  window._syncAideNewTaskContext?.(null);
}

// mark a session active without re-fetching/re-rendering its messages.
// used after lazy-create so the in-flight stream isn't wiped.
export function markActive(id) {
  _activeId = id;
  // replaced, not pushed: the new task takes the place of the fresh one. setting location.hash
  // added a history entry and fired a popstate that re-routed chat in the middle of a send
  if (id && !isIncognitoMode()) {
    const url = new URL(location.href);
    url.hash = id;
    replaceRouteUrl(url);
  }
  document.querySelectorAll('.session-item').forEach(el => {
    const active = el.dataset.id === id;
    syncSessionRowState(el, active);
  });
  window._syncAideNewTaskContext?.(window._currentSession || (id ? { id } : null));
}


export function renderSidebar(filter = '') {
  const list = document.getElementById('session-list');
  if (!_sessionsLoaded) { list.innerHTML = ''; return; }
  const fl = filter.toLowerCase();

  const archive = document.body.classList.contains('aide-central');
  let src = _allSessions.filter(session => !archive || !session.primary);
  if (fl) {
    src = src.filter(s => (s.name || '').toLowerCase().includes(fl));
  }

  if (!src.length) {
    const empty = fl ? (archive ? t('aide.no_matching_conversations') : t('aide.no_matching_tasks')) : archive ? t('aide.no_earlier_conversations') : t('aide.no_tasks');
    list.innerHTML = `<div class="empty-sessions">${empty}</div>`;
    if (!fl && !archive) renderProjectFolders(_allSessions, selectSidebarSession, () => loadSessions());
    return;
  }

  let html = '';

  if (archive) {
    html = src.map(s => renderItem(s)).join('');
  } else if (!fl && document.body.classList.contains('afterlife-aide-projects')) {
    html = '';
  } else if (!fl) {
    if (_sessions.today.length)     html += renderGroup('today', _sessions.today);
    if (_sessions.yesterday.length) html += renderGroup('yesterday', _sessions.yesterday);
    if (_sessions.earlier.length)   html += renderGroup('earlier', _sessions.earlier);
  } else {
    html = src.map(s => renderItem(s)).join('');
  }

  list.innerHTML = html;

  // inject project folders above the session groups
  if (!fl && !archive) renderProjectFolders(_allSessions, selectSidebarSession, () => loadSessions());

  list.querySelectorAll('.session-item').forEach(el => {
    const sid = el.dataset.id;
    const active = sid === _activeId;
    const openButton = el.querySelector('.session-open');
    syncSessionRowState(el, active);
    openButton?.addEventListener('click', () => selectSidebarSession(sid));
    openButton?.addEventListener('keydown', event => {
      if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
        event.preventDefault();
        const box = openButton.getBoundingClientRect();
        openCtxMenu({ clientX: box.left + 16, clientY: box.top + box.height }, sid, openButton);
      }
    });
    el.addEventListener('contextmenu', e => {
      e.preventDefault();
      openCtxMenu(e, sid, openButton);
    });
    el.querySelector('.star')?.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      toggleSessionStar(sid);
    });
    // rename, star, move and delete were right-click only, which a touch screen can't reach
    const more = el.querySelector('.session-more');
    more?.addEventListener('click', e => {
      e.stopPropagation();
      openCtxMenu({ anchor: more.getBoundingClientRect() }, sid, more);
    });
    _bindSessionDrag(el);
  });
}

async function selectSidebarSession(id) {
  // a conversation opened from the list is a place: back returns to the one before
  const selected = await selectSession(id, '', { push: true });
  if (selected) window._closeCompactAideSidebar?.();
  return selected;
}

const GROUP_LABELS = {
  today: () => t('aide.group_today'),
  yesterday: () => t('aide.group_yesterday'),
  earlier: () => t('aide.group_earlier'),
};

function renderGroup(label, items) {
  return `<span class="section-label">${GROUP_LABELS[label]()}</span>` + items.map(s => renderItem(s)).join('');
}

function renderItem(s) {
  const starred  = s.starred   ? ' starred'   : '';
  const incog    = s.incognito ? ' incognito' : '';
  const icon     = s.incognito ? `<span class="incognito-icon" title="${escHtml(t('aide.incognito_label'))}" aria-hidden="true"></span>` : '';
  return `<div class="session-item${starred}${incog}" data-id="${s.id}" draggable="true">
  <button type="button" class="session-open" aria-haspopup="menu" aria-current="${s.id === _activeId ? 'true' : 'false'}" aria-label="${escHtml(t('aide.open_session', { name: s.name }))}">
    <span class="session-dot"></span>
    ${icon}<span class="session-name">${escHtml(s.name)}</span>${s.starred ? `<span class="session-starred" title="${escHtml(t('aide.starred'))}">${_si('star-fill')}</span>` : ''}
  </button>
  <button type="button" class="session-more" aria-haspopup="menu" aria-label="${escHtml(t('aide.session_actions', { name: s.name }))}">${_si('more')}</button>
  <button type="button" class="star" title="${s.starred ? t('aide.unstar') : t('aide.star')}" aria-label="${s.starred ? t('aide.unstar_session') : t('aide.star_session')}"></button>
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
  if (!r.ok) { toast(t('aide.star_failed'), 'error'); return; }
  s.starred = next;
  const grouped = [..._sessions.today, ..._sessions.yesterday, ..._sessions.earlier].find(x => x.id === id);
  if (grouped) grouped.starred = next;
  const hadFocus = document.activeElement?.closest?.(`.session-item[data-id="${id}"]`);
  renderSidebar(document.getElementById('session-search')?.value || '');
  if (hadFocus) _focusSessionRow([id], '.star');
}


export function focusSessionMessage(messageId) {
  const row = [...document.querySelectorAll('#messages .msg-row')]
    .find(item => item.dataset.msgId === messageId);
  if (!row) return false;
  window._closeCompactAideSidebar?.();
  row.classList.add('record-target'); row.tabIndex = -1;
  row.scrollIntoView({ block: 'center', behavior: 'instant' }); row.focus({ preventScroll: true });
  return true;
}

export async function selectSession(id, messageId = '', options = {}) {
  if (options.isCurrent?.() === false) return false;
  if (messageId && !/^[a-zA-Z0-9_-]{1,160}$/.test(messageId)) return false;
  if (id !== _activeId && !options.skipDraft && saveDraft() === false) return false;
  const generation = _composerGeneration;
  const previousId = _activeId;
  const request = ++_sessionSelectionRequest;
  try {
    const r = await fetch(`/api/sessions/${id}/history`);
    if (!r.ok) throw new Error('conversation unavailable');
    const data = await r.json();
    if (request !== _sessionSelectionRequest || generation !== _composerGeneration || previousId !== _activeId || options.isCurrent?.() === false) return false;
    if (data.session?.id !== id || !Array.isArray(data.messages)) throw new Error('invalid conversation history');
    // Fetch before changing the owner. Failed or stale archive reads must keep
    // the currently visible thread, URL and unsent input intact. Save again so
    // text typed while the read was pending is not lost at the final switch.
    if (id !== _activeId && !options.skipDraft && saveDraft() === false) return false;
    ++_composerGeneration;
    document.getElementById('composer-send-recovery')?.setAttribute('hidden', '');
    _activeId = id;
    // Reloading the same owner must retain live input (including text typed
    // during a recovery fetch), not replace it with an older stored snapshot.
    if (id !== previousId) restoreDraft(id);
    setPrimaryConversationUnavailable(false);
    window._currentSession = data.session;
    const position = options.push ? routeHistoryPosition() : 0;
    window._enterChatView?.({ preserveRecord: options.preserveRecord === true });
    // the hash goes on after the chat route is in place: leaving another view clears it
    const sourceUrl = new URL(location.href);
    if (!options.preserveHash) sourceUrl.hash = id;
    if (messageId) sourceUrl.searchParams.set('message', messageId);
    // The boot fallback retains a missing reply's identity so the existing
    // source-link recovery notice can explain why the original did not open.
    else if (!options.preserveMessage) sourceUrl.searchParams.delete('message');
    // entering chat from a tool page already added the entry
    if (options.push && id !== previousId && routeHistoryPosition() === position) pushRouteUrl(sourceUrl);
    else replaceRouteUrl(sourceUrl);
    document.querySelectorAll('.session-item').forEach(el => syncSessionRowState(el, el.dataset.id === id));
    renderMessages(data.messages);
    showMessages();
    // a saved chat with nothing in it yet greets like a new one, with the starts
    if (!data.messages?.length) showWelcome();
    // the render scrolled while the list was still hidden (no height yet); now that it shows,
    // land on the newest message, unless a link asked for one in particular
    if (!messageId) scrollDown({ force: true });

    restoreSessionModel(data.session);
    updateSessionHeader(data.session);
    document.dispatchEvent(new CustomEvent('alles:aide-session'));
    window._setMode?.(data.session.mode || 'chat');   // restore this convo's last mode
    // refresh persona button
    try {
      window._refreshPersonaBtn?.();
    } catch (e) {}
    // Reattach durable Aide work to this same task after a reload or tab switch.
    import('./aidebackground.js?v=247').then(m => m.reattachBackgroundWork(id)).catch(() => {});
    if (messageId && !focusSessionMessage(messageId)) {
      toast(t('aide.original_reply_gone'), 'error'); return false;
    }
    return true;
  } catch (e) {
    console.error('selectSession', e);
    return false;
  }
}

// back/forward onto the conversation: the hash names its owner. a bare address while an earlier
// conversation shows means the main one; a new task with nothing saved yet stays as it is
export async function selectSessionFromRoute({ isCurrent = () => true } = {}) {
  if (isIncognitoMode()) return false;
  const id = location.hash.slice(1);
  if (id && id === _activeId) return true;
  if (id && (!_sessionsLoaded || _allSessions.some(session => session.id === id))) {
    const message = new URLSearchParams(location.search).get('message') || '';
    return selectSession(id, message, { preserveHash: true, preserveMessage: true, preserveRecord: true, isCurrent });
  }
  if (!_activeId || window._currentSession?.primary) return true;
  return await window._showPrimaryAide?.({ focus: false, isCurrent }) ?? false;
}

// Background completion updates its owner without reopening the conversation
// or dismissing the archive, call, coding workspace, or another active view.
window._reloadActiveSession = (sessionId = _activeId) => refreshActiveSessionQuietly(sessionId);

// A receipt updates message content without changing the owner's route, mode,
// selection, or composer draft. Never replace a foreground stream in progress.
let _quietRefreshTimer = null;
let _quietRefreshRequest = 0;
function canRefreshAideHistory(overEdits = false) {
  // Message edits have their own unsent text, separate from the composer draft.
  // Keep the whole message tree intact until that editor is saved or cancelled. a re-read the
  // edit itself asked for may draw over edit boxes: their words are kept and the boxes reopen
  const editor = document.getElementById('messages')?.querySelector(
    `textarea${overEdits ? ':not(.edit-inline)' : ''}:not([disabled]):not([readonly]), input:not([type="hidden"]):not([disabled]):not([readonly]), [contenteditable]:not([contenteditable="false"])`,
  );
  return !editor && window._canRefreshAideMessages?.() !== false;
}

// read the task again in place after an edit or regenerate found it moved on (or lost the
// connection mid-way); open edit boxes come back with their words
export function rereadActiveSession(sessionId = _activeId, { afterTurn = '' } = {}) {
  return refreshActiveSessionQuietly(sessionId, { overEdits: true, afterTurn });
}

export async function refreshActiveSessionQuietly(sessionId, { overEdits = false, afterTurn = '' } = {}) {
  if (!sessionId || sessionId !== _activeId) return false;
  clearTimeout(_quietRefreshTimer);
  if (!canRefreshAideHistory(overEdits)) {
    _quietRefreshTimer = setTimeout(() => refreshActiveSessionQuietly(sessionId, { overEdits }), 750);
    return false;
  }
  const request = ++_quietRefreshRequest;
  const generation = _composerGeneration;
  try {
    let data;
    // a stopped turn may still be saving: read once it has been let go (bounded)
    for (let waited = 0; ; waited += 150) {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/history`);
      if (!response.ok) return false;
      data = await response.json();
      if (!afterTurn || data.answering_turn !== afterTurn || waited >= 5000) break;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    if (request !== _quietRefreshRequest || generation !== _composerGeneration || sessionId !== _activeId) return false;
    if (!canRefreshAideHistory(overEdits)) {
      _quietRefreshTimer = setTimeout(() => refreshActiveSessionQuietly(sessionId, { overEdits }), 750);
      return false;
    }
    const chat = document.getElementById('chat');
    const top = chat?.scrollTop || 0;
    const atEnd = chat && chat.scrollHeight - chat.clientHeight - top < 80;
    window._currentSession = data.session;
    renderMessages(data.messages);
    if (data.messages.length) showMessages();
    requestAnimationFrame(() => {
      if (chat && sessionId === _activeId) chat.scrollTop = atEnd ? chat.scrollHeight : top;
    });
    document.dispatchEvent(new CustomEvent('alles:aide-session'));
    return true;
  } catch { return false; }
}
window._refreshAideSessionQuietly = refreshActiveSessionQuietly;


function renderMessages(msgs) {
  const container = document.getElementById('messages');
  container.innerHTML = '';
  for (const m of msgs) {
    if (m.role === 'user') {
      const row = appendUserMsg(m.content, m.meta?.context_scope || m.meta?.response_recovery?.request?.context_scope);
      row.dataset.msgId = m.id;
      if (m.meta?.interrupted) appendInterruptionNotice(row.querySelector('.user-wrap') || row);
      else if (m.meta?.response_recovery || m === msgs.at(-1)) {
        const pending = createStreamingAiRow();
        // a stand-in for a reply that never came: not a stored message
        pending.row.dataset.unsaved = '1';
        pending.body.classList.add('done');
        appendResponseRecovery(pending.body, m, m === msgs.at(-1), pending.row);
      }
    } else if (m.role === 'system' && m.content?.startsWith('[conversation summary]')) {
      // compact divider
      const div = document.createElement('div');
      div.className = 'compact-divider';
      div.innerHTML = `<span>${escHtml(t('aide.context_compacted'))}</span>`;
      container.appendChild(div);
    } else if (m.role === 'assistant') {
      const { row, wrap, body } = appendAiMsg(
        m.content,
        m.meta?.thinking,
        m.meta?.tool_steps,
        m.meta?.context_provenance,
        m.meta?.agent_run_id,
        m.meta?.source_citations,
      );
      row.dataset.msgId = m.id;
      reconcileAnswerNote(wrap);
      if (m.meta?.interrupted) appendInterruptionNotice(body);
      else if (m.meta?.response_recovery) appendResponseRecovery(body, m);
      const actions = wrap.querySelector('.msg-actions');
      // re-open artifact button from history
      if (m.meta?.artifacts?.length) {
        wrap.dataset.artifacts = JSON.stringify(m.meta.artifacts);
        if (actions) {
          const btn = document.createElement('button');
          btn.className = 'act-btn';
          btn.textContent = t('aide.open_artifact');
          btn.dataset.msgAct = 'artifact';
          actions.appendChild(btn);
        }
      }
      // branch: fork the chat from this reply into a new session, non-destructively
      if (actions) {
        const bb = document.createElement('button');
        bb.className = 'act-btn msg-branch-btn';
        bb.textContent = t('aide.branch_button');
        bb.title = t('aide.branch_title');
        bb.dataset.msgId = m.id;
        actions.appendChild(bb);
      }
      compactResponseActions(actions);
    }
  }
  // wire edit + branch buttons after all messages are rendered
  _wireEditButtons(container);
  _wireBranchButtons(container);
  _reopenEditDrafts(container);
  scrollDown({ force: true });
}

function appendResponseRecovery(target, message, latest = false, row = null) {
  const recovery = message.meta?.response_recovery;
  const request = recovery?.request;
  const retryable = latest && recovery?.status === 'failed' && request && typeof request === 'object';
  const notice = document.createElement('div');
  notice.className = 'error-msg model-error aide-response-recovery';
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.textContent = retryable
    ? t('aide.recovery_retryable')
    : recovery?.status === 'failed'
    ? t('aide.recovery_failed')
    : t('aide.recovery_none');
  const settings = document.createElement('button');
  settings.type = 'button'; settings.className = 'btn'; settings.textContent = t('aide.model_settings');
  settings.addEventListener('click', () => window._openSettings?.('models'));
  notice.append(status, settings);
  if (retryable) {
    const original = { ...request, session_id: _activeId, message: message.content, retry_message_id: message.id };
    const retry = document.createElement('button');
    retry.type = 'button'; retry.className = 'btn aide-retry-response'; retry.textContent = t('aide.retry_response');
    retry.addEventListener('click', async () => {
      const { retrySavedResponse } = await import('./chat.js');
      retrySavedResponse(original, row);
    });
    notice.appendChild(retry);
  }
  target.appendChild(notice);
}


export function appendUserMsg(text, documentScope = null) {
  const { row } = _makeRow('user');
  row.innerHTML = `<div class="user-wrap">
    ${documentScope?.path ? `<div class="user-context-scope">${escHtml(t('aide.using_note_path', { path: documentScope.path }))}</div>` : ''}
    ${documentScope?.documents ? `<details class="user-context-scope"><summary>${escHtml(tp('aide.selected_notes_summary', documentScope.documents.length))}</summary><ul tabindex="0" aria-label="${escHtml(t('aide.selected_source_notes'))}">${documentScope.documents.map(item => `<li>${escHtml(item.path)}</li>`).join('')}</ul></details>` : ''}
    <div class="user-bubble">${escHtml(text)}</div>
    <div class="user-actions">
    <button class="msg-memory-btn" type="button" data-msg-act="remember" aria-label="${escHtml(t('aide.remember_message'))}">${escHtml(t('aide.remember'))}</button>
    <button class="msg-edit-btn" type="button" title="${escHtml(t('common.edit'))}" aria-label="${escHtml(t('aide.edit_message'))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3a2.8 2.8 0 0 1 4 4L7 21l-4 1 1-4Z"></path><path d="m15 5 4 4"></path></svg></button>
    </div>
  </div>`;
  // an edit or regenerate asks again with the same notes
  row.contextScope = documentScope || null;
  document.getElementById('messages').appendChild(row);
  // a just-sent message can be edited as soon as the server tells it its id
  _wireEditButtons(row);
  scrollDown({ force: true });
  return row;
}


export function appendInterruptionNotice(target, text = t('aide.response_interrupted')) {
  const notice = document.createElement('div');
  notice.className = 'aide-interruption';
  notice.setAttribute('role', 'status');
  notice.textContent = text;
  target.appendChild(notice);
}


export function appendAiMsg(text, thinking, toolSteps, contextProvenance, agentRunId = '', sourceCitations = null) {
  const { row, wrap, body } = _makeAiRow();
  // strip artifact tags from display
  const displayText = text ? text.replace(/<aide-artifact[^>]*>[\s\S]*?<\/aide-artifact>/g, '').trim() : '';
  wrap.answerText = displayText;
  wrap.dataset.sessionId = _activeId || '';
  wrap.dataset.private = String(window._currentSession?.incognito || isIncognitoMode());
  const content = document.createElement('div');
  content.className = 'ai-content';
  content.innerHTML = displayText ? _md(stripEmojis(displayText)) : '';
  applyResponsePrivacy(content);
  body.appendChild(content);
  if (thinking) {
    const tb = document.createElement('details');
    tb.className = 'thinking-block';
    tb.innerHTML = `<summary>${escHtml(t('aide.thinking'))}</summary><div class="thinking-content"></div>`;
    tb.querySelector('.thinking-content').textContent = thinking;
    body.appendChild(tb);
  }
  if (toolSteps?.length) {
    const holder = document.createElement('div');
    holder.innerHTML = renderAgentSteps(toolSteps, false, agentRunId);
    body.append(...holder.children);  // the steps, then any doc cards
    wireAgentRunControls(body);
  }
  const provenance = contextProvenanceElement(contextProvenance);
  if (provenance) body.appendChild(provenance);
  const citationStatus = sourceCitationStatus(sourceCitations);
  if (citationStatus) body.appendChild(citationStatus);
  body.classList.add('done');

  const actions = document.createElement('div');
  actions.className = 'msg-actions';
  actions.innerHTML = `<button class="act-btn" data-msg-act="copy">${t('common.copy')}</button>
    <button class="act-btn" data-msg-act="note" title="${t('aide.note_title')}">${t('aide.note_button')}</button>
    <button class="act-btn" data-msg-act="task" title="${t('aide.review_plan_task')}">${t('aide.add_plan_task')}</button>
    <button class="msg-regen-btn act-btn" title="${t('aide.regenerate')}">${t('aide.regen')}</button>
    <button class="msg-rewrite-btn act-btn" data-style="shorter" title="${t('aide.rewrite_shorter_title')}">${t('aide.shorter')}</button>
    <button class="msg-rewrite-btn act-btn" data-style="simpler" title="${t('aide.rewrite_simpler_title')}">${t('aide.simpler')}</button>`;
  wrap.appendChild(actions);
  wireRewriteButtons(actions);
  compactResponseActions(actions);

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
    if (!_firstWiring(btn)) return;
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const row = btn.closest('.msg-row');
      // a stopped reply only knows the id it was promised: check it was kept, by that id
      if (row?.dataset.reservedId && !row.dataset.msgId) await _confirmReserved();
      const msgId = btn.dataset.msgId || row?.dataset.msgId;
      if (!_activeId) return;
      if (!msgId) { toast(row?.dataset.unsaved ? t('aide.branch_unsaved') : _MSG.reload, 'error'); return; }
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
        toast(t('aide.branch_failed'), 'error');
      }
    });
  });
}

// edit, regenerate and branch, for a row added after the list was drawn
export function wireMessageActions(scope) {
  _wireEditButtons(scope);
  _wireBranchButtons(scope);
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
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || t('aide.rewrite_failed'));
        const { content: text } = await r.json();
        content.innerHTML = _md(text);
        toast(style === 'simpler' ? t('aide.rewritten_simpler') : t('aide.rewritten_shorter'), 'success');
      } catch (err) {
        toast(String(err.message || err), 'error');
      } finally {
        siblings.forEach(b => b.disabled = false);
        btn.textContent = old;
      }
    });
  });
}

// once per button: a just-sent row is wired when it's added, a reload wires the whole list
const _wiredActions = new WeakSet();
const _firstWiring = btn => !_wiredActions.has(btn) && !!_wiredActions.add(btn);
// edit boxes still open; opening another closes the untouched ones
const _openEdits = new Set();
// changed edit drafts, by task and message, so leaving the task and coming back keeps them. kept
// in this tab's session storage too, so a reload keeps them (private tasks: memory only)
const _editDrafts = new Map();
const _editDraftKey = (sid, id) => `${sid}\n${id}`;
const _EDIT_DRAFTS = 'aide-edit-drafts-v1';
try {
  for (const [key, draft] of JSON.parse(sessionStorage.getItem(_EDIT_DRAFTS) || '[]')) _editDrafts.set(key, draft);
} catch { /* storage off: memory only */ }
function _storeEditDrafts() {
  try {
    sessionStorage.setItem(_EDIT_DRAFTS, JSON.stringify([..._editDrafts].filter(([, draft]) => !draft.private)));
  } catch { /* storage off or full: memory only */ }
}
function _setEditDraft(key, draft) { _editDrafts.set(key, draft); _storeEditDrafts(); }
// a private task's drafts end with private mode: they never reach storage, and once it's left
// they don't stay in this tab's memory either
function _forgetPrivateDrafts() {
  if (isIncognitoMode()) return;
  for (const [key, draft] of _editDrafts) if (draft.private) _editDrafts.delete(key);
}
function _dropEditDraft(key) { if (_editDrafts.delete(key)) _storeEditDrafts(); }

function _userRowBefore(row) {
  let prev = row?.previousElementSibling;
  while (prev && !prev.querySelector('.user-bubble, .edit-inline')) prev = prev.previousElementSibling;
  return prev || null;
}

const _MSG = {
  get offline() { return t('aide.msg_offline'); },
  get busy() { return t('aide.msg_busy'); },
  get reload() { return t('aide.msg_reload'); },
  get unsaved() { return t('aide.msg_unsaved'); },
};

// a reply stopped mid-way heard its id first but not whether it was kept. ask the saved history
// by that exact id (never by its words); false when alles can't be reached
async function _confirmReserved({ tries = 4, wait = 150 } = {}) {
  const sid = _activeId;
  for (let attempt = 1; ; attempt++) {
    const pending = [...document.querySelectorAll('#messages > .msg-row[data-reserved-id]')].filter(row => !row.dataset.msgId);
    if (!pending.length) return true;
    const r = await fetch(`/api/sessions/${encodeURIComponent(sid)}/history`).catch(() => null);
    const data = r?.ok ? await r.json().catch(() => null) : null;
    if (!data || sid !== _activeId) return false;
    const kept = new Set((data.messages || []).map(m => m.id));
    for (const row of pending) {
      if (!kept.has(row.dataset.reservedId)) continue;
      row.dataset.msgId = row.dataset.reservedId;
      delete row.dataset.reservedId;
    }
    if (pending.every(row => row.dataset.msgId)) return true;
    if (attempt < tries) {
      // a just-stopped reply is still being saved for a moment
      await new Promise(resolve => setTimeout(resolve, wait));
      continue;
    }
    // never kept (stopped before it had any words, in a private task): not a stored message
    for (const row of pending) {
      if (row.dataset.msgId) continue;
      row.dataset.unsaved = '1';
      delete row.dataset.reservedId;
    }
    return true;
  }
}

// the newest message this tab got an id for from the server. the server only cuts when that is
// still its newest, so turns another tab sent never vanish unseen. null: couldn't check
async function _newestShownId() {
  if (!await _confirmReserved()) return null;
  return [...document.querySelectorAll('#messages > .msg-row[data-msg-id]')].at(-1)?.dataset.msgId || '';
}

// put words in the message box, in front of anything already typed there
function _toComposer(text) {
  const composer = document.getElementById('composer-ta');
  if (!composer) return;
  composer.value = composer.value.trim() ? `${text}\n\n${composer.value}` : text;
  composer.dispatchEvent(new Event('input', { bubbles: true }));
}

// the task moved on (another tab) or the connection dropped mid-way: read it again in place. an
// edit box that still fits its question comes back open with its words
async function _rereadTask(sid, why, kind, msgId, afterTurn = '') {
  const fresh = sid === _activeId && await rereadActiveSession(sid, { afterTurn });
  if (fresh) {
    // the old box or button was drawn over: land on what's there now, never on the page
    const row = [...document.querySelectorAll('#messages > .msg-row[data-msg-id]')].find(r => r.dataset.msgId === msgId);
    const target = row?.querySelector('.edit-inline') || (row ? null : document.getElementById('composer-ta'));
    if (target) target.focus({ preventScroll: true });
    else if (row) _focusReply(row);
  }
  // stopped by its owner: the page just shows what was kept, nothing to explain
  if (why === 'stopped' && fresh) return;
  const editing = kind === 'edit';
  const words = !fresh
    ? (why === 'offline' ? _MSG.offline : t('aide.task_changed_reload'))
    : why === 'gone' ? (editing ? t('aide.message_removed_edit') : t('aide.message_removed'))
    : why === 'offline' ? t('aide.connection_dropped')
    : (editing ? t('aide.task_moved_edit') : t('aide.task_moved'));
  toast(words, 'error');
}

function _dropRowsAfter(row, keep = null) {
  let next = row?.nextElementSibling;
  while (next) { const n = next.nextElementSibling; if (next !== keep) next.remove(); next = n; }
}

function _focusReply(reply) {
  if (!reply?.isConnected) return;
  reply.tabIndex = -1;
  reply.focus({ preventScroll: true });
}

// a refused send's question and its error reply, never stored
function _dropRefusedRows(row) {
  const reply = row.nextElementSibling;
  if (reply?.dataset.unsaved && reply.querySelector('.ai-body')) reply.remove();
  row.remove();
}

// back on a task: open the edit boxes that still had changed words in them
function _reopenEditDrafts(container) {
  _forgetPrivateDrafts();
  for (const [key, draft] of _editDrafts) {
    const [sid, id] = key.split('\n');
    if (sid !== _activeId) continue;
    const row = [...container.querySelectorAll('.msg-row[data-msg-id]')].find(r => r.dataset.msgId === id);
    const btn = row?.querySelector('.msg-edit-btn');
    // the words changed under it (another tab): the old draft no longer fits
    if (!btn || row.querySelector('.user-bubble')?.textContent !== draft.original) { _dropEditDraft(key); continue; }
    _openEdit(btn, { text: draft.text, focus: false });
  }
}

function _openEdit(btn, { text = null, focus = true } = {}) {
  const wrap = btn.closest('.user-wrap');
  const bubble = wrap?.querySelector('.user-bubble');
  const row = btn.closest('.msg-row');
  if (!bubble) return;
  // an untouched box left open elsewhere just closes; one with changes keeps them
  for (const open of [..._openEdits]) {
    if (!open.ta.isConnected) _openEdits.delete(open);
    else if (open.unchanged()) open.cancel();
  }
  // textContent, not innerText: the exact words the server holds, newlines and all
  const original = bubble.textContent;
  const sid = _activeId;
  const draftKey = () => _editDraftKey(sid, row.dataset.msgId || '');
  const ta = document.createElement('textarea');
  ta.className = 'edit-inline';
  // one row to start, so it grows from its words rather than from a two-row default
  ta.rows = 1;
  ta.value = text ?? original;
  ta.setAttribute('aria-label', t('aide.edit_message'));
  // 16px on touch, or ios safari zooms the page in on focus
  if (globalThis.matchMedia?.('(pointer: coarse)')?.matches) ta.style.fontSize = '16px';
  // leaving the box never sends: a dismissed phone keyboard or a stray click would cut every
  // later turn. only send (or enter) does; cancel (or escape) puts the words back
  const actions = wrap.querySelector('.user-actions');
  const editActions = document.createElement('div');
  editActions.className = 'user-actions edit-actions';
  const [cancelBtn, sendBtn] = [['cancel', t('common.cancel')], ['send', t('common.send')]].map(([label, text]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `edit-${label}`;
    button.textContent = text;
    return button;
  });
  editActions.append(cancelBtn, sendBtn);
  bubble.replaceWith(ta);
  if (actions) { actions.style.display = 'none'; actions.after(editActions); }
  else ta.after(editActions);
  // grows with its words up to 40% of the screen, then scrolls
  const grow = () => {
    const cap = Math.round((globalThis.innerHeight || 800) * 0.4);
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, cap)}px`;
    ta.style.overflowY = ta.scrollHeight > cap ? 'auto' : 'hidden';
  };
  grow();
  if (focus) ta.focus();

  let done = false;  // guard so we only resolve the edit once
  const close = () => {
    _openEdits.delete(entry);
    _dropEditDraft(draftKey());
    editActions.remove();
    if (actions) actions.style.display = '';
  };
  const restore = ({ focus = false } = {}) => {
    if (done) return; done = true;
    const b = document.createElement('div');
    b.className = 'user-bubble'; b.textContent = original;
    if (ta.isConnected) ta.replaceWith(b);
    close();
    // cancel drops the box you were typing in: land back on the pencil that opened it
    if (focus && btn.isConnected) btn.focus();
  };
  const entry = { ta, unchanged: () => ta.value === original, cancel: () => restore() };
  _openEdits.add(entry);
  const remember = () => {
    if (!row.dataset.msgId) return;
    if (ta.value === original) _dropEditDraft(draftKey());
    else _setEditDraft(draftKey(), { text: ta.value, original, private: isIncognitoMode() });
  };
  remember();
  const save = async () => {
    if (done) return;
    const newText = ta.value.trim();
    // an empty box sends nothing; it isn't a way to ask the old words again
    if (!newText) { ta.focus(); return; }
    done = true;
    const chat = await import('./chat.js');
    if (sid !== _activeId || !ta.isConnected) return;
    // the new words stay in the box to try again (cancel still puts the old ones back)
    const keepEditing = () => { done = false; if (ta.isConnected) ta.focus(); };
    if (!chat.canSendMessage()) { keepEditing(); toast(_MSG.busy, ''); return; }
    // a refused send was never stored: its new words go out as a new message, nothing is cut
    if (row.dataset.unsaved) {
      close();
      _dropRefusedRows(row);
      chat.sendMessage(newText);
      return;
    }
    if (!row.dataset.msgId) { keepEditing(); toast(_MSG.reload, 'error'); return; }
    const newest = await _newestShownId();
    if (sid !== _activeId || !ta.isConnected) return;
    if (newest === null) { keepEditing(); toast(_MSG.offline, 'error'); return; }
    // the same words sent again ask again: the old answer stays until a new one has words
    const same = newText === original.trim();
    // the server checks, cuts and answers in one go; until it takes the request nothing moves
    const result = await chat.resendMessage(row, same ? original : newText, {
      edit: !same,
      newestId: newest,
      onAccepted: reply => {
        const active = document.activeElement;
        const hadFocus = editActions.contains(active) || ta === active || !active || active === document.body;
        close();
        if (!same) _dropRowsAfter(row, reply);
        const newBubble = document.createElement('div');
        newBubble.className = 'user-bubble';
        newBubble.textContent = same ? original : newText;
        if (ta.isConnected) ta.replaceWith(newBubble);
        // the send button just went: focus moves on with it, not down to the page
        if (hadFocus) _focusReply(reply);
      },
    });
    if (result === 'accepted') return;
    keepEditing();
    if (result === 'gone') {
      // the question went in another tab: its new words go to the message box instead
      _dropEditDraft(draftKey());
      _toComposer(newText);
    }
    const why = typeof result === 'object' ? result.reason : result;
    if (why === 'stale' || why === 'gone' || why === 'offline' || why === 'stopped') {
      await _rereadTask(sid, why, 'edit', row.dataset.msgId, result?.turn || '');
    }
  };

  ta.addEventListener('keydown', e => {
    // enter that picks an ime candidate isn't a send (safari reports it as keyCode 229)
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key !== 'Enter' && e.key !== 'Escape') return;
    // the box owns these keys: ctrl+enter must not also send the composer's draft
    e.stopPropagation();
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save(); }
    if (e.key === 'Escape') { e.preventDefault(); restore({ focus: true }); }
  });
  ta.addEventListener('input', () => { grow(); remember(); });
  cancelBtn.addEventListener('click', () => restore({ focus: true }));
  sendBtn.addEventListener('click', () => save());
  editActions.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); restore({ focus: true }); }
  });
}

function _wireEditButtons(container) {
  container.querySelectorAll('.msg-edit-btn').forEach(btn => {
    if (!_firstWiring(btn)) return;
    btn.addEventListener('click', e => {
      e.stopPropagation();
      // checked before any await: ios only raises the keyboard for a focus inside the tap itself
      if (document.body.classList.contains('aide-working')) { toast(_MSG.busy, ''); return; }
      _openEdit(btn);
    });
  });

  container.querySelectorAll('.msg-regen-btn').forEach(btn => {
    if (!_firstWiring(btn)) return;
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      // a second tap while the first is still checking would drop the first one's new reply
      if (btn.dataset.busy) return;
      const aiRow = btn.closest('.msg-row');
      const prev = _userRowBefore(aiRow);
      const userText = prev?.querySelector('.user-bubble')?.textContent;
      const sid = _activeId;
      if (!userText || !sid) return;
      btn.dataset.busy = '1';
      btn.setAttribute('aria-disabled', 'true');
      try {
        const chat = await import('./chat.js');
        if (!chat.canSendMessage()) { toast(_MSG.busy, ''); return; }
        if (prev.dataset.unsaved) { toast(_MSG.unsaved, 'error'); return; }
        if (!prev.dataset.msgId) { toast(_MSG.reload, 'error'); return; }
        const newest = await _newestShownId();
        if (sid !== _activeId || !aiRow.isConnected) return;
        if (newest === null) { toast(_MSG.offline, 'error'); return; }
        // something else already answered again (another regen, an edit): leave its reply be
        if (!chat.canSendMessage()) return;
        const result = await chat.resendMessage(prev, userText, {
          newestId: newest,
          onAccepted: reply => _focusReply(reply),
        });
        const why = typeof result === 'object' ? result.reason : result;
        if (why === 'stale' || why === 'gone' || why === 'offline' || why === 'stopped') {
          await _rereadTask(sid, why, 'regenerate', prev.dataset.msgId, result?.turn || '');
        }
      } finally {
        delete btn.dataset.busy;
        btn.removeAttribute('aria-disabled');
      }
    });
  });
}

// lazy md render — avoids import cycle with chat.js
function _md(text) {
  // pull from window if util.js already loaded it
  if (window._mdToHtml) return window._mdToHtml(text);
  // basic fallback
  const safe = String(text ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return `<p>${safe.replace(/\n\n/g,'</p><p>').replace(/\n/g,'<br>')}</p>`;
}


export function scrollDown(options = {}) {
  return scrollToLatest(options);
}


// claude-style greeting: time-of-day, your name, and a little variety per refresh
function _escName(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function greetingHtml() {
  const h = new Date().getHours();
  const name = (localStorage.getItem('alles-name') || '').trim();
  const period = h < 5 ? 'night' : h < 12 ? 'morning' : h < 18 ? 'afternoon' : 'evening';
  const pool = [1, 2, 3].map(index => t(`home.greeting.${period}.${index}`));
  const pick = pool[Math.floor(Math.random() * pool.length)];
  return _withName(pick, name);
}

// incognito hero title — same dynamic, time-of-day idea as the welcome greeting but
// with an off-the-record flavor. changes every time you open / refresh.
function incognitoTitle() {
  const h = new Date().getHours();
  let pool;
  if (h < 5)        pool = [t('aide.incognito_night_1'), t('aide.incognito_night_2'), t('aide.incognito_night_3'), t('aide.incognito_night_4'), t('aide.incognito_night_5'), t('aide.incognito_night_6')];
  else if (h < 12)  pool = [t('aide.incognito_morning_1'), t('aide.incognito_morning_2'), t('aide.incognito_morning_3'), t('aide.incognito_morning_4'), t('aide.incognito_morning_5'), t('aide.incognito_morning_6')];
  else if (h < 18)  pool = [t('aide.incognito_afternoon_1'), t('aide.incognito_afternoon_2'), t('aide.incognito_afternoon_3'), t('aide.incognito_afternoon_4'), t('aide.incognito_afternoon_5'), t('aide.incognito_afternoon_6')];
  else              pool = [t('aide.incognito_evening_1'), t('aide.incognito_evening_2'), t('aide.incognito_evening_3'), t('aide.incognito_evening_4'), t('aide.incognito_evening_5'), t('aide.incognito_evening_6')];
  return pool[Math.floor(Math.random() * pool.length)];
}

// drop the name in before any trailing ? . ! so "one more thing?" → "one more thing, eric?"
function _withName(g, name) {
  if (!name) return _escName(g);
  const punct = /[?.!]$/.test(g) ? g.slice(-1) : '';
  const base = punct ? g.slice(0, -1) : g;
  return `${_escName(base)}, <span class="accent">${_escName(name)}</span>${punct}`;
}

// a few real starts under the greeting, so an empty chat says what Aide can do
const STARTS = () => [
  [t('aide.start_plan_label'), t('aide.start_plan_text')],
  [t('aide.start_doc_label'), t('aide.start_doc_text')],
  [t('aide.start_search_label'), t('aide.start_search_text')],
  [t('aide.start_can_label'), t('aide.start_can_text')],
];
function welcomeStarts() {
  return `<div class="welcome-starts" role="list">${STARTS().map(([label, text], n) =>
    `<button type="button" class="welcome-start" role="listitem" style="--n:${n}" data-start="${_escName(text)}">${_escName(label)}</button>`).join('')}</div>`;
}
if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
  document.addEventListener('click', event => {
    const start = event.target.closest?.('.welcome-start');
    if (!start) return;
    const box = document.getElementById('composer-ta');
    if (!box) return;
    box.value = start.dataset.start;
    box.dispatchEvent(new Event('input', { bubbles: true }));
    box.focus();
    box.setSelectionRange(box.value.length, box.value.length);
  });
}

export function showWelcome() {
  const g = document.getElementById('welcome-greeting');
  if (isIncognitoMode()) {
    // dedicated incognito hero — always shown off the record (à la Claude)
    if (g) g.innerHTML = `
      <div class="incognito-hero">
        <svg class="incognito-hero-mark incognito-ghost" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 21v-9a7 7 0 0 1 14 0v9l-2.4-1.5L14.2 21l-2.2-1.5L9.8 21l-2.4-1.5L5 21z"/><circle cx="9.5" cy="11" r="0.5" fill="currentColor"/><circle cx="14.5" cy="11" r="0.5" fill="currentColor"/></svg>
        <div class="incognito-hero-title">${incognitoTitle()}</div>
        <div class="incognito-hero-note">${escHtml(t('aide.incognito_note'))}</div>
      </div>`;
    document.getElementById('welcome').style.display = 'flex';
    document.getElementById('messages').style.display = 'none';
  } else if (welcomeEnabled()) {
    if (g) g.innerHTML = greetingHtml() + welcomeStarts();
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
  const tokValue = document.getElementById('session-token-count-value');
  const conversation = document.getElementById('aide-conversation-name');
  const projectName = document.getElementById('aide-project-name');
  const project = session?.project_id ? getProjects().find(item => item.id === session.project_id) : null;
  if (conversation) {
    conversation.textContent = session?.name || t('aide.new_task');
    conversation.title = conversation.textContent;
  }
  if (projectName) {
    projectName.textContent = project?.name || '';
    projectName.title = projectName.textContent;
  }
  window._syncAideNewTaskContext?.(session || null);
  if (!session) {
    if (actBtn)   actBtn.style.display   = 'none';
    if (tokCount) {
      tokCount.hidden = true;
      tokCount.removeAttribute('aria-label');
    }
    if (tokValue) tokValue.textContent = '';
    return;
  }
  if (actBtn)   actBtn.style.display   = '';
  // token count stays hidden until chat.js populates it
}

// download the active chat in any format — the server builds md/json/txt/html
export function downloadSession(fmt = 'md') {
  if (!_activeId) { toast(t('aide.no_active_chat'), 'error'); return; }
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

window.addEventListener('alles:localization-change', () => {
  const welcome = document.getElementById('welcome');
  if (welcome && welcome.style.display !== 'none') showWelcome();
  updateSessionHeader(window._currentSession || null);
});


export async function createSession(model = '', endpointId = '', options = {}) {
  const override = modelOverrideForNewSession(model, endpointId);
  const r = await fetch('/api/sessions', {
    method: 'POST',
    headers: {'content-type':'application/json'},
    body: JSON.stringify({
      name: 'new task',
      model: override.model,
      endpoint_id: override.endpointId,
      incognito: !!options.incognito,
      mode: options.mode || 'chat',
      chat_behavior: options.chatBehavior ?? window._pendingChatBehavior ?? '',
      project_id: options.projectId ?? window._pendingProjectId ?? '',
      working_dir: options.workingDir ?? window._pendingWorkingDir ?? '',
    }),
  });
  if (!r.ok) return null;
  const s = await r.json();
  if (!options.incognito) await loadSessions();
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
  const openButton = el.querySelector('.session-open');
  const current = nameEl.textContent;
  const inp = document.createElement('input');
  inp.value = current;
  inp.style.cssText = 'background:none;border:none;border-bottom:1px solid var(--muted);color:var(--text);font:inherit;font-size:0.8rem;min-width:0;flex:1;outline:none;padding:0';
  openButton.hidden = true;
  openButton.insertAdjacentElement('afterend', inp);
  inp.focus(); inp.select();
  let restoreRowFocus = false;

  const commit = async () => {
    const name = inp.value.trim() || current;
    await fetch(`/api/sessions/${id}`, {
      method:'PATCH', headers:{'content-type':'application/json'},
      body: JSON.stringify({ name }),
    });
    nameEl.textContent = name;
    inp.remove();
    openButton.hidden = false;
    updateSessionName(id, name);
    if (restoreRowFocus && openButton.isConnected) openButton.focus();
  };
  inp.addEventListener('blur', commit);
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); restoreRowFocus = true; inp.blur(); }
    if (e.key === 'Escape') { restoreRowFocus = true; inp.value = current; inp.blur(); }
  });
}


// below and right of the point or button, flipped when it doesn't fit. the row's more button
// sits near a phone's right edge, and a low row pushed delete off the bottom where touch can't go
function placeCtxMenu(menu, at) {
  const pad = 8;
  menu.style.maxHeight = `${Math.max(0, innerHeight - pad * 2)}px`;
  menu.style.overflowY = 'auto';
  // kokuen's observer gives the rows their 44px only after this task; stamp them now so the
  // height measured here is the height shown
  menu.querySelectorAll('[role="menuitem"]:not([data-kokuen-primitive])').forEach(item => { item.dataset.kokuenPrimitive = 'menu-item'; });
  // measured at the corner, so the last spot near an edge doesn't squeeze it
  menu.style.left = menu.style.top = '0px';
  const { width, height } = menu.getBoundingClientRect();
  let x = at.left, y = at.bottom;
  if (x + width > innerWidth - pad) x = at.right - width;
  if (y + height > innerHeight - pad) y = at.top - height;
  menu.style.left = `${Math.max(pad, Math.min(x, innerWidth - pad - width))}px`;
  menu.style.top = `${Math.max(pad, Math.min(y, innerHeight - pad - height))}px`;
}

function _focusSessionRow(ids, control = '.session-open') {
  for (const sid of ids) {
    const target = sid && document.querySelector(`.session-item[data-id="${sid}"] ${control}`);
    if (target?.getClientRects().length) { target.focus(); return true; }
  }
  return false;
}

function _focusSessionFallback() {
  const search = document.getElementById('session-search');
  (search?.getClientRects().length ? search : document.getElementById('composer-ta'))?.focus();
}

function openCtxMenu(e, id, source = null) {
  const menu = document.getElementById('ctx-menu');
  const s = _allSessions.find(x => x.id === id);
  if (!s) return;

  const projects = getProjects();
  const projectItems = projects.map(p =>
    `<button type="button" role="menuitem" class="ctx-item" data-action="move-project" data-pid="${p.id}">${escHtml(t('aide.move_to_project', { name: p.name }))}</button>`
  ).join('');
  menu.innerHTML = `
    <button type="button" role="menuitem" class="ctx-item" data-action="rename">${escHtml(t('aide.rename'))}</button>
    <button type="button" role="menuitem" class="ctx-item" data-action="star">${s.starred ? t('aide.unstar') : t('aide.star')}</button>
    <button type="button" role="menuitem" class="ctx-item" data-action="archive">${escHtml(t('aide.archive'))}</button>
    ${projectItems}
    <button type="button" role="menuitem" class="ctx-item" data-action="new-project">${escHtml(t('aide.new_project'))}</button>
    <button type="button" role="menuitem" class="ctx-item danger" data-action="delete">${escHtml(t('common.delete'))}</button>
  `;
  _contextMenuController ||= createMenuController(menu);
  _contextMenuController.open({ source: source || e.currentTarget });
  placeCtxMenu(menu, e.anchor || { left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY });

  menu.querySelectorAll('.ctx-item').forEach(item => {
    item.addEventListener('click', async () => {
      const action = item.dataset.action;
      _contextMenuController.close({ restoreFocus: action !== 'rename' });
      // every change rebuilds the list under the menu's button: come back to this row, or to the
      // next one when it left the list
      const ids = [...document.querySelectorAll('#session-list .session-item')].map(row => row.dataset.id);
      const at = ids.indexOf(id);
      const control = source?.classList?.contains('session-more') ? '.session-more' : '.session-open';
      const refocus = (gone = false) => _focusSessionRow(gone ? [ids[at + 1], ids[at - 1]] : [id], control) || _focusSessionFallback();
      if (action === 'rename') {
        const el = document.querySelector(`.session-item[data-id="${id}"]`);
        if (el) startRename(el, id);
      } else if (action === 'star') {
        await fetch(`/api/sessions/${id}`, {
          method:'PATCH', headers:{'content-type':'application/json'},
          body: JSON.stringify({ starred: !s.starred }),
        });
        await loadSessions();
        refocus();
      } else if (action === 'archive') {
        await fetch(`/api/sessions/${id}/archive`, { method: 'POST' });
        await loadSessions();
        // only reset the view if we archived the chat we're actually looking at —
        // archiving some other session while on a fresh chat shouldn't wipe it
        if (id === _activeId) newChat();
        refocus(true);
      } else if (action === 'move-project') {
        const pid = item.dataset.pid;
        await fetch(`/api/projects/${pid}/sessions/${id}`, { method: 'POST' });
        await loadProjects();
        await loadSessions();
        refocus();
        toast(t('aide.moved_to_project'), 'success');
      } else if (action === 'new-project') {
        const name = await _dlgPrompt('', '', { title: t('aide.new_project'), label: t('aide.project_name'), confirmLabel: t('aide.create') });
        if (!name?.trim()) return;
        const p = await createProject(name.trim());
        if (p) {
          await assignSession(p.id, id);   // file this chat into the new project
          await loadProjects();
          await loadSessions();
          refocus();
          toast(t('aide.project_created', { name }), 'success');
        }
      } else if (action === 'delete') {
        if (!await _dlgConfirm(t('aide.delete_session_confirm'))) return;
        const res = await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
        if (!res.ok) {
          const detail = (await res.json().catch(() => ({})))?.detail;
          toast(typeof detail === 'string' && detail ? detail : (s.starred ? t('aide.unstar_before_delete') : t('aide.delete_failed')), 'error');
          return;
        }
        const wasActive = id === _activeId;
        await loadSessions();
        if (wasActive) newChat();
        refocus(true);
      }
    });
  });
}
