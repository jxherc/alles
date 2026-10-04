import { toast } from './util.js';
import { confirm } from './dialog.js';
import { initCustomDropdown } from './dropdown.js?v=212';
import { initDatePicker, dateTimeParts } from './datepick.js';
import { calendarDateKey, formatDate, formatDateParts, formatTime, resolvedTimeZone } from './i18n.js';

let _reminders = [];
let _pollTimer = null;
let _checking = false;
let _revision = 0;
let _loaded = false;
let _loading = false;
let _loadError = '';
let _creation = null;
let _saving = false;
let _reloadPanel = null;
const _pendingChanges = new Set();
const _cancelling = new Set();
const _cancelRecovery = new Map();

export async function loadReminders(fetcher = fetch) {
  const retryFocused = document.activeElement?.hasAttribute('data-reminder-retry');
  const revision = ++_revision;
  _loading = true;
  _loadError = '';
  _render();
  try {
    const r = await fetcher('/api/reminders');
    if (!r.ok) throw new Error('could not load reminders');
    const rows = await r.json();
    if (!Array.isArray(rows)) throw new Error('could not load reminders');
    if (revision !== _revision) return;
    _reminders = rows;
    _loaded = true;
  } catch (error) {
    if (revision === _revision) _loadError = 'could not load reminders';
    throw error;
  } finally {
    if (revision === _revision) {
      _loading = false;
      _render();
      _focusLoadResult(retryFocused);
    }
  }
}

function _focusLoadResult(owned) {
  if (!owned || document.activeElement !== document.body) return;
  const target = document.querySelector('#reminder-list [data-reminder-retry], #reminder-list [data-reminder-cancel]:not(:disabled)') || document.getElementById('reminder-text');
  if (target?.getClientRects().length) target.focus();
}

async function _retryLoad() {
  const owned = document.activeElement?.hasAttribute('data-reminder-retry');
  try {
    if (_reloadPanel) await _reloadPanel();
    else await loadReminders();
  } catch {} finally { _focusLoadResult(owned); }
}

function _render() {
  const el = document.getElementById('reminder-list');
  if (!el) return;
  const focusedId = el.contains(document.activeElement) ? document.activeElement.dataset.reminderCancel : null;
  const focusedRetry = el.contains(document.activeElement) && document.activeElement.hasAttribute('data-reminder-retry');
  const status = _loadError
    ? `<div role="alert">${_loadError} <button type="button" class="btn" data-reminder-retry>retry</button></div>`
    : _loading ? '<div role="status" data-reminder-loading>loading reminders…</div>' : '';
  el.innerHTML = status + (!_reminders.length
    ? (_loaded && !_loadError && !_loading ? '<div class="page-empty">no reminders</div>' : '')
    : _reminders.map(r => `
      <div class="settings-list-row" data-id="${_esc(r.id)}">
        <div style="flex:1;min-width:0">
          <div class="row-name">${_esc(r.text)}</div>
          <div class="reminder-meta">${_esc(_fmtTime(r.trigger_at))} · ${r.type === 'message' ? 'scheduled message' : 'reminder'}${r.delivery_started ? ' · delivery started; check the conversation for a reply' : ''}</div>
        </div>
        <button type="button" class="act-btn" data-reminder-cancel="${_esc(r.id)}"${_cancelling.has(r.id) ? ' disabled' : ''}>cancel</button>
      </div>`).join(''));
  el.querySelector('[data-reminder-retry]')?.addEventListener('click', _retryLoad);
  el.querySelectorAll('[data-reminder-cancel]').forEach(button => {
    button.addEventListener('click', () => window._delReminder(button.dataset.reminderCancel, button));
  });
  if (focusedRetry && document.activeElement === document.body) {
    el.querySelector('[data-reminder-retry]')?.focus();
  } else if (focusedId && document.activeElement === document.body) {
    const target = [...el.querySelectorAll('[data-reminder-cancel]')].find(button => button.dataset.reminderCancel === focusedId);
    (target && !target.disabled ? target : document.getElementById('reminder-text'))?.focus();
  }
  _renderCancelRecovery();
}

