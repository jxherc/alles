import { toast } from './util.js';
import { initCustomDropdown } from './dropdown.js';
import { initDatePickers } from './datepick.js';
import { prompt as dlgPrompt } from './dialog.js';
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe

let _events = [];
let _tasks = [];  // tasks with due dates, overlaid on the month/agenda
let _calendars = [];
let _editing = null;
let _editOcc = null;             // occurrence date when editing a recurring instance
let _cursor = new Date();
let _view = localStorage.getItem('cal-view') || 'month';
let _viewBooted = false;          // has loadCalendar seeded the view once this session
let _lastDefaultView = null;      // last cal_default_view we applied (detects a cog change)
let _search = '';
let _miniCursor = new Date();    // month shown in the mini-navigator
let _navBound = false;
let _prefill = null;             // {start,end} for a drag-created event

const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
let _weekStart = 0;   // 0 = sunday, 1 = monday (per-app setting)
let _workStart = 9, _workEnd = 18;   // 8a working-hours shading (week/day grid)
let _secondaryTz = '';               // 8a secondary timezone (IANA name) for a world clock
let _subs = [];                      // 8a ICS-URL subscriptions
const _wdLabels = () => _weekStart ? [...WD.slice(1), WD[0]] : WD;
// leading blanks before the 1st, honoring week-start
const _lead = (y, m) => (new Date(y, m, 1).getDay() - _weekStart + 7) % 7;
const HOUR_H = 44;
const _pad = n => String(n).padStart(2, '0');
const ymd = d => `${d.getFullYear()}-${_pad(d.getMonth() + 1)}-${_pad(d.getDate())}`;
const localISO = d => `${ymd(d)}T${_pad(d.getHours())}:${_pad(d.getMinutes())}`;
const apiPatch = (id, body) => fetch(`/api/calendar/${id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
const apiPost = body => fetch('/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
const timeShort = dt => new Date(dt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

// google-ish categorical palette (event colours are categorisation here, not status)
const PALETTE = {
  accent: 'var(--accent)', tomato: '#f87171', flamingo: '#fb9a8f', tangerine: '#fb923c',
  banana: '#fbbf24', sage: '#5ec88a', basil: '#2dba6e', peacock: '#39b3e5',
  blueberry: '#5b8def', lavender: '#8b9cf8', grape: '#c08cf8', graphite: '#94a3b8',
  // back-compat with the old class names
  green: '#5ec88a', warn: '#fbbf24', error: '#f87171', red: '#f87171', blue: '#5b8def',
};
const COLOR_NAMES = ['accent', 'tomato', 'tangerine', 'banana', 'sage', 'basil', 'peacock', 'blueberry', 'lavender', 'grape', 'graphite'];
const calById = id => _calendars.find(c => c.id === id);
const hexOf = name => PALETTE[name] || (String(name || '').startsWith('#') ? name : PALETTE.accent);
const evColorName = e => e.color || calById(e.calendar_id)?.color || 'accent';
const evHex = e => hexOf(evColorName(e));

let _clockTimer = null;
function _tickWorldClock() {
  if (_clockTimer) return;  // one interval, updates whatever clock is in the DOM
  _clockTimer = setInterval(() => {
    const el = document.querySelector('#cal-worldclock .cal-wc-time');
    if (!el || !_secondaryTz) return;
    try { el.textContent = new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: _secondaryTz }); } catch {}
  }, 60000);
}

export async function loadCalendar() {
  _bindNav();
  _tickWorldClock();
  const [cals, evs, s, tasks, subs] = await Promise.all([
    fetch('/api/calendars').then(r => r.json()).catch(() => []),
    fetch('/api/calendar').then(r => r.json()).catch(() => []),
    fetch('/api/settings').then(r => r.json()).catch(() => ({})),
    fetch('/api/calendar/tasks').then(r => r.json()).catch(() => []),
    fetch('/api/calendar/subscriptions').then(r => r.json()).catch(() => []),
  ]);
  _tasks = Array.isArray(tasks) ? tasks : [];
  _subs = Array.isArray(subs) ? subs : [];
  _weekStart = s.cal_week_start === 'mon' ? 1 : 0;
  _workStart = Number.isFinite(+s.cal_work_start) && s.cal_work_start !== '' ? +s.cal_work_start : 9;
  _workEnd = Number.isFinite(+s.cal_work_end) && s.cal_work_end !== '' ? +s.cal_work_end : 18;
  _secondaryTz = (s.cal_secondary_tz || '').trim();
  // default-view setting: seed the opening view on first mount (last-used in localStorage
  // wins if present), then only re-apply when the setting itself actually changes (cog save).
  // otherwise leave _view alone so navigating / editing doesn't yank you out of week/day.
  const dv = (s.cal_default_view === 'month' || s.cal_default_view === 'week') ? s.cal_default_view : null;
  if (!_viewBooted) {
    _viewBooted = true;
    if (!localStorage.getItem('cal-view') && dv) _view = dv;
    _lastDefaultView = dv;
    _syncViewBtns();
  } else if (dv && dv !== _lastDefaultView) {
    _lastDefaultView = dv; _view = dv; _syncViewBtns();
  }
  _calendars = Array.isArray(cals) ? cals : [];
  _events = Array.isArray(evs) ? evs : [];
  renderSidebar();
  render();
}

function _bindNav() {
  if (_navBound) return;
  _navBound = true;
  document.getElementById('cal-prev')?.addEventListener('click', () => shift(-1));
  document.getElementById('cal-next')?.addEventListener('click', () => shift(1));
  document.getElementById('cal-today')?.addEventListener('click', () => { _cursor = new Date(); _miniCursor = new Date(); render(); renderSidebar(); });
  document.querySelectorAll('#cal-view .seg-opt').forEach(b =>
    b.addEventListener('click', () => { _view = b.dataset.view; localStorage.setItem('cal-view', _view); _syncViewBtns(); render(); }));
  _syncViewBtns();
  document.getElementById('cal-sync-btn')?.addEventListener('click', openCaldavPanel);
  document.getElementById('cal-find')?.addEventListener('click', findTime);

  // quick-add: natural language → event (was a dead input before)
  const quick = document.getElementById('cal-quick');
  quick?.addEventListener('keydown', async e => {
    if (e.key !== 'Enter') return;
    const text = quick.value.trim();
    if (!text) return;
    try {
      const r = await fetch('/api/calendar/quick', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text }) });
      if (!r.ok) throw new Error();
      const ev = await r.json();
      quick.value = '';
      toast(`added “${ev.title}”`, 'success');
      if (ev.start_dt) { _cursor = new Date(ev.start_dt.slice(0, 10) + 'T00:00'); }
      await loadCalendar();
    } catch { toast('could not parse that — try “lunch fri 1pm”', 'error'); }
  });

  const imp = document.getElementById('cal-import');
  if (imp && !imp.dataset.bound) {
    imp.dataset.bound = '1';
    const fileInp = document.getElementById('cal-import-file');
    imp.addEventListener('click', () => fileInp?.click());
    fileInp?.addEventListener('change', async e => {
      const f = e.target.files[0]; if (!f) return;
      try {
        const r = await fetch('/api/calendar/import', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ics: await f.text() }) });
        const d = await r.json();
        toast(`imported ${d.imported} event${d.imported === 1 ? '' : 's'}`, 'success');
        loadCalendar();
      } catch { toast('import failed', 'error'); }
      fileInp.value = '';
    });
  }
}

function _syncViewBtns() {
  document.querySelectorAll('#cal-view .seg-opt').forEach(b => b.classList.toggle('active', b.dataset.view === _view));
}

function shift(dir) {
  if (_view === 'month') _cursor.setMonth(_cursor.getMonth() + dir);
  else if (_view === 'week') _cursor.setDate(_cursor.getDate() + 7 * dir);
  else _cursor.setDate(_cursor.getDate() + dir);
  _miniCursor = new Date(_cursor);
  render();
  renderSidebar();
}

// ── sidebar: search + mini-month + my-calendars ──────────────────────────────
function renderSidebar() {
  const el = document.getElementById('cal-sidebar');
  if (!el) return;
  el.innerHTML = `
    <input type="text" id="cal-search" class="cal-side-search" placeholder="search events…" value="${esc(_search)}">
    <div class="cal-mini" id="cal-mini"></div>
    ${_clockHtml()}
    <div class="cal-cals">
      <div class="cal-cals-head"><span>my calendars</span><button class="cal-cal-add" id="cal-cal-add" title="new calendar">+</button></div>
      <div id="cal-cals-list"></div>
    </div>
    <div class="cal-cals cal-feeds">
      <div class="cal-cals-head"><span>subscriptions</span><button class="cal-cal-add" id="cal-feed-add" title="subscribe to an ICS URL">+</button></div>
      <div id="cal-feeds-list"></div>
    </div>
    <div class="cal-cals cal-bookings">
      <div class="cal-cals-head"><span>booking pages</span><button class="cal-cal-add" id="cal-book-add" title="new booking page">+</button></div>
      <div id="cal-book-list"></div>
    </div>`;
  renderMini();
  renderCalList();
  renderFeeds();
  renderBookingPages();
  const s = document.getElementById('cal-search');
  s.addEventListener('input', () => { _search = s.value.trim(); render(); });
  document.getElementById('cal-cal-add').addEventListener('click', () => calForm(null));
  document.getElementById('cal-feed-add').addEventListener('click', addFeed);
  document.getElementById('cal-book-add').addEventListener('click', addBookingPage);
}

let _bookingPages = [];
async function renderBookingPages() {
  const el = document.getElementById('cal-book-list');
  if (!el) return;
  _bookingPages = await fetch('/api/calendar/booking-pages').then(r => r.json()).catch(() => []);
  if (!_bookingPages.length) { el.innerHTML = '<div class="cal-feed-empty">none yet</div>'; return; }
  el.innerHTML = _bookingPages.map(b => `
    <div class="cal-feed-row" data-id="${b.id}">
      <span class="cal-feed-name" title="${b.duration_min}-min slots">${esc(b.title)}</span>
      <button class="cal-feed-x" data-act="copy" title="copy public link">${_si('link')}</button>
      <button class="cal-feed-x" data-act="del" title="delete">×</button>
    </div>`).join('');
  el.querySelectorAll('.cal-feed-row').forEach(row => {
    const b = _bookingPages.find(x => x.id === row.dataset.id);
    row.querySelector('[data-act="copy"]').addEventListener('click', async () => {
      const url = location.origin + b.url;
      try { await navigator.clipboard.writeText(url); toast('booking link copied', 'success'); }
      catch { toast(url, ''); }
    });
    row.querySelector('[data-act="del"]').addEventListener('click', async () => {
      await fetch(`/api/calendar/booking-pages/${b.id}`, { method: 'DELETE' });
      renderBookingPages();
    });
  });
}

async function addBookingPage() {
  const title = await dlgPrompt('booking page title:', 'Book a time');
  if (title === null) return;
  const dur = await dlgPrompt('slot length in minutes:', '30');
  try {
    await fetch('/api/calendar/booking-pages', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title: title?.trim() || 'Book a time', duration_min: parseInt(dur) || 30 }),
    });
    toast('booking page created', 'success');
    renderBookingPages();
  } catch { toast('failed', 'error'); }
}

// 8a — secondary timezone world clock
function _clockHtml() {
  if (!_secondaryTz) return '';
  let t = '';
  try {
    t = new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: _secondaryTz });
  } catch { return ''; }
  const label = _secondaryTz.split('/').pop().replace(/_/g, ' ');
  return `<div class="cal-worldclock" id="cal-worldclock" title="${esc(_secondaryTz)}"><span class="cal-wc-zone">${esc(label)}</span><span class="cal-wc-time">${esc(t)}</span></div>`;
}

function renderFeeds() {
  const el = document.getElementById('cal-feeds-list');
  if (!el) return;
  if (!_subs.length) { el.innerHTML = '<div class="cal-feed-empty">no feeds yet</div>'; return; }
  el.innerHTML = _subs.map(s => `
    <div class="cal-feed-row" data-id="${s.id}">
      <span class="cal-feed-name" title="${esc(s.url)} · ${esc(s.last_status || '')}">${esc(s.name)} <span class="cal-feed-n">${s.event_count}</span></span>
      <button class="cal-feed-x" data-act="del" title="remove">×</button>
    </div>`).join('');
  el.querySelectorAll('.cal-feed-row').forEach(row => {
    row.querySelector('[data-act="del"]').addEventListener('click', async () => {
      await fetch(`/api/calendar/subscriptions/${row.dataset.id}`, { method: 'DELETE' });
      loadCalendar();
    });
  });
}

async function addFeed() {
  const url = await dlgPrompt('ICS feed URL (Google/Apple public calendar, holidays…):');
  if (!url?.trim()) return;
  const name = await dlgPrompt('name this subscription:', 'Subscription');
  toast('subscribing…');
  try {
    const r = await fetch('/api/calendar/subscriptions', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: name?.trim() || 'Subscription', url: url.trim() }),
    });
    if (!r.ok) throw 0;
    toast('subscribed', 'success');
    loadCalendar();
  } catch { toast('subscription failed', 'error'); }
}

function renderMini() {
  const el = document.getElementById('cal-mini');
  if (!el) return;
  const y = _miniCursor.getFullYear(), m = _miniCursor.getMonth();
  const today = new Date();
  const startDay = _lead(y, m);
  const dim = new Date(y, m + 1, 0).getDate();
  const miniWd = _weekStart ? ['M', 'T', 'W', 'T', 'F', 'S', 'S'] : ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
  let html = `<div class="cal-mini-head"><button class="cal-mini-nav" data-d="-1">‹</button>
    <span>${_miniCursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}</span>
    <button class="cal-mini-nav" data-d="1">›</button></div><div class="cal-mini-grid">`;
  for (const w of miniWd) html += `<div class="cal-mini-wd">${w}</div>`;
  for (let i = 0; i < startDay; i++) html += '<div></div>';
  for (let d = 1; d <= dim; d++) {
    const date = new Date(y, m, d);
    const cls = ['cal-mini-day'];
    if (sameDay(date, today)) cls.push('today');
    if (sameDay(date, _cursor)) cls.push('sel');
    html += `<div class="${cls.join(' ')}" data-date="${ymd(date)}">${d}</div>`;
  }
  html += '</div>';
  el.innerHTML = html;
  el.querySelectorAll('.cal-mini-nav').forEach(b => b.addEventListener('click', () => {
    _miniCursor.setMonth(_miniCursor.getMonth() + (+b.dataset.d)); renderMini();
  }));
  el.querySelectorAll('.cal-mini-day').forEach(c => c.addEventListener('click', () => {
    _cursor = new Date(c.dataset.date + 'T00:00:00'); render(); renderMini();
  }));
}

function renderCalList() {
  const el = document.getElementById('cal-cals-list');
  if (!el) return;
  el.innerHTML = _calendars.map(c => `
    <div class="cal-cal-row" data-id="${c.id}">
      <span class="cal-cal-chk ${c.visible ? 'on' : ''}" data-act="vis" style="--cc:${hexOf(c.color)}"></span>
      <span class="cal-cal-name" data-act="edit">${esc(c.name)}</span>
    </div>`).join('');
  el.querySelectorAll('.cal-cal-row').forEach(row => {
    const c = calById(row.dataset.id);
    row.querySelector('[data-act="vis"]').addEventListener('click', async () => {
      await fetch(`/api/calendars/${c.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ visible: !c.visible }) });
      c.visible = !c.visible; renderCalList(); render();
    });
    row.querySelector('[data-act="edit"]').addEventListener('click', () => calForm(c));
  });
}

