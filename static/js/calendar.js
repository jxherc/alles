import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
import { initDatePickers } from './datepick.js';

let _events = [];
let _editing = null;
let _cursor = new Date();        // a day inside the viewed period
let _view = localStorage.getItem('cal-view') || 'month';   // month | week | day
let _navBound = false;

const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const HOUR_H = 40;
const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const COLORS = { accent: 'accent', green: 'green', warn: 'warn', error: 'error', red: 'error' };
const colorClass = c => COLORS[c] || 'accent';
const timeShort = dt => new Date(dt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

export async function loadCalendar() {
  _bindNav();
  const r = await fetch('/api/calendar');
  _events = await r.json();
  render();
}

function _bindNav() {
  if (_navBound) return;
  _navBound = true;
  document.getElementById('cal-prev')?.addEventListener('click', () => { shift(-1); });
  document.getElementById('cal-next')?.addEventListener('click', () => { shift(1); });
  document.getElementById('cal-today')?.addEventListener('click', () => { _cursor = new Date(); render(); });
  document.querySelectorAll('.cal-view-btn').forEach(b =>
    b.addEventListener('click', () => { _view = b.dataset.view; localStorage.setItem('cal-view', _view); _syncViewBtns(); render(); }));
  _syncViewBtns();
  document.getElementById('cal-sync-btn')?.addEventListener('click', openCaldavPanel);
}

function _syncViewBtns() {
  document.querySelectorAll('.cal-view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === _view));
}

function shift(dir) {
  if (_view === 'month') _cursor.setMonth(_cursor.getMonth() + dir);
  else if (_view === 'week') _cursor.setDate(_cursor.getDate() + 7 * dir);
  else _cursor.setDate(_cursor.getDate() + dir);
  render();
}

// expand recurring events into concrete occurrences within [rs, re)
function expand(rs, re) {
  const step = (d, rec) => {
    if (rec === 'daily') d.setDate(d.getDate() + 1);
    else if (rec === 'weekly') d.setDate(d.getDate() + 7);
    else if (rec === 'monthly') d.setMonth(d.getMonth() + 1);
  };
  const out = [];
  for (const e of _events) {
    const base = new Date(e.start_dt);
    if (!e.recurrence) {
      if (base >= rs && base < re) out.push({ ...e, _date: base });
      continue;
    }
    const until = e.recur_until ? new Date(e.recur_until + 'T23:59:59') : null;
    const d = new Date(base);
    let g = 0;
    while (d < rs && g++ < 6000) step(d, e.recurrence);
    g = 0;
    while (d < re && g++ < 1000) {
      if (!until || d <= until) out.push({ ...e, _date: new Date(d), _recur: true });
      step(d, e.recurrence);
    }
  }
  return out;
}

function render() {
  const lbl = document.getElementById('cal-month-label');
  if (_view === 'month') { if (lbl) lbl.textContent = _cursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' }); renderMonth(); }
  else if (_view === 'week') renderWeek(lbl);
  else renderDay(lbl);
}

function renderMonth() {
  const el = document.getElementById('calendar-list');
  if (!el) return;
  const year = _cursor.getFullYear(), month = _cursor.getMonth();
  const startDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();

  const rangeStart = new Date(year, month, 1 - startDay);
  const rangeEnd = new Date(year, month, daysInMonth + 7);
  const occ = expand(rangeStart, rangeEnd);
  const byDay = {};
  for (const o of occ) { const k = ymd(o._date); (byDay[k] = byDay[k] || []).push(o); }

  const cells = [];
  for (let i = 0; i < startDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7) cells.push(null);

  let html = '<div class="cal-grid">';
  for (const w of WD) html += `<div class="cal-weekday">${w}</div>`;
  for (const cell of cells) {
    if (!cell) { html += '<div class="cal-cell empty"></div>'; continue; }
    const key = ymd(cell);
    const evts = (byDay[key] || []).sort((a, b) => (a._date - b._date));
    const chips = evts.slice(0, 4).map(o =>
      `<div class="cal-chip ${colorClass(o.color)}" data-id="${o.id}" title="${esc(o.title)}">${esc((o.all_day ? '' : timeShort(o._date) + ' ') + o.title)}</div>`).join('');
    const more = evts.length > 4 ? `<div class="cal-more">+${evts.length - 4} more</div>` : '';
    html += `<div class="cal-cell${sameDay(cell, today) ? ' today' : ''}" data-date="${key}">
      <div class="cal-cell-num">${cell.getDate()}</div>
      <div class="cal-cell-events">${chips}${more}</div></div>`;
  }
  html += '</div>';
  el.innerHTML = html;
  el.querySelectorAll('.cal-cell:not(.empty)').forEach(c => c.addEventListener('click', ev => {
    const chip = ev.target.closest('.cal-chip');
    if (chip) { openEditor(_events.find(e => e.id === chip.dataset.id)); return; }
    openEditor(null, c.dataset.date);
  }));
}

function weekStart(d) { const s = new Date(d); s.setDate(s.getDate() - s.getDay()); s.setHours(0, 0, 0, 0); return s; }

function renderWeek(lbl) {
  const days = [];
  const ws = weekStart(_cursor);
  for (let i = 0; i < 7; i++) { const d = new Date(ws); d.setDate(d.getDate() + i); days.push(d); }
  if (lbl) lbl.textContent = `${days[0].toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${days[6].toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
  const re = new Date(days[6]); re.setDate(re.getDate() + 1);
  renderTimeGrid(document.getElementById('calendar-list'), days, expand(ws, re));
}

function renderDay(lbl) {
  const day = new Date(_cursor); day.setHours(0, 0, 0, 0);
  if (lbl) lbl.textContent = day.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  const re = new Date(day); re.setDate(re.getDate() + 1);
  renderTimeGrid(document.getElementById('calendar-list'), [day], expand(day, re));
}

function renderTimeGrid(el, days, occ) {
  if (!el) return;
  const today = new Date();
  // header
  let head = '<div class="cal-tg-gutter-head"></div>';
  for (const d of days) head += `<div class="cal-tg-dayhead${sameDay(d, today) ? ' today' : ''}" data-date="${ymd(d)}"><span class="cal-tg-wd">${WD[d.getDay()]}</span> <span class="cal-tg-dn">${d.getDate()}</span></div>`;
  // all-day row
  let allday = '<div class="cal-tg-gutter">all-day</div>';
  for (const d of days) {
    const items = occ.filter(o => o.all_day && sameDay(o._date, d))
      .map(o => `<div class="cal-allday-ev ${colorClass(o.color)}" data-id="${o.id}" title="${esc(o.title)}">${esc(o.title)}</div>`).join('');
    allday += `<div class="cal-tg-allday" data-date="${ymd(d)}">${items}</div>`;
  }
  // hour grid
  let gutter = '';
  for (let h = 0; h < 24; h++) gutter += `<div class="cal-tg-hour" style="height:${HOUR_H}px">${h === 0 ? '' : (h % 12 || 12) + (h < 12 ? 'a' : 'p')}</div>`;
  let cols = '';
  for (const d of days) {
    let evHtml = '';
    for (const o of occ.filter(x => !x.all_day && sameDay(x._date, d))) {
      const bs = new Date(o.start_dt), be = o.end_dt ? new Date(o.end_dt) : new Date(bs.getTime() + 3600000);
      const durH = Math.max(0.5, (be - bs) / 3600000);
      const top = (o._date.getHours() + o._date.getMinutes() / 60) * HOUR_H;
      evHtml += `<div class="cal-tev ${colorClass(o.color)}" data-id="${o.id}" style="top:${top}px;height:${durH * HOUR_H - 2}px" title="${esc(o.title)}"><b>${esc(timeShort(o._date))}</b> ${esc(o.title)}</div>`;
    }
    const lines = Array.from({ length: 24 }, (_, h) => `<div class="cal-tg-slot" style="height:${HOUR_H}px" data-date="${ymd(d)}" data-hour="${h}"></div>`).join('');
    cols += `<div class="cal-tg-col">${lines}${evHtml}</div>`;
  }
  el.innerHTML = `<div class="cal-timegrid ${days.length === 1 ? 'one-day' : ''}" style="--cols:${days.length}">
    <div class="cal-tg-headrow">${head}</div>
    <div class="cal-tg-alldayrow">${allday}</div>
    <div class="cal-tg-scroll"><div class="cal-tg-body"><div class="cal-tg-gutter-col">${gutter}</div>${cols}</div></div>
  </div>`;

  el.querySelectorAll('.cal-tev, .cal-allday-ev').forEach(ev => ev.addEventListener('click', e => {
    e.stopPropagation(); openEditor(_events.find(x => x.id === ev.dataset.id));
  }));
  el.querySelectorAll('.cal-tg-slot').forEach(s => s.addEventListener('click', () => openEditor(null, s.dataset.date, +s.dataset.hour)));
  el.querySelectorAll('.cal-tg-allday').forEach(s => s.addEventListener('click', e => { if (e.target === s) openEditor(null, s.dataset.date, null, true); }));
  // scroll to ~8am
  const sc = el.querySelector('.cal-tg-scroll'); if (sc) sc.scrollTop = 7 * HOUR_H;
}

function openEditor(event, defaultDate, hour, allDay) {
  const list = document.getElementById('calendar-list');
  _editing = event || null;
  const isNew = !event;
  const now = new Date().toISOString().slice(0, 16);
  const hh = hour != null ? String(hour).padStart(2, '0') : '09';
  const start = event?.start_dt?.slice(0, 16) || (defaultDate ? `${defaultDate}T${hh}:00` : now);
  const colors = ['accent', 'green', 'warn', 'error'];
  const recur = event?.recurrence || '';

  list.innerHTML = `<div class="note-editor">
    <input class="note-editor-title" id="cal-title" value="${esc(event?.title || '')}" placeholder="event title...">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-top:0.25rem">
      <div><div class="cal-flabel">start</div><div class="date-input" id="cal-start" data-type="datetime" data-value="${start}" data-ph="start" style="width:100%"></div></div>
      <div><div class="cal-flabel">end</div><div class="date-input" id="cal-end" data-type="datetime" data-value="${event?.end_dt?.slice(0, 16) || ''}" data-ph="end (optional)" style="width:100%"></div></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.5rem;margin-top:0.5rem">
      <div><div class="cal-flabel">repeat</div>
        <div class="settings-input custom-select" id="cal-recur" data-value="${recur}" data-options="|does not repeat;daily|daily;weekly|weekly;monthly|monthly" style="width:100%"></div>
      </div>
      <div><div class="cal-flabel">repeat until (optional)</div><div class="date-input" id="cal-until" data-type="date" data-value="${event?.recur_until || ''}" data-ph="never" style="width:100%"></div></div>
    </div>
    <div style="display:flex;align-items:center;gap:0.5rem;margin-top:0.5rem">
      <label class="cal-flabel" style="display:flex;align-items:center;gap:0.3rem;margin:0"><input type="checkbox" id="cal-allday" ${event?.all_day || allDay ? 'checked' : ''}> all day</label>
      <span class="cal-flabel" style="margin:0 0 0 0.5rem">color</span>
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

  initCustomDropdown(document.getElementById('cal-recur'));
  initDatePickers(list);

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
      recurrence: document.getElementById('cal-recur').value,
      recur_until: document.getElementById('cal-until').value || null,
    };
    if (!body.title || !body.start_dt) { toast('title + start required', 'error'); return; }
    if (_editing) await fetch(`/api/calendar/${_editing.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    else await fetch('/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    toast('saved', 'success');
    await loadCalendar();
  });
}

// ── CalDAV sync panel ───────────────────────────────────────────────────────
async function openCaldavPanel() {
  const list = document.getElementById('calendar-list');
  let cfg = {};
  try { cfg = await fetch('/api/caldav/status').then(r => r.json()); } catch {}
  list.innerHTML = `<div class="note-editor" style="max-width:520px">
    <div style="font-size:0.9rem;color:var(--text);margin-bottom:0.2rem">CalDAV sync</div>
    <div style="font-size:0.72rem;color:var(--muted);line-height:1.5;margin-bottom:0.6rem">
      two-way sync with iCloud / Google / any CalDAV server. credentials are stored locally.
      ${cfg.available ? '' : '<br><b style="color:var(--warn)">needs the caldav library — run: pip install caldav</b>'}
      ${cfg.connected ? `<br>connected as <b>${esc(cfg.username || '')}</b>` : ''}
    </div>
    <div class="cal-flabel">server url</div>
    <input class="settings-input" id="cd-url" placeholder="https://caldav.icloud.com/" value="${esc(cfg.url || '')}" style="width:100%">
    <div class="cal-flabel" style="margin-top:0.4rem">username</div>
    <input class="settings-input" id="cd-user" placeholder="you@icloud.com" value="${esc(cfg.username || '')}" style="width:100%">
    <div class="cal-flabel" style="margin-top:0.4rem">app password</div>
    <input class="settings-input" id="cd-pass" type="password" placeholder="app-specific password" style="width:100%">
    <div style="display:flex;gap:0.4rem;justify-content:flex-end;margin-top:0.7rem">
      <button class="btn" id="cd-back">← back</button>
      <button class="btn" id="cd-save">save</button>
      <button class="btn primary" id="cd-sync">sync now</button>
    </div>
    <div id="cd-status" style="font-size:0.72rem;color:var(--muted);margin-top:0.5rem"></div>
  </div>`;
  document.getElementById('cd-back').addEventListener('click', () => loadCalendar());
  const save = async () => {
    const body = { url: document.getElementById('cd-url').value.trim(), username: document.getElementById('cd-user').value.trim(), password: document.getElementById('cd-pass').value };
    await fetch('/api/caldav/connect', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  };
  document.getElementById('cd-save').addEventListener('click', async () => { await save(); toast('saved', 'success'); });
  document.getElementById('cd-sync').addEventListener('click', async () => {
    const st = document.getElementById('cd-status');
    st.textContent = 'syncing…';
    await save();
    try {
      const r = await fetch('/api/caldav/sync', { method: 'POST' }).then(x => x.json());
      if (r.error) { st.textContent = 'error: ' + r.error; return; }
      st.textContent = `synced — pulled ${r.pulled || 0}, pushed ${r.pushed || 0}`;
      await loadCalendar();
    } catch (e) { st.textContent = 'sync failed'; }
  });
}

export function newEvent() { openEditor(null); }

function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