function _renderCancelRecovery() {
  const el = document.getElementById('reminder-undo-list');
  if (!el) return;
  const focusedAction = ['data-reminder-recover', 'data-reminder-dismiss'].find(name => document.activeElement?.hasAttribute(name));
  const focused = focusedAction && el.contains(document.activeElement) ? document.activeElement.getAttribute(focusedAction) : null;
  el.hidden = !_cancelRecovery.size;
  el.innerHTML = [..._cancelRecovery].map(([id, entry]) => {
    const busy = _cancelling.has(id) || entry.restoring;
    const label = entry.restoring ? 'restoring…' : !entry.cancelled ? 'retry cancel' : entry.error ? 'retry undo' : 'undo';
    const status = entry.error || (entry.cancelled ? 'cancelled; undo is available until this page reloads' : 'cancelling…');
    return `<div class="settings-list-row">
      <div style="flex:1;min-width:0">
        <div class="row-name">${_esc(entry.reminder.text)}</div>
        <div class="reminder-meta">${_esc(_fmtTime(entry.reminder.trigger_at))} · ${entry.reminder.type === 'message' ? 'scheduled message' : 'reminder'}</div>
        <div class="reminder-meta" role="status">${_esc(status)}</div>
      </div>
      <button type="button" class="act-btn" data-reminder-recover="${_esc(id)}"${busy ? ' disabled' : ''}>${label}</button>
      <button type="button" class="act-btn" data-reminder-dismiss="${_esc(id)}"${busy ? ' disabled' : ''}>dismiss</button>
    </div>`;
  }).join('');
  el.querySelectorAll('[data-reminder-recover]').forEach(button => {
    button.addEventListener('click', () => {
      const id = button.dataset.reminderRecover;
      if (_cancelRecovery.get(id)?.cancelled) _undoReminder(id, button);
      else window._delReminder(id, button);
    });
  });
  el.querySelectorAll('[data-reminder-dismiss]').forEach(button => {
    button.addEventListener('click', async () => {
      const id = button.dataset.reminderDismiss;
      const entry = _cancelRecovery.get(id);
      if (!entry || entry.restoring || _cancelling.has(id)) return;
      if ((!entry.cancelled || entry.request) && !await confirm('this reminder may still be active. dismiss this retry? check the reminder list before creating another.')) return;
      if (entry.restoring || _cancelling.has(id)) return;
      const hadFocus = document.activeElement === button;
      _cancelRecovery.delete(id);
      _renderCancelRecovery();
      if (hadFocus && document.activeElement === document.body) document.getElementById('reminder-text')?.focus();
    });
  });
  if (focused && document.activeElement === document.body) {
    [...el.querySelectorAll(`[${focusedAction}]`)].find(button => button.getAttribute(focusedAction) === focused && !button.disabled)?.focus();
  }
}

async function _undoReminder(id, button) {
  const entry = _cancelRecovery.get(id);
  if (!entry?.cancelled || entry.restoring) return;
  const hadFocus = document.activeElement === button;
  entry.restoring = true;
  _renderCancelRecovery();
  let restored;
  try {
    const reminder = entry.reminder;
    const triggerAt = reminder.trigger_at + (/(Z|[+-]\d\d:\d\d)$/.test(reminder.trigger_at) ? '' : 'Z');
    if (!entry.request) {
      if (reminder.type === 'message' && new Date(triggerAt) <= new Date()
          && !await confirm('the scheduled time has passed. restoring this message will send it now. restore it?')) return;
      entry.request = Object.freeze({ text: reminder.text, trigger_at: triggerAt, type: reminder.type, session_id: reminder.session_id, request_id: newRequestId() });
    }
    restored = await createReminder(entry.request);
    _cancelRecovery.delete(id);
    toast(restored.fired ? 'reminder already delivered' : 'reminder restored', 'success');
  } catch (error) {
    if (error.status === 410) _cancelRecovery.delete(id);
    else entry.error = `${error.message || 'could not confirm restoration'}. retry undo to confirm the same reminder.`;
    toast(error.status === 410 ? 'the restored reminder was cancelled' : entry.error, 'error');
  } finally {
    entry.restoring = false;
    _renderCancelRecovery();
    if (hadFocus && document.activeElement === document.body) {
      const retry = [...document.querySelectorAll('[data-reminder-recover]')].find(node => node.dataset.reminderRecover === id);
      const saved = [...document.querySelectorAll('[data-reminder-cancel]')].find(node => node.dataset.reminderCancel === restored?.id);
      (retry || saved || document.getElementById('reminder-text'))?.focus();
    }
  }
}

