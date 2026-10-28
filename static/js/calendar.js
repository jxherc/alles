import { plainError, toast, writeClipboard } from './util.js';
import { replaceLinkedRecord } from './recordlinks.js';
import { initCustomDropdown } from './dropdown.js?v=215';
import { initDatePickers } from './datepick.js';
import { prompt as dlgPrompt, confirm as dlgConfirm, choose as dlgChoose } from './dialog.js';
import { initKokuenPrimitives, wireActionMenu } from './kokuen.js?v=4';
import { openAppSettings } from './appsettings.js';
import { wireGridNav, WEEK_ROWS } from './grid_nav.js';
import { chosenTimeZone, formatDate, formatDateParts, formatTime, localizationState, resolvedTimeZone, t as tr, tp as trp } from './i18n.js';
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe

const _browserTimeZone = () => {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; }
  catch { return 'UTC'; }
};

function _instantAsCalendarWallDate(value, zone = resolvedTimeZone()) {
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return instant;
  const parts = formatDateParts(instant, {
    calendar: 'gregory',
    numberingSystem: 'latn',
    timeZone: zone,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hourCycle: 'h23',
  });
  const fields = Object.fromEntries(parts.map(part => [part.type, Number(part.value)]));
  return new CalendarWallDate(Date.UTC(
    fields.year,
    fields.month - 1,
    fields.day,
    fields.hour,
    fields.minute,
    fields.second,
    instant.getUTCMilliseconds(),
  ));
}

class CalendarWallDate extends Date {
  getFullYear() { return super.getUTCFullYear(); }
  getMonth() { return super.getUTCMonth(); }
  getDate() { return super.getUTCDate(); }
  getDay() { return super.getUTCDay(); }
  getHours() { return super.getUTCHours(); }
  getMinutes() { return super.getUTCMinutes(); }
  getSeconds() { return super.getUTCSeconds(); }
  getMilliseconds() { return super.getUTCMilliseconds(); }
  setFullYear(...args) { return super.setUTCFullYear(...args); }
  setMonth(...args) { return super.setUTCMonth(...args); }
  setDate(...args) { return super.setUTCDate(...args); }
  setHours(...args) { return super.setUTCHours(...args); }
  setMinutes(...args) { return super.setUTCMinutes(...args); }
  setSeconds(...args) { return super.setUTCSeconds(...args); }
  setMilliseconds(...args) { return super.setUTCMilliseconds(...args); }
}

const _calendarWallDate = (year, month, day, hour = 0, minute = 0, second = 0, millis = 0) =>
  new CalendarWallDate(Date.UTC(year, month, day, hour, minute, second, millis));
const _cloneCalendarDate = value => value instanceof CalendarWallDate
  ? new CalendarWallDate(value.getTime())
  : new Date(value);

export function calendarPlacementDate(value) {
  const text = typeof value === 'string' ? value.trim() : '';
  const naive = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?$/.exec(text);
  if (naive) {
    const [, year, month, day, hour = '0', minute = '0', second = '0', millis = '0'] = naive;
    return _calendarWallDate(
      Number(year), Number(month) - 1, Number(day),
      Number(hour), Number(minute), Number(second), Number(millis.slice(0, 3).padEnd(3, '0')),
    );
  }
  return _instantAsCalendarWallDate(value);
}

const _calendarNow = () => _instantAsCalendarWallDate(new Date());

let _events = [];
let _tasks = [];  // tasks with due dates, overlaid on the month/agenda
let _birthdays = [];  // contact birthdays, overlaid as annual all-day items
let _calendars = [];
let _calendarMetadataError = '';
let _preserveEditorOnRetry = false;
let _editing = null;
let _saving = false;
let _editDates = null;
let _readDraft = null;
let _draftSnapshot = '';
let _loadSequence = 0;
let _editOcc = null;             // occurrence date when editing a recurring instance
let _cursor = _calendarNow();
let _view = localStorage.getItem('cal-view') || 'month';
let _viewBooted = false;          // has loadCalendar seeded the view once this session
let _lastDefaultView = null;      // last cal_default_view we applied (detects a cog change)
let _search = '';
let _searchTimer = null;
let _miniCursor = _calendarNow();    // month shown in the mini-navigator
let _navBound = false;
let _prefill = null;             // {start,end} for a drag-created event

let _weekStart = 0;   // 0 = sunday, 1 = monday (per-app setting)
let _workStart = 9, _workEnd = 18;   // 8a working-hours shading (week/day grid)
let _secondaryTz = '';               // 8a secondary timezone (IANA name) for a world clock
let _subs = [];                      // 8a ICS-URL subscriptions
const formatCalendarDate = (date, options = {}) => {
  const neutral = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate(), 12));
  return formatDate(neutral, { ...options, timeZone: 'UTC' });
};
const _weekdayLabels = (width = 'short') => {
  const sunday = new Date(2026, 6, 19, 12);
  const labels = Array.from({ length: 7 }, (_, index) => {
    const day = new Date(sunday);
    day.setDate(sunday.getDate() + index);
    return formatCalendarDate(day, { weekday: width });
  });
  return [...labels.slice(_weekStart), ...labels.slice(0, _weekStart)];
};
// leading blanks before the 1st, honoring week-start
const _lead = (y, m) => (new Date(y, m, 1).getDay() - _weekStart + 7) % 7;
const HOUR_H = 44;
export const CAL_SEARCH_DEBOUNCE_MS = 180;
const _pad = n => String(n).padStart(2, '0');
const ymd = d => `${d.getFullYear()}-${_pad(d.getMonth() + 1)}-${_pad(d.getDate())}`;
const localISO = d => `${ymd(d)}T${_pad(d.getHours())}:${_pad(d.getMinutes())}`;
const timeShort = dt => formatTime(dt, {
  hour: 'numeric', minute: '2-digit',
  timeZone: dt instanceof CalendarWallDate ? 'UTC' : _browserTimeZone(),
});
const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

// Editor dates are wall-clock values; untouched values retain their original precision/offset.
function occurrenceDates(event, occ) {
  // a kept offset: the occurrence at its own moment, the same one the grid shows on that day
  if (event.recurrence && !event.all_day && keptFrame(event.start_dt, event.source_zone)) {
    const day = calendarPlacementDate(String(occ).slice(0, 10));
    const next = _cloneCalendarDate(day); next.setDate(next.getDate() + 1);
    const hit = expand(day, next, [{ ...event, recur_except: [] }])[0];
    if (hit) {
      const length = event.end_dt ? new Date(event.end_dt).getTime() - new Date(event.start_dt).getTime() : null;
      return { start_dt: new Date(hit._at).toISOString(), end_dt: length == null ? null : new Date(hit._at + length).toISOString() };
    }
  }
  const start = calendarPlacementDate(event.start_dt);
  const delta = calendarPlacementDate(occ).getTime() - calendarPlacementDate(ymd(start)).getTime();
  if (!delta) return { start_dt: event.start_dt, end_dt: event.end_dt || null };
  const aware = /(?:Z|[+-]\d{2}:?\d{2})$/.test(event.start_dt);
  const result = {};
  for (const key of ['start_dt', 'end_dt']) {
    const original = event[key];
    if (!original) { result[key] = null; continue; }
    if (key === 'end_dt' && aware && !event.all_day) continue;
    const wall = new CalendarWallDate(calendarPlacementDate(original).getTime() + delta);
    result[key] = aware
      ? wallTimeForStorage(`${localISO(wall)}:${_pad(wall.getSeconds())}.${String(wall.getMilliseconds()).padStart(3, '0')}`, original)
      : original.replace(/^\d{4}-\d{2}-\d{2}/, ymd(wall));
  }
  if (aware && event.end_dt && !event.all_day) {
    const duration = new Date(event.end_dt).getTime() - new Date(event.start_dt).getTime();
    result.end_dt = new Date(new Date(result.start_dt).getTime() + duration).toISOString();
  }
  return result;
}

export function editorDates(event, occ = null) {
  if (!event?.start_dt) return { start: '', end: '' };
  let values = event;
  if (event.recurrence && occ) {
    try { values = occurrenceDates(event, occ); }
    catch {
      // Keep a DST-gap occurrence editable; saving it asks for a valid time.
      const start = calendarPlacementDate(event.start_dt);
      const delta = calendarPlacementDate(occ).getTime() - calendarPlacementDate(ymd(start)).getTime();
      return {
        start: localISO(new CalendarWallDate(start.getTime() + delta)),
        end: event.end_dt ? localISO(new CalendarWallDate(calendarPlacementDate(event.end_dt).getTime() + delta)) : '',
      };
    }
  }
  return { start: localISO(calendarPlacementDate(values.start_dt)), end: values.end_dt ? localISO(calendarPlacementDate(values.end_dt)) : '' };
}

export function wallTimeForStorage(value, original) {
  if (!value) return null;
  if (!original || !/(?:Z|[+-]\d{2}:?\d{2})$/.test(original)) return value;
  const wall = calendarPlacementDate(value).getTime();
  const offsets = new Set();
  for (let hours = -36; hours <= 36; hours += 6) {
    const instant = wall + hours * 3600000;
    offsets.add(_instantAsCalendarWallDate(new Date(instant)).getTime() - instant);
  }
  const matches = [...offsets].map(offset => wall - offset)
    .filter(instant => _instantAsCalendarWallDate(new Date(instant)).getTime() === wall)
    .sort((a, b) => a - b);
  if (!matches.length) throw new Error(tr('calendar.time_not_in_zone'));
  const previous = new Date(original).getTime();
  const previousOffset = _instantAsCalendarWallDate(new Date(previous)).getTime() - previous;
  return new Date(matches.find(instant => wall - instant === previousOffset) ?? matches[0]).toISOString();
}

// plan stores wall time; a zoned value becomes the wall time it shows as here
export function storedWallTime(value) {
  if (typeof value !== 'string' || !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) return value;
  const wall = calendarPlacementDate(value);
  if (Number.isNaN(wall.getTime())) return value;
  const ms = wall.getMilliseconds();
  return `${localISO(wall)}:${_pad(wall.getSeconds())}${ms ? '.' + String(ms).padStart(3, '0') : ''}`;
}

export function eventTimeValues(event, initial, values, scope = 'all') {
  if (!event) return { start_dt: values.start, end_dt: values.end || null };
  const result = {};
  for (const [key, name] of [['start_dt', 'start'], ['end_dt', 'end']]) {
    const original = event[key];
    if (scope === 'all' && values[name] === initial[name]) {
      result[key] = original || null;
      continue;
    }
    if (scope !== 'all' && values[name] === initial[name]) {
      result[key] = occurrenceDates(event, initial.start.slice(0, 10))[key];
      continue;
    }
    let value = values[name];
    if (scope === 'all' && event.recurrence && original && value && initial[name]) {
      const delta = calendarPlacementDate(value).getTime() - calendarPlacementDate(initial[name]).getTime();
      value = localISO(new CalendarWallDate(calendarPlacementDate(original).getTime() + delta));
    }
    result[key] = wallTimeForStorage(value, original || event.start_dt);
  }
  return result;
}

async function readCalendarResponse(response) {
  let data;
  try { data = await response.json(); } catch { throw Object.assign(new Error(tr('calendar.unreadable_reply')), { status: response.status }); }
  if (!response.ok) throw Object.assign(new Error(typeof data?.detail === 'string' ? data.detail : tr('calendar.request_failed')), { status: response.status });
  return data;
}
// every calendar request says the browser's zone: the server reads an offset a row kept in
// the same zone this page does, and remembers it for reminders. nothing when the browser won't say
const zoneHeader = () => { const zone = chosenTimeZone(); return zone ? { 'x-alles-time-zone': zone } : {}; };
const withZone = (init = {}) => ({ ...init, headers: { ...(init.headers || {}), ...zoneHeader() } });
// the server keeps wall time, so a zoned value comes back naive at the same moment
function sameStoredTime(saved, sent) {
  return saved === sent || (typeof saved === 'string' && typeof sent === 'string' && saved.length > 10
    && calendarPlacementDate(saved).getTime() === calendarPlacementDate(sent).getTime());
}
async function saveCalendarRequest(url, method, body, expectedId = null) {
  const data = await readCalendarResponse(await fetch(url, {
    method, headers: { 'content-type': 'application/json', ...zoneHeader() }, body: JSON.stringify(body),
  }));
  if (!data || typeof data.id !== 'string' || !data.id || data.title !== body.title
      || !sameStoredTime(data.start_dt, body.start_dt) || !Object.prototype.hasOwnProperty.call(data, 'end_dt')
      || (body.end_dt && !sameStoredTime(data.end_dt, body.end_dt)) || data.description !== body.description
      || (expectedId && data.id !== expectedId)) {
    throw new Error(tr('calendar.save_unconfirmed'));
  }
  return data;
}
function editorError(message) {
  const el = document.getElementById('cal-save-error');
  message = plainError(message);
  if (el) { el.textContent = message; el.hidden = false; el.scrollIntoView({ block: 'nearest' }); }
  else toast(message, 'error');
}
function editorBusy(busy) {
  const editor = document.querySelector('.cal-editor');
  if (editor) { editor.inert = busy; editor.setAttribute('aria-busy', String(busy)); }
  const save = document.getElementById('cal-save');
  if (save) { save.disabled = busy; save.textContent = busy ? tr('common.saving') : (_editing ? tr('common.save') : tr('common.create')); }
}
// the editor is replaced by the grid, so focus goes to the event's chip (or agenda row), else
// the day's "+N more", else "+ event"; never the page body
function focusAfterEditor(id = '', day = '') {
  // the grid loads after the editor closes: someone who already moved on (a tab, a menu) keeps
  // the focus they chose
  const held = document.activeElement;
  if (held && held !== document.body && held !== document.documentElement && held.isConnected) return;
  const list = document.getElementById('calendar-list');
  const shown = node => node?.isConnected && node.getClientRects().length ? node : null;
  const own = id ? `:is(button.cal-chip, button.cal-allday-ev, .cal-tev, button.cal-agenda-ev)[data-id="${CSS.escape(id)}"]` : '';
  const target = (own && (shown(list?.querySelector(`${own}[data-occ="${CSS.escape(day)}"]`)) || shown(list?.querySelector(own))))
    || (day && shown(list?.querySelector(`.cal-more[data-day="${CSS.escape(day)}"]`)))
    || shown(document.getElementById('cal-new-btn'));
  target?.focus();
}
// Escape leaves the editor like back. an open picker, menu or dialog takes its own Escape first:
// it stops the key or marks it handled
function escapeLeaves(e) {
  if (e.key !== 'Escape' || e.defaultPrevented || e.isComposing) return;
  e.preventDefault();
  leaveEditor();
}
// safari leaves focus on the page after a click on a button or on blank space, where the
// editor's own listener never hears the key, so the page listens while the editor is open
let _pageEscape = null;
function watchPageEscape(editor) {
  if (_pageEscape) document.removeEventListener('keydown', _pageEscape);
  _pageEscape = e => {
    if (!editor?.isConnected) { document.removeEventListener('keydown', _pageEscape); _pageEscape = null; return; }
    // a click on the discard question's text drops focus to the page too: that Escape is the
    // question's, not a second request to leave
    if (document.querySelector('.dialog-overlay')) return;
    if (e.target === document.body || e.target === document.documentElement) escapeLeaves(e);
  };
  document.addEventListener('keydown', _pageEscape);
}

let _leaving = false;
async function leaveEditor() {
  if (_saving || _leaving) return;
  _leaving = true;   // one question at a time, however many escapes or clicks arrive meanwhile
  try {
    if (_readDraft && _readDraft() !== _draftSnapshot && !(await dlgConfirm(tr('calendar.discard_changes')))) {
      // kept: the question handed focus back to the page it came from, so put it in the editor
      if (document.activeElement === document.body) focusEditor(Boolean(_editing));
      return;
    }
    const id = _editing?.id || '', day = (_editOcc || _editing?.start_dt || '').slice(0, 10);
    if (await loadCalendar()) focusAfterEditor(id, day);
  } finally { _leaving = false; }
}
function calendarLoadError(message) {
  const host = document.getElementById('calendar-list');
  if (!host) return;
  document.getElementById('cal-load-error')?.remove();
  const notice = document.createElement('div');
  notice.id = 'cal-load-error'; notice.className = 'cal-load-error'; notice.setAttribute('role', 'alert');
  const text = document.createElement('span'); text.textContent = tr('calendar.load_failed', { reason: plainError(message) });
  const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn'; retry.textContent = tr('common.retry');
  retry.addEventListener('click', retryCalendarView);
  notice.append(text, retry); host.prepend(notice);
}

