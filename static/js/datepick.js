// custom date / datetime picker — replaces native <input type=datetime-local|date>.
// a .date-input div carries data-type="date|datetime" and data-value; .value
// reads/writes the same strings the backend expects (YYYY-MM-DD / YYYY-MM-DDTHH:MM).
import {
  formatCalendarDate,
  formatDate,
  formatDateForLocale,
  formatDateParts,
  resolvedTimeZone,
  formatTime,
  localizationState,
} from './i18n.js';

let _open = null;

export function initDatePickers(root = document) {
  root.querySelectorAll('.date-input').forEach(initDatePicker);
}

export function initDatePicker(el) {
  if (!el || el.dataset.dpReady === '1') return;
  el.dataset.dpReady = '1';
  el.tabIndex = 0;
  el.setAttribute('role', 'button');
  el.setAttribute('aria-haspopup', 'dialog');
  el.setAttribute('aria-expanded', 'false');
  if (!el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby')) el.setAttribute('aria-label', el.dataset.ph || 'pick a date');
  Object.defineProperty(el, 'value', {
    configurable: true,
    get() { return el.dataset.value || ''; },
    set(v) { el.dataset.value = v || ''; _trigger(el); if (_open?.el === el) _render(el); },
  });
  _trigger(el);
  el.addEventListener('click', e => { e.stopPropagation(); _toggle(el); });
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _toggle(el); }
    else if (e.key === 'Escape') _close();
  });
}


const _isDate = el => el.dataset.type === 'date';
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
function _trigger(el) {
  const v = el.dataset.value;
  el.innerHTML = `<span class="date-input-label${v ? '' : ' ph'}">${v ? _display(v, _isDate(el)) : (el.dataset.ph || 'pick a date')}</span>` +
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>`;
}

function _toggle(el) { if (el.getAttribute('aria-disabled') === 'true') return; if (_open?.el === el) _close(); else _openPanel(el); }

function _openPanel(el) {
  _close(false);
  const panel = document.createElement('div');
  panel.className = 'date-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', el.getAttribute('aria-label') || 'choose date');
  el.setAttribute('aria-expanded', 'true');
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); _close(); return; }
    if (event.key !== 'Tab') return;
    const items = [...panel.querySelectorAll('button')];
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  document.body.appendChild(panel);
  const cur = _parse(el);
  _open = { el, panel, view: { y: cur.y, mo: cur.mo }, sel: cur };
  _render(el);
  (panel.querySelector('.dp-day.sel') || panel.querySelector('.dp-day')).focus();
  window.addEventListener('resize', _reposition);
  window.visualViewport?.addEventListener('resize', _reposition);
  setTimeout(() => document.addEventListener('click', _outside), 0);
}

function _render(el) {
  const { panel, view, sel } = _open;
  const active = panel.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = active?.dataset.d ? `[data-d="${active.dataset.d}"]` : active?.dataset.step ? `[data-step="${active.dataset.step}"]` : active?.dataset.nav ? `[data-nav="${active.dataset.nav}"]` : null;
  const isDate = _isDate(el);
  const monthName = formatCalendarDate(
    `${view.y}-${_z(view.mo + 1)}-01`,
    { month: 'long', year: 'numeric' },
  );
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
  const time = isDate ? '' : `
    <div class="dp-time">
      <button type="button" class="dp-step" data-step="h-1" aria-label="previous hour">‹</button><span class="dp-tv">${_z(sel.h)}</span><button type="button" class="dp-step" data-step="h1" aria-label="next hour">›</button>
      <span class="dp-colon">:</span>
      <button type="button" class="dp-step" data-step="mi-1" aria-label="previous minute">‹</button><span class="dp-tv">${_z(sel.mi)}</span><button type="button" class="dp-step" data-step="mi1" aria-label="next minute">›</button>
    </div>`;
  panel.innerHTML = `
    <div class="dp-head"><button type="button" class="dp-nav" data-nav="-1" aria-label="previous month">‹</button><span>${monthName}</span><button type="button" class="dp-nav" data-nav="1" aria-label="next month">›</button></div>
    <div class="dp-grid">${grid}</div>${time}
    <div class="dp-foot"><button type="button" class="dp-clear">clear</button><button type="button" class="dp-now">now</button></div>`;

  panel.querySelectorAll('.dp-nav').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    view.mo += +b.dataset.nav;
    if (view.mo < 0) { view.mo = 11; view.y--; }
    if (view.mo > 11) { view.mo = 0; view.y++; }
    _render(el);
  }));
  panel.querySelectorAll('.dp-day').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    sel.y = view.y; sel.mo = view.mo; sel.d = +b.dataset.d;
    _commit(el);
    if (isDate) _close(); else _render(el);
  }));
  panel.querySelectorAll('.dp-step').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    const s = b.dataset.step;
    if (s.startsWith('h')) sel.h = (sel.h + (s === 'h1' ? 1 : 23)) % 24;
    else sel.mi = (sel.mi + (s === 'mi1' ? 1 : 59)) % 60;
    _commit(el); _render(el);
  }));
  panel.querySelector('.dp-clear').addEventListener('click', e => { e.stopPropagation(); el.value = ''; _close(); });
  panel.querySelector('.dp-now').addEventListener('click', e => {
    e.stopPropagation();
    Object.assign(sel, _currentParts());
    view.y = sel.y; view.mo = sel.mo;
    _commit(el);
    if (isDate) _close(); else _render(el);
  });

  _position(el, panel);
  if (focusKey) panel.querySelector(focusKey)?.focus({ preventScroll: true });
}

function _commit(el) {
  el.dataset.value = _fmt(_open.sel, _isDate(el));
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
