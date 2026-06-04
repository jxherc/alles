import { toast } from './util.js';

let _reminders = [];
let _pollTimer = null;

export async function loadReminders() {
  try {
    const r = await fetch('/api/reminders');
    _reminders = await r.json();
  } catch { _reminders = []; }
  _render();
}

function _render() {
  const el = document.getElementById('reminder-list');
  if (!el) return;
  if (!_reminders.length) {
    el.innerHTML = '<div class="page-empty">no reminders</div>';
    return;
  }
  el.innerHTML = _reminders.map(r => `
    <div class="settings-list-row" data-id="${r.id}">
      <div style="flex:1;min-width:0">
        <div class="row-name">${_esc(r.text)}</div>
        <div style="font-size:0.68rem;color:var(--muted);margin-top:2px">
          ${_fmtTime(r.trigger_at)} · ${r.type}
          ${r.session_id ? ' · in session' : ''}
        </div>
      </div>
      <button class="act-btn" data-id="${r.id}" onclick="window._delReminder('${r.id}')">cancel</button>
    </div>`).join('');
}

function _fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  const now = Date.now();
  const diff = d.getTime() - now;
  if (diff < 0) return 'overdue';
  if (diff < 60000) return 'in <1m';
  if (diff < 3600000) return `in ${Math.round(diff/60000)}m`;
  if (diff < 86400000) return `in ${Math.round(diff/3600000)}h`;
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
}

export async function createReminder(text, triggerAt, type = 'reminder', sessionId = null) {
  const r = await fetch('/api/reminders', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text, trigger_at: triggerAt.toISOString(), type, session_id: sessionId }),
  });
  if (!r.ok) { toast('failed to set reminder', 'error'); return null; }
  const data = await r.json();
  _reminders.unshift(data);
  _render();
  return data;
}

window._delReminder = async id => {
  await fetch(`/api/reminders/${id}`, { method: 'DELETE' });
  _reminders = _reminders.filter(r => r.id !== id);
  _render();
};

// start polling for due reminders every 30s
export function startReminderPoll() {
  if (_pollTimer) return;
  _pollTimer = setInterval(_checkDue, 30000);
  // check immediately on first load too
  setTimeout(_checkDue, 2000);
}

async function _checkDue() {
  try {
    const r = await fetch('/api/reminders/due');
    const due = await r.json();
    for (const rem of due) {
      toast(`reminder: ${rem.text}`, 'success');
      // update local list
      _reminders = _reminders.filter(x => x.id !== rem.id);
    }
    if (due.length) _render();
  } catch {}
}

export function initReminderPanel() {
  loadReminders();

  const addBtn = document.getElementById('reminder-add-btn');
  const textEl = document.getElementById('reminder-text');
  const timeEl = document.getElementById('reminder-time');
  const typeEl = document.getElementById('reminder-type-select');

  addBtn?.addEventListener('click', async () => {
    const text = textEl?.value.trim();
    const timeVal = timeEl?.value;
    if (!text || !timeVal) { toast('enter text and time', 'error'); return; }
    const triggerAt = new Date(timeVal);
    if (isNaN(triggerAt.getTime()) || triggerAt <= new Date()) {
      toast('pick a future time', 'error'); return;
    }
    const type = typeEl?.value || 'reminder';
    const sessionId = type === 'message' ? (window._currentSession?.id || null) : null;
    const result = await createReminder(text, triggerAt, type, sessionId);
    if (result) {
      if (textEl) textEl.value = '';
      if (timeEl) timeEl.value = '';
      toast(type === 'message' ? 'message scheduled' : 'reminder set', 'success');
    }
  });
}

// parse time from slash command: "in 2h", "in 30m", "at 15:30", "at 3pm", "tomorrow at 9am"
export function parseReminderTime(str) {
  const s = str.trim().toLowerCase();

  // "in Xm" / "in Xh" / "in Xd"
  const relM = s.match(/^in\s+(\d+)\s*(m(?:in)?|h(?:r|our)?|d(?:ay)?)$/);
  if (relM) {
    const n = parseInt(relM[1]);
    const unit = relM[2][0];
    const ms = unit === 'm' ? n*60000 : unit === 'h' ? n*3600000 : n*86400000;
    return new Date(Date.now() + ms);
  }

  // "at HH:MM" or "at 3pm"
  const atM = s.match(/^(?:today\s+)?at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/);
  if (atM) {
    let h = parseInt(atM[1]);
    const m = parseInt(atM[2] || '0');
    const ampm = atM[3];
    if (ampm === 'pm' && h < 12) h += 12;
    if (ampm === 'am' && h === 12) h = 0;
    const d = new Date();
    d.setHours(h, m, 0, 0);
    if (d <= new Date()) d.setDate(d.getDate() + 1);
    return d;
  }

  // "tomorrow at ..."
  const tomM = s.match(/^tomorrow\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/);
  if (tomM) {
    let h = parseInt(tomM[1]);
    const m = parseInt(tomM[2] || '0');
    const ampm = tomM[3];
    if (ampm === 'pm' && h < 12) h += 12;
    if (ampm === 'am' && h === 12) h = 0;
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(h, m, 0, 0);
    return d;
  }

  return null;
}

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