async function retryCalendarView() {
  _preserveEditorOnRetry = Boolean(document.querySelector('.cal-editor'));
  try { return await (typeof window._navigateTo === 'function' ? window._navigateTo('calendar', { preserveRecord: true }) : loadCalendar()); }
  finally { _preserveEditorOnRetry = false; }
}

function refreshCalendarPicker() {
  const picker = document.getElementById('cal-calendar');
  if (!picker) return;
  const value = _calendarMetadataError && _editing ? (_editing.calendar_id || '') : picker.value;
  picker.dataset.options = _calendars.map(c => `${c.id}|${c.name}`).join(';');
  picker.dataset.placeholder = _calendarMetadataError ? tr('calendar.calendar_unavailable') : tr('calendar.select');
  picker.disabled = Boolean(_calendarMetadataError);
  picker.value = value;
}

function calendarMetadataNotice() {
  document.getElementById('cal-metadata-error')?.remove();
  const layout = document.getElementById('calendar-list')?.parentElement;
  if (!layout || !_calendarMetadataError) return;
  const notice = document.createElement('div');
  notice.id = 'cal-metadata-error'; notice.className = 'cal-load-error'; notice.setAttribute('role', 'alert');
  const text = document.createElement('span');
  text.textContent = tr('calendar.names_failed', { reason: plainError(_calendarMetadataError) });
  const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn'; retry.textContent = tr('common.retry');
  retry.addEventListener('click', retryCalendarView);
  notice.append(text, retry); layout.before(notice);
}

const SUNDAY_FIRST_REGIONS = new Set(['AG', 'AS', 'BD', 'BR', 'BS', 'BT', 'BW', 'BZ', 'CA', 'CN', 'CO', 'DM', 'DO', 'ET', 'GT', 'GU', 'HK', 'HN', 'ID', 'IL', 'IN', 'JM', 'JP', 'KE', 'KH', 'KR', 'LA', 'MH', 'MM', 'MO', 'MT', 'MX', 'MZ', 'NI', 'NP', 'PA', 'PE', 'PH', 'PK', 'PR', 'PT', 'PY', 'SA', 'SG', 'SV', 'TH', 'TT', 'TW', 'UM', 'US', 'VE', 'VI', 'WS', 'YE', 'ZA', 'ZW']);

export function resolveCalendarWeekStart(settings = {}) {
  const hasUniversal = Object.prototype.hasOwnProperty.call(settings, 'week_start')
    || Object.prototype.hasOwnProperty.call(settings, 'weekStart');
  const universal = hasUniversal ? (settings.week_start || settings.weekStart || 'auto') : '';
  if (universal === 'mon') return 1;
  if (universal === 'sun') return 0;
  if (!hasUniversal && settings.cal_week_start === 'mon') return 1;
  if (!hasUniversal && settings.cal_week_start === 'sun') return 0;
  const state = localizationState();
  const region = String(settings.region || settings.effectiveRegion || state.effectiveRegion || '').toUpperCase();
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

// google-ish categorical palette (event colours are categorisation here, not status). the default
// "accent" calendar draws in the first data hue, blue like google's default; purple means ai now
const PALETTE = {
  accent: 'var(--cat-blue)', tomato: '#f87171', flamingo: '#fb9a8f', tangerine: '#fb923c',
  banana: '#fbbf24', sage: '#5ec88a', basil: '#2dba6e', peacock: '#39b3e5',
  blueberry: '#5b8def', lavender: '#8b9cf8', grape: '#c08cf8', graphite: '#94a3b8',
  // back-compat with the old class names
  green: '#5ec88a', warn: '#fbbf24', error: '#f87171', red: '#f87171', blue: '#5b8def',
};
const COLOR_NAMES = ['accent', 'tomato', 'tangerine', 'banana', 'sage', 'basil', 'peacock', 'blueberry', 'lavender', 'grape', 'graphite'];
const colorLabel = name => ({
  accent: tr('calendar.color_accent'), tomato: tr('calendar.color_tomato'), tangerine: tr('calendar.color_tangerine'),
  banana: tr('calendar.color_banana'), sage: tr('calendar.color_sage'), basil: tr('calendar.color_basil'),
  peacock: tr('calendar.color_peacock'), blueberry: tr('calendar.color_blueberry'), lavender: tr('calendar.color_lavender'),
  grape: tr('calendar.color_grape'), graphite: tr('calendar.color_graphite'),
})[name] || name;
const calById = id => _calendars.find(c => c.id === id);
// a custom colour must be a real hex: it lands inside style="…", where anything after a quote
// would be markup (an event colour can come from aide, steered by a mail or a page)
const hexOf = name => PALETTE[name] || (/^#[0-9a-f]{3,8}$/i.test(String(name || '')) ? name : PALETTE.accent);
const evColorName = e => e.color || calById(e.calendar_id)?.color || 'accent';
const evHex = e => hexOf(evColorName(e));

let _clockTimer = null;
function _tickWorldClock() {
  if (_clockTimer) return;  // one interval, updates whatever clock is in the DOM
  _clockTimer = setInterval(() => {
    const el = document.querySelector('#cal-worldclock .cal-wc-time');
    if (!el || !_secondaryTz) return;
    try { el.textContent = formatTime(new Date(), { hour: 'numeric', minute: '2-digit', timeZone: _secondaryTz }); } catch {}
  }, 60000);
}

let _eventsReady = false;

export async function loadCalendar(fetcher = fetch, canReplaceEditor = () => true) {
  _eventsReady = false;
  _bindNav();
  _tickWorldClock();
  const sequence = ++_loadSequence;
  const preserveEditor = _preserveEditorOnRetry && Boolean(document.querySelector('.cal-editor'));
  try {
  const requiredList = async (url, init) => { const data = await readCalendarResponse(await (init ? fetcher(url, init) : fetcher(url))); if (!Array.isArray(data)) throw new Error(tr('calendar.unreadable_reply')); return data; };
  const [cals, evs, s, tasks, subs, bdays] = await Promise.all([
    requiredList('/api/calendars').then(items => ({ items, error: '' })).catch(error => ({ error: error.message || tr('calendar.check_connection') })),
    // the browser's zone: the server reads kept offsets in it and remembers it for reminders
    requiredList('/api/calendar', { headers: zoneHeader() }),
    fetcher('/api/settings').then(r => r.json()).catch(() => ({})),
    fetcher('/api/calendar/tasks', withZone()).then(r => r.json()).catch(() => []),
    fetcher('/api/calendar/subscriptions', withZone()).then(r => r.json()).catch(() => []),
    fetcher('/api/calendar/birthdays', withZone()).then(r => r.json()).catch(() => []),
  ]);
  if (sequence !== _loadSequence) return false;
  _tasks = Array.isArray(tasks) ? tasks : [];
  _subs = Array.isArray(subs) ? subs : [];
  _birthdays = Array.isArray(bdays) ? bdays : [];
  _weekStart = resolveCalendarWeekStart(s);
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
  if (cals.items) _calendars = cals.items;
  _calendarMetadataError = cals.error;
  _events = Array.isArray(evs) ? evs : [];
  _eventsReady = true;
  renderSidebar();
  if (preserveEditor || !canReplaceEditor()) refreshCalendarPicker();
  // the agenda draws after a fetch: wait for it, so focus can go back to the row that was open
  else { _editing = null; _readDraft = null; await render(); }
  calendarMetadataNotice();
  return true;
  } catch (error) {
    if (sequence === _loadSequence) calendarLoadError(error.message || tr('calendar.check_connection'));
    return false;
  }
}

function _bindNav() {
  if (_navBound) return;
  _navBound = true;
  document.getElementById('cal-prev')?.addEventListener('click', () => shift(-1));
  document.getElementById('cal-next')?.addEventListener('click', () => shift(1));
  document.getElementById('cal-today')?.addEventListener('click', () => { _cursor = _calendarNow(); _miniCursor = _calendarNow(); render(); renderMini(); });
  document.querySelectorAll('#cal-view .seg-opt').forEach(b =>
    b.addEventListener('click', () => { _view = b.dataset.view; localStorage.setItem('cal-view', _view); _syncViewBtns(); render(); }));
  _syncViewBtns();
  const tools = document.getElementById('cal-tools');
  const toolsToggle = document.getElementById('cal-tools-toggle');
  const setToolsOpen = open => {
    if (tools) tools.dataset.open = String(open);
    toolsToggle?.setAttribute('aria-expanded', String(open));
  };
  toolsToggle?.addEventListener('click', () => {
    setToolsOpen(toolsToggle.getAttribute('aria-expanded') !== 'true');
  });
  tools?.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || toolsToggle?.getAttribute('aria-expanded') !== 'true') return;
    event.preventDefault();
    event.stopPropagation();
    setToolsOpen(false);
    toolsToggle.focus();
  });
  // the month cap depends on the width, so a rotate or resize across it redraws the grid
  window.matchMedia?.(MONTH_NARROW).addEventListener?.('change', () => {
    if (_view === 'month' && document.querySelector('#calendar-list > .cal-grid')) render();
  });
  const compactToolbar = window.matchMedia?.('(max-width: 760px)');
  compactToolbar?.addEventListener('change', () => {
    if (compactToolbar.matches && tools?.contains(document.activeElement)) setToolsOpen(true);
    else if (!compactToolbar.matches && document.activeElement === toolsToggle) document.getElementById('cal-new-btn')?.focus();
  });
  wireActionMenu(document.getElementById('cal-more-btn'), document.getElementById('cal-more-menu'));
  document.getElementById('cal-settings-btn')?.addEventListener('click', event => {
    event.stopPropagation();
    openAppSettings('calendar', document.getElementById('cal-more-btn'));
  });
  document.getElementById('cal-sync-btn')?.addEventListener('click', openCaldavPanel);
  document.getElementById('cal-find')?.addEventListener('click', findTime);
  window.addEventListener('alles:localization-change', event => {
    _weekStart = resolveCalendarWeekStart(event.detail || {});
    renderSidebar();
    render();
  });

  const quick = document.getElementById('cal-quick');
  const quickFeedback = document.getElementById('cal-quick-feedback');
  const quickStatus = document.getElementById('cal-quick-status');
  const quickUndo = document.getElementById('cal-quick-undo');
  let quickBusy = false;
  let quickEvent = null;
  const quickMessage = message => {
    quickFeedback.hidden = false;
    quickStatus.textContent = message;
    quickUndo.hidden = !quickEvent;
    clearTimeout(quickMessage.timer);
    // on wide screens it floats, so it can go like home's receipt; not while it's busy,
    // focused or under the pointer. on a phone it sits in the page and hiding it would
    // pull everything up under the finger
    if (!window.matchMedia?.('(min-width: 761px)').matches) return;
    quickMessage.timer = setTimeout(function hide() {
      if (quickBusy || quickFeedback.contains(document.activeElement) || quickFeedback.matches(':hover')) {
        quickMessage.timer = setTimeout(hide, 4000);
        return;
      }
      quickFeedback.hidden = true;
    }, 8000);
  };
  const setQuickBusy = busy => {
    quickBusy = busy;
    quick.readOnly = busy;
    quick.setAttribute('aria-busy', String(busy));
    quickUndo.setAttribute('aria-disabled', String(busy));
    quickUndo.setAttribute('aria-busy', String(busy));
  };
  const canReplaceDraft = async () => !_readDraft || _readDraft() === _draftSnapshot
    || await dlgConfirm(tr('calendar.discard_changes'));
  quick?.addEventListener('keydown', async e => {
    if (e.key !== 'Enter' || e.isComposing || quickBusy || _saving) return;
    e.preventDefault();
    const text = quick.value.trim();
    if (!text) return;
    setQuickBusy(true);
    try {
      if (!(await canReplaceDraft())) return;
      const draftReader = _readDraft, draftValue = draftReader?.();
      const sameEditor = () => _readDraft === draftReader && (!draftReader || draftReader() === draftValue);
      quickEvent = null;
      quickMessage(tr('common.saving'));
      const r = await fetch('/api/calendar/quick', { method: 'POST', headers: { 'content-type': 'application/json', ...zoneHeader() }, body: JSON.stringify({ text }) });
      const ev = await readCalendarResponse(r);
      if (typeof ev?.id !== 'string' || !ev.id || typeof ev.title !== 'string' || !ev.start_dt) throw new Error();
      quickEvent = ev;
      quick.value = '';
      quickMessage(tr(r.headers?.get?.('x-alles-no-date') === '1' ? 'calendar.added_today' : 'calendar.added', { title: ev.title }));
      _cursor = calendarPlacementDate(ev.start_dt); _cursor.setHours(0, 0, 0, 0);
      await loadCalendar(fetch, sameEditor);
    } catch (error) {
      // a 400 is the server saying why ("feb 30 isn't a date"); the text stays to fix
      quickMessage(error?.status === 400 ? plainError(error.message) : tr('calendar.quick_unconfirmed'));
    } finally { setQuickBusy(false); }
  });
  quickUndo?.addEventListener('click', async () => {
    if (quickBusy || _saving || !quickEvent) return;
    const event = quickEvent;
    setQuickBusy(true);
    try {
      if (!(await canReplaceDraft())) return;
      const draftReader = _readDraft, draftValue = draftReader?.();
      const sameEditor = () => _readDraft === draftReader && (!draftReader || draftReader() === draftValue);
      const response = await fetch(`/api/calendar/${encodeURIComponent(event.id)}`, {
        method: 'DELETE', headers: { 'content-type': 'application/json', ...zoneHeader() }, body: JSON.stringify(event),
      });
      // A retry after a lost acknowledgment may find the exact event already gone.
      if (response.status !== 404 && (await readCalendarResponse(response))?.ok !== true) throw new Error();
      quickEvent = null;
      if (document.activeElement === quickUndo) quick.focus();
      quickMessage(tr('calendar.quick_undone', { title: event.title }));
      await loadCalendar(fetch, sameEditor);
    } catch { quickMessage(tr('calendar.quick_undo_failed', { title: event.title })); }
    finally { setQuickBusy(false); }
  });

  const imp = document.getElementById('cal-import');
  if (imp && !imp.dataset.bound) {
    imp.dataset.bound = '1';
    const fileInp = document.getElementById('cal-import-file');
    const feedback = document.createElement('div');
    feedback.id = 'cal-import-feedback'; feedback.className = 'cal-quick-feedback'; feedback.hidden = true;
    const status = document.createElement('span');
    status.id = 'cal-import-status'; status.setAttribute('role', 'alert');
    const retry = document.createElement('button');
    retry.id = 'cal-import-retry'; retry.type = 'button'; retry.className = 'btn'; retry.textContent = tr('calendar.retry_import');
    const choose = document.createElement('button');
    choose.id = 'cal-import-choose'; choose.type = 'button'; choose.className = 'btn'; choose.textContent = tr('calendar.choose_another_file');
    feedback.append(status, retry, choose);
    document.getElementById('cal-quick-feedback')?.after(feedback);
    let importing = false, retainedFile = null;
    const chooseFile = () => { if (!importing && fileInp) { fileInp.value = ''; fileInp.click(); } };
    const importSelected = async f => {
      if (!f || importing) return;
      retainedFile = f;
      // import sits in the "more" menu, which hands focus back to its button before the picker opens
      const more = document.getElementById('cal-more-btn');
      const origin = [imp, retry, choose, more].includes(document.activeElement) ? document.activeElement : null;
      importing = true; imp.disabled = true; fileInp.disabled = true; retry.disabled = true; choose.disabled = true;
      try {
        const r = await fetch('/api/calendar/import', { method: 'POST', headers: { 'content-type': 'application/json', ...zoneHeader() }, body: JSON.stringify({ ics: await f.text() }) });
        const d = await readCalendarResponse(r);
        if (!Number.isInteger(d?.imported) || d.imported < 0) throw new Error(tr('calendar.import_unconfirmed'));
        if (document.getElementById('cal-import-file') !== fileInp) return;
        if (fileInp.files[0] === f) fileInp.value = '';
        retainedFile = null; feedback.hidden = true;
        // a repeat alles can't show (a monthly "2nd tuesday", extra RDATE days) came in as its first
        // time only; the receipt says so and stays up long enough to read
        const cut = Number.isInteger(d.first_only) && d.first_only > 0 ? importFirstOnly(d.first_only) : '';
        toast(cut ? tr('calendar.imported_with_note', { imported: trp('calendar.imported_count', d.imported), note: cut }) : trp('calendar.imported_count', d.imported), 'success', cut ? 9000 : 3000);
        await loadCalendar(fetch, () => !document.querySelector('.cal-editor'));
      } catch (error) {
        if (document.getElementById('cal-import-file') === fileInp) {
          // a 400 means the file was read and refused; only a lost reply is unknown. a real .ics
          // with one bad event is refused too, so pass the server's reason through
          const name = f.name || tr('calendar.selected_file');
          status.textContent = error?.status !== 400
            ? tr('calendar.import_not_confirmed', { name })
            : /complete \.ics calendar file/i.test(error.message || '')
              ? tr('calendar.import_not_ics', { name })
              : tr('calendar.import_failed_named', { name, reason: plainError(error.message) });
          feedback.hidden = false;
        }
      } finally {
        importing = false; imp.disabled = false; fileInp.disabled = false; retry.disabled = false; choose.disabled = false;
        if (origin && (document.activeElement === origin || document.activeElement === document.body)
            && document.getElementById('cal-import') === imp) (feedback.hidden ? (imp.getClientRects?.().length ? imp : more || imp) : origin).focus();
      }
    };
    imp.addEventListener('click', chooseFile);
    choose.addEventListener('click', chooseFile);
    retry.addEventListener('click', () => importSelected(retainedFile));
    fileInp?.addEventListener('change', () => importSelected(fileInp.files[0]));
  }
}

