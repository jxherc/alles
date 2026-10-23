// Offline changes stay in this browser until the server accepts them or the owner
// explicitly discards a reviewed failure.
import { confirm as confirmDialog } from './dialog.js';

function _sw() {
  return navigator.serviceWorker;
}

function flush(retryAuth = false) {
  _sw()?.controller?.postMessage({ type: 'alles-flush', retryAuth });
}

function ping() {
  _sw()?.controller?.postMessage({ type: 'alles-pending' });
}

function outboxMessage(type, extra = {}) {
  return new Promise((resolve, reject) => {
    const worker = _sw()?.controller;
    if (!worker) { reject(new Error('offline storage is not ready. try again.')); return; }
    const channel = new MessageChannel();
    const timer = setTimeout(() => {
      channel.port1.close();
      reject(new Error('offline storage did not respond. try again.'));
    }, 15000);
    channel.port1.onmessage = event => {
      clearTimeout(timer);
      channel.port1.close();
      if (event.data?.ok) resolve(event.data);
      else reject(new Error(event.data?.error || 'could not read offline changes. try again.'));
    };
    worker.postMessage({ type, ...extra }, [channel.port2]);
  });
}

function node(tag, text, className = '') {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function button(label, action, className = 'btn') {
  const element = node('button', label, className);
  element.type = 'button';
  element.addEventListener('click', action);
  return element;
}

function itemTitle(item) {
  let area = 'Alles';
  try {
    const part = new URL(item.url, location.origin).pathname.split('/')[2];
    area = ({ health: 'Health', tasks: 'Plan', calendar: 'Plan', reminders: 'Plan',
      habits: 'Health', wiki: 'Docs', files: 'Files', books: 'Library', read: 'Library',
      mail: 'Inbox', contacts: 'Inbox' })[part] || 'Alles';
  } catch {}
  const action = ({ POST: 'add', PUT: 'update', PATCH: 'update', DELETE: 'delete' })[item.method] || 'change';
  return `${area} · ${action}`;
}

function itemReason(item, earlierPending = false) {
  switch (item.blocked_reason) {
    case 'auth_required': return 'sign in to send this saved change.';
    case 'conflict': return 'this change conflicts with the current saved data. check the app before retrying.';
    case 'validation_failed': return 'the server could not accept this input. save a copy, correct it in the app, then discard this copy.';
    case 'replay_policy_changed': return 'this change needs to be entered again in its app. this version cannot send it automatically.';
    case 'request_rejected': return 'the server rejected this change. check the saved input and the app before retrying.';
    default: return earlierPending
      ? 'waiting for an earlier offline change to be resolved.'
      : item.response_status
      ? 'the server is temporarily unavailable. this change is kept for another attempt.'
      : 'waiting to send when the connection returns.';
  }
}

function saveCopy(item) {
  const blob = new Blob([JSON.stringify(item, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = node('a');
  link.href = url;
  link.download = `alles-offline-change-${item.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let reviewOpen = false;
async function reviewOutbox() {
  if (reviewOpen) return;
  reviewOpen = true;
  const previousFocus = document.activeElement;
  const overlay = node('div', null, 'dialog-overlay');
  const card = node('div', null, 'dialog-card sync-review');
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-modal', 'true');
  card.setAttribute('aria-labelledby', 'sync-review-title');
  const title = node('h2', 'offline changes');
  title.id = 'sync-review-title';
  const status = node('p', 'loading saved changes…', 'sync-review-status');
  status.id = 'sync-review-status';
  status.setAttribute('role', 'status');
  status.tabIndex = -1;
  const list = node('div', null, 'sync-review-list');
  const actions = node('div', null, 'dialog-btns');
  const close = button('close', dismiss);
  actions.append(close);
  card.append(title, status, list, actions);
  overlay.append(card);
  const background = [...document.body.children].map(element => [element, element.inert]);
  background.forEach(([element]) => { element.inert = true; });
  document.body.append(overlay);
  close.focus();
  let busy = false;

  function dismiss() {
    overlay.remove();
    background.forEach(([element, inert]) => { element.inert = inert; });
    reviewOpen = false;
    const target = previousFocus?.isConnected && previousFocus.getClientRects().length
      ? previousFocus : document.getElementById('app-drawer-btn');
    target?.focus();
  }

  overlay.addEventListener('click', event => { if (event.target === overlay) dismiss(); });
  overlay.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); dismiss(); }
    if (event.key !== 'Tab') return;
    const items = [...card.querySelectorAll('button, input, textarea, summary')].filter(item => !item.disabled);
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });

  async function refresh() {
    const { items } = await outboxMessage('alles-outbox-list');
    if (!overlay.isConnected) return;
    list.replaceChildren();
    status.textContent = items.length
      ? 'saved in this browser. they are not yet saved on the server.'
      : 'all changes have been sent or discarded.';
    let earlierPending = false;
    for (const item of items) {
      renderItem(item, earlierPending);
      earlierPending ||= item.blocked_reason !== 'replay_policy_changed';
    }
  }

  async function run(action) {
    if (busy) return;
    busy = true;
    list.querySelectorAll('button').forEach(element => { element.disabled = true; });
    status.textContent = 'updating…';
    try {
      await action();
      await refresh();
      if (overlay.isConnected) status.focus();
    } catch (error) {
      status.textContent = error.message;
      if (overlay.isConnected) status.focus();
    } finally {
      busy = false;
      list.querySelectorAll('button').forEach(element => { element.disabled = element.dataset.outboxWaiting === 'true'; });
    }
  }

  function renderItem(item, earlierPending) {
    const section = node('section', null, 'sync-review-item');
    section.dataset.outboxId = item.id;
    section.append(node('h3', itemTitle(item)), node('p', itemReason(item, earlierPending)));
    if (item.response_detail) section.append(node('p', item.response_detail, 'sync-review-detail'));
    if (earlierPending && item.blocked_reason !== 'replay_policy_changed') {
      const waiting = node('p', 'resolve the earlier offline change before retrying this one.');
      waiting.id = `sync-waiting-${item.id}`;
      section.append(waiting);
    }
    const values = node('dl', null, 'sync-review-values');
    let payload;
    try { payload = JSON.parse(item.body); } catch { payload = { input: item.body }; }
    const fields = payload && typeof payload === 'object' && !Array.isArray(payload)
      ? Object.entries(payload) : [['input', payload]];
    for (const [key, value] of fields) {
      values.append(node('dt', key.replace(/_/g, ' ')), node('dd', typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')));
    }
    if (fields.length) section.append(values);
    const controls = node('div', null, 'sync-review-actions');
    controls.append(button('save a copy', () => saveCopy(item)));
    if (item.blocked_reason === 'auth_required' && !earlierPending) {
      const label = node('label', 'Alles password');
      const password = node('input', null, 'settings-input');
      password.type = 'password';
      password.autocomplete = 'current-password';
      password.id = `sync-password-${item.id}`;
      password.setAttribute('aria-describedby', 'sync-review-status');
      label.htmlFor = password.id;
      const signIn = () => run(async () => {
        let response;
        try {
          response = await fetch('/api/auth/login', {
            method: 'POST', headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ password: password.value }),
          });
        } catch { throw new Error('could not reach Alles. your offline change is kept.'); }
        if (!response.ok) throw new Error(response.status === 401 ? 'wrong password. your offline change is kept.'
          : response.status === 429 ? 'too many attempts. wait a few minutes and try again.'
            : 'sign-in is temporarily unavailable. your offline change is kept.');
        password.value = '';
        await outboxMessage('alles-flush', { retryAuth: true });
      });
      password.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); signIn(); }
      });
      section.append(label, password);
      controls.append(button('sign in & retry', signIn));
    } else if (item.blocked_reason !== 'replay_policy_changed') {
      const retry = button('retry saved change', () => run(() => outboxMessage('alles-retry-outbox', { id: item.id })));
      if (earlierPending) {
        retry.disabled = true;
        retry.dataset.outboxWaiting = 'true';
        retry.setAttribute('aria-describedby', `sync-waiting-${item.id}`);
      }
      controls.append(retry);
    }
    if (item.blocked_reason) {
      controls.append(button('discard', async () => {
        if (await confirmDialog('discard this offline change? its saved input will be removed from this browser.')) {
          await run(() => outboxMessage('alles-discard-outbox', { id: item.id }));
        }
      }, 'btn danger'));
    }
    section.append(controls);
    list.append(section);
  }

  try { await refresh(); }
  catch (error) { status.textContent = error.message; }
}

function updateBadge(n, blocked = 0, auth = 0) {
  const el = document.getElementById('sync-indicator');
  if (!el) return;
  let status = el.querySelector('span');
  if (!status) {
    status = node('span');
    el.replaceChildren(status, button('review', reviewOutbox));
  }
  status.textContent = auth > 0 ? `${n} offline change${n === 1 ? '' : 's'} · sign in needed`
    : blocked > 0 ? `${n} offline change${n === 1 ? '' : 's'} · needs attention` : `${n} pending`;
  el.style.display = n > 0 ? 'flex' : 'none';
  el.title = 'changes saved in this browser, waiting to reach the server';
}

export function initSync() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('/sw.js').catch(() => {});
  let lastAt = 0;
  navigator.serviceWorker.addEventListener('message', e => {
    if (e.data?.type === 'alles-sync') {
      const at = e.data.at || 0;
      if (at >= lastAt) { lastAt = at; updateBadge(e.data.pending, e.data.blocked, e.data.auth); }
    }
  });
  window.addEventListener('online', () => { flush(); ping(); });
  window.addEventListener('offline', ping);
  // Boot follows the app's sign-in check, so a login after reload can resume
  // authentication failures. Validation and conflict failures always need review.
  navigator.serviceWorker.ready.then(() => { ping(); if (navigator.onLine) flush(true); });
  navigator.serviceWorker.addEventListener('controllerchange', () => { ping(); if (navigator.onLine) flush(true); });
}
