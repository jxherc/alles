// Offline changes stay in this browser until the server accepts them or the owner
// explicitly discards a reviewed failure.
import { confirm as confirmDialog } from './dialog.js';
import { t, tp } from './i18n.js';

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
    if (!worker) { reject(new Error(t('sync.storage_not_ready'))); return; }
    const channel = new MessageChannel();
    const timer = setTimeout(() => {
      channel.port1.close();
      reject(new Error(t('sync.storage_no_response')));
    }, 15000);
    channel.port1.onmessage = event => {
      clearTimeout(timer);
      channel.port1.close();
      if (event.data?.ok) resolve(event.data);
      else reject(new Error(event.data?.error || t('sync.read_failed')));
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
    area = ({ health: t('sync.area_health'), tasks: t('sync.area_plan'), calendar: t('sync.area_plan'), reminders: t('sync.area_plan'),
      habits: t('sync.area_health'), wiki: t('sync.area_docs'), files: t('sync.area_files'), books: t('sync.area_library'), read: t('sync.area_library'),
      mail: t('sync.area_inbox'), contacts: t('sync.area_inbox') })[part] || 'Alles';
  } catch {}
  const action = ({ POST: t('common.add'), PUT: t('sync.action_update'), PATCH: t('sync.action_update'), DELETE: t('common.delete') })[item.method] || t('sync.action_change');
  return t('sync.item_title', { area, action });
}

function itemReason(item, earlierPending = false) {
  switch (item.blocked_reason) {
    case 'auth_required': return t('sync.reason_auth');
    case 'conflict': return t('sync.reason_conflict');
    case 'validation_failed': return t('sync.reason_validation');
    case 'replay_policy_changed': return t('sync.reason_policy');
    case 'request_rejected': return t('sync.reason_rejected');
    default: return earlierPending
      ? t('sync.reason_earlier')
      : item.response_status
      ? t('sync.reason_unavailable')
      : t('sync.reason_waiting');
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
  const title = node('h2', t('sync.title'));
  title.id = 'sync-review-title';
  const status = node('p', t('sync.loading'), 'sync-review-status');
  status.id = 'sync-review-status';
  status.setAttribute('role', 'status');
  status.tabIndex = -1;
  const list = node('div', null, 'sync-review-list');
  const actions = node('div', null, 'dialog-btns');
  const close = button(t('common.close'), dismiss);
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
      ? t('sync.pending_note')
      : t('sync.all_clear');
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
    status.textContent = t('sync.updating');
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
      const waiting = node('p', t('sync.resolve_earlier'));
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
    controls.append(button(t('sync.save_copy'), () => saveCopy(item)));
    if (item.blocked_reason === 'auth_required' && !earlierPending) {
      const label = node('label', t('sync.password'));
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
        } catch { throw new Error(t('sync.signin_unreachable')); }
        if (!response.ok) throw new Error(response.status === 401 ? t('sync.signin_wrong')
          : response.status === 429 ? t('sync.signin_throttled')
            : t('sync.signin_unavailable'));
        password.value = '';
        await outboxMessage('alles-flush', { retryAuth: true });
      });
      password.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); signIn(); }
      });
      section.append(label, password);
      controls.append(button(t('sync.signin_retry'), signIn));
    } else if (item.blocked_reason !== 'replay_policy_changed') {
      const retry = button(t('sync.retry'), () => run(() => outboxMessage('alles-retry-outbox', { id: item.id })));
      if (earlierPending) {
        retry.disabled = true;
        retry.dataset.outboxWaiting = 'true';
        retry.setAttribute('aria-describedby', `sync-waiting-${item.id}`);
      }
      controls.append(retry);
    }
    if (item.blocked_reason) {
      controls.append(button(t('sync.discard'), async () => {
        if (await confirmDialog(t('sync.discard_confirm'))) {
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
    el.replaceChildren(status, button(t('sync.review'), reviewOutbox));
  }
  status.textContent = auth > 0 ? tp('sync.badge_sign_in', n)
    : blocked > 0 ? tp('sync.badge_attention', n) : t('sync.badge_pending', { count: n });
  el.style.display = n > 0 ? 'flex' : 'none';
  el.title = t('sync.badge_title');
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