function _syncViewBtns() {
  document.querySelectorAll('#cal-view .seg-opt').forEach(b => { b.classList.toggle('active', b.dataset.view === _view); b.setAttribute('aria-pressed', String(b.dataset.view === _view)); });
}

function shift(dir) {
  // use addMonths (defined below, hoisted) — it clamps the day to the target month so plain
  // setMonth() can't overflow May 31 -> Jul 1 and silently skip a month from a 29th-31st cursor.
  if (_view === 'month') _cursor = addMonths(_cursor, dir);
  else if (_view === 'week') _cursor.setDate(_cursor.getDate() + 7 * dir);
  else _cursor.setDate(_cursor.getDate() + dir);
  _miniCursor = new Date(_cursor);
  render();
  renderMini();
}

// ── sidebar: search + mini-month + my-calendars ──────────────────────────────
function renderSidebar() {
  const el = document.getElementById('cal-sidebar');
  if (!el) return;
  el.innerHTML = `
    <input type="text" id="cal-search" class="cal-side-search" aria-label="${esc(tr('calendar.search_events'))}" placeholder="${esc(tr('calendar.search_events'))}" value="${esc(_search)}">
    <div class="cal-mini" id="cal-mini"></div>
    ${_clockHtml()}
    <div class="cal-cals">
      <div class="cal-cals-head"><span>${esc(tr('calendar.my_calendars'))}</span><button class="cal-cal-add" id="cal-cal-add" title="${esc(tr('calendar.new_calendar'))}">+</button></div>
      <div id="cal-cals-list"></div>
    </div>
    <div class="cal-cals cal-feeds">
      <div class="cal-cals-head"><span>${esc(tr('calendar.subscriptions'))}</span><button class="cal-cal-add" id="cal-feed-add" title="${esc(tr('calendar.subscribe_ics'))}">+</button></div>
      <div id="cal-feeds-list"></div>
    </div>
    <div class="cal-cals cal-bookings">
      <div class="cal-cals-head"><span>${esc(tr('calendar.booking_pages'))}</span><button class="cal-cal-add" id="cal-book-add" title="${esc(tr('calendar.new_booking_page'))}">+</button></div>
      <div id="cal-book-list"></div>
    </div>`;
  renderMini();
  renderCalList();
  renderFeeds();
  renderBookingPages();
  const s = document.getElementById('cal-search');
  s.addEventListener('input', () => queueSearchRender(s.value, render));
  document.getElementById('cal-cal-add').addEventListener('click', () => calForm(null));
  document.getElementById('cal-feed-add').addEventListener('click', addFeed);
  document.getElementById('cal-book-add').addEventListener('click', addBookingPage);
}

export function queueSearchRender(value, renderFn = render, delay = CAL_SEARCH_DEBOUNCE_MS) {
  _search = String(value ?? '').trim();
  if (_searchTimer) clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => {
    _searchTimer = null;
    renderFn();
  }, delay);
}

let _bookingPages = [];
async function renderBookingPages() {
  const el = document.getElementById('cal-book-list');
  if (!el) return;
  _bookingPages = await fetch('/api/calendar/booking-pages', withZone()).then(r => r.json()).catch(() => []);
  if (!_bookingPages.length) { el.innerHTML = `<div class="cal-feed-empty">${esc(tr('calendar.none_yet'))}</div>`; return; }
  el.innerHTML = _bookingPages.map(b => `
    <div class="cal-feed-row" data-id="${b.id}">
      <span class="cal-feed-name" title="${esc(tr('calendar.slot_length', { minutes: b.duration_min }))}">${esc(b.title)}</span>
      <button class="cal-feed-x" data-act="copy" title="${esc(tr('calendar.copy_public_link'))}">${_si('link')}</button>
      <button class="cal-feed-x" data-act="del" title="${esc(tr('common.delete'))}">×</button>
    </div>`).join('');
  el.querySelectorAll('.cal-feed-row').forEach(row => {
    const b = _bookingPages.find(x => x.id === row.dataset.id);
    row.querySelector('[data-act="copy"]').addEventListener('click', async () => {
      const url = location.origin + b.url;
      try { await writeClipboard(url); toast(tr('calendar.booking_link_copied'), 'success'); }
      catch { toast(url, ''); }
    });
    row.querySelector('[data-act="del"]').addEventListener('click', async () => {
      await fetch(`/api/calendar/booking-pages/${b.id}`, withZone({ method: 'DELETE' }));
      renderBookingPages();
    });
  });
}

async function addBookingPage() {
  const title = await dlgPrompt('', tr('calendar.booking_default_title'), { title: tr('calendar.new_booking_page'), label: tr('calendar.page_title'), confirmLabel: tr('common.next') });
  if (title === null) return;
  const dur = await dlgPrompt('', '30', { title: tr('calendar.new_booking_page'), label: tr('calendar.slot_minutes'), confirmLabel: tr('calendar.create_page') });
  try {
    await fetch('/api/calendar/booking-pages', {
      method: 'POST', headers: { 'content-type': 'application/json', ...zoneHeader() },
      body: JSON.stringify({ title: title?.trim() || tr('calendar.booking_default_title'), duration_min: parseInt(dur) || 30 }),
    });
    toast(tr('calendar.booking_page_created'), 'success');
    renderBookingPages();
  } catch { toast(tr('calendar.failed'), 'error'); }
}

// 8a — secondary timezone world clock
function _clockHtml() {
  if (!_secondaryTz) return '';
  let t = '';
  try {
    t = formatTime(new Date(), { hour: 'numeric', minute: '2-digit', timeZone: _secondaryTz });
  } catch { return ''; }
  const label = _secondaryTz.split('/').pop().replace(/_/g, ' ');
  return `<div class="cal-worldclock" id="cal-worldclock" title="${esc(_secondaryTz)}"><span class="cal-wc-zone">${esc(label)}</span><span class="cal-wc-time">${esc(t)}</span></div>`;
}

function renderFeeds() {
  const el = document.getElementById('cal-feeds-list');
  if (!el) return;
  if (!_subs.length) { el.innerHTML = `<div class="cal-feed-empty">${esc(tr('calendar.no_feeds'))}</div>`; return; }
  el.innerHTML = _subs.map(s => `
    <div class="cal-feed-row" data-id="${s.id}">
      <span class="cal-feed-name" title="${esc(s.url)} · ${esc(s.last_status || '')}">${esc(s.name)} <span class="cal-feed-n">${s.event_count}</span></span>
      <button class="cal-feed-x" data-act="del" title="${esc(tr('common.remove'))}">×</button>
    </div>`).join('');
  el.querySelectorAll('.cal-feed-row').forEach(row => {
    row.querySelector('[data-act="del"]').addEventListener('click', async () => {
      await fetch(`/api/calendar/subscriptions/${row.dataset.id}`, withZone({ method: 'DELETE' }));
      loadCalendar();
    });
  });
}

async function addFeed() {
  const url = await dlgPrompt('', '', { title: tr('calendar.subscribe_title'), label: tr('calendar.feed_url'), hint: tr('calendar.feed_hint'), confirmLabel: tr('common.next') });
  if (!url?.trim()) return;
  const name = await dlgPrompt('', tr('calendar.subscription_default_name'), { title: tr('calendar.subscribe_title'), label: tr('calendar.name_label'), confirmLabel: tr('calendar.subscribe') });
  toast(tr('calendar.subscribing'));
  try {
    const r = await fetch('/api/calendar/subscriptions', {
      method: 'POST', headers: { 'content-type': 'application/json', ...zoneHeader() },
      body: JSON.stringify({ name: name?.trim() || tr('calendar.subscription_default_name'), url: url.trim() }),
    });
    if (!r.ok) throw 0;
    toast(tr('calendar.subscribed'), 'success');
    loadCalendar();
  } catch { toast(tr('calendar.subscription_failed'), 'error'); }
}

function renderMini() {
  const el = document.getElementById('cal-mini');
  if (!el) return;
  const y = _miniCursor.getFullYear(), m = _miniCursor.getMonth();
  const today = _calendarNow();
  const startDay = _lead(y, m);
  const dim = new Date(y, m + 1, 0).getDate();
  const miniWd = _weekdayLabels('narrow');
  let html = `<div class="cal-mini-head"><button type="button" class="cal-mini-nav" data-d="-1" aria-label="${esc(tr('calendar.previous_month'))}">‹</button>
    <span>${formatCalendarDate(_miniCursor, { month: 'long', year: 'numeric' })}</span>
    <button type="button" class="cal-mini-nav" data-d="1" aria-label="${esc(tr('calendar.next_month'))}">›</button></div><div class="cal-mini-grid">`;
  html += '<div class="cal-row" role="row">';
  for (const w of miniWd) html += `<div class="cal-mini-wd" role="columnheader">${w}</div>`;
  html += '</div><div class="cal-row" role="row">';
  for (let i = 0; i < startDay; i++) html += '<div aria-hidden="true"></div>';
  for (let d = 1; d <= dim; d++) {
    if ((startDay + d - 1) % 7 === 0 && d > 1) html += '</div><div class="cal-row" role="row">';
    const date = new Date(y, m, d);
    const cls = ['cal-mini-day'];
    if (sameDay(date, today)) cls.push('today');
    if (sameDay(date, _cursor)) cls.push('sel');
    html += `<div class="${cls.join(' ')}" data-date="${ymd(date)}" aria-label="${esc(formatCalendarDate(date, { dateStyle: 'full' }))}"${sameDay(date, _cursor) ? ' aria-selected="true"' : ''}>${d}</div>`;
  }
  html += '</div></div>';
  el.innerHTML = html;
  wireGridNav(el.querySelector('.cal-mini-grid'), {
    cells: '.cal-mini-day', steps: WEEK_ROWS, label: formatCalendarDate(_miniCursor, { month: 'long', year: 'numeric' }),
    start: c => c.classList.contains('sel'),
  });
  el.querySelectorAll('.cal-mini-nav').forEach(b => b.addEventListener('click', () => {
    _miniCursor = addMonths(_miniCursor, +b.dataset.d); renderMini();  // clamp, else 29-31 skips a month
  }));
  el.querySelectorAll('.cal-mini-day').forEach(c => c.addEventListener('click', () => {
    _cursor = calendarPlacementDate(c.dataset.date); render(); renderMini();
  }));
}

