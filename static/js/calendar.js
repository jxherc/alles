import { toast } from './util.js';

let _events = [];
let _editing = null;

export async function loadCalendar() {
  const r = await fetch('/api/calendar');
  _events = await r.json();
  renderCalendar();
}

function renderCalendar() {
  const list = document.getElementById('calendar-list');
  if (!list) return;

  if (!_events.length) {
    list.innerHTML = '<div class="page-empty">no events</div>';
    return;
  }

  // group by month
  const groups = {};
  for (const e of _events) {
    const d = new Date(e.start_dt);
    const key = d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    (groups[key] = groups[key] || []).push(e);
  }

  list.innerHTML = Object.entries(groups).map(([month, evts]) => `
    <div class="cal-month-label">${month}</div>
    ${evts.map(e => renderEvent(e)).join('')}
  `).join('');

  list.querySelectorAll('.cal-event').forEach(el => {
    el.addEventListener('click', () => openEditor(_events.find(e => e.id === el.dataset.id)));
  });
  list.querySelectorAll('.cal-del').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await fetch(`/api/calendar/${btn.dataset.id}`, { method: 'DELETE' });
      await loadCalendar();
    });
  });
}

function renderEvent(e) {
  const d = new Date(e.start_dt);
  const day = d.toLocaleDateString('en-US', { weekday: 'short', day: 'numeric' });
  const time = e.all_day ? 'all day' : d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  return `<div class="cal-event" data-id="${e.id}">
    <div class="cal-date">
      <span class="cal-day">${day}</span>
      <span class="cal-time">${time}</span>
    </div>
    <div class="cal-info">
      <div class="cal-title">${esc(e.title)}</div>
      ${e.description ? `<div class="cal-desc">${esc(e.description)}</div>` : ''}
    </div>
    <button class="cal-del act-btn" data-id="${e.id}">delete</button>
  </div>`;
}

function openEditor(event) {
  const list = document.getElementById('calendar-list');
  _editing = event || null;
  const isNew = !event;
  const now = new Date().toISOString().slice(0, 16);

  list.innerHTML = `<div class="note-editor">
    <input class="note-editor-title" id="cal-title" value="${esc(event?.title || '')}" placeholder="event title...">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-top:0.25rem">
      <div>
        <div style="font-size:0.68rem;color:var(--muted);letter-spacing:0.04em;margin-bottom:0.25rem">start</div>
        <input class="settings-input" id="cal-start" type="datetime-local" value="${event?.start_dt?.slice(0,16) || now}" style="width:100%">
      </div>
      <div>
        <div style="font-size:0.68rem;color:var(--muted);letter-spacing:0.04em;margin-bottom:0.25rem">end</div>
        <input class="settings-input" id="cal-end" type="datetime-local" value="${event?.end_dt?.slice(0,16) || ''}" style="width:100%">
      </div>
    </div>
    <textarea class="note-editor-body" id="cal-desc" rows="3" placeholder="description...">${esc(event?.description || '')}</textarea>
    <div style="display:flex;gap:0.4rem;justify-content:flex-end">
      <button class="btn" id="cal-back">← back</button>
      <button class="btn primary" id="cal-save">${isNew ? 'create' : 'save'}</button>
    </div>
  </div>`;

  document.getElementById('cal-back').addEventListener('click', () => loadCalendar());
  document.getElementById('cal-save').addEventListener('click', async () => {
    const body = {
      title: document.getElementById('cal-title').value.trim(),
      description: document.getElementById('cal-desc').value,
      start_dt: document.getElementById('cal-start').value,
      end_dt: document.getElementById('cal-end').value || null,
      all_day: false,
    };
    if (!body.title || !body.start_dt) { toast('title + start required', 'error'); return; }
    if (_editing) {
      await fetch(`/api/calendar/${_editing.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    } else {
      await fetch('/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    }
    toast('saved', 'success');
    await loadCalendar();
  });
}

export function newEvent() { openEditor(null); }

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
