// messages sent while aide is still replying. each shows in the chat at once, under the reply that
// is running, with a remove button; the next turn answers them all together. normal tasks keep
// them on the server (they survive a reload); a private task keeps them here only
import { toast } from './util.js';
import { t } from './i18n.js';
import { appendUserMsg, scrollDown } from './sessions.js';

// the active task's waiting messages, oldest first: { id, text, fileIds, row, local }
let _items = [];
let _sessionId = '';
let _localCount = 0;

const jsonHeaders = { 'content-type': 'application/json' };

export function queuedItems(sessionId) {
  return sessionId === _sessionId ? _items.slice() : [];
}

function drawRow(item) {
  const row = appendUserMsg(item.text);
  row.dataset.queued = item.id;
  const actions = row.querySelector('.user-actions');
  if (actions) {
    actions.replaceChildren();
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'msg-unqueue-btn';
    remove.textContent = t('common.remove');
    const snippet = item.text.length > 40 ? `${item.text.slice(0, 40)}…` : item.text;
    remove.setAttribute('aria-label', `${t('common.remove')}: ${snippet}`);
    remove.addEventListener('click', () => void removeQueued(item.id));
    actions.appendChild(remove);
  }
  item.row = row;
  return row;
}

// a task was opened or re-read: its waiting messages go back under the history
export function drawQueued(sessionId, list = []) {
  const local = sessionId === _sessionId ? _items.filter(item => item.local) : [];
  _sessionId = sessionId;
  _items = [
    ...list.map(entry => ({ id: entry.id, text: entry.message, fileIds: entry.file_ids || [], row: null, local: false })),
    ...local,
  ];
  for (const item of _items) drawRow(item);
}

export async function addQueued(sessionId, text, fileIds, { privateTask = false } = {}) {
  let item;
  if (privateTask) {
    item = { id: `local-${++_localCount}`, text, fileIds: [...fileIds], row: null, local: true };
  } else {
    let entry = null;
    try {
      const r = await fetch('/api/chat/queue', {
        method: 'POST', headers: jsonHeaders,
        body: JSON.stringify({ session_id: sessionId, message: text, file_ids: fileIds }),
      });
      if (r.ok) entry = await r.json();
    } catch { /* the draft stays in the box */ }
    if (!entry) { toast(t('common.request_failed'), 'error'); return false; }
    item = { id: entry.id, text, fileIds: [...fileIds], row: null, local: false };
  }
  if (sessionId !== _sessionId) { _sessionId = sessionId; _items = []; }
  _items.push(item);
  drawRow(item);
  return true;
}

export async function removeQueued(id) {
  const item = _items.find(entry => entry.id === id);
  if (!item) return;
  const button = item.row?.querySelector('.msg-unqueue-btn');
  // read before disabling: a disabled button drops focus
  const hadFocus = item.row?.contains(document.activeElement);
  if (button) button.disabled = true;
  if (!item.local) {
    const r = await fetch(`/api/chat/queue/${encodeURIComponent(_sessionId)}/${encodeURIComponent(id)}`, { method: 'DELETE' }).catch(() => null);
    if (!r?.ok) {
      if (button) button.disabled = false;
      toast(t('common.request_failed'), 'error');
      return;
    }
    // aide may have taken it a moment ago: that turn answers it, so only the list is told
    const { removed } = await r.json().catch(() => ({ removed: true }));
    if (!removed) { if (button) button.disabled = false; return; }
  }
  const composer = document.getElementById('composer-ta');
  item.row?.remove();
  _items = _items.filter(entry => entry !== item);
  if (hadFocus) composer?.focus();
}

// the next turn takes everything waiting: one question made of the messages in order
export function takeQueued(sessionId) {
  if (sessionId !== _sessionId || !_items.length) return null;
  const items = _items.slice();
  return {
    items,
    text: items.map(item => item.text).join('\n\n'),
    fileIds: [...new Set(items.flatMap(item => item.fileIds))],
    ids: items.filter(item => !item.local).map(item => item.id),
    // the waiting rows become the one question the server saves
    askRow() {
      const row = appendUserMsg(this.text);
      for (const item of items) item.row?.remove();
      return row;
    },
  };
}

// a turn that took them is under way: nothing waits any more
export function clearQueued(taken) {
  _items = _items.filter(item => !taken.items.includes(item));
}

// the turn that should have taken them was refused: they go back as they were
export function restoreQueued(taken, askRow) {
  askRow?.remove();
  for (const item of taken.items) if (item.row && !item.row.isConnected) drawRow(item);
  scrollDown();
}