function renderCalList() {
  const el = document.getElementById('cal-cals-list');
  if (!el) return;
  el.innerHTML = _calendars.map(c => `
    <div class="cal-cal-row" data-id="${c.id}">
      <button type="button" class="cal-cal-vis" data-act="vis" role="switch" aria-checked="${!!c.visible}" aria-label="${esc(tr('calendar.show_named', { name: c.name }))}" style="--cc:${hexOf(c.color)}"><span class="cal-cal-chk ${c.visible ? 'on' : ''}" aria-hidden="true"></span></button>
      <button type="button" class="cal-cal-name" data-act="edit" aria-label="${esc(tr('calendar.edit_named', { name: c.name }))}">${esc(c.name)}</button>
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
    <input class="settings-input" id="cc-name" placeholder="${esc(tr('calendar.calendar_name'))}" value="${esc(cal?.name || '')}" style="width:100%">
    <div class="cal-swatches" id="cc-colors" role="radiogroup" aria-label="${esc(tr('calendar.calendar_color'))}">${COLOR_NAMES.map(c => `<button type="button" class="cal-sw ${c === sel ? 'sel' : ''}" data-c="${c}" role="radio" aria-checked="${c === sel}" aria-label="${esc(colorLabel(c))}" style="--cal-swatch:${hexOf(c)}"></button>`).join('')}</div>
    <div class="cal-cal-form-btns">
      ${isNew || cal.is_default ? '' : `<button class="btn" id="cc-del" style="color:var(--error);border-color:var(--error);margin-right:auto">${esc(tr('common.delete'))}</button>`}
      <button class="btn" id="cc-cancel">${esc(tr('common.cancel'))}</button>
      <button class="btn primary" id="cc-save">${esc(isNew ? tr('common.add') : tr('common.save'))}</button>
    </div>`;
  wrap.prepend(form);
  let color = sel;
  form.querySelectorAll('.cal-sw').forEach(s => s.addEventListener('click', () => {
    color = s.dataset.c; form.querySelectorAll('.cal-sw').forEach(x => { x.classList.toggle('sel', x === s); x.setAttribute('aria-checked', String(x === s)); });
  }));
  form.querySelector('#cc-cancel').addEventListener('click', () => renderCalList());
  form.querySelector('#cc-del')?.addEventListener('click', async () => {
    await fetch(`/api/calendars/${cal.id}`, { method: 'DELETE' });
    await loadCalendar();
  });
  form.querySelector('#cc-save').addEventListener('click', async () => {
    const name = form.querySelector('#cc-name').value.trim();
    if (!name) { toast(tr('calendar.name_it'), 'error'); return; }
    const body = { name, color };
    if (isNew) await fetch('/api/calendars', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    else await fetch(`/api/calendars/${cal.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    await loadCalendar();
  });
}

// the day-keys an occurrence covers. a multi-day all-day event (end date > start) spans every
// day in [start, end] inclusive (the whole app stores all-day end as the inclusive last day);
// everything else is just its start day. recurring events stay on the start day (their end_dt is
// the master's, not the occurrence's, so spanning would be wrong).
function _spanKeys(o) {
  const startK = ymd(o._date);
  if (!o.all_day || !o.end_dt || o._recur) return [startK];
  const start = _cloneCalendarDate(o._date); start.setHours(0, 0, 0, 0);
  const end = calendarPlacementDate(String(o.end_dt).slice(0, 10));
  if (isNaN(end) || end <= start) return [startK];
  const out = [];
  for (const cur = _cloneCalendarDate(start); cur <= end && out.length < 366; cur.setDate(cur.getDate() + 1)) out.push(ymd(cur));
  return out;
}

// pack overlapping timed events into side-by-side columns so a covered event isn't hidden.
// sets .col (which sub-column) and .ncols (how many the cluster needs) on each item.
function _layoutCols(evs) {
  evs.sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs);
  let cluster = [], clusterEnd = -Infinity, colEnds = [], cid = 0;
  const flush = () => {
    const n = cluster.reduce((m, e) => Math.max(m, e.col + 1), 1);
    cluster.forEach(e => { e.ncols = n; e.cid = cid; });
    cluster = []; colEnds = []; cid++;
  };
  for (const e of evs) {
    if (e.startMs >= clusterEnd) flush();   // a gap → start a fresh cluster
    let col = colEnds.findIndex(end => end <= e.startMs);
    if (col === -1) col = colEnds.length;
    colEnds[col] = e.endMs;
    e.col = col;
    cluster.push(e);
    clusterEnd = Math.max(clusterEnd, e.endMs);
  }
  flush();
  return evs;
}

// ── recurrence expansion (mirrors services/recur.py) ─────────────────────────
const PYWD = { MO: 0, TU: 1, WE: 2, TH: 3, FR: 4, SA: 5, SU: 6 };
const parseByday = s => new Set((s || '').split(',').map(t => PYWD[t.trim().toUpperCase()]).filter(v => v != null));
export function addMonths(d, n) {
  const x = _cloneCalendarDate(d); const day = d.getDate();
  x.setDate(1); x.setMonth(x.getMonth() + n);
  const monthEnd = x instanceof CalendarWallDate
    ? _calendarWallDate(x.getFullYear(), x.getMonth() + 1, 0)
    : new Date(x.getFullYear(), x.getMonth() + 1, 0);
  x.setDate(Math.min(day, monthEnd.getDate()));
  return x;
}
function* candidates(start, rec, interval, byday) {
  if (rec === 'weekly') {
    const days = (byday && byday.size) ? byday : new Set([(start.getDay() + 6) % 7]);
    const monday = _cloneCalendarDate(start); monday.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    const floor = _cloneCalendarDate(start); floor.setSeconds(0, 0);
    let wk = 0;
    while (true) {
      for (const wd of [...days].sort((a, b) => a - b)) {
        const c = _cloneCalendarDate(monday); c.setDate(monday.getDate() + wk * 7 * interval + wd);
        if (c >= floor) yield c;
      }
      wk++;
    }
  } else if (rec === 'daily') {
    let cur = _cloneCalendarDate(start);
    while (true) { yield _cloneCalendarDate(cur); cur.setDate(cur.getDate() + interval); }
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

export function expand(rs, re, events = visibleEvents()) {
  const out = [];
  for (const e of events) {
    // an all-day event is its date wherever you are: "2026-10-30T00:00:00Z" is the 30th, not the
    // evening of the 29th in toronto
    const start = calendarPlacementDate(e.all_day ? String(e.start_dt).slice(0, 10) : e.start_dt);
    if (isNaN(start)) continue;
    if (!e.recurrence) {
      // a multi-day all-day event that began before the range still covers days in it (_spanKeys)
      const last = e.all_day && e.end_dt ? calendarPlacementDate(String(e.end_dt).slice(0, 10)) : start;
      if (start < re && (start >= rs || last >= rs)) out.push({ ...e, _date: start });
      continue;
    }
    // a repeat that kept its offset repeats in that offset's own frame - its weekdays, weeks,
    // month days, last day and skipped days - and each start is then read here, like the server
    const kept = e.all_day ? null : keptFrame(e.start_dt, e.source_zone);
    const first = kept ? kept.wall : start;
    const seen = kept ? cand => _instantAsCalendarWallDate(new Date(kept.at(cand))) : cand => cand;
    const interval = Math.max(1, e.recur_interval || 1);
    const until = e.recur_until ? calendarPlacementDate(e.recur_until + 'T23:59:59') : null;
    const count = e.recur_count || null;
    const excepts = new Set((e.recur_except || []).map(d => String(d).slice(0, 10)));
    const byday = e.recurrence === 'weekly' ? parseByday(e.recur_byday) : null;
    const gen = candidates(first, e.recurrence, interval, byday);
    let emitted = 0, guard = 0;
    while (guard++ < 8000) {
      const nx = gen.next(); if (nx.done) break;
      const cand = nx.value;
      if (until && cand > until) break;
      if (count != null && emitted >= count) break;
      emitted++;
      if (excepts.has(ymd(cand))) continue;
      const at = seen(cand);
      if (at >= re) break;
      if (at >= rs) out.push({ ...e, _date: _cloneCalendarDate(at), _recur: true, ...(kept ? { _at: kept.at(cand) } : {}) });
      if (out.length > 3000) break;
    }
  }
  return out;
}

// a wall time in an IANA zone as an instant, the way python reads it: an hour the clocks repeat
// is its first, an hour they skip is read with the offset from before
function _zonedInstant(zone, wall) {
  const w = wall.getTime();
  const offsetAt = t => _instantAsCalendarWallDate(new Date(t), zone).getTime() - t;
  const before = w - offsetAt(w - 86400000), after = w - offsetAt(w + 86400000);
  const fits = [before, after].filter(t => _instantAsCalendarWallDate(new Date(t), zone).getTime() === w);
  return fits.length ? Math.min(...fits) : before;
}

// a stored time that kept its offset: its wall time in that frame, and at(wall) for the instant a
// wall time of that frame is. the frame is the source zone when the series has one (the server
// ignores a name it can't read), else the fixed offset. null for wall time
export function keptFrame(value, sourceZone) {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)(Z|[+-]\d{2}:?\d{2})$/i.exec(String(value || '').trim());
  if (!match) return null;
  const digits = match[2].replace(/\D/g, '');
  const sign = match[2][0] === '-' ? -1 : 1;
  const offset = /z/i.test(match[2]) ? 0 : sign * (Number(digits.slice(0, 2)) * 60 + Number(digits.slice(2, 4) || 0)) * 60000;
  const zone = String(sourceZone || '').trim();
  try {
    if (zone) {
      const instant = calendarPlacementDate(match[1]).getTime() - offset;
      return { wall: _instantAsCalendarWallDate(new Date(instant), zone), zone, at: cand => _zonedInstant(zone, cand) };
    }
  } catch { /* not a zone name: the offset it kept */ }
  return { wall: calendarPlacementDate(match[1]), offset, at: cand => cand.getTime() - offset };
}

// ── rendering ────────────────────────────────────────────────────────────────
function render() {
  const lbl = document.getElementById('cal-month-label');
  if (_view === 'month') { if (lbl) lbl.textContent = formatCalendarDate(_cursor, { month: 'long', year: 'numeric' }); renderMonth(); }
  else if (_view === 'week') renderWeek(lbl);
  else if (_view === 'agenda') return renderAgenda(lbl);   // fetches its days; callers may wait
  else if (_view === 'year') renderYear(lbl);
  else renderDay(lbl);
}

// an open task in the agenda reads like home and plan: an overdue one leads today, the rest sit
// on their due day. every agenda row is a 44px button, so the keyboard opens it too
const _agendaTask = (task, overdue) => {
  const label = overdue ? tr('home.overdue') : tr('tasks.due');
  return `<button type="button" class="cal-agenda-ev cal-agenda-task${overdue ? ' overdue' : ''}" data-task="${esc(task.id)}" aria-label="${esc(overdue ? tr('calendar.open_task_overdue', { title: task.title, due: task.due }) : tr('calendar.open_task_due', { title: task.title }))}" title="${esc(tr('calendar.task_title', { title: task.title }))}"><span class="cal-agenda-dot" aria-hidden="true"></span><span class="cal-agenda-time">${esc(label)}</span><span class="cal-agenda-title">${esc(task.title)}</span></button>`;
};
export const agendaDays = d => {
  const days = Array.isArray(d?.days) ? d.days : [];
  const overdue = Array.isArray(d?.overdue) ? d.overdue : [];
  if (!overdue.length || !d.today) return days;
  return days[0]?.date === d.today ? days : [{ date: d.today, events: [], tasks: [] }, ...days];
};

export function importFirstOnly(count) {
  const text = trp('calendar.import_first_only', count);
  if (text !== 'calendar.import_first_only') return text;
  return count === 1
    ? "1 event repeats in a way alles can't show yet; only its first time was imported"
    : `${count} events repeat in a way alles can't show yet; only their first time was imported`;
}

// agenda (8a) — flat upcoming list grouped by day, from /calendar/agenda
async function renderAgenda(lbl) {
  if (lbl) lbl.textContent = tr('calendar.agenda');
  const el = document.getElementById('calendar-list');
  if (!el) return;
  const d = await fetch('/api/calendar/agenda?days=60', withZone()).then(r => r.json()).catch(() => ({ days: [] }));
  const days = agendaDays(d);
  if (!days.length) { el.innerHTML = `<div class="cal-agenda-empty">${esc(tr('calendar.nothing_upcoming'))}</div>`; return; }
  let html = '<div class="cal-agenda">';
  for (const g of days) {
    const dd = new Date(g.date + 'T00:00:00');
    html += `<div class="cal-agenda-day"><div class="cal-agenda-date">${formatCalendarDate(dd, { weekday: 'short', month: 'short', day: 'numeric' })}</div><div class="cal-agenda-evs">`;
    if (g.date === d.today) for (const task of d.overdue || []) html += _agendaTask(task, true);
    for (const task of g.tasks || []) html += _agendaTask(task, false);
    for (const o of g.events || []) {
      // a later day of a multi-day event reads as all day there, like plan does, not a fresh start time
      const t = o.all_day || o.continued ? tr('home.all_day') : timeShort(calendarPlacementDate(o.start_dt));
      html += `<button type="button" class="cal-agenda-ev" data-id="${o.id}" data-occ="${o.recurring ? o.start_dt.slice(0, 10) : ''}"><span class="cal-agenda-dot" style="background:${evHex(o)}"></span><span class="cal-agenda-time">${esc(t)}</span><span class="cal-agenda-title">${esc(o.title)}${o.recurring ? ` <span class="cal-agenda-recur">${esc(tr('calendar.repeats_paren'))}</span>` : ''}</span></button>`;
    }
    html += '</div></div>';
  }
  html += '</div>';
  el.innerHTML = html;
  el.querySelectorAll('.cal-agenda-ev:not(.cal-agenda-task)').forEach(r => r.addEventListener('click', () => openEvent(r.dataset.id, r.dataset.occ || null)));
  el.querySelectorAll('.cal-agenda-task').forEach(r => r.addEventListener('click', () => window._openRecord?.('tasks', r.dataset.task)));
}

// year (8a) — 12 mini-months; click a day jumps to the day view
function renderYear(lbl) {
  const year = _cursor.getFullYear();
  if (lbl) lbl.textContent = String(year);
  const el = document.getElementById('calendar-list');
  if (!el) return;
  const today = _calendarNow();
  // expand recurrences across the whole year so a repeating event dots every occurrence,
  // not just its first date — and respect calendar-visibility filters like the other views.
  const dotDays = new Set(
    expand(_calendarWallDate(year, 0, 1), _calendarWallDate(year + 1, 0, 1))
      .map(o => ymd(o._date))
  );
  let html = '<div class="cal-year">';
  for (let m = 0; m < 12; m++) {
    const startDay = _lead(year, m);
    const dim = new Date(year, m + 1, 0).getDate();
    html += `<div class="cal-year-month"><div class="cal-year-mname">${formatCalendarDate(new Date(year, m, 1), { month: 'long' })}</div><div class="cal-year-grid">`;
    for (const w of _weekdayLabels('narrow')) html += `<div class="cal-year-wd">${w}</div>`;
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
    _cursor = calendarPlacementDate(c.dataset.date); _view = 'day'; localStorage.setItem('cal-view', _view); _syncViewBtns(); render();
  }));
}

// a tint of the calendar's color with a bar of it at the start, like the week view's blocks
const chipStyle = o => `background:color-mix(in srgb, ${evHex(o)} 22%, transparent);color:var(--text);box-shadow:inset 3px 0 0 ${evHex(o)}`;
const chipTitle = o => `${esc(o.title)}${o.location ? ' · ' + esc(o.location) : ''}${o._recur ? ` ${esc(tr('calendar.repeats_paren'))}` : ''}`;

// 4a — birthdays keyed by "MM-DD" (year-agnostic), and a lookup for a given Date
function _bdayMap() {
  const m = {};
  for (const b of _birthdays) {
    const k = String(b.month).padStart(2, '0') + '-' + String(b.day).padStart(2, '0');
    (m[k] = m[k] || []).push(b.name);
  }
  return m;
}
const _bdayKey = d => String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const _bdayChips = (map, d) => (map[_bdayKey(d)] || [])
  .map(n => `<div class="cal-bday" title="${esc(tr('calendar.birthday_of', { name: n }))}">${_si('cake')} ${esc(n)}</div>`).join('');
// the title gets its own span: the chip is a flex row, so an ellipsis on it never shows.
// in a month cell a task line opens its day instead of completing it: the lines are packed
// tight there and a stray tap shouldn't tick a task off. the day's 44px toggle completes it
const _taskChip = t =>
  `<button type="button" class="cal-task${t.done ? ' done' : ''}" data-task="${esc(t.id)}" aria-label="${esc(t.done ? tr('calendar.task_done', { title: t.title }) : t.title)}" title="${esc(tr('calendar.task_title', { title: t.title }))}"><span class="cal-task-chk${t.done ? ' on' : ''}" aria-hidden="true">${t.done ? _si('check') : ''}</span><span class="cal-task-title">${esc(t.title)}</span></button>`;
// the day/week all-day row has room for a real control: a 44px button you can tab to and toggle
// with enter or space. month cells keep the compact chip
const _taskToggle = t =>
  `<button type="button" class="cal-task${t.done ? ' done' : ''}" role="checkbox" aria-checked="${t.done ? 'true' : 'false'}" data-task="${esc(t.id)}" title="${esc(tr('calendar.task_title', { title: t.title }))}"><span class="cal-task-chk${t.done ? ' on' : ''}" aria-hidden="true">${t.done ? _si('check') : ''}</span><span class="cal-task-title">${esc(t.title)}</span></button>`;
const _tasksByDay = () => {
  const out = {};
  for (const t of _tasks) (out[t.date] = out[t.date] || []).push(t);
  return out;
};
async function _toggleCalTask(id, refocus = false) {
  const t = _tasks.find(x => x.id === id);
  if (!t) return;
  t.done = !t.done;
  const ok = await fetch(`/api/tasks/${t.id}`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ done: t.done }) })
    .then(r => r.ok, () => false);
  if (!ok) { t.done = !t.done; toast(tr('calendar.task_update_failed'), 'error'); }
  render();
  // the row is redrawn, so put focus back on the same task's new toggle
  if (refocus) document.querySelector(`.cal-tg-allday .cal-task[data-task="${CSS.escape(id)}"]`)?.focus();
}
// month cells fit 4 lines, 3 on a phone; the rest is counted on a "+N more" that opens the day
const MONTH_NARROW = '(max-width: 600px)';
export const monthCellFit = (count, narrow) => Math.min(count, narrow ? 3 : 4);
// the date row is one 44px strip in every cell, covered by a button that opens the day: a tap
// on the date does the same everywhere, and "+N more" lives in that strip instead of on a line
// of its own, so a short cell (a laptop, a phone) still shows a title. with nothing hidden the
// button is pointer-only (tabindex -1): the grid's arrow keys already reach every day
const HEAD_STYLE = 'position:relative;display:flex;align-items:flex-start;min-height:44px';
// inset from the strip's edge, so the button's focus ring clears the number
const NUM_STYLE = 'position:relative;z-index:1;pointer-events:none;margin:2px 0 0 6px';
const _dayLabel = day => formatCalendarDate(calendarPlacementDate(day), { month: 'short', day: 'numeric' }).toLowerCase();
const _dayBtn = (day, n) => n > 0
  ? `<button type="button" class="cal-more" data-day="${day}" aria-label="${esc(trp('calendar.more_on_day', n, { day: _dayLabel(day) }))}" style="${DAY_BTN_STYLE}">${esc(trp('calendar.plus_more', n))}</button>`
  : `<button type="button" class="cal-day-open" data-day="${day}" tabindex="-1" aria-label="${esc(tr('calendar.open_day', { day: _dayLabel(day) }))}" style="${DAY_BTN_STYLE}"></button>`;
