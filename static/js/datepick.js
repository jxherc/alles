// custom date / datetime picker — replaces native <input type=datetime-local|date>.
// a .date-input div carries data-type="date|datetime|due" and data-value; .value
// reads/writes the same strings the backend expects (YYYY-MM-DD / YYYY-MM-DDTHH:MM).
// "due" is a date with an optional time: YYYY-MM-DD until a time is added, then YYYY-MM-DDTHH:MM.
// "time" is a time of day alone (HH:MM, a bedtime or a start): no calendar, the hour in the owner's
// 12 or 24 hour choice.
import {
  formatCalendarDate,
  formatDate,
  formatDateForLocale,
  formatDateParts,
  resolvedTimeZone,
  formatTime,
  formatClock,
  localizationState,
  t,
} from './i18n.js';

let _open = null;

export function initDatePickers(root = document) {
  root.querySelectorAll('.date-input').forEach(initDatePicker);
}

// data-ph-key names the catalog message; data-ph is a literal for built markup
function _placeholder(el) {
  return el.dataset.phKey ? t(el.dataset.phKey) : (el.dataset.ph || t('common.datepick_pick'));
}

export function initDatePicker(el) {
  if (!el || el.dataset.dpReady === '1') return;
  el.dataset.dpReady = '1';
  el.tabIndex = 0;
  el.setAttribute('role', 'button');
  el.setAttribute('aria-haspopup', 'dialog');
  el.setAttribute('aria-expanded', 'false');
  if (!el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby')) el.setAttribute('aria-label', _placeholder(el));
  Object.defineProperty(el, 'value', {
    configurable: true,
    get() { return el.dataset.value || ''; },
    set(v) { el.dataset.value = v || ''; _trigger(el); if (_open?.el === el) _render(el); },
  });
  _trigger(el);
  el.addEventListener('click', e => { e.stopPropagation(); _toggle(el); });
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _toggle(el); }
    // escape closes the open picker and stops there, so a form around it (mail compose) doesn't
    // read it as "leave and discard"
    else if (e.key === 'Escape' && _open?.el === el) { e.stopPropagation(); _close(); }
  });
}


const _isDate = el => el.dataset.type === 'date';
const _isDue = el => el.dataset.type === 'due';
const _isTime = el => el.dataset.type === 'time';
const _clockParts = value => {
  const match = /^(\d{2}):(\d{2})$/.exec(String(value || ''));
  return match && Number(match[1]) < 24 && Number(match[2]) < 60 ? { h: Number(match[1]), mi: Number(match[2]) } : null;
};
// the owner's clock setting, else the language's own habit: a 12 hour language writes 1 pm, not 13
export function uses12Hours(state = localizationState()) {
  if (state.clockFormat === '12') return true;
  if (state.clockFormat === '24') return false;
  return !formatClock('13:00').includes('13');
}
// "am" or "pm" in the interface language, lowercase like the rest of the app
function _period(h) {
  const parts = formatDateParts(Date.UTC(2000, 0, 1, h), { hour: 'numeric', hour12: true, timeZone: 'UTC' });
  return (parts.find(part => part.type === 'dayPeriod')?.value || (h < 12 ? 'am' : 'pm')).toLocaleLowerCase();
}
export const clockText = value => _clockParts(value) ? formatClock(value).toLocaleLowerCase() : String(value || '');
// a due value without a time reads and writes like a plain date
const _dateOnly = el => _isDate(el) || (_isDue(el) && !(_open?.el === el ? _open.sel.timed : String(el.dataset.value || '').includes('T')));