function calForm(cal) {
  const isNew = !cal;
  const wrap = document.getElementById('cal-cals-list');
  const sel = cal?.color || 'accent';
  const form = document.createElement('div');
  form.className = 'cal-cal-form';
  form.innerHTML = `
    <input class="settings-input" id="cc-name" placeholder="calendar name" value="${esc(cal?.name || '')}" style="width:100%">
    <div class="cal-swatches" id="cc-colors">${COLOR_NAMES.map(c => `<span class="cal-sw ${c === sel ? 'sel' : ''}" data-c="${c}" style="background:${hexOf(c)}"></span>`).join('')}</div>
    <div class="cal-cal-form-btns">
      ${isNew || cal.is_default ? '' : '<button class="btn" id="cc-del" style="color:var(--error);border-color:var(--error);margin-right:auto">delete</button>'}
      <button class="btn" id="cc-cancel">cancel</button>
      <button class="btn primary" id="cc-save">${isNew ? 'add' : 'save'}</button>
    </div>`;
  wrap.prepend(form);
  let color = sel;
  form.querySelectorAll('.cal-sw').forEach(s => s.addEventListener('click', () => {
    color = s.dataset.c; form.querySelectorAll('.cal-sw').forEach(x => x.classList.toggle('sel', x === s));
  }));
  form.querySelector('#cc-cancel').addEventListener('click', () => renderCalList());
  form.querySelector('#cc-del')?.addEventListener('click', async () => {
    await fetch(`/api/calendars/${cal.id}`, { method: 'DELETE' });
    await loadCalendar();
  });
  form.querySelector('#cc-save').addEventListener('click', async () => {
    const name = form.querySelector('#cc-name').value.trim();
    if (!name) { toast('name it', 'error'); return; }
    const body = { name, color };
    if (isNew) await fetch('/api/calendars', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    else await fetch(`/api/calendars/${cal.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    await loadCalendar();
  });
}

// ── recurrence expansion (mirrors services/recur.py) ─────────────────────────
const PYWD = { MO: 0, TU: 1, WE: 2, TH: 3, FR: 4, SA: 5, SU: 6 };
const parseByday = s => new Set((s || '').split(',').map(t => PYWD[t.trim().toUpperCase()]).filter(v => v != null));
function addMonths(d, n) {
  const x = new Date(d); const day = d.getDate();
  x.setDate(1); x.setMonth(x.getMonth() + n);
  x.setDate(Math.min(day, new Date(x.getFullYear(), x.getMonth() + 1, 0).getDate()));
  return x;
}
function* candidates(start, rec, interval, byday) {
  if (rec === 'weekly') {
    const days = (byday && byday.size) ? byday : new Set([(start.getDay() + 6) % 7]);
    const monday = new Date(start); monday.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    const floor = new Date(start); floor.setSeconds(0, 0);
    let wk = 0;
    while (true) {
      for (const wd of [...days].sort((a, b) => a - b)) {
        const c = new Date(monday); c.setDate(monday.getDate() + wk * 7 * interval + wd);
        if (c >= floor) yield c;
      }
      wk++;
    }
  } else if (rec === 'daily') {
    let cur = new Date(start);
    while (true) { yield new Date(cur); cur.setDate(cur.getDate() + interval); }
  } else {
    const months = rec === 'monthly' ? interval : 12 * interval; let i = 0;
    while (true) { yield addMonths(start, i * months); i++; }
  }
}

function visibleEvents() {
  let list = _events.filter(e => { const c = calById(e.calendar_id); return !c || c.visible; });
  if (_search) {
    const q = _search.toLowerCase();
    list = list.filter(e => `${e.title || ''} ${e.description || ''} ${e.location || ''}`.toLowerCase().includes(q));
  }
  return list;
}

function expand(rs, re) {
  const out = [];
  for (const e of visibleEvents()) {
    const start = new Date(e.start_dt);
    if (isNaN(start)) continue;
    if (!e.recurrence) { if (start >= rs && start < re) out.push({ ...e, _date: start }); continue; }
    const interval = Math.max(1, e.recur_interval || 1);
    const until = e.recur_until ? new Date(e.recur_until + 'T23:59:59') : null;
    const count = e.recur_count || null;
    const excepts = new Set((e.recur_except || []).map(d => String(d).slice(0, 10)));
    const byday = e.recurrence === 'weekly' ? parseByday(e.recur_byday) : null;
    const gen = candidates(start, e.recurrence, interval, byday);
    let emitted = 0, guard = 0;
    while (guard++ < 8000) {
      const nx = gen.next(); if (nx.done) break;
      const cand = nx.value;
      if (until && cand > until) break;
      if (count != null && emitted >= count) break;
      emitted++;
      if (excepts.has(ymd(cand))) continue;
      if (cand >= re) break;
      if (cand >= rs) out.push({ ...e, _date: new Date(cand), _recur: true });
      if (out.length > 3000) break;
    }
  }
  return out;
}

// ── rendering ────────────────────────────────────────────────────────────────
function render() {
  const lbl = document.getElementById('cal-month-label');
  if (_view === 'month') { if (lbl) lbl.textContent = _cursor.toLocaleDateString('en-US', { month: 'long', year: 'numeric' }); renderMonth(); }
  else if (_view === 'week') renderWeek(lbl);
  else if (_view === 'agenda') renderAgenda(lbl);
  else if (_view === 'year') renderYear(lbl);
  else renderDay(lbl);
}

// agenda (8a) — flat upcoming list grouped by day, from /calendar/agenda
async function renderAgenda(lbl) {
  if (lbl) lbl.textContent = 'agenda';
  const el = document.getElementById('calendar-list');
  if (!el) return;
  const d = await fetch('/api/calendar/agenda?days=60').then(r => r.json()).catch(() => ({ days: [] }));
  if (!d.days?.length) { el.innerHTML = '<div class="cal-agenda-empty">nothing coming up</div>'; return; }
  let html = '<div class="cal-agenda">';
  for (const g of d.days) {
    const dd = new Date(g.date + 'T00:00:00');
    html += `<div class="cal-agenda-day"><div class="cal-agenda-date">${dd.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</div><div class="cal-agenda-evs">`;
    for (const o of g.events) {
      const t = o.all_day ? 'all day' : timeShort(o.start_dt);
      html += `<div class="cal-agenda-ev" data-id="${o.id}" data-occ="${o.recurring ? o.start_dt.slice(0, 10) : ''}"><span class="cal-agenda-dot" style="background:${evHex(o)}"></span><span class="cal-agenda-time">${esc(t)}</span><span class="cal-agenda-title">${esc(o.title)}${o.recurring ? ' <span class="cal-agenda-recur">(repeats)</span>' : ''}</span></div>`;
    }
    html += '</div></div>';
  }
  html += '</div>';
  el.innerHTML = html;
  el.querySelectorAll('.cal-agenda-ev').forEach(r => r.addEventListener('click', () => openEvent(r.dataset.id, r.dataset.occ || null)));
}

// year (8a) — 12 mini-months; click a day jumps to the day view
function renderYear(lbl) {
  const year = _cursor.getFullYear();
  if (lbl) lbl.textContent = String(year);
  const el = document.getElementById('calendar-list');
  if (!el) return;
  const today = new Date();
  const dotDays = new Set(_events.map(e => (e.start_dt || '').slice(0, 10)));
  let html = '<div class="cal-year">';
  for (let m = 0; m < 12; m++) {
    const startDay = _lead(year, m);
    const dim = new Date(year, m + 1, 0).getDate();
    html += `<div class="cal-year-month"><div class="cal-year-mname">${new Date(year, m, 1).toLocaleDateString('en-US', { month: 'long' })}</div><div class="cal-year-grid">`;
    for (const w of (_weekStart ? ['M', 'T', 'W', 'T', 'F', 'S', 'S'] : ['S', 'M', 'T', 'W', 'T', 'F', 'S'])) html += `<div class="cal-year-wd">${w}</div>`;
    for (let i = 0; i < startDay; i++) html += '<div></div>';
    for (let dnum = 1; dnum <= dim; dnum++) {
      const date = new Date(year, m, dnum);
      const k = ymd(date);
      const cls = ['cal-year-day'];
      if (sameDay(date, today)) cls.push('today');
      if (dotDays.has(k)) cls.push('has');
      html += `<div class="${cls.join(' ')}" data-date="${k}">${dnum}</div>`;
    }
    html += '</div></div>';
  }
  html += '</div>';
  el.innerHTML = html;
  el.querySelectorAll('.cal-year-day').forEach(c => c.addEventListener('click', () => {
    _cursor = new Date(c.dataset.date + 'T00:00:00'); _view = 'day'; localStorage.setItem('cal-view', _view); _syncViewBtns(); render();
  }));
}

const chipStyle = o => `background:${evHex(o)};color:#0a0a0a`;
const chipTitle = o => `${esc(o.title)}${o.location ? ' · ' + esc(o.location) : ''}${o._recur ? ' (repeats)' : ''}`;

function renderMonth() {
  const el = document.getElementById('calendar-list');
  if (!el) return;
  const year = _cursor.getFullYear(), month = _cursor.getMonth();
  const startDay = _lead(year, month);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date();
  const rangeStart = new Date(year, month, 1 - startDay);
  const rangeEnd = new Date(year, month, daysInMonth + 7);
  const occ = expand(rangeStart, rangeEnd);
  const byDay = {};
  for (const o of occ) { const k = ymd(o._date); (byDay[k] = byDay[k] || []).push(o); }
  const tasksByDay = {};
  for (const t of _tasks) (tasksByDay[t.date] = tasksByDay[t.date] || []).push(t);

  const cells = [];
  for (let i = 0; i < startDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7) cells.push(null);

  let html = '<div class="cal-grid">';
  for (const w of _wdLabels()) html += `<div class="cal-weekday">${w}</div>`;
  for (const cell of cells) {
    if (!cell) { html += '<div class="cal-cell empty"></div>'; continue; }
    const key = ymd(cell);
    const evts = (byDay[key] || []).sort((a, b) => (a.all_day ? 0 : a._date) - (b.all_day ? 0 : b._date));
    const chips = evts.slice(0, 4).map(o =>
      `<div class="cal-chip${o._recur ? ' recurring' : ''}" data-id="${o.id}" data-occ="${ymd(o._date)}" style="${chipStyle(o)}" title="${chipTitle(o)}">${o._recur ? `<span class="cal-chip-recur">${_si('refresh')}</span>` : ''}${esc((o.all_day ? '' : timeShort(o._date) + ' ') + o.title)}</div>`).join('');
    const more = evts.length > 4 ? `<div class="cal-more">+${evts.length - 4} more</div>` : '';
    const tchips = (tasksByDay[key] || []).slice(0, 3).map(t =>
      `<div class="cal-task${t.done ? ' done' : ''}" data-task="${esc(t.id)}" title="task: ${esc(t.title)}"><span class="cal-task-chk${t.done ? ' on' : ''}">${t.done ? _si('check') : ''}</span>${esc(t.title)}</div>`).join('');
    html += `<div class="cal-cell${sameDay(cell, today) ? ' today' : ''}" data-date="${key}">
      <div class="cal-cell-num">${cell.getDate()}</div>
      <div class="cal-cell-events">${chips}${more}${tchips}</div></div>`;
  }
  html += '</div>';
  el.innerHTML = html;
  el.querySelectorAll('.cal-cell:not(.empty)').forEach(c => c.addEventListener('click', async ev => {
    const task = ev.target.closest('.cal-task');
    if (task) {
      ev.stopPropagation();
      const t = _tasks.find(x => x.id === task.dataset.task);
      if (t) {
        t.done = !t.done;
        await fetch(`/api/tasks/${t.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ done: t.done }) }).catch(() => {});
        render();
      }
      return;
    }
    const chip = ev.target.closest('.cal-chip');
    if (chip) { openEvent(chip.dataset.id, chip.dataset.occ); return; }
    openEditor(null, c.dataset.date);
  }));
}

function weekStart(d) { const s = new Date(d); s.setDate(s.getDate() - ((s.getDay() - _weekStart + 7) % 7)); s.setHours(0, 0, 0, 0); return s; }

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
  let head = '<div class="cal-tg-gutter-head"></div>';
  for (const d of days) head += `<div class="cal-tg-dayhead${sameDay(d, today) ? ' today' : ''}" data-date="${ymd(d)}"><span class="cal-tg-wd">${WD[d.getDay()]}</span> <span class="cal-tg-dn">${d.getDate()}</span></div>`;
  let allday = '<div class="cal-tg-gutter">all-day</div>';
  for (const d of days) {
    const items = occ.filter(o => o.all_day && sameDay(o._date, d))
      .map(o => `<div class="cal-allday-ev${o._recur ? ' recurring' : ''}" data-id="${o.id}" data-occ="${ymd(o._date)}" style="${chipStyle(o)}" title="${chipTitle(o)}">${o._recur ? `<span class="cal-chip-recur">${_si('refresh')}</span>` : ''}${esc(o.title)}</div>`).join('');
    allday += `<div class="cal-tg-allday" data-date="${ymd(d)}">${items}</div>`;
  }
  let gutter = '';
  for (let h = 0; h < 24; h++) gutter += `<div class="cal-tg-hour" style="height:${HOUR_H}px">${h === 0 ? '' : (h % 12 || 12) + (h < 12 ? 'a' : 'p')}</div>`;
  const nowTop = (today.getHours() + today.getMinutes() / 60) * HOUR_H;
  let cols = '';
  for (const d of days) {
    let evHtml = '';
    for (const o of occ.filter(x => !x.all_day && sameDay(x._date, d))) {
      const bs = new Date(o.start_dt), be = o.end_dt ? new Date(o.end_dt) : new Date(bs.getTime() + 3600000);
      const durH = Math.max(0.5, (be - bs) / 3600000);
      const top = (o._date.getHours() + o._date.getMinutes() / 60) * HOUR_H;
      const hx = evHex(o);
      evHtml += `<div class="cal-tev${o._recur ? ' recurring' : ''}" data-id="${o.id}" data-occ="${ymd(o._date)}" style="top:${top}px;height:${durH * HOUR_H - 2}px;background:color-mix(in srgb, ${hx} 24%, transparent);border-left:3px solid ${hx}" title="${chipTitle(o)}"><b>${esc(timeShort(o._date))}</b> ${o._recur ? `<span class="cal-chip-recur">${_si('refresh')}</span>` : ''}${esc(o.title)}${o.location ? `<span class="cal-tev-loc">${esc(o.location)}</span>` : ''}<span class="cal-tev-resize"></span></div>`;
    }
    const isToday = sameDay(d, today);
    const nowLine = isToday ? `<div class="cal-now-line" style="top:${nowTop}px"></div>` : '';
    const lines = Array.from({ length: 24 }, (_, h) => `<div class="cal-tg-slot${h < _workStart || h >= _workEnd ? ' offhours' : ''}" style="height:${HOUR_H}px" data-date="${ymd(d)}" data-hour="${h}"></div>`).join('');
    cols += `<div class="cal-tg-col">${lines}${nowLine}${evHtml}</div>`;
  }
  el.innerHTML = `<div class="cal-timegrid ${days.length === 1 ? 'one-day' : ''}" style="--cols:${days.length}">
    <div class="cal-tg-headrow">${head}</div>
    <div class="cal-tg-alldayrow">${allday}</div>
    <div class="cal-tg-scroll"><div class="cal-tg-body"><div class="cal-tg-gutter-col">${gutter}</div>${cols}</div></div>
  </div>`;

  el.querySelectorAll('.cal-allday-ev').forEach(ev => ev.addEventListener('click', e => {
    e.stopPropagation(); openEvent(ev.dataset.id, ev.dataset.occ);
  }));
  el.querySelectorAll('.cal-tg-allday').forEach(s => s.addEventListener('click', e => { if (e.target === s) openEditor(null, s.dataset.date, null, true); }));
  attachDrag(el, days);   // drag to create / move / resize timed events
  const sc = el.querySelector('.cal-tg-scroll'); if (sc) sc.scrollTop = Math.max(0, nowTop - 3 * HOUR_H);
}

function openEvent(id, occ) {
  const ev = _events.find(e => e.id === id);
  if (ev) openEditor(ev, null, null, false, occ);
}

// ── drag: create / move / resize timed events in week & day views ────────────
function attachDrag(el, days) {
  const body = el.querySelector('.cal-tg-body');
  const cols = [...el.querySelectorAll('.cal-tg-col')];
  if (!body || !cols.length) return;
  const SNAP = HOUR_H / 4;                         // 15-minute grid
  const snap = px => Math.max(0, Math.round(px / SNAP) * SNAP);
  const colAt = x => cols.findIndex(c => { const r = c.getBoundingClientRect(); return x >= r.left && x < r.right; });
  const atTime = (date, px) => { const d = new Date(date); d.setHours(0, Math.round((px / HOUR_H) * 60 / 15) * 15, 0, 0); return localISO(d); };
  let st = null;

  function down(e) {
    if (e.button !== 0) return;
    const resize = e.target.closest('.cal-tev-resize');
    const tev = e.target.closest('.cal-tev');
    const slot = e.target.closest('.cal-tg-slot');
    if (resize && tev) {
      st = { mode: 'resize', tev, id: tev.dataset.id, occ: tev.dataset.occ, y0: e.clientY, h0: tev.offsetHeight, moved: false };
    } else if (tev) {
      st = { mode: 'move', tev, id: tev.dataset.id, occ: tev.dataset.occ, y0: e.clientY, x0: e.clientX, top0: tev.offsetTop, ci: cols.indexOf(tev.closest('.cal-tg-col')), moved: false };
      tev.classList.add('dragging');
    } else if (slot) {
      const ci = colAt(e.clientX); if (ci < 0) return;
      const rect = cols[ci].getBoundingClientRect();
      const y = snap(e.clientY - rect.top);
      const ghost = document.createElement('div');
      ghost.className = 'cal-tev cal-ghost'; ghost.style.cssText = `top:${y}px;height:${SNAP}px`;
      cols[ci].appendChild(ghost);
      st = { mode: 'create', ci, y, top: y, h: SNAP, ghost, hour: +slot.dataset.hour, date: slot.dataset.date, moved: false };
    } else return;
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
    e.preventDefault();
  }

  function move(e) {
    if (!st) return;
    if (st.mode === 'move') {
      if (Math.abs(e.clientY - st.y0) > 3 || Math.abs(e.clientX - st.x0) > 3) st.moved = true;
      st.tev.style.top = snap(st.top0 + (e.clientY - st.y0)) + 'px';
      const ci = colAt(e.clientX);
      if (ci >= 0 && ci !== st.ci) { cols[ci].appendChild(st.tev); st.ci = ci; }
    } else if (st.mode === 'resize') {
      if (Math.abs(e.clientY - st.y0) > 3) st.moved = true;
      st.tev.style.height = Math.max(SNAP, snap(st.h0 + (e.clientY - st.y0))) + 'px';
    } else {
      const rect = cols[st.ci].getBoundingClientRect();
      const cur = snap(e.clientY - rect.top);
      st.top = Math.min(cur, st.y); st.h = Math.max(SNAP, Math.abs(cur - st.y));
      st.ghost.style.top = st.top + 'px'; st.ghost.style.height = st.h + 'px';
      if (Math.abs(cur - st.y) > 4) st.moved = true;
    }
  }

  async function up() {
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    const s = st; st = null;
    if (!s) return;
    if (s.mode === 'create') {
      s.ghost.remove();
      if (s.moved) {
        _prefill = { start: atTime(days[s.ci], s.top), end: atTime(days[s.ci], s.top + s.h) };
        openEditor(null, ymd(days[s.ci]));
      } else openEditor(null, s.date, s.hour);
      return;
    }
    s.tev.classList.remove('dragging');
    if (!s.moved) { openEvent(s.id, s.occ); return; }   // a plain click
    const ci = s.ci >= 0 ? s.ci : cols.indexOf(s.tev.closest('.cal-tg-col'));
    const date = days[ci];
    const top = s.tev.offsetTop, h = s.tev.offsetHeight;
    await applyTimeChange(s.id, s.occ, atTime(date, top), atTime(date, top + h));
  }

  body.addEventListener('mousedown', down);
}

function buildCopy(ev, ov) {
  return {
    title: ev.title, calendar_id: ev.calendar_id, description: ev.description,
    location: ev.location, guests: ev.guests, all_day: ev.all_day, color: ev.color,
    reminders: ev.reminders || [], start_dt: ev.start_dt, end_dt: ev.end_dt,
    recurrence: ev.recurrence, recur_interval: ev.recur_interval, recur_byday: ev.recur_byday,
    recur_count: ev.recur_count, recur_until: ev.recur_until, ...ov,
  };
}

async function applyTimeChange(id, occ, newStart, newEnd) {
  const ev = _events.find(e => e.id === id);
  if (!ev) return;
  if (!ev.recurrence) {
    await apiPatch(id, { start_dt: newStart, end_dt: newEnd });
    return loadCalendar();
  }
  const scope = await chooseScope('move');
  if (!scope) return loadCalendar();   // cancelled → revert the visual drag
  if (scope === 'all') {
    await apiPatch(id, { start_dt: newStart, end_dt: newEnd });
  } else if (scope === 'this') {
    await apiPatch(id, { recur_except: [...(ev.recur_except || []), occ] });
    await apiPost(buildCopy(ev, { start_dt: newStart, end_dt: newEnd, recurrence: '', recur_byday: '', recur_count: null, recur_until: null, recur_interval: 1 }));
  } else {
    const db = new Date(occ + 'T00:00:00'); db.setDate(db.getDate() - 1);
    await apiPatch(id, { recur_until: ymd(db), recur_count: null });
    await apiPost(buildCopy(ev, { start_dt: newStart, end_dt: newEnd }));
  }
  loadCalendar();
}

// ── scope chooser (this / following / all) ───────────────────────────────────
function chooseScope(verb) {
  return new Promise(resolve => {
    const ov = document.createElement('div');
    ov.className = 'cal-scope-ov';
    ov.innerHTML = `<div class="cal-scope">
      <div class="cal-scope-h">${verb} recurring event</div>
      <button class="btn" data-s="this">This event</button>
      <button class="btn" data-s="following">This and following</button>
      <button class="btn" data-s="all">All events</button>
      <button class="btn cal-scope-cancel" data-s="">cancel</button>
    </div>`;
    document.body.appendChild(ov);
    const done = v => { ov.remove(); resolve(v); };
    ov.addEventListener('click', e => { if (e.target === ov) done(null); });
    ov.querySelectorAll('[data-s]').forEach(b => b.addEventListener('click', () => done(b.dataset.s || null)));
  });
}

// ── find a time: show open slots on the focused day, click to book ───────────
async function findTime() {
  const mins = parseInt(await dlgPrompt('how many minutes do you need?')) || 60;
  const dstr = ymd(_cursor);
  let slots = [];
  try { slots = (await fetch(`/api/calendar/free?date=${dstr}&minutes=${mins}`).then(r => r.json())).slots || []; }
  catch { toast('could not load free slots', 'error'); return; }
  const ov = document.createElement('div');
  ov.className = 'cal-scope-ov';
  const fmt = iso => iso.slice(11);
  ov.innerHTML = `<div class="cal-scope"><div class="cal-scope-h">free on ${dstr} (${mins} min)</div>${
    slots.length ? slots.map(s => `<button class="btn" data-s="${s.start}" data-e="${s.end}">${fmt(s.start)} – ${fmt(s.end)}</button>`).join('')
                 : '<div style="color:var(--muted);font-size:0.78rem;padding:0.4rem">no free slots that day</div>'
  }<button class="btn cal-scope-cancel">cancel</button></div>`;
  document.body.appendChild(ov);
  ov.addEventListener('click', e => { if (e.target === ov || e.target.classList.contains('cal-scope-cancel')) ov.remove(); });
  ov.querySelectorAll('[data-s]').forEach(b => b.addEventListener('click', async () => {
    const title = await dlgPrompt('event title:');
    if (!title?.trim()) { ov.remove(); return; }
    const start = b.dataset.s;
    const end = new Date(new Date(start).getTime() + mins * 60000);
    await fetch('/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ title: title.trim(), start_dt: start, end_dt: localISO(end) }) });
    ov.remove(); toast('booked', 'success'); loadCalendar();
  }));
}

// ── the event editor ─────────────────────────────────────────────────────────
const REMIND_PRESETS = [[0, 'at time'], [5, '5m'], [10, '10m'], [30, '30m'], [60, '1h'], [1440, '1d']];
const FREQS = [['', 'does not repeat'], ['daily', 'daily'], ['weekly', 'weekly'], ['monthly', 'monthly'], ['yearly', 'yearly']];
const UNIT = { daily: 'days', weekly: 'weeks', monthly: 'months', yearly: 'years' };
const DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const DOW_LETTER = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'];

function openEditor(event, defaultDate, hour, allDay, occ) {
  const el = document.getElementById('calendar-list');
  _editing = event || null;
  _editOcc = occ || null;
  const pf = _prefill; _prefill = null;   // start/end from a drag-create
  const isNew = !event;
  const now = new Date(); now.setMinutes(0, 0, 0);
  const hh = hour != null ? String(hour).padStart(2, '0') : '09';
  // editing a specific occurrence of a recurring event: keep the master's time-of-day but use
  // the clicked occurrence's date (occ), not the master's original start
  const mStart = event?.start_dt?.slice(0, 16) || '';
  const mEnd = event?.end_dt?.slice(0, 16) || '';
  const occStart = (occ && mStart) ? occ + mStart.slice(10) : '';
  const occEnd = (occ && mEnd) ? occ + mEnd.slice(10) : '';
  const start = pf?.start || occStart || mStart || (defaultDate ? `${defaultDate}T${hh}:00` : now.toISOString().slice(0, 16));
  const endVal = pf?.end || occEnd || mEnd || '';
  const defaultCal = event?.calendar_id || (_calendars.find(c => c.is_default)?.id || _calendars[0]?.id || '');
  const rec = event?.recurrence || '';
  const reminders = new Set(event?.reminders || (isNew ? [10] : []));
  const startDow = new Date(start).getDay();
  let byday = new Set(parseBydayJs(event?.recur_byday) || (rec === 'weekly' ? [startDow] : []));
  if (rec === 'weekly' && byday.size === 0) byday.add(startDow);
  let color = event?.color || '';   // '' = use the calendar's colour
  const endsMode = event?.recur_count ? 'after' : (event?.recur_until ? 'on' : 'never');

  el.innerHTML = `<div class="cal-editor">
    <input class="note-editor-title" id="cal-title" value="${esc(event?.title || '')}" placeholder="event title…">
    <div class="cal-ed-grid">
      <div><div class="cal-flabel">start</div><div class="date-input" id="cal-start" data-type="datetime" data-value="${start}" data-ph="start" style="width:100%"></div></div>
      <div><div class="cal-flabel">end</div><div class="date-input" id="cal-end" data-type="datetime" data-value="${endVal}" data-ph="end (optional)" style="width:100%"></div></div>
    </div>
    <div class="cal-ed-row">
      <label class="cal-flabel cal-chk-row" id="cal-allday-row"><span class="chk" id="cal-allday" role="checkbox" aria-checked="${event?.all_day || allDay ? 'true' : 'false'}"></span> all day</label>
      <div class="cal-cal-pick"><span class="cal-flabel">calendar</span>
        <div class="settings-input custom-select" id="cal-calendar" data-value="${defaultCal}" data-options="${_calendars.map(c => `${c.id}|${esc(c.name)}`).join(';')}" style="min-width:130px"></div></div>
    </div>

    <div class="cal-flabel">repeat</div>
    <div class="settings-input custom-select" id="cal-recur" data-value="${rec}" data-options="${FREQS.map(([v, l]) => `${v}|${l}`).join(';')}" style="width:100%"></div>
    <div id="cal-recur-adv" style="display:${rec ? 'block' : 'none'}">
      <div class="cal-recur-line">every <input class="settings-input cal-int" id="cal-interval" type="text" inputmode="numeric" value="${event?.recur_interval || 1}"> <span id="cal-unit">${UNIT[rec] || 'weeks'}</span></div>
      <div class="cal-dow" id="cal-dow" style="display:${rec === 'weekly' ? 'flex' : 'none'}">${DOW.map((d, i) => `<span class="cal-dow-b ${byday.has(i) ? 'on' : ''}" data-i="${i}">${d}</span>`).join('')}</div>
      <div class="cal-ends">
        <span class="cal-flabel">ends</span>
        <label class="cal-radio"><input type="radio" name="cal-ends" value="never" ${endsMode === 'never' ? 'checked' : ''}> never</label>
        <label class="cal-radio"><input type="radio" name="cal-ends" value="on" ${endsMode === 'on' ? 'checked' : ''}> on <div class="date-input cal-ends-date" id="cal-until" data-type="date" data-value="${event?.recur_until || ''}" data-ph="date" style="width:130px"></div></label>
        <label class="cal-radio"><input type="radio" name="cal-ends" value="after" ${endsMode === 'after' ? 'checked' : ''}> after <input class="settings-input cal-int" id="cal-count" type="text" inputmode="numeric" value="${event?.recur_count || 10}"> times</label>
      </div>
    </div>

    <div class="cal-flabel">reminders</div>
    <div class="cal-reminders" id="cal-reminders">${REMIND_PRESETS.map(([m, l]) => `<span class="cal-rem ${reminders.has(m) ? 'on' : ''}" data-m="${m}">${l}</span>`).join('')}</div>

    <div class="cal-ed-grid">
      <div><div class="cal-flabel">location</div><input class="settings-input" id="cal-loc" value="${esc(event?.location || '')}" placeholder="add location" style="width:100%"></div>
      <div><div class="cal-flabel">guests</div><input class="settings-input" id="cal-guests" value="${esc(event?.guests || '')}" placeholder="comma-separated" style="width:100%"></div>
    </div>

    <div class="cal-flabel">video call</div>
    <div class="cal-meet-row">
      <input class="settings-input" id="cal-meeting" value="${esc(event?.meeting_url || '')}" placeholder="paste a link or generate one" style="flex:1">
      <button class="btn" id="cal-meet-gen" type="button" title="generate a Jitsi room">${_si('video')} add</button>
      ${event?.meeting_url ? `<a class="btn" id="cal-meet-open" href="${esc(event.meeting_url)}" target="_blank" rel="noopener">join</a>` : ''}
    </div>

    ${isNew ? '' : `<div class="cal-flabel">invites &amp; rsvp</div>
    <div class="cal-invites" id="cal-invites"></div>
    <div class="cal-invite-add">
      <input class="settings-input" id="cal-inv-name" placeholder="name" style="flex:1">
      <input class="settings-input" id="cal-inv-email" placeholder="email" style="flex:1.4">
      <button class="btn" id="cal-inv-btn" type="button">invite</button>
    </div>`}

    <div class="cal-flabel">color</div>
    <div class="cal-swatches" id="cal-colors">
      <span class="cal-sw cal-sw-def ${color === '' ? 'sel' : ''}" data-c="" title="calendar default">○</span>
      ${COLOR_NAMES.map(c => `<span class="cal-sw ${color === c ? 'sel' : ''}" data-c="${c}" style="background:${hexOf(c)}"></span>`).join('')}
    </div>

    <textarea class="note-editor-body" id="cal-desc" rows="3" placeholder="description…">${esc(event?.description || '')}</textarea>
    <div class="cal-ed-actions">
      ${isNew ? '' : '<button class="btn" id="cal-del" style="margin-right:auto;color:var(--error);border-color:var(--error)">delete</button>'}
      ${isNew ? '' : '<button class="btn" id="cal-dup" title="duplicate this event">duplicate</button>'}
      <button class="btn ic-btn-lbl" id="cal-back">${_si('chevron-left')} back</button>
      <button class="btn primary" id="cal-save">${isNew ? 'create' : 'save'}</button>
    </div>
  </div>`;

  initCustomDropdown(document.getElementById('cal-recur'));
  initCustomDropdown(document.getElementById('cal-calendar'));
  initDatePickers(el);

  document.getElementById('cal-allday-row').addEventListener('click', e => {
    if (e.target.closest('.date-input')) return;
    const c = document.getElementById('cal-allday');
    c.setAttribute('aria-checked', c.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
  });
  const recSel = document.getElementById('cal-recur');
  recSel.addEventListener('change', () => {
    const v = recSel.value;
    document.getElementById('cal-recur-adv').style.display = v ? 'block' : 'none';
    document.getElementById('cal-unit').textContent = UNIT[v] || 'weeks';
    document.getElementById('cal-dow').style.display = v === 'weekly' ? 'flex' : 'none';
    if (v === 'weekly' && byday.size === 0) { byday.add(startDow); syncDow(); }
  });
  function syncDow() { el.querySelectorAll('.cal-dow-b').forEach(b => b.classList.toggle('on', byday.has(+b.dataset.i))); }
  el.querySelectorAll('.cal-dow-b').forEach(b => b.addEventListener('click', () => {
    const i = +b.dataset.i; byday.has(i) ? byday.delete(i) : byday.add(i); syncDow();
  }));
  el.querySelectorAll('.cal-rem').forEach(r => r.addEventListener('click', () => r.classList.toggle('on')));
  el.querySelectorAll('#cal-colors .cal-sw').forEach(s => s.addEventListener('click', () => {
    color = s.dataset.c; el.querySelectorAll('#cal-colors .cal-sw').forEach(x => x.classList.toggle('sel', x === s));
  }));

  document.getElementById('cal-back').addEventListener('click', () => loadCalendar());
  document.getElementById('cal-del')?.addEventListener('click', () => deleteEvent());
  document.getElementById('cal-dup')?.addEventListener('click', async () => {
    if (!_editing?.id) return;
    try {
      await fetch(`/api/calendar/${_editing.id}/duplicate`, { method: 'POST' });
      toast('event duplicated', 'success');
      loadCalendar();
    } catch { toast('duplicate failed', 'error'); }
  });
  document.getElementById('cal-save').addEventListener('click', () => saveEvent(byday));

  // 8b — video call link generator
  document.getElementById('cal-meet-gen')?.addEventListener('click', async () => {
    const inp = document.getElementById('cal-meeting');
    if (event?.id) {
      try {
        const d = await fetch(`/api/calendar/${event.id}/meeting-link`, { method: 'POST' }).then(r => r.json());
        inp.value = d.meeting_url; toast('video room added', 'success');
      } catch { toast('failed', 'error'); }
    } else {
      // new event: mint a room name client-side; saved with the event
      const slug = (document.getElementById('cal-title').value || 'Meet').replace(/[^a-zA-Z0-9]+/g, '').slice(0, 24) || 'Meet';
      inp.value = `https://meet.jit.si/${slug}-${Math.random().toString(36).slice(2, 12)}`;
    }
  });

  // 8b — invites + rsvp (existing events only)
  if (event?.id) renderAttendees(event.id);
  document.getElementById('cal-inv-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('cal-inv-name').value.trim();
    const email = document.getElementById('cal-inv-email').value.trim();
    if (!name && !email) { toast('name or email needed', ''); return; }
    try {
      await fetch(`/api/calendar/${event.id}/invite`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name, email }),
      });
      document.getElementById('cal-inv-name').value = '';
      document.getElementById('cal-inv-email').value = '';
      renderAttendees(event.id);
    } catch { toast('invite failed', 'error'); }
  });
}

const RSVP_LABEL = { invited: 'invited', accepted: 'yes', declined: 'no', tentative: 'maybe' };

async function renderAttendees(eid) {
  const box = document.getElementById('cal-invites');
  if (!box) return;
  const list = await fetch(`/api/calendar/${eid}/attendees`).then(r => r.json()).catch(() => []);
  if (!list.length) { box.innerHTML = '<div class="cal-inv-empty">no invites yet</div>'; return; }
  box.innerHTML = list.map(a => `
    <div class="cal-inv-row" data-id="${a.id}">
      <span class="cal-inv-who">${esc(a.name || a.email)}</span>
      <span class="cal-inv-status s-${a.status}">${RSVP_LABEL[a.status] || a.status}</span>
      <button class="cal-inv-x" data-act="del" title="remove">×</button>
    </div>`).join('');
  box.querySelectorAll('.cal-inv-row').forEach(row => {
    row.querySelector('[data-act="del"]').addEventListener('click', async () => {
      await fetch(`/api/calendar/attendees/${row.dataset.id}`, { method: 'DELETE' });
      renderAttendees(eid);
    });
  });
}

function parseBydayJs(s) {
  return s ? (s.split(',').map(t => DOW_LETTER.indexOf(t.trim().toUpperCase())).filter(v => v >= 0)) : null;
}

function collectBody(byday) {
  const el = document.getElementById('calendar-list');
  const rec = document.getElementById('cal-recur').value;
  const ends = el.querySelector('input[name="cal-ends"]:checked')?.value || 'never';
  const reminders = [...el.querySelectorAll('.cal-rem.on')].map(r => +r.dataset.m).sort((a, b) => a - b);
  const body = {
    title: document.getElementById('cal-title').value.trim(),
    calendar_id: document.getElementById('cal-calendar').value,
    description: document.getElementById('cal-desc').value,
    location: document.getElementById('cal-loc').value.trim(),
    guests: document.getElementById('cal-guests').value.trim(),
    meeting_url: document.getElementById('cal-meeting')?.value.trim() || '',
    start_dt: document.getElementById('cal-start').value,
    end_dt: document.getElementById('cal-end').value || null,
    all_day: document.getElementById('cal-allday').getAttribute('aria-checked') === 'true',
    color: document.querySelector('#cal-colors .cal-sw.sel')?.dataset.c ?? '',
    reminders,
    recurrence: rec,
    recur_interval: rec ? Math.max(1, parseInt(document.getElementById('cal-interval').value) || 1) : 1,
    recur_byday: rec === 'weekly' ? [...byday].sort((a, b) => a - b).map(i => DOW_LETTER[i]).join(',') : '',
    recur_count: rec && ends === 'after' ? Math.max(1, parseInt(document.getElementById('cal-count').value) || 1) : null,
    recur_until: rec && ends === 'on' ? (document.getElementById('cal-until').value || null) : null,
  };
  return body;
}

async function saveEvent(byday) {
  const body = collectBody(byday);
  if (!body.title || !body.start_dt) { toast('title + start required', 'error'); return; }

  // new, or a non-recurring edit → straightforward
  if (!_editing) {
    await fetch('/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    toast('created', 'success'); return loadCalendar();
  }
  if (!_editing.recurrence) {
    await fetch(`/api/calendar/${_editing.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    toast('saved', 'success'); return loadCalendar();
  }

  // editing a recurring series → ask scope
  const scope = await chooseScope('edit');
  if (!scope) return;
  const occ = _editOcc || _editing.start_dt.slice(0, 10);
  if (scope === 'all') {
    await fetch(`/api/calendar/${_editing.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  } else if (scope === 'this') {
    // exclude this occurrence on the master, create a standalone single event
    const ex = [...(_editing.recur_except || []), occ];
    await fetch(`/api/calendar/${_editing.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ recur_except: ex }) });
    const single = { ...body, recurrence: '', recur_byday: '', recur_count: null, recur_until: null, recur_interval: 1 };
    await fetch('/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(single) });
  } else { // following — end the old series before occ, start a new one here
    const dayBefore = new Date(occ + 'T00:00:00'); dayBefore.setDate(dayBefore.getDate() - 1);
    await fetch(`/api/calendar/${_editing.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ recur_until: ymd(dayBefore), recur_count: null }) });
    await fetch('/api/calendar', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  }
  toast('saved', 'success'); loadCalendar();
}

async function deleteEvent() {
  if (!_editing) return;
  if (!_editing.recurrence) {
    await fetch(`/api/calendar/${_editing.id}`, { method: 'DELETE' });
    return loadCalendar();
  }
  const scope = await chooseScope('delete');
  if (!scope) return;
  const occ = _editOcc || _editing.start_dt.slice(0, 10);
  await fetch(`/api/calendar/${_editing.id}?scope=${scope}&occ=${occ}`, { method: 'DELETE' });
  loadCalendar();
}

// ── CalDAV sync panel ───────────────────────────────────────────────────────
async function openCaldavPanel() {
  const list = document.getElementById('calendar-list');
  let cfg = {};
  try { cfg = await fetch('/api/caldav/status').then(r => r.json()); } catch {}
  list.innerHTML = `<div class="cal-editor" style="max-width:520px">
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
    <div class="cal-ed-actions">
      <button class="btn ic-btn-lbl" id="cd-back">${_si('chevron-left')} back</button>
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
    st.textContent = 'syncing…'; await save();
    try {
      const r = await fetch('/api/caldav/sync', { method: 'POST' }).then(x => x.json());
      if (r.error) { st.textContent = 'error: ' + r.error; return; }
      st.textContent = `synced — pulled ${r.pulled || 0}, pushed ${r.pushed || 0}`;
      await loadCalendar();
    } catch (e) { st.textContent = 'sync failed'; }
  });
}

export function newEvent() { openEditor(null); }

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