const DAY_BTN_STYLE = 'position:absolute;inset:0;margin:0;width:100%;display:flex;align-items:flex-start;justify-content:flex-end;padding:2px 6px 0;background:none;border:0;color:var(--muted);font:inherit;font-size:0.8125rem;cursor:pointer';
function _setMore(cell, n) {
  const head = cell.querySelector('.cal-cell-head');
  if (!head) return null;
  let btn = head.querySelector('.cal-more, .cal-day-open');
  const want = n > 0 ? 'cal-more' : 'cal-day-open';
  if (!btn || !btn.classList.contains(want)) {
    const focused = btn && btn === document.activeElement;
    btn?.remove();
    head.insertAdjacentHTML('beforeend', _dayBtn(cell.dataset.date, n));
    btn = head.querySelector(`.${want}`);
    initKokuenPrimitives(head);   // kokuen styles it; size it now, before the trim measures
    if (focused) btn.focus();
  }
  if (n <= 0) return null;
  btn.setAttribute('aria-label', trp('calendar.more_on_day', n, { day: _dayLabel(cell.dataset.date) }));
  // a phone cell is about 50px wide: just "+N" there
  btn.textContent = head.clientWidth && head.clientWidth < 100 ? `+${n}` : trp('calendar.plus_more', n);
  return btn;
}
// a phone squeezes the month into the screen, so a cell can be shorter than its lines. drop lines
// until the last one sits inside the cell; clipped, it couldn't be seen or tapped
function _fitMonthCells(grid, counts) {
  for (let pass = 0; pass < 3; pass++) {
    let trimmed = false;
    for (const cell of grid.querySelectorAll('.cal-cell[data-date]')) {
      const box = cell.querySelector('.cal-cell-events');
      const lines = [...box.children];
      while (lines.length && box.getBoundingClientRect().bottom > cell.getBoundingClientRect().bottom + 0.5) {
        const line = lines.pop(), focused = line.contains(document.activeElement);
        line.remove();
        const more = _setMore(cell, counts[cell.dataset.date] - lines.length);
        if (focused) more?.focus();   // the line it was on is gone
        trimmed = true;
      }
    }
    if (!trimmed) break;
  }
  // the label reads the cell's width, which a resize changes
  for (const cell of grid.querySelectorAll('.cal-cell[data-date]')) {
    const shown = cell.querySelector('.cal-cell-events')?.children.length || 0;
    _setMore(cell, (counts[cell.dataset.date] || 0) - shown);
  }
}
// put each cell back to its first fit, so a cell that grew (a rotate, a taller window) gets its
// lines back before the next trim. a cell holding focus keeps what it has
function _refillMonthCells(grid, items) {
  const narrow = Boolean(window.matchMedia?.(MONTH_NARROW).matches);
  for (const cell of grid.querySelectorAll('.cal-cell[data-date]')) {
    const box = cell.querySelector('.cal-cell-events'), list = items[cell.dataset.date] || [];
    if (!box || box.contains(document.activeElement)) continue;
    const fit = monthCellFit(list.length, narrow);
    box.innerHTML = list.slice(0, fit).join('');
    _setMore(cell, list.length - fit);
  }
  // kokuen would size the new chips on its own a moment later, after the trim already measured
  // them small; size them now
  initKokuenPrimitives(grid);
}
// "+N more" and a month task line open their day; the month and that button are gone after, so
// focus lands on what was picked, else the day's first event or task, else "today"
function _openDay(day, focusSelector = '') {
  _cursor = calendarPlacementDate(day); _view = 'day'; localStorage.setItem('cal-view', _view); _syncViewBtns(); render();
  const list = document.getElementById('calendar-list');
  const target = (focusSelector && list?.querySelector(focusSelector))
    || list?.querySelector('.cal-tg-allday button, .cal-tev[data-id]') || document.getElementById('cal-today');
  target?.focus();
}
let _monthFitWatch = null;

function renderMonth() {
  const el = document.getElementById('calendar-list');
  if (!el) return;
  const year = _cursor.getFullYear(), month = _cursor.getMonth();
  const startDay = _lead(year, month);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = _calendarNow();
  const rangeStart = _calendarWallDate(year, month, 1 - startDay);
  const rangeEnd = _calendarWallDate(year, month, daysInMonth + 7);
  const occ = expand(rangeStart, rangeEnd);
  const byDay = {};
  for (const o of occ) for (const k of _spanKeys(o)) (byDay[k] = byDay[k] || []).push(o);
  const tasksByDay = _tasksByDay();
  const bmap = _bdayMap();
  const narrow = Boolean(window.matchMedia?.(MONTH_NARROW).matches);
  const counts = {}, lines = {};
  // a cell under ~150px cut "9:00 AM lunch" to "9:00 A…": there the title leads and the time follows
  const titleFirst = narrow || (el.clientWidth && el.clientWidth / 7 < 150);
  const chipText = o => o.all_day ? o.title : titleFirst ? `${o.title} ${timeShort(o._date)}` : `${timeShort(o._date)} ${o.title}`;

  const cells = [];
  for (let i = 0; i < startDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));
  while (cells.length % 7) cells.push(null);

  let html = '<div class="cal-grid"><div class="cal-row" role="row">';
  for (const w of _weekdayLabels()) html += `<div class="cal-weekday" role="columnheader">${esc(w)}</div>`;
  html += '</div>';
  for (const [index, cell] of cells.entries()) {
    if (index % 7 === 0) html += `${index ? '</div>' : ''}<div class="cal-row" role="row">`;
    if (!cell) { html += '<div class="cal-cell empty" aria-hidden="true"></div>'; continue; }
    const key = ymd(cell);
    const evts = (byDay[key] || []).sort((a, b) => (a.all_day ? 0 : a._date) - (b.all_day ? 0 : b._date));
    // everything past the fit is counted on a real "+N more" that opens the day, and the day
    // view shows all of it (tasks and birthdays too), so nothing is cut off without a word
    const items = [
      ...evts.map(o =>
        `<button type="button" class="cal-chip${o._recur ? ' recurring' : ''}" data-id="${o.id}" data-occ="${ymd(o._date)}" style="${chipStyle(o)}" title="${chipTitle(o)}">${o._recur ? `<span class="cal-chip-recur">${_si('refresh')}</span>` : ''}<span class="cal-ev-title">${esc(chipText(o))}</span></button>`),
      ...(tasksByDay[key] || []).map(_taskChip),
      ...(bmap[_bdayKey(cell)] || []).map(n => `<div class="cal-bday" title="${esc(tr('calendar.birthday_of', { name: n }))}">${_si('cake')} ${esc(n)}</div>`),
    ];
    counts[key] = items.length;
    lines[key] = items;
    const fit = monthCellFit(items.length, narrow);
    html += `<div class="cal-cell${sameDay(cell, today) ? ' today' : ''}" data-date="${key}">
      <div class="cal-cell-head" style="${HEAD_STYLE}"><div class="cal-cell-num" style="${NUM_STYLE}">${cell.getDate()}</div>${_dayBtn(key, items.length - fit)}</div>
      <div class="cal-cell-events">${items.slice(0, fit).join('')}</div></div>`;
  }
  html += '</div></div>';
  el.innerHTML = html;
  // chips only get their 44px from kokuen after this task, and the space can still change (a
  // rotate, the phone's url bar), so fit once it's laid out and again when the space changes
  const grid = el.querySelector('.cal-grid');
  _monthFitWatch?.disconnect();
  let seen = '';
  _monthFitWatch = typeof ResizeObserver === 'function' ? new ResizeObserver(([entry]) => {
    if (!grid.isConnected) { _monthFitWatch?.disconnect(); return; }
    // only a real size change refills; refilling moves lines, which can't feed back forever
    // because the next call sees the same size and stops
    const size = `${Math.round(entry.contentRect.width)}x${Math.round(entry.contentRect.height)}`;
    if (size === seen) return;
    if (seen) _refillMonthCells(grid, lines);
    else initKokuenPrimitives(grid);
    seen = size;
    _fitMonthCells(grid, counts);
  }) : null;
  _monthFitWatch?.observe(el.parentElement || el);
  // Enter on a day creates an event there, same as a click on its empty space
  wireGridNav(el.querySelector('.cal-grid'), {
    cells: '.cal-cell:not(.empty)', steps: WEEK_ROWS, label: tr('calendar.month'),
    start: c => c.classList.contains('today'),
  });
  el.querySelectorAll('.cal-cell:not(.empty)').forEach(c => c.addEventListener('click', ev => {
    const task = ev.target.closest('.cal-task');
    if (task) {
      ev.stopPropagation();
      _openDay(c.dataset.date, `.cal-tg-allday .cal-task[data-task="${CSS.escape(task.dataset.task)}"]`);
      return;
    }
    const more = ev.target.closest('.cal-more, .cal-day-open');
    if (more) {
      _openDay(more.dataset.day);
      return;
    }
    const chip = ev.target.closest('.cal-chip');
    if (chip) { openEvent(chip.dataset.id, chip.dataset.occ); return; }
    createAt(c.dataset.date);
  }));
}

function weekStart(d) { const s = _cloneCalendarDate(d); s.setDate(s.getDate() - ((s.getDay() - _weekStart + 7) % 7)); s.setHours(0, 0, 0, 0); return s; }

function renderWeek(lbl) {
  const days = [];
  const ws = weekStart(_cursor);
  for (let i = 0; i < 7; i++) { const d = _cloneCalendarDate(ws); d.setDate(d.getDate() + i); days.push(d); }
  if (lbl) lbl.textContent = `${formatCalendarDate(days[0], { month: 'short', day: 'numeric' })} - ${formatCalendarDate(days[6], { month: 'short', day: 'numeric', year: 'numeric' })}`;
  const re = _cloneCalendarDate(days[6]); re.setDate(re.getDate() + 1);
  renderTimeGrid(document.getElementById('calendar-list'), days, expand(ws, re));
}