// a task's due_date and due_time as one due field value, and back
export function joinDue(date, time) { return date ? (time ? `${date}T${String(time).slice(0, 5)}` : date) : ''; }
export function splitDue(value) {
  const [date, time] = String(value || '').split('T');
  return { due_date: date || null, due_time: date && time ? time.slice(0, 5) : null };
}
const _z = n => String(n).padStart(2, '0');
const SUNDAY_FIRST_REGIONS = new Set(['AG', 'AS', 'BD', 'BR', 'BS', 'BT', 'BW', 'BZ', 'CA', 'CN', 'CO', 'DM', 'DO', 'ET', 'GT', 'GU', 'HK', 'HN', 'ID', 'IL', 'IN', 'JM', 'JP', 'KE', 'KH', 'KR', 'LA', 'MH', 'MM', 'MO', 'MT', 'MX', 'MZ', 'NI', 'NP', 'PA', 'PE', 'PH', 'PK', 'PR', 'PT', 'PY', 'SA', 'SG', 'SV', 'TH', 'TT', 'TW', 'UM', 'US', 'VE', 'VI', 'WS', 'YE', 'ZA', 'ZW']);

export function resolveDatePickerWeekStart(state = localizationState()) {
  if (state.weekStart === 'mon') return 1;
  if (state.weekStart === 'sun') return 0;
  const region = String(state.effectiveRegion || state.region || '').toUpperCase();
  try {
    const language = String(state.language || 'en').split('-')[0];
    const locale = new Intl.Locale(region ? `${language}-${region}` : state.locale || 'en');
    const info = typeof locale.getWeekInfo === 'function' ? locale.getWeekInfo() : locale.weekInfo;
    if (Number.isInteger(info?.firstDay) && info.firstDay >= 1 && info.firstDay <= 7) {
      return info.firstDay % 7;
    }
  } catch {}
  return SUNDAY_FIRST_REGIONS.has(region) ? 0 : 1;
}

export function datePickerWeekdayLabels(state = localizationState()) {
  return Array.from({ length: 7 }, (_value, index) =>
    formatDateForLocale(
      new Date(Date.UTC(2024, 0, 7 + index, 12)),
      state.locale || state.language || 'en',
      { weekday: 'short', timeZone: 'UTC' },
    ),
  );
}

export function calendarDateParts(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) return null;
  const y = Number(match[1]);
  const mo = Number(match[2]) - 1;
  const d = Number(match[3]);
  const date = new Date(Date.UTC(y, mo, d));
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== mo || date.getUTCDate() !== d) {
    return null;
  }
  return { y, mo, d, h: 0, mi: 0 };
}