function _fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso + (/(Z|[+-]\d\d:\d\d)$/.test(iso) ? '' : 'Z'));
  const diff = d.getTime() - Date.now();
  if (diff < 0) return 'due now';
  if (diff < 60000) return 'in <1m';
  if (diff < 3600000) return `in ${Math.round(diff / 60000)}m`;
  if (diff < 86400000) return `in ${Math.round(diff / 3600000)}h`;
  return `${formatDate(d)} ${formatTime(d, { hour: '2-digit', minute: '2-digit' })}`;
}

// The picker displays the configured timezone, which may differ from this browser's zone.
export function reminderTimeFromWall(value) {
  const p = dateTimeParts(value);
  if (!p) throw new Error('pick a valid date and time');
  const wall = Date.UTC(p.y, p.mo, p.d, p.h, p.mi);
  const options = {
    timeZone: resolvedTimeZone(), calendar: 'gregory', numberingSystem: 'latn',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  };
  const asWall = instant => {
    const parts = Object.fromEntries(formatDateParts(new Date(instant), options).map(part => [part.type, Number(part.value)]));
    return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute);
  };
  const offsets = new Set();
  for (let hours = -36; hours <= 36; hours += 6) {
    const instant = wall + hours * 3600000;
    offsets.add(asWall(instant) - instant);
  }
  const matches = [...offsets].map(offset => wall - offset).filter(instant => asWall(instant) === wall).sort((a, b) => a - b);
  if (!matches.length) throw new Error('that time does not exist in this timezone; choose another time');
  // A repeated autumn clock time selects its first occurrence.
  return new Date(matches[0]);
}

function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function reminderRequest(text, triggerAt, type = 'reminder', sessionId = null) {
  return Object.freeze({ text, trigger_at: triggerAt.toISOString(), type, session_id: sessionId, request_id: newRequestId() });
}

function _beginReminderChange() {
  let resolve;
  const pending = new Promise(done => { resolve = done; });
  _pendingChanges.add(pending);
  _revision++;
  return () => {
    _revision++;
    _loading = false;
    document.querySelector('#reminder-list [data-reminder-loading]')?.remove();
    _pendingChanges.delete(pending);
    resolve();
  };
}

export async function createReminder(request) {
  let data;
  for (let attempt = 0; attempt < 3; attempt++) {
    await Promise.all([..._pendingChanges]);
    const revision = _revision;
    const response = await fetch('/api/reminders', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(request),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const error = new Error(typeof body.detail === 'string' ? body.detail : 'could not save reminder');
      error.status = response.status;
      if (response.status === 410) await loadReminders().catch(() => {});
      throw error;
    }
    data = await response.json();
    if (!data.id || data.text !== request.text || data.type !== request.type || data.session_id !== request.session_id || typeof data.fired !== 'boolean') {
      throw new Error('could not confirm the saved reminder');
    }
    await Promise.all([..._pendingChanges]);
    if (revision === _revision) break;
    // A cancellation or acknowledgment may have overtaken this response. Replay the
    // same identity to confirm current server state before publishing success.
    if (attempt === 2) throw new Error('reminders changed while saving; retry to confirm');
  }
  _revision++;
  _loading = false;
  _reminders = _reminders.filter(row => row.id !== data.id);
  if (!data.fired) _reminders.push(data);
  _reminders.sort((a, b) => a.trigger_at.localeCompare(b.trigger_at));
  _render();
  return data;
}