function renderDay(lbl) {
  const day = _cloneCalendarDate(_cursor); day.setHours(0, 0, 0, 0);
  if (lbl) lbl.textContent = formatCalendarDate(day, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  const re = _cloneCalendarDate(day); re.setDate(re.getDate() + 1);
  renderTimeGrid(document.getElementById('calendar-list'), [day], expand(day, re));
}

function renderTimeGrid(el, days, occ) {
  if (!el) return;
  const today = _calendarNow();
  let head = '<div class="cal-tg-gutter-head"></div>';
  for (const d of days) head += `<div class="cal-tg-dayhead${sameDay(d, today) ? ' today' : ''}" data-date="${ymd(d)}"><span class="cal-tg-wd">${esc(formatCalendarDate(d, { weekday: 'short' }))}</span> <span class="cal-tg-dn">${d.getDate()}</span></div>`;
  let allday = `<div class="cal-tg-gutter">${esc(tr('calendar.all_day_row'))}</div>`;
  const bmap = _bdayMap();
  const tasksByDay = _tasksByDay();
  for (const d of days) {
    // a real button like the tasks under it: 44px, and tab plus enter opens it
    const items = occ.filter(o => o.all_day && _spanKeys(o).includes(ymd(d)))
      .map(o => `<button type="button" class="cal-allday-ev${o._recur ? ' recurring' : ''}" data-id="${o.id}" data-occ="${ymd(o._date)}" style="${chipStyle(o)}" title="${chipTitle(o)}">${o._recur ? `<span class="cal-chip-recur">${_si('refresh')}</span>` : ''}<span class="cal-ev-title">${esc(o.title)}</span></button>`).join('');
    // the day's tasks live here too, so a "+N more" from the month always lands on them
    const tasks = (tasksByDay[ymd(d)] || []).map(_taskToggle).join('');
    allday += `<div class="cal-tg-allday" data-date="${ymd(d)}">${items}${tasks}${_bdayChips(bmap, d)}</div>`;
  }
  let gutter = '';
  for (let h = 0; h < 24; h++) gutter += `<div class="cal-tg-hour" style="height:${HOUR_H}px">${h === 0 ? '' : (h % 12 || 12) + (h < 12 ? 'a' : 'p')}</div>`;
  const nowTop = (today.getHours() + today.getMinutes() / 60) * HOUR_H;
  // overlapping events sit side by side; when that leaves each under 44px (four overlaps on a
  // phone drew 14px boxes, six at 640px drew 12px) the group becomes one stack that opens its
  // day. a week only: in the day view a stack would open the same day again
  const colWidth = width => (width - 52) / days.length;   // 52: the hour gutter at its widest
  const stacks = (n, width) => days.length > 1 && n > 1 && (colWidth(width) - 4) / n < 44;
  // the day view keeps as many 44px boxes side by side as fit and folds the rest into "+N",
  // which lists them
  const fits = width => Math.max(2, Math.floor((colWidth(width) - 4) / 44));
  const folds = (n, width) => days.length === 1 && n > fits(width);
  const layout = width => [...grouped].map(n => `${stacks(n, width)}${folds(n, width) ? fits(width) : 0}`).join();
  const grouped = new Set();   // the overlap sizes on screen, to re-check on a resize
  let cols = '';
  for (const d of days) {
    let evHtml = '';
    const stacked = new Set();
    const dayEvs = occ.filter(x => !x.all_day && sameDay(x._date, d)).map(o => {
      const bs = new Date(o.start_dt), be = o.end_dt ? new Date(o.end_dt) : new Date(bs.getTime() + 3600000);
      const durH = Math.max(0.5, (be - bs) / 3600000);
      const startMs = o._date.getTime();
      const end = _cloneCalendarDate(o._date); end.setTime(startMs + (be - bs));
      return { o, durH, startMs, endMs: startMs + durH * 3600000, end };
    });
    _layoutCols(dayEvs);
    const folded = new Map();   // cluster -> the events behind its "+N"
    for (const it of dayEvs) {
      const o = it.o;
      const top = (o._date.getHours() + o._date.getMinutes() / 60) * HOUR_H;
      if (it.ncols > 1) grouped.add(it.ncols);
      if (folds(it.ncols, el.clientWidth)) {
        const keep = fits(el.clientWidth) - 1;
        if (it.col >= keep) { folded.set(it.cid, [...(folded.get(it.cid) || []), it]); continue; }
        Object.assign(it, { ncols: keep + 1 });
      }
      if (stacks(it.ncols, el.clientWidth)) {
        if (stacked.has(it.cid)) continue;
        stacked.add(it.cid);
        const group = dayEvs.filter(x => x.cid === it.cid);   // in start order, so `it` is first
        const height = (Math.max(...group.map(x => x.endMs)) - it.startMs) / 3600000 * HOUR_H - 2;
        const last = group.reduce((latest, x) => (x.end > latest ? x.end : latest), it.end);
        // the box shows the count; a half-hour box has no room for a word
        const name = trp('calendar.overlap_stack', group.length, { start: timeShort(o._date), end: timeShort(last) });
        evHtml += `<div class="cal-tstack" role="button" tabindex="0" aria-label="${esc(name)}" data-day="${ymd(d)}" data-first="${o.id}" style="top:${top}px;height:${height}px" title="${esc(group.map(x => x.o.title).join(', '))}"><div class="cal-tev-box" aria-hidden="true">${_si('columns')}<b>${group.length}</b></div></div>`;
        continue;
      }
      const hx = evHex(o);
      const w = `calc((100% - 4px) / ${it.ncols})`;
      const left = `calc(2px + ${it.col} * (100% - 4px) / ${it.ncols})`;
      // dom order is time order, so tab walks the day in time order
      const name = tr('calendar.event_span', { title: o.title, start: timeShort(o._date), end: timeShort(it.end) });
      evHtml += `<div class="cal-tev${o._recur ? ' recurring' : ''}" role="button" tabindex="0" aria-label="${esc(name)}" data-id="${o.id}" data-occ="${ymd(o._date)}" style="top:${top}px;height:${it.durH * HOUR_H - 2}px;left:${left};width:${w};right:auto" title="${chipTitle(o)}"><div class="cal-tev-box" style="background:color-mix(in srgb, ${hx} 24%, transparent);color:var(--text);border-left:3px solid ${hx}"><b>${esc(timeShort(o._date))}</b> ${o._recur ? `<span class="cal-chip-recur">${_si('refresh')}</span>` : ''}<span class="cal-tev-title">${esc(o.title)}</span>${o.location ? `<span class="cal-tev-loc">${esc(o.location)}</span>` : ''}<span class="cal-tev-resize"></span></div></div>`;
    }
    for (const hidden of folded.values()) {
      const n = fits(el.clientWidth), first = hidden[0];
      const top = (first.o._date.getHours() + first.o._date.getMinutes() / 60) * HOUR_H;
      const height = (Math.max(...hidden.map(x => x.endMs)) - first.startMs) / 3600000 * HOUR_H - 2;
      const last = hidden.reduce((latest, x) => (x.end > latest ? x.end : latest), first.end);
      const name = trp('calendar.overlap_more', hidden.length, { start: timeShort(first.o._date), end: timeShort(last) });
      const picks = JSON.stringify(hidden.map(x => ({ value: `${x.o.id}@${ymd(x.o._date)}`, label: `${timeShort(x.o._date)} ${x.o.title}` })));
      evHtml += `<div class="cal-tstack cal-tmore" role="button" tabindex="0" aria-label="${esc(name)}" data-picks="${esc(picks)}" style="top:${top}px;height:${height}px;left:calc(2px + ${n - 1} * (100% - 4px) / ${n});width:calc((100% - 4px) / ${n});right:auto"><div class="cal-tev-box" aria-hidden="true"><b>+${hidden.length}</b></div></div>`;
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
  el.querySelectorAll('.cal-tg-allday .cal-task').forEach(t => t.addEventListener('click', e => {
    e.stopPropagation(); _toggleCalTask(t.dataset.task, true);
  }));
  el.querySelectorAll('.cal-tg-allday').forEach(s => s.addEventListener('click', e => { if (e.target === s) createAt(s.dataset.date, null, true); }));
  el.querySelectorAll('.cal-tstack').forEach(stack => stack.addEventListener('click', () => openStack(stack)));
  attachDrag(el, days);   // drag to create / move / resize timed events
  const sc = el.querySelector('.cal-tg-scroll'); if (sc) sc.scrollTop = Math.max(0, nowTop - 3 * HOUR_H);
  // turning a phone sideways can change whether the week stacks its overlaps
  const grid = el.querySelector('.cal-timegrid');
  _gridWidthWatch?.disconnect();
  const drawn = layout(el.clientWidth);
  _gridWidthWatch = grouped.size && typeof ResizeObserver === 'function' ? new ResizeObserver(() => {
    if (!grid.isConnected) { _gridWidthWatch?.disconnect(); return; }
    if (layout(el.clientWidth) !== drawn) render();
  }) : null;
  _gridWidthWatch?.observe(el);
}
let _gridWidthWatch = null;

// a stack of overlapping events opens their day, on the first of them. the day view's "+N"
// lists the events it folded away
async function openStack(stack) {
  if (!stack.classList.contains('cal-tmore')) {
    _openDay(stack.dataset.day, `.cal-tev[data-id="${CSS.escape(stack.dataset.first)}"]`);
    return;
  }
  const picked = await dlgChoose(tr('calendar.overlap_pick'), JSON.parse(stack.dataset.picks));
  if (picked) { const [id, occ] = picked.split('@'); openEvent(id, occ); }
  else stack.focus();
}

function hasOccurrence(event, day) {
  const start = calendarPlacementDate(`${day}T00:00`);
  const end = _cloneCalendarDate(start); end.setDate(end.getDate() + 1);
  return expand(start, end, [event]).some(item => ymd(item._date) === day);
}

// a tap on an empty cell or slot focused nothing, so focus fell to the page: start in the editor
function createAt(day, hour, allDay) {
  openEditor(null, day, hour, allDay);
  focusEditor(false);
}

// on a touch screen a focused field raises the keyboard over the event, so the editor's heading
// takes focus there. with a keyboard the title takes it, and an existing title keeps its text
// ahead of the caret instead of getting typed in front of
function focusEditor(existing) {
  const title = document.getElementById('cal-title');
  if (window.matchMedia?.('(pointer: coarse)')?.matches) {
    document.getElementById('cal-ed-head')?.focus();
    return;
  }
  title?.focus();
  if (existing && title) title.setSelectionRange(title.value.length, title.value.length);
}

export function openEvent(id, occ) {
  const ev = _events.find(e => e.id === id);
  if (!_eventsReady || !ev) return false;
  if (ev.recurrence && occ && !hasOccurrence(ev, occ)) return false;
  if (_editing?.id === id && _editOcc === (occ || null) && document.querySelector('.cal-editor')) {
    return true;
  }
  openEditor(ev, null, null, false, occ);
  focusEditor(true);
  return true;
}

// 4a — the proposed [start,end) from the editor's pickers, or null if not a valid timed span
function _proposedSpan() {
  const sVal = document.getElementById('cal-start')?.value;
  if (!sVal) return null;
  const a = calendarPlacementDate(sVal);
  const eVal = document.getElementById('cal-end')?.value;
  const b = eVal ? calendarPlacementDate(eVal) : new CalendarWallDate(a.getTime() + 30 * 60000);
  if (isNaN(a) || isNaN(b) || b <= a) return null;
  return [a, b];
}

// live double-booking hint: does the proposed time overlap any existing timed occurrence that day
function checkConflict() {
  const warn = document.getElementById('cal-conflict');
  if (!warn) return;
  const allDay = document.getElementById('cal-allday')?.getAttribute('aria-checked') === 'true';
  const span = _proposedSpan();
  if (allDay || !span) { warn.textContent = ''; return; }
  const [a, b] = span;
  const ds = _cloneCalendarDate(a); ds.setHours(0, 0, 0, 0);
  const de = _cloneCalendarDate(ds); de.setDate(de.getDate() + 1);
  const hits = [];
  for (const o of expand(ds, de)) {
    if (o.all_day) continue;
    if (_editing && o.id === _editing.id) continue;   // an event never conflicts with itself
    const bs = new Date(o.start_dt), be = o.end_dt ? new Date(o.end_dt) : new Date(bs.getTime() + 3600000);
    const os = o._date, oe = new Date(os.getTime() + (be - bs));
    if (a < oe && os < b) hits.push(o.title || tr('calendar.untitled_paren'));
    if (hits.length >= 3) break;
  }
  warn.textContent = hits.length ? tr('calendar.overlaps', { titles: hits.join(', ') }) : '';
}

function _addMin(hhmm, min) {
  const [h, m] = hhmm.split(':').map(Number);
  const t = h * 60 + m + min;
  return `${String(Math.floor(t / 60) % 24).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
}

// find free time: reuses the /free-slots advisor for the chosen day, fills the time on click
async function findFreeSlots() {
  const box = document.getElementById('cal-slots');
  if (!box) return;
  const day = (document.getElementById('cal-start')?.value || '').slice(0, 10);
  if (!day) { toast(tr('calendar.set_start_first'), ''); return; }
  const span = _proposedSpan();
  const dur = span ? Math.max(15, Math.round((span[1] - span[0]) / 60000)) : 30;
  const slots = await fetch(`/api/calendar/free-slots?day=${day}&duration_min=${dur}`, withZone())
    .then(r => r.ok ? r.json() : { slots: [] }).then(j => j.slots || []).catch(() => []);
  if (!slots.length) { box.innerHTML = `<div class="cal-slots-empty">${esc(tr('calendar.no_free_slots_workday'))}</div>`; return; }
  box.innerHTML = slots.map(s =>
    `<button class="cal-slot-chip" type="button" data-start="${s.start}">${s.start} - ${s.end}</button>`).join('');
  box.querySelectorAll('.cal-slot-chip').forEach(b => b.addEventListener('click', () => {
    document.getElementById('cal-start').value = `${day}T${b.dataset.start}`;
    document.getElementById('cal-end').value = `${day}T${_addMin(b.dataset.start, dur)}`;
    box.innerHTML = '';
    checkConflict();
  }));
}

// ── drag: create / move / resize timed events in week & day views ────────────
function attachDrag(el, days) {
  const body = el.querySelector('.cal-tg-body');
  const cols = [...el.querySelectorAll('.cal-tg-col')];
  if (!body || !cols.length) return;
  const SNAP = HOUR_H / 4;                         // 15-minute grid
  const snap = px => Math.max(0, Math.round(px / SNAP) * SNAP);
  const colAt = x => cols.findIndex(c => { const r = c.getBoundingClientRect(); return x >= r.left && x < r.right; });
  const atTime = (date, px) => { const d = _cloneCalendarDate(date); d.setHours(0, Math.round((px / HOUR_H) * 60 / 15) * 15, 0, 0); return localISO(d); };
  let st = null;

  function down(e) {
    if (e.button !== 0) return;
    const resize = e.target.closest('.cal-tev-resize');
    const tev = e.target.closest('.cal-tev');
    const slot = e.target.closest('.cal-tg-slot');
    if (resize && tev) {
      st = { mode: 'resize', tev, id: tev.dataset.id, occ: tev.dataset.occ, y0: e.clientY, h0: tev.offsetHeight, top0: tev.offsetTop, moved: false };
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

  // the day ends at 24:00: dragging past the bottom used to wrap into the next morning. only a
  // move into another column changes the day
  const DAY_H = 24 * HOUR_H;
  function move(e) {
    if (!st) return;
    if (st.mode === 'move') {
      if (Math.abs(e.clientY - st.y0) > 3 || Math.abs(e.clientX - st.x0) > 3) st.moved = true;
      // the box ends by midnight; one that already ran past it (an overnight event) may stay there
      const lowest = Math.max(st.top0, DAY_H - st.tev.offsetHeight - 2);
      st.tev.style.top = Math.min(snap(st.top0 + (e.clientY - st.y0)), lowest) + 'px';
      const ci = colAt(e.clientX);
      if (ci >= 0 && ci !== st.ci) { cols[ci].appendChild(st.tev); st.ci = ci; }
    } else if (st.mode === 'resize') {
      if (Math.abs(e.clientY - st.y0) > 3) st.moved = true;
      st.tev.style.height = Math.min(Math.max(SNAP, snap(st.h0 + (e.clientY - st.y0))), DAY_H - st.top0) + 'px';
    } else {
      const rect = cols[st.ci].getBoundingClientRect();
      const cur = Math.min(snap(e.clientY - rect.top), DAY_H);
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
        createAt(ymd(days[s.ci]));
      } else createAt(s.date, s.hour);
      return;
    }
    s.tev.classList.remove('dragging');
    if (!s.moved) { openEvent(s.id, s.occ); return; }   // a plain click
    const ci = s.ci >= 0 ? s.ci : cols.indexOf(s.tev.closest('.cal-tg-col'));
    const date = days[ci];
    const top = s.tev.offsetTop, h = s.tev.offsetHeight;
    if (s.mode === 'resize') {
      // only the end moves: a start off the 15-minute lines (13:10) stays where it was
      await applyTimeChange(s.id, s.occ, ...resizedTimes(s.id, s.occ, atTime(date, top + h)));
      return;
    }
    // a move keeps the event's own length: the box can be taller than it (15 minutes draw as 30)
    const start = atTime(date, top);
    await applyTimeChange(s.id, s.occ, start, endAfterMove(s.id, s.occ, start));
  }

  body.addEventListener('mousedown', down);
  // dragging stays pointer-only; the keyboard opens the event and changes its time in the editor
  body.addEventListener('keydown', e => {
    const tev = (e.key === 'Enter' || e.key === ' ') && e.target.closest('.cal-tev[data-id], .cal-tstack');
    if (!tev) return;
    e.preventDefault();
    if (tev.classList.contains('cal-tstack')) openStack(tev);
    else openEvent(tev.dataset.id, tev.dataset.occ);
  });
}

export function buildCopy(ev, ov) {
  return {
    title: ev.title, calendar_id: ev.calendar_id, description: ev.description,
    location: ev.location, guests: ev.guests, all_day: ev.all_day, color: ev.color,
    meeting_url: ev.meeting_url || '',
    reminders: ev.reminders || [], start_dt: ev.start_dt, end_dt: ev.end_dt,
    recurrence: ev.recurrence, recur_interval: ev.recur_interval, recur_byday: ev.recur_byday,
    recur_count: ev.recur_count, recur_until: ev.recur_until, ...ov,
  };
}

function resizedTimes(id, occ, end) {
  const ev = _events.find(e => e.id === id);
  const start = ev ? editorDates(ev, occ).start : '';
  const from = calendarPlacementDate(start).getTime();
  // the end snaps to a line; one that would land on or before the start keeps 15 minutes
  if (!start || calendarPlacementDate(end).getTime() > from) return [start || end, end];
  return [start, localISO(new CalendarWallDate(from + 15 * 60000))];
}

function endAfterMove(id, occ, start) {
  const ev = _events.find(e => e.id === id);
  const was = ev ? editorDates(ev, occ) : null;
  if (!was?.end) return '';
  const length = calendarPlacementDate(was.end).getTime() - calendarPlacementDate(was.start).getTime();
  return localISO(new CalendarWallDate(calendarPlacementDate(start).getTime() + length));
}

async function applyTimeChange(id, occ, newStart, newEnd) {
  const ev = _events.find(e => e.id === id);
  if (!ev || _saving) return;
  _saving = true;
  try {
    const scope = ev.recurrence ? await chooseScope('move') : 'all';
    if (!scope) return;
    const times = eventTimeValues(ev, editorDates(ev, occ), { start: newStart, end: newEnd || '' }, scope);
    const body = buildCopy(ev, times);
    await saveCalendarRequest(`/api/calendar/${id}?${new URLSearchParams({ scope, occ, time_zone: chosenTimeZone() })}`, 'PATCH', body, scope === 'all' ? id : null);
  } catch (error) { toast(plainError(error.message || tr('calendar.move_failed')), 'error'); }
  finally { _saving = false; await loadCalendar(); }
}

// ── scope chooser (this / following / all) ───────────────────────────────────
function chooseScope(verb, hasSelectedOccurrence = true) {
  const title = { move: tr('calendar.scope_move'), delete: tr('calendar.scope_delete') }[verb] || tr('calendar.scope_edit');
  return dlgChoose(title, [
    ...(hasSelectedOccurrence ? [
      { value: 'this', label: tr('calendar.scope_this') },
      { value: 'following', label: tr('calendar.scope_following') },
    ] : []),
    { value: 'all', label: tr('calendar.scope_all') },
  ]);
}

// ── find a time: show open slots on the focused day, click to book ───────────
async function findTime() {
  const answer = await dlgPrompt('', '', { title: tr('calendar.find_free_title'), label: tr('calendar.how_long'), confirmLabel: tr('calendar.find_times') });
  if (answer === null) return;
  const mins = parseInt(answer) || 60;
  const dstr = ymd(_cursor);
  let slots = [];
  try { slots = (await fetch(`/api/calendar/free?date=${dstr}&minutes=${mins}`, { headers: zoneHeader() }).then(r => r.json())).slots || []; }
  catch { toast(tr('calendar.free_slots_failed'), 'error'); return; }
  const ov = document.createElement('div');
  ov.className = 'cal-scope-ov';
  const fmt = iso => iso.slice(11);
  ov.innerHTML = `<div class="cal-scope"><div class="cal-scope-h">${esc(tr('calendar.free_on', { date: dstr, minutes: mins }))}</div>${
    slots.length ? slots.map(s => `<button class="btn" data-s="${s.start}" data-e="${s.end}">${fmt(s.start)} – ${fmt(s.end)}</button>`).join('')
                 : `<div style="color:var(--muted);font-size:0.8125rem;padding:0.4rem">${esc(tr('calendar.no_free_slots'))}</div>`
  }<button class="btn cal-scope-cancel">${esc(tr('common.cancel'))}</button></div>`;
  document.body.appendChild(ov);
  ov.addEventListener('click', e => { if (e.target === ov || e.target.classList.contains('cal-scope-cancel')) ov.remove(); });
  const errorBox = document.createElement('div');
  errorBox.className = 'cal-save-error'; errorBox.setAttribute('role', 'alert'); errorBox.hidden = true;
  ov.querySelector('.cal-scope').appendChild(errorBox);
  let booking = false;
  ov.querySelectorAll('[data-s]').forEach(b => {
    let titleDraft = '';
    b.addEventListener('click', async () => {
      if (booking || !ov.isConnected) return;
      booking = true;
      ov.querySelectorAll('[data-s]').forEach(button => { button.disabled = true; });
      try {
        const title = await dlgPrompt('', titleDraft, { title: tr('calendar.editor_new'), label: tr('calendar.title_label'), confirmLabel: tr('common.create') });
        if (!title?.trim() || !ov.isConnected) return;
        titleDraft = title;
        errorBox.hidden = true;
        const start = b.dataset.s;
        const end = new Date(new Date(start).getTime() + mins * 60000);
        await saveCalendarRequest('/api/calendar', 'POST', { title: title.trim(), start_dt: start, end_dt: localISO(end), description: '' });
        if (!ov.isConnected) return;
        ov.remove(); toast(tr('calendar.booked'), 'success');
        await loadCalendar(fetch, () => !document.querySelector('.cal-editor'));
      } catch {
        if (ov.isConnected) {
          errorBox.textContent = tr('calendar.booking_unconfirmed', { title: titleDraft });
          errorBox.hidden = false;
        }
      } finally {
        booking = false;
        ov.querySelectorAll('[data-s]').forEach(button => { button.disabled = false; });
      }
    });
  });
}

// ── the event editor ─────────────────────────────────────────────────────────
// labels are read at render time, so a language switch shows on the next editor
const remindPresets = () => [
  [0, tr('calendar.remind_at_time')], [5, tr('calendar.minutes_short', { count: 5 })], [10, tr('calendar.minutes_short', { count: 10 })],
  [30, tr('calendar.minutes_short', { count: 30 })], [60, tr('calendar.hours_short', { count: 1 })], [1440, tr('calendar.days_short', { count: 1 })],
];
const freqs = () => [['', tr('calendar.no_repeat')], ['daily', tr('tasks.repeat.daily')], ['weekly', tr('tasks.repeat.weekly')], ['monthly', tr('tasks.repeat.monthly')], ['yearly', tr('tasks.repeat.yearly')]];
// "every 1 days" reads as "every 1 day"
const unitLabel = (rec, n) => ({
  daily: trp('calendar.unit_days', n), monthly: trp('calendar.unit_months', n), yearly: trp('calendar.unit_years', n),
})[rec] || trp('calendar.unit_weeks', n);
// sunday first, the way the editor's day buttons are numbered
const _weekdayNames = width => Array.from({ length: 7 }, (_, index) => formatCalendarDate(new Date(2026, 6, 19 + index, 12), { weekday: width }));
// a template with an inline control: the words are translated, the markup goes where its placeholder is
const _fill = (text, html) => esc(text).replace(/\{(\w+)\}/g, (match, name) => html[name] ?? match);
const DOW_LETTER = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'];

function openEditor(event, defaultDate, hour, allDay, occ) {
  if (_searchTimer) { clearTimeout(_searchTimer); _searchTimer = null; }
  const el = document.getElementById('calendar-list');
  _editing = event || null;
  _editOcc = occ || null;
  const pf = _prefill; _prefill = null;   // start/end from a drag-create
  const isNew = !event;
  // a new event starts at the next full hour; this hour's start (2:00 at 2:43) is already gone
  const now = _calendarNow(); now.setHours(now.getHours() + 1, 0, 0, 0);
  const hh = hour != null ? String(hour).padStart(2, '0') : '09';
  const dates = editorDates(event, occ);
  const start = pf?.start || dates.start || (defaultDate ? `${defaultDate}T${hh}:00` : localISO(now));
  const endVal = pf?.end || dates.end || '';
  _editDates = { start, end: endVal };
  const defaultCal = event?.calendar_id || (_calendars.find(c => c.is_default)?.id || _calendars[0]?.id || '');
  const rec = event?.recurrence || '';
  const reminders = new Set(event?.reminders || (isNew ? [10] : []));
  const startDow = calendarPlacementDate(start).getDay();
  // a kept offset's repeat days are its own frame's: shown and picked as the days they land on here
  const shift = frameShift(event);
  const storedDays = parseBydayJs(event?.recur_byday);
  let byday = new Set(storedDays ? storedDays.map(i => (i + shift + 7) % 7) : (rec === 'weekly' ? [startDow] : []));
  if (rec === 'weekly' && byday.size === 0) byday.add(startDow);
  const untilShown = shiftDay(event?.recur_until, shift);
  _rulesShown = event ? { byday: dowLetters(byday), until: untilShown, raw: { byday: event.recur_byday || '', until: event.recur_until || null } } : null;
  let color = event?.color || '';   // '' = use the calendar's colour
  const endsMode = event?.recur_count ? 'after' : (event?.recur_until ? 'on' : 'never');

  el.innerHTML = `<div class="cal-editor" role="form" aria-labelledby="cal-ed-head">
    <h2 class="cal-ed-head" id="cal-ed-head" tabindex="-1">${esc(tr(isNew ? 'calendar.editor_new' : 'calendar.editor_edit'))}</h2>
    <input class="note-editor-title" id="cal-title" aria-label="${esc(tr('calendar.event_title'))}" value="${esc(event?.title || '')}" placeholder="${esc(tr('calendar.event_title_placeholder'))}">
    <div class="cal-ed-grid">
      <div><div class="cal-flabel">${esc(tr('calendar.start'))}</div><div class="date-input" id="cal-start" aria-label="${esc(tr('calendar.start'))}" data-type="datetime" data-value="${start}" data-ph="${esc(tr('calendar.start'))}" style="width:100%"></div></div>
      <div><div class="cal-flabel">${esc(tr('calendar.end'))}</div><div class="date-input" id="cal-end" aria-label="${esc(tr('calendar.end'))}" data-type="datetime" data-value="${endVal}" data-ph="${esc(tr('calendar.end_optional'))}" style="width:100%"></div></div>
    </div>
    <div class="cal-sched">
      <button class="btn cal-sched-btn" id="cal-freeslot" type="button">${esc(tr('calendar.find_free_time'))}</button>
      <span class="cal-conflict" id="cal-conflict"></span>
    </div>
    <div class="cal-slots" id="cal-slots"></div>
    <div class="cal-ed-row">
      <div id="cal-allday-row"><button type="button" class="cal-flabel cal-chk-row" id="cal-allday" role="checkbox" aria-checked="${event?.all_day || allDay ? 'true' : 'false'}"><span class="chk" aria-hidden="true"></span>${esc(tr('home.all_day'))}</button></div>
      <div class="cal-cal-pick"><span class="cal-flabel">${esc(tr('calendar.title'))}</span>
        <div class="settings-input custom-select" id="cal-calendar" aria-label="${esc(tr('calendar.title'))}" aria-disabled="${Boolean(_calendarMetadataError)}" data-placeholder="${esc(_calendarMetadataError ? tr('calendar.calendar_unavailable') : tr('calendar.select'))}" data-value="${defaultCal}" data-options="${_calendars.map(c => `${c.id}|${esc(c.name)}`).join(';')}" style="min-width:130px"></div></div>
    </div>

    <div class="cal-flabel">${esc(tr('tasks.repeat.label'))}</div>
    <div class="settings-input custom-select" id="cal-recur" aria-label="${esc(tr('tasks.repeat.label'))}" data-value="${rec}" data-options="${freqs().map(([v, l]) => `${v}|${esc(l)}`).join(';')}" style="width:100%"></div>
    <div id="cal-recur-adv" style="display:${rec ? 'block' : 'none'}">
      <div class="cal-recur-line">${_fill(tr('calendar.repeat_every', { interval: '{interval}', unit: '{unit}' }), {
        interval: `<input class="settings-input cal-int" id="cal-interval" aria-label="${esc(tr('calendar.repeat_interval'))}" type="text" inputmode="numeric" value="${event?.recur_interval || 1}">`,
        unit: `<span id="cal-unit">${esc(unitLabel(rec, event?.recur_interval || 1))}</span>`,
      })}</div>
      <div class="cal-dow" id="cal-dow" style="display:${rec === 'weekly' ? 'flex' : 'none'}">${_weekdayNames('narrow').map((d, i) => `<button type="button" class="cal-dow-b ${byday.has(i) ? 'on' : ''}" data-i="${i}" aria-label="${esc(_weekdayNames('long')[i])}" aria-pressed="${byday.has(i)}">${esc(d)}</button>`).join('')}</div>
      <div class="cal-ends" role="radiogroup" aria-label="${esc(tr('calendar.recurrence_ends'))}">
        <span class="cal-flabel">${esc(tr('calendar.ends'))}</span>
        <div class="cal-ends-choices">
        <div class="cal-radio"><button type="button" class="cal-radio-choice" role="radio" data-value="never" aria-checked="${endsMode === 'never'}" tabindex="${endsMode === 'never' ? '0' : '-1'}"><span class="radio-mark" aria-hidden="true"></span>${esc(tr('calendar.ends_never'))}</button></div>
        <div class="cal-radio"><button type="button" class="cal-radio-choice" role="radio" data-value="on" aria-checked="${endsMode === 'on'}" tabindex="${endsMode === 'on' ? '0' : '-1'}"><span class="radio-mark" aria-hidden="true"></span>${esc(tr('calendar.ends_on'))}</button><div class="date-input cal-ends-date" id="cal-until" aria-label="${esc(tr('calendar.repeat_until'))}" data-type="date" data-value="${untilShown || ''}" data-ph="${esc(tr('calendar.date'))}" style="width:130px"></div></div>
        <div class="cal-radio"><button type="button" class="cal-radio-choice" role="radio" data-value="after" aria-checked="${endsMode === 'after'}" tabindex="${endsMode === 'after' ? '0' : '-1'}"><span class="radio-mark" aria-hidden="true"></span>${esc(tr('calendar.ends_after'))}</button><input class="settings-input cal-int" id="cal-count" aria-label="${esc(tr('calendar.occurrence_count'))}" type="text" inputmode="numeric" value="${event?.recur_count || 10}"> ${esc(tr('calendar.times_suffix'))}</div>
        </div>
      </div>
    </div>

    <div class="cal-flabel">${esc(tr('calendar.reminders'))}</div>
    <div class="cal-reminders" id="cal-reminders">${remindPresets().map(([m, l]) => `<button type="button" class="cal-rem ${reminders.has(m) ? 'on' : ''}" data-m="${m}" aria-pressed="${reminders.has(m)}" aria-label="${esc(m === 0 ? tr('calendar.remind_at_event_time') : trp('calendar.remind_minutes_before', m))}">${esc(l)}</button>`).join('')}</div>

    <div class="cal-ed-grid">
      <div><div class="cal-flabel">${esc(tr('calendar.location'))}</div><input class="settings-input" id="cal-loc" value="${esc(event?.location || '')}" placeholder="${esc(tr('calendar.add_location'))}" style="width:100%"></div>
      <div><div class="cal-flabel">${esc(tr('calendar.guests'))}</div><input class="settings-input" id="cal-guests" value="${esc(event?.guests || '')}" placeholder="${esc(tr('calendar.comma_separated'))}" style="width:100%"></div>
    </div>

    <div class="cal-flabel">${esc(tr('calendar.video_call'))}</div>
    <div class="cal-meet-row">
      <input class="settings-input" id="cal-meeting" value="${esc(event?.meeting_url || '')}" placeholder="${esc(tr('calendar.meeting_placeholder'))}" style="flex:1">
      <button class="btn" id="cal-meet-gen" type="button" title="${esc(tr('calendar.generate_jitsi'))}">${_si('video')} ${esc(tr('common.add'))}</button>
      ${event?.meeting_url ? `<a class="btn" id="cal-meet-open" href="${esc(event.meeting_url)}" target="_blank" rel="noopener">${esc(tr('calendar.join'))}</a>` : ''}
    </div>

    ${isNew ? '' : `<div class="cal-flabel">${esc(tr('calendar.invites_rsvp'))}</div>
    <div class="cal-invites" id="cal-invites"></div>
    <div class="cal-inv-suggest" id="cal-inv-suggest"></div>
    <div class="cal-invite-add">
      <input class="settings-input" id="cal-inv-name" placeholder="${esc(tr('calendar.name_label'))}" style="flex:1">
      <input class="settings-input" id="cal-inv-email" placeholder="${esc(tr('calendar.email'))}" style="flex:1.4">
      <button class="btn" id="cal-inv-btn" type="button">${esc(tr('calendar.invite'))}</button>
    </div>`}

    <div class="cal-flabel">${esc(tr('calendar.color'))}</div>
    <div class="cal-swatches" id="cal-colors">
      <button type="button" class="cal-sw cal-sw-def ${color === '' ? 'sel' : ''}" data-c="" aria-label="${esc(tr('calendar.default_color'))}" aria-pressed="${color === ''}">${_si('none')}</button>
      ${COLOR_NAMES.map(c => `<button type="button" class="cal-sw ${color === c ? 'sel' : ''}" data-c="${c}" style="--cal-swatch:${hexOf(c)}" aria-label="${esc(tr('calendar.color_swatch', { color: colorLabel(c) }))}" aria-pressed="${color === c}"></button>`).join('')}
    </div>

    <textarea class="note-editor-body" id="cal-desc" rows="3" placeholder="${esc(tr('calendar.description_placeholder'))}">${esc(event?.description || '')}</textarea>
    ${event?.source?.kind === 'mail' ? `<button type="button" class="btn" id="cal-source">${esc(tr('calendar.open_original_message'))}</button>` : ''}
    ${event?.source?.kind === 'capture' ? `<details class="capture-source"><summary>${esc(tr('calendar.original_capture'))}</summary><pre>${esc(event.source.excerpt)}</pre></details>` : ''}
    <div id="cal-save-error" class="cal-save-error" role="alert" hidden></div>
    <div class="cal-ed-actions">
      ${isNew ? '' : `<button class="btn" id="cal-del" style="margin-right:auto;color:var(--error);border-color:var(--error)">${esc(tr('common.delete'))}</button>`}
      ${isNew ? '' : `<button class="btn" id="cal-dup" title="${esc(tr('calendar.duplicate_help'))}">${esc(tr('calendar.duplicate'))}</button>`}
      <button class="btn ic-btn-lbl" id="cal-back">${_si('chevron-left')} back</button>
      <button class="btn primary" id="cal-save">${esc(isNew ? tr('common.create') : tr('common.save'))}</button>
    </div>
  </div>`;

  initCustomDropdown(document.getElementById('cal-recur'));
  initCustomDropdown(document.getElementById('cal-calendar'));
  refreshCalendarPicker();
  initDatePickers(el);

  // 4a scheduling advisor: live overlap warning + free-slot finder (timed events only)
  document.getElementById('cal-start')?.addEventListener('change', checkConflict);
  document.getElementById('cal-end')?.addEventListener('change', checkConflict);
  document.getElementById('cal-freeslot')?.addEventListener('click', findFreeSlots);
  checkConflict();

  // all day picks days, not times: the start and end fields switch between the two in place
  const keptTimes = {};
  const syncAllDayFields = (on, capture = true) => {
    for (const id of ['cal-start', 'cal-end']) {
      const field = document.getElementById(id);
      if (!field) continue;
      const value = String(field.value || '');
      const day = value.slice(0, 10);
      if (capture && on && value.length > 10) keptTimes[id] = value.slice(10);   // turning it back gives the times back
      field.dataset.type = on ? 'date' : 'datetime';
      field.value = !day ? '' : on ? day : `${day}${keptTimes[id] || `T${id === 'cal-start' ? hh : String(Math.min(+hh + 1, 23)).padStart(2, '0')}:00`}`;
    }
  };
  // an event that opens all day only has a placeholder midnight; keeping it would turn it into 00:00-00:00
  if (document.getElementById('cal-allday')?.getAttribute('aria-checked') === 'true') syncAllDayFields(true, false);
  document.getElementById('cal-allday-row').addEventListener('click', e => {
    if (e.target.closest('.date-input')) return;
    const c = document.getElementById('cal-allday');
    const on = c.getAttribute('aria-checked') !== 'true';
    c.setAttribute('aria-checked', String(on));
    syncAllDayFields(on);
    checkConflict();   // all-day events never conflict; clear/refresh the hint
  });
  function selectEndsMode(value) {
    el.querySelectorAll('.cal-radio-choice').forEach(choice => {
      const selected = choice.dataset.value === value;
      choice.setAttribute('aria-checked', String(selected));
      choice.tabIndex = selected ? 0 : -1;
    });
  }
  el.querySelectorAll('.cal-radio-choice').forEach(button => button.addEventListener('click', () => {
    selectEndsMode(button.dataset.value);
  }));
  el.querySelector('.cal-ends')?.addEventListener('keydown', event => {
    const choices = [...el.querySelectorAll('.cal-radio-choice')];
    const current = choices.indexOf(event.target.closest('.cal-radio-choice'));
    if (current < 0) return;
    let next = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (current + 1) % choices.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (current - 1 + choices.length) % choices.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = choices.length - 1;
    if (next === null) return;
    event.preventDefault();
    selectEndsMode(choices[next].dataset.value);
    choices[next].focus();
  });
  const untilInput = document.getElementById('cal-until');
  untilInput?.addEventListener('change', () => selectEndsMode('on'));
  untilInput?.addEventListener('focusin', () => selectEndsMode('on'));
  const countInput = document.getElementById('cal-count');
  countInput?.addEventListener('input', () => selectEndsMode('after'));
  countInput?.addEventListener('focus', () => selectEndsMode('after'));
  const recSel = document.getElementById('cal-recur');
  const syncUnit = () => {
    document.getElementById('cal-unit').textContent = unitLabel(recSel.value, parseInt(document.getElementById('cal-interval')?.value, 10));
  };
  document.getElementById('cal-interval')?.addEventListener('input', syncUnit);
  syncUnit();
  recSel.addEventListener('change', () => {
    const v = recSel.value;
    document.getElementById('cal-recur-adv').style.display = v ? 'block' : 'none';
    syncUnit();
    document.getElementById('cal-dow').style.display = v === 'weekly' ? 'flex' : 'none';
    if (v === 'weekly' && byday.size === 0) { byday.add(calendarPlacementDate(document.getElementById('cal-start').value).getDay()); syncDow(); }
  });
  function syncDow() { el.querySelectorAll('.cal-dow-b').forEach(b => { const on = byday.has(+b.dataset.i); b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); }); }
  el.querySelectorAll('.cal-dow-b').forEach(b => b.addEventListener('click', () => {
    const i = +b.dataset.i; byday.has(i) ? byday.delete(i) : byday.add(i); syncDow();
  }));
  el.querySelectorAll('.cal-rem').forEach(r => r.addEventListener('click', () => { r.classList.toggle('on'); r.setAttribute('aria-pressed', String(r.classList.contains('on'))); }));
  el.querySelectorAll('#cal-colors .cal-sw').forEach(s => s.addEventListener('click', () => {
    color = s.dataset.c; el.querySelectorAll('#cal-colors .cal-sw').forEach(x => { x.classList.toggle('sel', x === s); x.setAttribute('aria-pressed', String(x === s)); });
  }));

  _readDraft = () => JSON.stringify(collectBody(byday));
  _draftSnapshot = _readDraft();
  document.getElementById('cal-back').addEventListener('click', leaveEditor);
  const editor = el.querySelector('.cal-editor');
  editor?.addEventListener('keydown', escapeLeaves);
  watchPageEscape(editor);
  document.getElementById('cal-source')?.addEventListener('click', async () => {
    if (_saving) return;
    if (_readDraft && _readDraft() !== _draftSnapshot && !(await dlgConfirm(tr('calendar.discard_changes_short')))) return;
    await window._openRecord?.('mail', `event-${event.id}`);
  });
  document.getElementById('cal-del')?.addEventListener('click', () => deleteEvent());
  document.getElementById('cal-dup')?.addEventListener('click', async () => {
    if (!_editing?.id) return;
    try {
      await fetch(`/api/calendar/${_editing.id}/duplicate`, withZone({ method: 'POST' }));
      toast(tr('calendar.event_duplicated'), 'success');
      loadCalendar();
    } catch { toast(tr('calendar.duplicate_failed'), 'error'); }
  });
  document.getElementById('cal-save').addEventListener('click', () => saveEvent(byday));

  // 8b — video call link generator
  document.getElementById('cal-meet-gen')?.addEventListener('click', async () => {
    const inp = document.getElementById('cal-meeting');
    if (event?.id) {
      try {
        const d = await fetch(`/api/calendar/${event.id}/meeting-link`, withZone({ method: 'POST' })).then(r => r.json());
        inp.value = d.meeting_url; toast(tr('calendar.video_room_added'), 'success');
      } catch { toast(tr('calendar.failed'), 'error'); }
    } else {
      // new event: mint a room name client-side; saved with the event
      const slug = (document.getElementById('cal-title').value || 'Meet').replace(/[^a-zA-Z0-9]+/g, '').slice(0, 24) || 'Meet';
      inp.value = `https://meet.jit.si/${slug}-${Math.random().toString(36).slice(2, 12)}`;
    }
  });

  // 8b — invites + rsvp (existing events only)
  if (event?.id) renderAttendees(event.id);
  const inviteButton = document.getElementById('cal-inv-btn');
  const inviteName = document.getElementById('cal-inv-name');
  const inviteEmail = document.getElementById('cal-inv-email');
  const ownsInvite = () => _editing?.id === event?.id && document.getElementById('cal-inv-btn') === inviteButton;
  inviteButton?.addEventListener('click', async () => {
    if (!ownsInvite() || inviteButton.disabled) return;
    const originalName = inviteName.value, originalEmail = inviteEmail.value;
    const name = originalName.trim(), email = originalEmail.trim();
    if (!name && !email) { toast(tr('calendar.name_or_email'), ''); return; }
    inviteButton.disabled = true;
    try {
      const attendee = await readCalendarResponse(await fetch(`/api/calendar/${event.id}/invite`, {
        method: 'POST', headers: { 'content-type': 'application/json', ...zoneHeader() }, body: JSON.stringify({ name, email }),
      }));
      if (typeof attendee?.id !== 'string' || !attendee.id || attendee.event_id !== event.id
          || attendee.name !== name || attendee.email !== email) throw new Error(tr('calendar.invite_unconfirmed'));
      if (!ownsInvite()) return;
      if (inviteName.value === originalName && inviteEmail.value === originalEmail) {
        inviteName.value = ''; inviteEmail.value = '';
      }
      await renderAttendees(event.id);
    } catch (error) { if (ownsInvite()) toast(error.message === 'Failed to fetch'
      ? tr('calendar.invite_unconfirmed') : (error.message || tr('calendar.invite_failed')), 'error'); }
    finally { inviteButton.disabled = false; }
  });
}