export function dateTimeParts(value) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/.exec(String(value || ''));
  if (!match) return null;
  const day = calendarDateParts(match[1]);
  const h = Number(match[2]), mi = Number(match[3]);
  return day && h < 24 && mi < 60 ? { ...day, h, mi } : null;
}
function _currentParts(value = new Date()) {
  const parts = Object.fromEntries(formatDateParts(value, {
    timeZone: resolvedTimeZone(), calendar: 'gregory', numberingSystem: 'latn',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).map(part => [part.type, Number(part.value)]));
  return { y: parts.year, mo: parts.month - 1, d: parts.day, h: parts.hour, mi: parts.minute };
}
function _parse(el) {
  const v = el.dataset.value;
  if (_isTime(el)) {
    const now = _currentParts();
    return { ...now, ...(_clockParts(v) || { h: now.h, mi: now.mi }) };
  }
  if (_isDue(el)) {
    const timed = dateTimeParts(v);
    if (timed) return { ...timed, timed: true };
    const day = calendarDateParts(v) || _currentParts();
    return { ...day, h: 9, mi: 0, timed: false };
  }
  const literal = _isDate(el) ? calendarDateParts(v) : dateTimeParts(v);
  if (literal) return literal;
  const dt = v ? new Date(v) : new Date();
  return _currentParts(isNaN(dt) ? new Date() : dt);
}
function _fmt(p, isDate) {
  const date = `${p.y}-${_z(p.mo + 1)}-${_z(p.d)}`;
  return isDate ? date : `${date}T${_z(p.h)}:${_z(p.mi)}`;
}
function _display(v, isDate) {
  if (isDate) {
    if (!calendarDateParts(v)) return v;
    return formatCalendarDate(v, { month: 'short', day: 'numeric', year: 'numeric' });
  }
  const wall = dateTimeParts(v);
  const dt = wall ? new Date(Date.UTC(wall.y, wall.mo, wall.d, wall.h, wall.mi)) : new Date(v);
  if (isNaN(dt)) return v;
  const zone = wall ? { timeZone: 'UTC' } : {};
  const d = formatDate(dt, { month: 'short', day: 'numeric', year: 'numeric', ...zone });
  return `${d}, ${formatTime(dt, { hour: 'numeric', minute: '2-digit', ...zone })}`;
}
const CLOCK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';
function _trigger(el) {
  const v = el.dataset.value;
  if (_isTime(el)) {
    el.innerHTML = `<span class="date-input-label${v ? '' : ' ph'}">${v ? clockText(v) : _placeholder(el)}</span>${CLOCK}`;
    return;
  }
  el.innerHTML = `<span class="date-input-label${v ? '' : ' ph'}">${v ? _display(v, _isDate(el) || (_isDue(el) && !v.includes('T'))) : _placeholder(el)}</span>` +
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`;
}

function _toggle(el) { if (el.getAttribute('aria-disabled') === 'true') return; if (_open?.el === el) _close(); else _openPanel(el); }

function _openPanel(el) {
  _close(false);
  const panel = document.createElement('div');
  panel.className = 'date-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', el.getAttribute('aria-label') || t('common.datepick_choose'));
  el.setAttribute('aria-expanded', 'true');
  // a tap on a weekday label, the month name or the time row's background focuses the panel
  // itself, so escape still reaches it
  panel.tabIndex = -1;
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); _close(); return; }
    if (event.key !== 'Tab') return;
    // tab is walked here over every control, inputs too: safari's own tab skips buttons and
    // walked out of the panel with it still open
    const items = [...panel.querySelectorAll('button, input')].filter(node => !node.disabled && node.getClientRects().length);
    if (!items.length) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement);
    const next = at < 0 ? (event.shiftKey ? items.length - 1 : 0) : (at + (event.shiftKey ? -1 : 1) + items.length) % items.length;
    items[next].focus();
  });
  document.body.appendChild(panel);
  const cur = _parse(el);
  _open = { el, panel, view: { y: cur.y, mo: cur.mo }, sel: cur };
  _render(el);
  (panel.querySelector('.dp-day.sel') || panel.querySelector('.dp-day') || panel.querySelector('.dp-tv')).focus();
  window.addEventListener('resize', _reposition);
  window.visualViewport?.addEventListener('resize', _reposition);
  setTimeout(() => document.addEventListener('click', _outside), 0);
}

// a time of day alone: hour and minute (with am or pm on a 12 hour clock), clear and now
function _renderTime(el) {
  const { panel, sel } = _open;
  const active = panel.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = active?.dataset.step ? `[data-step="${active.dataset.step}"]` : active?.dataset.part ? `[data-part="${active.dataset.part}"]`
    : active?.classList.contains('dp-now') ? '.dp-now' : null;
  const twelve = uses12Hours();
  const hour = twelve ? String(sel.h % 12 || 12) : _z(sel.h);
  panel.innerHTML = `
    <div class="dp-time dp-time-only">
      <button type="button" class="dp-step" data-step="h-1" aria-label="${t('common.datepick_prev_hour')}">‹</button><input class="dp-tv" data-part="h" inputmode="numeric" maxlength="2" aria-label="${t('common.datepick_hour')}" value="${hour}"><button type="button" class="dp-step" data-step="h1" aria-label="${t('common.datepick_next_hour')}">›</button>
      <span class="dp-colon">:</span>
      <button type="button" class="dp-step" data-step="mi-1" aria-label="${t('common.datepick_minutes_earlier')}">‹</button><input class="dp-tv" data-part="mi" inputmode="numeric" maxlength="2" aria-label="${t('common.datepick_minute')}" value="${_z(sel.mi)}"><button type="button" class="dp-step" data-step="mi1" aria-label="${t('common.datepick_minutes_later')}">›</button>
      ${twelve ? `<button type="button" class="dp-step dp-period" data-step="ap">${_period(sel.h)}</button>` : ''}
    </div>
    <div class="dp-foot"><button type="button" class="dp-clear">${t('common.datepick_clear')}</button><button type="button" class="dp-now">${t('common.datepick_now')}</button></div>`;
  const hold = b => { if (panel.contains(b) && document.activeElement !== b) b.focus({ preventScroll: true }); };
  panel.querySelectorAll('.dp-step').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    hold(b);
    const s = b.dataset.step;
    if (s === 'ap') sel.h = (sel.h + 12) % 24;
    else if (s.startsWith('h')) sel.h = (sel.h + (s === 'h1' ? 1 : 23)) % 24;
    else sel.mi = s === 'mi1' ? (Math.floor(sel.mi / 5) * 5 + 5) % 60 : (Math.ceil(sel.mi / 5) * 5 + 55) % 60;
    _commit(el); _render(el);
  }));
  panel.querySelectorAll('.dp-tv').forEach(input => {
    const part = input.dataset.part;
    const apply = () => {
      if (_open?.panel !== panel) return;
      const n = parseInt(input.value, 10);
      // on a 12 hour clock a typed hour keeps the half of the day it's in (12 is the first hour)
      const h = twelve && part === 'h' && n >= 1 && n <= 12 ? (n % 12) + (sel.h >= 12 ? 12 : 0) : n;
      const top = part === 'h' ? 23 : 59;
      if (Number.isFinite(h) && h >= 0 && h <= top && h !== sel[part]) { sel[part] = h; _commit(el); }
      input.value = part === 'h' && twelve ? String(sel.h % 12 || 12) : _z(sel[part]);
    };
    input.addEventListener('click', e => e.stopPropagation());
    input.addEventListener('change', apply);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); apply(); _render(el); } });
  });
  panel.querySelector('.dp-clear').addEventListener('click', e => { e.stopPropagation(); el.value = ''; el.dispatchEvent(new Event('change', { bubbles: true })); _close(); });
  panel.querySelector('.dp-now').addEventListener('click', e => {
    e.stopPropagation();
    hold(e.currentTarget);
    const now = _currentParts();
    sel.h = now.h; sel.mi = now.mi;
    _commit(el); _render(el);
  });
  _position(el, panel);
  if (focusKey) panel.querySelector(focusKey)?.focus({ preventScroll: true });
}

function _render(el) {
  if (_isTime(el)) { _renderTime(el); return; }
  const { panel, view, sel } = _open;
  const active = panel.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = active?.dataset.d ? `[data-d="${active.dataset.d}"]` : active?.dataset.step ? `[data-step="${active.dataset.step}"]` : active?.dataset.nav ? `[data-nav="${active.dataset.nav}"]`
    : active?.dataset.part ? `[data-part="${active.dataset.part}"]` : active?.classList.contains('dp-year') ? '.dp-year'
    : active?.classList.contains('dp-now') ? '.dp-now'
    : active?.classList.contains('dp-time-add') ? '[data-part="h"]' : active?.classList.contains('dp-time-remove') ? '.dp-time-add' : null;
  const isDate = _dateOnly(el);
  const due = _isDue(el);
  const monthName = formatCalendarDate(
    `${view.y}-${_z(view.mo + 1)}-01`,
    { month: 'long' },
  );
  const time = due && !sel.timed
    ? `<div class="dp-time"><button type="button" class="dp-time-add">${t('common.datepick_add_time')}</button></div>`
    : isDate ? '' : `
    <div class="dp-time">
      <button type="button" class="dp-step" data-step="h-1" aria-label="${t('common.datepick_prev_hour')}">‹</button><input class="dp-tv" data-part="h" inputmode="numeric" maxlength="2" aria-label="${t('common.datepick_hour')}" value="${_z(sel.h)}"><button type="button" class="dp-step" data-step="h1" aria-label="${t('common.datepick_next_hour')}">›</button>
      <span class="dp-colon">:</span>
      <button type="button" class="dp-step" data-step="mi-1" aria-label="${t('common.datepick_minutes_earlier')}">‹</button><input class="dp-tv" data-part="mi" inputmode="numeric" maxlength="2" aria-label="${t('common.datepick_minute')}" value="${_z(sel.mi)}"><button type="button" class="dp-step" data-step="mi1" aria-label="${t('common.datepick_minutes_later')}">›</button>
    </div>`;
  panel.innerHTML = `
    <div class="dp-head"><button type="button" class="dp-nav" data-nav="-1" aria-label="${t('calendar.previous_month')}">‹</button><span>${monthName} <input class="dp-year" inputmode="numeric" maxlength="4" aria-label="${t('common.datepick_year')}" value="${view.y}"></span><button type="button" class="dp-nav" data-nav="1" aria-label="${t('calendar.next_month')}">›</button></div>
    <div class="dp-grid">${_grid(view, sel)}</div>${time}
    <div class="dp-foot"><button type="button" class="dp-clear">${t('common.datepick_clear')}</button>${due && sel.timed ? `<button type="button" class="dp-time-remove">${t('common.datepick_no_time')}</button>` : ''}<button type="button" class="dp-now">${t('common.datepick_now')}</button></div>`;

  // safari doesn't focus a clicked button, so focus would sit on <body>: the rebuild couldn't
  // put it back and escape stopped closing the picker. focus what was clicked first
  const hold = b => { if (panel.contains(b) && document.activeElement !== b) b.focus({ preventScroll: true }); };
  panel.querySelectorAll('.dp-nav').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    hold(b);
    view.mo += +b.dataset.nav;
    if (view.mo < 0) { view.mo = 11; view.y--; }
    if (view.mo > 11) { view.mo = 0; view.y++; }
    _render(el);
  }));
  const grid = panel.querySelector('.dp-grid');
  grid.addEventListener('click', e => {
    e.stopPropagation();
    const b = e.target.closest('.dp-day');
    if (!b) return;
    sel.y = view.y; sel.mo = view.mo; sel.d = +b.dataset.d;
    hold(b);
    _commit(el);
    if (isDate) _close(); else _render(el);
  });
  panel.querySelectorAll('.dp-step').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    hold(b);
    const s = b.dataset.step;
    if (s.startsWith('h')) sel.h = (sel.h + (s === 'h1' ? 1 : 23)) % 24;
    // minutes move in fives (onto the next five); one at a time took 30 clicks to reach :30
    else sel.mi = s === 'mi1' ? (Math.floor(sel.mi / 5) * 5 + 5) % 60 : (Math.ceil(sel.mi / 5) * 5 + 55) % 60;
    _commit(el); _render(el);
  }));
  // hour and minute can be typed. leaving the field applies them in place: change fires on the
  // mousedown/tab that leaves it, and a rebuild there ate that click or dropped focus to <body>
  panel.querySelectorAll('.dp-tv').forEach(input => {
    const part = input.dataset.part;
    const apply = () => {
      if (_open?.panel !== panel) return;
      const n = parseInt(input.value, 10);
      if (Number.isFinite(n) && n >= 0 && n <= (part === 'h' ? 23 : 59) && n !== sel[part]) { sel[part] = n; _commit(el); }
      input.value = _z(sel[part]);
    };
    input.addEventListener('click', e => e.stopPropagation());
    input.addEventListener('change', apply);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); apply(); _render(el); } });
  });
  // the year moves the grid as it's typed, so nothing needs rebuilding when the field is left
  const yearInput = panel.querySelector('.dp-year');
  yearInput.addEventListener('click', e => e.stopPropagation());
  yearInput.addEventListener('input', () => {
    const n = Number(yearInput.value);
    if (!/^\d{4}$/.test(yearInput.value) || n < 1000 || n === view.y) return;
    view.y = n;
    grid.innerHTML = _grid(view, sel);
  });
  yearInput.addEventListener('change', () => { if (_open?.panel === panel) yearInput.value = view.y; });
  yearInput.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); _render(el); } });
  // arrows walk the days, a week up or down, into the next or previous month
  panel.querySelector('.dp-grid')?.addEventListener('keydown', e => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    const from = e.target.closest?.('.dp-day');
    if (!step || !from) return;
    e.preventDefault();
    const next = new Date(view.y, view.mo, +from.dataset.d + step);
    view.y = next.getFullYear(); view.mo = next.getMonth();
    _render(el);
    panel.querySelector(`.dp-day[data-d="${next.getDate()}"]`)?.focus();
  });
  // a due date takes a time only when asked; taking it away keeps the day
  panel.querySelector('.dp-time-add')?.addEventListener('click', e => {
    e.stopPropagation();
    hold(e.currentTarget);
    sel.timed = true;
    _commit(el); _render(el);
  });
  panel.querySelector('.dp-time-remove')?.addEventListener('click', e => {
    e.stopPropagation();
    hold(e.currentTarget);
    sel.timed = false;
    _commit(el); _render(el);
  });
  panel.querySelector('.dp-clear').addEventListener('click', e => { e.stopPropagation(); el.value = ''; el.dispatchEvent(new Event('change', { bubbles: true })); _close(); });
  panel.querySelector('.dp-now').addEventListener('click', e => {
    e.stopPropagation();
    hold(e.currentTarget);
    Object.assign(sel, due && !sel.timed ? { ..._currentParts(), h: sel.h, mi: sel.mi } : _currentParts());
    view.y = sel.y; view.mo = sel.mo;
    _commit(el);
    if (isDate) _close(); else _render(el);
  });

  _position(el, panel);
  if (focusKey) panel.querySelector(focusKey)?.focus({ preventScroll: true });
}

function _grid(view, sel) {
  const weekStart = resolveDatePickerWeekStart();
  const first = (new Date(view.y, view.mo, 1).getDay() - weekStart + 7) % 7;
  const days = new Date(view.y, view.mo + 1, 0).getDate();
  const weekdays = datePickerWeekdayLabels();
  const orderedWeekdays = [...weekdays.slice(weekStart), ...weekdays.slice(0, weekStart)];
  let grid = orderedWeekdays.map(d => `<span class="dp-dow">${d}</span>`).join('');
  for (let i = 0; i < first; i++) grid += '<span></span>';
  for (let d = 1; d <= days; d++) {
    const on = sel.y === view.y && sel.mo === view.mo && sel.d === d;
    grid += `<button type="button" class="dp-day${on ? ' sel' : ''}" data-d="${d}">${d}</button>`;
  }
  return grid;
}

function _commit(el) {
  el.dataset.value = _isTime(el) ? `${_z(_open.sel.h)}:${_z(_open.sel.mi)}` : _fmt(_open.sel, _dateOnly(el));
  _trigger(el);
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

function _reposition() { if (_open) _position(_open.el, _open.panel); }
function _position(el, panel) {
  const r = el.getBoundingClientRect();
  const viewport = window.visualViewport;
  const left = viewport?.offsetLeft || 0, topEdge = viewport?.offsetTop || 0;
  const width = viewport?.width || window.innerWidth, height = viewport?.height || window.innerHeight;
  const compact = width < 350;
  const margin = compact ? 2 : 8;
  panel.classList.toggle('dp-compact', compact);
  panel.style.maxHeight = `${Math.max(44, height - margin * 2)}px`;
  panel.style.maxWidth = `${Math.max(44, width - margin * 2)}px`;
  const h = panel.offsetHeight, w = panel.offsetWidth;
  const below = r.bottom + 4;
  const top = below + h <= topEdge + height - margin ? below : r.top - h - 4;
  panel.style.top = `${Math.max(topEdge + margin, Math.min(top, topEdge + height - h - margin))}px`;
  panel.style.left = `${Math.max(left + margin, Math.min(r.left, left + width - w - margin))}px`;
}
function _outside(e) {
  if (!_open) return;
  if (_open.el.contains(e.target) || _open.panel.contains(e.target)) return;
  _close(false);
}
function _close(restoreFocus = true) {
  if (!_open) return;
  const el = _open.el;
  _open.panel.remove();
  el.setAttribute('aria-expanded', 'false');
  _open = null;
  if (restoreFocus && el.isConnected) el.focus({ preventScroll: true });
  window.removeEventListener('resize', _reposition);
  window.visualViewport?.removeEventListener('resize', _reposition);
  document.removeEventListener('click', _outside);
}
