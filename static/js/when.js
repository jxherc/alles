// how a date reads everywhere in alles (u.04): today, tomorrow, yesterday, the weekday inside the
// next week ("sun"), "in 9 days" or "3 days ago" inside two weeks, then the short date ("nov 12").
// the full date sits in the title (hover) and shows on a long press. built on Intl through
// i18n.js, so every interface language gets its own words; times follow the owner's 12/24 hour
// setting. lowercase like the rest of the app.
import { calendarDateKey, formatCalendarDate, formatClock, formatDateParts, formatRelativeTime, localeTag } from './i18n.js';

const DAY = 86400000;
const low = text => String(text).toLocaleLowerCase(localeTag());

// "2026-11-01", "2026-11-01T09:00", a Date or an instant: the owner's calendar day as a key
export function dayKey(value) {
  if (!value) return '';
  if (value instanceof Date) return calendarDateKey(value);
  const raw = String(value);
  const plain = /^(\d{4}-\d{2}-\d{2})(?:$|T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$)/.exec(raw);
  if (plain) return plain[1];   // a wall date or wall clock time is already the owner's day
  const parsed = new Date(raw);
  return Number.isNaN(parsed.valueOf()) ? '' : calendarDateKey(parsed);
}

// whole days from today to the key (negative is the past)
export function daysFromToday(key, now = new Date()) {
  const a = Date.parse(`${dayKey(now)}T00:00:00Z`), b = Date.parse(`${dayKey(key)}T00:00:00Z`);
  return Number.isNaN(a) || Number.isNaN(b) ? NaN : Math.round((b - a) / DAY);
}

export function addDays(key, n) {
  const date = new Date(`${dayKey(key)}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + n);
  return date.toISOString().slice(0, 10);
}

export function whenDay(value, { now = new Date() } = {}) {
  const key = dayKey(value);
  if (!key) return '';
  const diff = daysFromToday(key, now);
  if (Number.isNaN(diff)) return key;
  if (Math.abs(diff) <= 1) return low(formatRelativeTime(diff, 'day', { numeric: 'auto' }));
  if (diff > 1 && diff < 7) return low(formatCalendarDate(key, { weekday: 'short' })).replace(/\.$/, '');
  if (Math.abs(diff) < 14) return low(formatRelativeTime(diff, 'day'));
  const sameYear = key.slice(0, 4) === dayKey(now).slice(0, 4);
  return low(formatCalendarDate(key, sameYear ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' }));
}

// "09:00" or an instant: the time in the owner's 12/24 hour choice ("9:00 am")
export function whenTime(value) {
  const raw = String(value || '');
  if (/^\d{1,2}:\d{2}$/.test(raw)) return low(formatClock(raw));
  const wall = /T(\d{2}:\d{2})(?::\d{2}(?:\.\d+)?)?$/.exec(raw);
  if (wall) return low(formatClock(wall[1]));
  const parsed = new Date(raw);
  if (!raw.includes('T') || Number.isNaN(parsed.valueOf())) return '';
  const parts = Object.fromEntries(formatDateParts(parsed, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).map(p => [p.type, p.value]));
  return low(formatClock(`${parts.hour}:${parts.minute}`));
}

// a day plus its time when there is one: "tomorrow 9:00 am", "sun", "nov 12 3:30 pm"
export function when(value, { time = '', now } = {}) {
  const day = whenDay(value, { now });
  const clock = time ? whenTime(time) : whenTime(value);
  return clock ? `${day} ${clock}` : day;
}

// the full date for hover and long press: "sunday, november 1, 2026"
const fullDays = new Map();
export function whenFull(value, { time = '' } = {}) {
  const key = dayKey(value);
  if (!key) return '';
  const memo = `${localeTag()}|${key}`;   // a year grid asks for 365 of these at once
  let day = fullDays.get(memo);
  if (day === undefined) {
    day = low(formatCalendarDate(key, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }));
    if (fullDays.size > 800) fullDays.clear();
    fullDays.set(memo, day);
  }
  const clock = time ? whenTime(time) : whenTime(value);
  return clock ? `${day} ${clock}` : day;
}

// a <time> element: the short words, the full date in the title and on a long press
export function whenElement(value, options = {}) {
  const node = document.createElement('time');
  node.dateTime = dayKey(value);
  node.dataset.when = '';
  node.textContent = when(value, options);
  node.title = whenFull(value, options);
  return node;
}

export function whenHtml(value, options = {}) {
  const esc = text => String(text).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  return `<time datetime="${esc(dayKey(value))}" data-when title="${esc(whenFull(value, options))}">${esc(when(value, options))}</time>`;
}

// touch has no hover: holding a date for half a second shows the full date in place for 3s
if (typeof document !== 'undefined' && document.documentElement?.dataset && document.addEventListener && !document.documentElement.dataset.whenPress) {
  document.documentElement.dataset.whenPress = '1';
  let timer = 0;
  document.addEventListener('touchstart', event => {
    const node = event.target.closest?.('time[data-when]');
    if (!node?.title) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (node.dataset.short) return;
      node.dataset.short = node.textContent;
      node.textContent = node.title;
      setTimeout(() => { node.textContent = node.dataset.short; delete node.dataset.short; }, 3000);
    }, 500);
  }, { passive: true });
  for (const name of ['touchend', 'touchmove', 'touchcancel']) {
    document.addEventListener(name, () => clearTimeout(timer), { passive: true });
  }
}