const RSVP_LABEL = { invited: 'invited', accepted: 'yes', declined: 'no', tentative: 'maybe' };
const rsvpLabel = status => ({
  invited: tr('calendar.rsvp_invited'), yes: tr('calendar.rsvp_yes'), no: tr('calendar.rsvp_no'), maybe: tr('calendar.rsvp_maybe'),
})[RSVP_LABEL[status]] || status;

async function renderAttendees(eid) {
  const box = document.getElementById('cal-invites');
  const ownsBox = () => _editing?.id === eid && document.getElementById('cal-invites') === box;
  if (!box || !ownsBox()) return;
  const list = await fetch(`/api/calendar/${eid}/attendees`, withZone()).then(r => r.json()).catch(() => []);
  if (!ownsBox()) return;
  if (!list.length) {
    box.innerHTML = `<div class="cal-inv-empty">${esc(tr('calendar.no_invites'))}</div>`;
  } else {
    box.innerHTML = list.map(a => `
      <div class="cal-inv-row" data-id="${a.id}">
        <span class="cal-inv-who">${esc(a.name || a.email)}</span>
        <span class="cal-inv-status s-${a.status}">${esc(rsvpLabel(a.status))}</span>
        <button class="cal-inv-x" data-act="del" title="${esc(tr('common.remove'))}">×</button>
      </div>`).join('');
    box.querySelectorAll('.cal-inv-row').forEach(row => {
      row.querySelector('[data-act="del"]').addEventListener('click', async () => {
        if (!ownsBox()) return;
        await fetch(`/api/calendar/attendees/${row.dataset.id}`, withZone({ method: 'DELETE' }));
        if (ownsBox()) renderAttendees(eid);
      });
    });
  }
  renderInviteSuggestions(eid);
}