export function reminderMayHaveSaved(error) {
  return ![400, 401, 403, 404, 422].includes(error?.status);
}

window._delReminder = async (id, button) => {
  if (_cancelling.has(id)) return false;
  const reminder = _reminders.find(row => row.id === id);
  if (!_cancelRecovery.has(id) && reminder) _cancelRecovery.set(id, { reminder, cancelled: false, uncertain: false, restoring: false, request: null, error: '' });
  const recovery = _cancelRecovery.get(id);
  _cancelling.add(id);
  const hadFocus = button && document.activeElement === button;
  if (button) button.disabled = true;
  const settle = _beginReminderChange();
  try {
    const response = await fetch(`/api/reminders/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 404) {
      const data = await response.json().catch(() => ({}));
      const error = new Error(typeof data.detail === 'string' ? data.detail : 'could not cancel reminder; try again');
      error.status = response.status;
      throw error;
    }
    _revision++;
    _loading = false;
    _reminders = _reminders.filter(r => r.id !== id);
    if (recovery) { recovery.cancelled = true; recovery.uncertain = false; recovery.error = ''; }
    return true;
  } catch (error) {
    if ([400, 401, 403, 409, 422].includes(error.status) && !recovery?.uncertain) _cancelRecovery.delete(id);
    else if (recovery) {
      recovery.uncertain = true;
      recovery.error = 'could not confirm cancellation. retry cancel to check.';
    }
    toast(error.message || 'could not cancel reminder; try again', 'error');
    return false;
  } finally {
    settle();
    _cancelling.delete(id);
    _render();
    if (hadFocus && document.activeElement === document.body) {
      const retry = [...document.querySelectorAll('[data-reminder-cancel]')].find(node => node.dataset.reminderCancel === id);
      const undo = [...document.querySelectorAll('[data-reminder-recover]')].find(node => node.dataset.reminderRecover === id);
      const target = retry || undo || document.getElementById('reminder-text');
      if (target?.getClientRects().length) target.focus();
    }
  }
};

export function startReminderPoll() {
  if (_pollTimer) return;
  _pollTimer = setInterval(_checkDue, 30000);
  setTimeout(_checkDue, 2000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) _checkDue(); });
}

async function _checkDue() {
  if (_checking || document.hidden) return;
  _checking = true;
  try {
    const r = await fetch('/api/reminders/due');
    if (!r.ok) return;
    const due = await r.json();
    if (!Array.isArray(due)) return;
    for (const rem of due) {
      if (document.hidden) break;
      toast(`reminder: ${rem.text}`, 'success');
      const settle = _beginReminderChange();
      try {
        const ack = await fetch(`/api/reminders/${encodeURIComponent(rem.id)}/ack`, { method: 'POST' });
        if (!ack.ok) throw new Error('could not confirm reminder delivery');
        _reminders = _reminders.filter(x => x.id !== rem.id);
      } catch {
        // A failed reply can follow a committed acknowledgment. Refresh known state;
        // if that read also fails, the list retains its rows and exposes retry.
        await loadReminders().catch(() => {});
      } finally { settle(); }
    }
    if (due.length) _render();
  } catch {} finally { _checking = false; }
}

function _panelState(message = '') {
  const locked = _saving || !!_creation;
  const text = document.getElementById('reminder-text');
  const time = document.getElementById('reminder-time');
  const type = document.getElementById('reminder-type-select');
  const add = document.getElementById('reminder-add-btn');
  const discard = document.getElementById('reminder-discard');
  if (text) text.disabled = locked;
  if (time) { time.setAttribute('aria-disabled', String(locked)); time.tabIndex = locked ? -1 : 0; }
  if (type) type.disabled = locked;
  if (add) { add.disabled = _saving; add.textContent = _saving ? 'saving…' : _creation ? 'retry save' : 'set'; }
  if (discard) { discard.hidden = !_creation; discard.disabled = _saving; }
  const status = document.getElementById('reminder-status');
  if (status) status.textContent = message;
}

export function initReminderPanel(fetcher = fetch, reloadPanel = null) {
  _reloadPanel = reloadPanel;
  const loading = loadReminders(fetcher);
  import('./push.js').then(m => m.initPushButton()).catch(() => {});
  const addBtn = document.getElementById('reminder-add-btn');
  const textEl = document.getElementById('reminder-text');
  const timeEl = document.getElementById('reminder-time');
  const typeEl = document.getElementById('reminder-type-select');
  initCustomDropdown(typeEl);
  initDatePicker(timeEl);
  document.getElementById('reminder-zone').textContent = `times use ${resolvedTimeZone()}`;
  if (!addBtn || addBtn.dataset.wired === '1') return loading;
  addBtn.dataset.wired = '1';
  document.getElementById('reminder-discard').addEventListener('click', async () => {
    if (_saving || !_creation) return;
    if (!await confirm('this reminder may already be saved. discard this retry? check the reminder list before creating another.')) return;
    _creation = null;
    textEl.value = ''; timeEl.value = '';
    _panelState(); textEl.focus();
  });
  addBtn.addEventListener('click', async () => {
    if (_saving) return;
    const hadFocus = document.activeElement === addBtn;
    let saved = false;
    try {
      if (!_creation) {
        const text = textEl.value.trim();
        if (!text) throw new Error('enter reminder text');
        const triggerAt = reminderTimeFromWall(timeEl.value);
        if (triggerAt <= new Date()) throw new Error('pick a future time');
        const type = typeEl.value || 'reminder';
        _creation = { request: reminderRequest(text, triggerAt, type, type === 'message' ? window._currentSession?.id || null : null), uncertain: false };
      }
      _saving = true;
      _panelState('saving…');
      const result = await createReminder(_creation.request);
      saved = true;
      _creation = null;
      textEl.value = ''; timeEl.value = '';
      toast(result.fired ? 'reminder already delivered' : result.type === 'message' ? 'message scheduled' : 'reminder set', 'success');
      _panelState();
    } catch (error) {
      if (_creation) {
        _creation.uncertain ||= reminderMayHaveSaved(error);
        if (!_creation.uncertain) _creation = null;
      }
      const message = `${error.message || 'could not save reminder'}${_creation ? '. retry to confirm the same reminder, or discard this retry.' : ''}`;
      _panelState(message);
      toast(message, 'error');
    } finally {
      _saving = false;
      _panelState(document.getElementById('reminder-status').textContent);
      if (hadFocus && document.activeElement === document.body && addBtn.getClientRects().length) {
        (saved ? textEl : addBtn).focus();
      }
    }
  });
  return loading;
}

export function parseReminderTime(str) {
  const s = str.trim().toLowerCase();
  const relative = s.match(/^in\s+(\d+)\s*(m(?:in)?|h(?:r|our)?|d(?:ay)?)$/);
  if (relative) {
    const duration = Number(relative[1]) * ({ m: 60000, h: 3600000, d: 86400000 }[relative[2][0]]);
    const date = new Date(Date.now() + duration);
    return duration > 0 && !isNaN(date) ? date : null;
  }
  const clock = s.match(/^(?:(today|tomorrow)\s+)?at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/);
  if (!clock) return null;
  let hour = Number(clock[2]);
  const minute = Number(clock[3] || 0), period = clock[4];
  if (minute > 59 || (period ? hour < 1 || hour > 12 : hour > 23)) return null;
  if (period) hour = hour % 12 + (period === 'pm' ? 12 : 0);
  const day = new Date(calendarDateKey() + 'T12:00:00Z');
  if (clock[1] === 'tomorrow') day.setUTCDate(day.getUTCDate() + 1);
  const parse = () => reminderTimeFromWall(`${day.toISOString().slice(0, 10)}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`);
  try {
    let result = parse();
    if (result <= new Date() && clock[1] !== 'tomorrow') { day.setUTCDate(day.getUTCDate() + 1); result = parse(); }
    return result;
  } catch { return null; }
}

function _esc(s = '') {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
