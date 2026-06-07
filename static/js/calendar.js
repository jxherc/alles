import { toast } from './util.js';

let _events = [];
let _editing = null;
let _cursor = new Date();   // month being viewed (any day in it)
let _navBound = false;

const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const COLORS = { accent: 'accent', green: 'green', warn: 'warn', error: 'error', red: 'error' };
const colorClass = c => COLORS[c] || 'accent';
const timeShort = e => e.all_day ? '' : new Date(e.start_dt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });

export async function loadCalendar() {
  _bindNav();
  const r = await fetch('/api/calendar');
  _events = await r.json();
  renderMonthGrid();
}

function _bindNav() {
  if (_navBound) return;
  _navBound = true;
  document.getElementById('cal-prev')?.addEventListener('click', () => { _cursor.setMonth(_cursor.getMonth() - 1); renderMonthGrid(); });
  document.getElementById('cal-next')?.addEventListener('click', () => { _cursor.setMonth(_cursor.getMonth() + 1); renderMonthGrid(); });
  document.getElementById('cal-today')?.addEventListener('click', () => { _cursor = new Date(); renderMonthGrid(); });
}

function renderMonthGrid() {
  const el = document.getElementById('calendar-list');
  if (!el) return;
  const year = _cursor.getFullYear(), month = _cursor.getMonth();
  const lbl = document.getElementById('cal-month-label');
  if (lbl) lbl.textContent = _cursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

  const startDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayKey = ymd(new Date());

  const byDay = {};
  for (const e of _events) {
    const k = ymd(new Date(e.start_dt));
    (byDay[k] = byDay[k] || []).push(e);
  }

  const cells = [];
  for (let i = 0; i < startDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7) cells.push(null);

  let html = '<div class="cal-grid">';
  for (const w of WD) html += `<div class="cal-weekday">${w}</div>`;
  for (const cell of cells) {
    if (!cell) { html += '<div class="cal-cell empty"></div>'; continue; }
    const key = ymd(cell);
    const evts = (byDay[key] || []).sort((a, b) => (a.start_dt > b.start_dt ? 1 : -1));
    const chips = evts.slice(0, 4).map(e =>
      `<div class="cal-chip ${colorClass(e.color)}" data-id="${e.id}" title="${esc(e.title)}">${esc((timeShort(e) ? timeShort(e) + ' ' : '') + e.title)}</div>`).join('');
    const more = evts.length > 4 ? `<div class="cal-more">+${evts.length - 4} more</div>` : '';
    html += `<div class="cal-cell${key === todayKey ? ' today' : ''}" data-date="${key}">
      <div class="cal-cell-num">${cell.getDate()}</div>
      <div class="cal-cell-events">${chips}${more}</div>
    </div>`;
  }
  html += '</div>';
  el.innerHTML = html;

  el.querySelectorAll('.cal-cell:not(.empty)').forEach(c => {
    c.addEventListener('click', ev => {
      const chip = ev.target.closest('.cal-chip');
      if (chip) { openEditor(_events.find(e => e.id === chip.dataset.id)); return; }
      openEditor(null, c.dataset.date);   // click empty day → new event that day
    });
  });
}

function openEditor(event, defaultDate) {
  const list = document.getElementById('calendar-list');
  _editing = event || null;
  const isNew = !event;
  const now = new Date().toISOString().slice(0, 16);
  const start = event?.start_dt?.slice(0, 16) || (defaultDate ? `${defaultDate}T09:00` : now);
  const colors = ['accent', 'green', 'warn', 'error'];

  list.innerHTML = `<div class="note-editor">
    <input class="note-editor-title" id="cal-title" value="${esc(event?.title || '')}" placeholder="event title...">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-top:0.25rem">
      <div>
        <div style="font-size:0.68rem;color:var(--muted);letter-spacing:0.04em;margin-bottom:0.25rem">start</div>
        <input class="settings-input" id="cal-start" type="datetime-local" value="${start}" style="width:100%">
      </div>
      <div>
        <div style="font-size:0.68rem;color:var(--muted);letter-spacing:0.04em;margin-bottom:0.25rem">end</div>
        <input class="settings-input" id="cal-end" type="datetime-local" value="${event?.end_dt?.slice(0,16) || ''}" style="width:100%">
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:0.5rem;margin-top:0.5rem">
      <label style="font-size:0.72rem;color:var(--muted);display:flex;align-items:center;gap:0.3rem"><input type="checkbox" id="cal-allday" ${event?.all_day ? 'checked' : ''}> all day</label>
      <span style="font-size:0.68rem;color:var(--muted);margin-left:0.5rem">color</span>
      <div id="cal-colors" style="display:flex;gap:0.3rem">
        ${colors.map(c => `<span class="cal-color-dot ${c}${(event?.color || 'accent') === c ? ' sel' : ''}" data-c="${c}"></span>`).join('')}
      </div>
    </div>
    <textarea class="note-editor-body" id="cal-desc" rows="3" placeholder="description...">${esc(event?.description || '')}</textarea>
    <div style="display:flex;gap:0.4rem;justify-content:flex-end">
      ${isNew ? '' : '<button class="btn" id="cal-del" style="margin-right:auto;color:var(--error);border-color:var(--error)">delete</button>'}
      <button class="btn" id="cal-back">← back</button>
      <button class="btn primary" id="cal-save">${isNew ? 'create' : 'save'}</button>
    </div>
  </div>`;

  let _color = event?.color || 'accent';
  list.querySelectorAll('.cal-color-dot').forEach(d => d.addEventListener('click', () => {
    _color = d.dataset.c;
    list.querySelectorAll('.cal-color-dot').forEach(x => x.classList.toggle('sel', x === d));
  }));
  document.getElementById('cal-del')?.addEventListener('click', async () => {
    await fetch(`/api/calendar/${_editing.id}`, { method: 'DELETE' });
    await loadCalendar();
  });
  document.getElementById('cal-back').addEventListener('click', () => loadCalendar());
  document.getElementById('cal-save').addEventListener('click', async () => {
    const body = {
      title: document.getElementById('cal-title').value.trim(),
      description: document.getElementById('cal-desc').value,
      start_dt: document.getElementById('cal-start').value,
      end_dt: document.getElementById('cal-end').value || null,
      all_day: document.getElementById('cal-allday').checked,
      color: _color,
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