// 4a — suggest contacts linked to whoever's already invited; one click invites them
async function renderInviteSuggestions(eid) {
  const box = document.getElementById('cal-inv-suggest');
  const ownsBox = () => _editing?.id === eid && document.getElementById('cal-inv-suggest') === box;
  if (!box || !ownsBox()) return;
  const sugg = await fetch(`/api/calendar/${eid}/invite-suggestions`, withZone())
    .then(r => r.ok ? r.json() : { suggestions: [] }).then(j => j.suggestions || []).catch(() => []);
  if (!ownsBox()) return;
  if (!sugg.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="cal-inv-suggest-lbl">${esc(tr('calendar.suggested_contacts'))}</div>`
    + sugg.map(s => `
      <button class="cal-inv-chip" type="button" data-name="${esc(s.name)}" data-email="${esc(s.email)}" title="${esc(tr('calendar.kind_of_invitee', { kind: s.kind || tr('calendar.linked') }))}">
        + ${esc(s.name)}${s.kind ? ` <span class="cal-inv-chip-kind">${esc(s.kind)}</span>` : ''}
      </button>`).join('');
  box.querySelectorAll('.cal-inv-chip').forEach(b => b.addEventListener('click', async () => {
    if (!ownsBox()) return;
    await fetch(`/api/calendar/${eid}/invite`, {
      method: 'POST', headers: { 'content-type': 'application/json', ...zoneHeader() },
      body: JSON.stringify({ name: b.dataset.name, email: b.dataset.email }),
    });
    if (ownsBox()) renderAttendees(eid);
  }));
}

function parseBydayJs(s) {
  return s ? (s.split(',').map(t => DOW_LETTER.indexOf(t.trim().toUpperCase())).filter(v => v >= 0)) : null;
}
const dowLetters = days => [...days].sort((a, b) => a - b).map(i => DOW_LETTER[i]).join(',');

// days between a kept-offset start's own date and the date it lands on here (sunday 09:00 in
// tokyo is saturday here in toronto: -1). 0 for wall time
function frameShift(event) {
  const kept = event && event.recurrence && !event.all_day ? keptFrame(event.start_dt, event.source_zone) : null;
  if (!kept) return 0;
  const here = calendarPlacementDate(ymd(calendarPlacementDate(event.start_dt)));
  return Math.round((here - calendarPlacementDate(ymd(kept.wall))) / 86400000);
}
function shiftDay(value, days) {
  if (!value || !days) return value || '';
  const day = calendarPlacementDate(String(value).slice(0, 10)); day.setDate(day.getDate() + days);
  return ymd(day);
}
// what the editor showed for a repeat's days. left as shown, they go back as stored, so saving a
// title leaves a kept offset's rule exactly as it was; changed, they're days here
let _rulesShown = null;

function collectBody(byday) {
  const el = document.getElementById('calendar-list');
  const rec = document.getElementById('cal-recur').value;
  const ends = el.querySelector('.cal-radio-choice[aria-checked="true"]')?.dataset.value || 'never';
  const reminders = [...el.querySelectorAll('.cal-rem.on')].map(r => +r.dataset.m).sort((a, b) => a - b);
  const body = {
    title: document.getElementById('cal-title').value.trim(),
    calendar_id: _calendarMetadataError && _editing ? (_editing.calendar_id || '') : document.getElementById('cal-calendar').value,
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
    recur_byday: rec === 'weekly' ? dowLetters(byday) : '',
    recur_count: rec && ends === 'after' ? Math.max(1, parseInt(document.getElementById('cal-count').value) || 1) : null,
    recur_until: rec && ends === 'on' ? (document.getElementById('cal-until').value || null) : null,
  };
  if (_editing && _rulesShown) {
    if (body.recur_byday === _rulesShown.byday) body.recur_byday = _rulesShown.raw.byday;
    if ((body.recur_until || '') === (_rulesShown.until || '')) body.recur_until = _rulesShown.raw.until;
  }
  return body;
}

async function saveEvent(byday) {
  if (_saving) return;
  _saving = true;
  try {
    const body = collectBody(byday);
    if (!body.title || !body.start_dt) throw new Error(tr('calendar.needs_title_start'));
    const occ = _editOcc || _editDates?.start?.slice(0, 10) || '';
    const scope = _editing?.recurrence ? await chooseScope('edit', hasOccurrence(_editing, occ)) : 'all';
    if (!scope) return;
    const selectedDay = body.start_dt.slice(0, 10);
    Object.assign(body, eventTimeValues(_editing, _editDates, { start: body.start_dt, end: body.end_dt || '' }, scope));
    const id = _editing?.id;
    const query = new URLSearchParams({ scope, occ, time_zone: chosenTimeZone() });
    editorBusy(true);
    const saved = await saveCalendarRequest(id ? `/api/calendar/${id}?${query}` : '/api/calendar', id ? 'PATCH' : 'POST', body, id && scope === 'all' ? id : null);
    if (id) replaceLinkedRecord('calendar', id, saved.id,
      saved.recurrence && saved.id === id && hasOccurrence(saved, selectedDay) ? selectedDay : '');
    toast(id ? tr('common.saved') : tr('calendar.created'), 'success');
    if (!(await loadCalendar())) {
      openEditor(saved);
      editorError(tr('calendar.saved_reload_failed'));
    } else focusAfterEditor(saved.id, selectedDay);
  } catch (error) {
    editorError(error.message === 'Failed to fetch' ? tr('calendar.save_offline') : (error.message || tr('calendar.save_failed')));
  } finally { _saving = false; editorBusy(false); }
}

async function deleteEvent() {
  if (!_editing || _saving) return;
  _saving = true;
  try {
    const occ = _editOcc || _editing.start_dt.slice(0, 10);
    const scope = _editing.recurrence ? await chooseScope('delete', hasOccurrence(_editing, occ)) : 'all';
    if (!scope) return;
    editorBusy(true);
    const response = await readCalendarResponse(await fetch(`/api/calendar/${_editing.id}?${new URLSearchParams({ scope, occ })}`, withZone({ method: 'DELETE' })));
    if (response?.ok !== true) throw new Error(tr('calendar.delete_unconfirmed'));
    if (!(await loadCalendar())) { document.querySelector('.cal-editor')?.remove(); calendarLoadError(tr('calendar.deleted_refresh')); }
    else focusAfterEditor('', occ);
  } catch (error) { editorError(error.message || tr('calendar.delete_failed')); }
  finally { _saving = false; editorBusy(false); }
}

// ── CalDAV sync panel ───────────────────────────────────────────────────────
async function openCaldavPanel() {
  const list = document.getElementById('calendar-list');
  let cfg = {};
  try { cfg = await fetch('/api/caldav/status').then(r => r.json()); } catch {}
  list.innerHTML = `<div class="cal-editor" style="max-width:520px">
    <div style="font-size:0.875rem;color:var(--text);margin-bottom:0.2rem">${esc(tr('calendar.sync_help'))}</div>
    <div style="font-size:0.8125rem;color:var(--muted);line-height:1.5;margin-bottom:0.6rem">
      ${esc(tr('calendar.caldav_intro'))}
      ${cfg.available ? '' : `<br><b style="color:var(--warn)">${esc(tr('calendar.caldav_missing'))}</b>`}
      ${cfg.connected ? `<br>${_fill(tr('calendar.caldav_connected', { name: '{name}' }), { name: `<b>${esc(cfg.username || '')}</b>` })}` : ''}
    </div>
    <div class="cal-flabel">${esc(tr('calendar.server_url'))}</div>
    <input class="settings-input" id="cd-url" placeholder="https://caldav.icloud.com/" value="${esc(cfg.url || '')}" style="width:100%">
    <div class="cal-flabel" style="margin-top:0.4rem">${esc(tr('calendar.username'))}</div>
    <input class="settings-input" id="cd-user" placeholder="you@icloud.com" value="${esc(cfg.username || '')}" style="width:100%">
    <div class="cal-flabel" style="margin-top:0.4rem">${esc(tr('calendar.app_password'))}</div>
    <input class="settings-input" id="cd-pass" type="password" placeholder="${esc(tr('calendar.app_password_placeholder'))}" style="width:100%">
    <div class="cal-ed-actions">
      <button class="btn ic-btn-lbl" id="cd-back">${_si('chevron-left')} back</button>
      <button class="btn" id="cd-save">${esc(tr('common.save'))}</button>
      <button class="btn primary" id="cd-sync">${esc(tr('calendar.sync_now'))}</button>
    </div>
    <div id="cd-status" style="font-size:0.8125rem;color:var(--muted);margin-top:0.5rem"></div>
  </div>`;
  document.getElementById('cd-back').addEventListener('click', () => loadCalendar());
  const save = async () => {
    const body = { url: document.getElementById('cd-url').value.trim(), username: document.getElementById('cd-user').value.trim(), password: document.getElementById('cd-pass').value };
    await fetch('/api/caldav/connect', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  };
  document.getElementById('cd-save').addEventListener('click', async () => { await save(); toast(tr('common.saved'), 'success'); });
  document.getElementById('cd-sync').addEventListener('click', async () => {
    const st = document.getElementById('cd-status');
    st.textContent = tr('calendar.syncing'); await save();
    try {
      const r = await fetch('/api/caldav/sync', { method: 'POST' }).then(x => x.json());
      if (r.error) { st.textContent = tr('calendar.sync_error', { error: r.error }); return; }
      st.textContent = tr('calendar.synced_counts', { pulled: r.pulled || 0, pushed: r.pushed || 0 });
      await loadCalendar();
    } catch (e) { st.textContent = tr('calendar.sync_failed'); }
  });
}

export function newEvent() { openEditor(null); }

function esc(s) { return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
