// F17 — month navigation must not skip a month when the cursor is on the 29th-31st.
// plain Date.setMonth() overflows short months (May 31 + 1mo -> Jul 1). addMonths clamps;
// shift() now routes month paging through it instead of setMonth(). run: node --test this file.
import { test } from 'node:test';
import assert from 'node:assert/strict';

process.env.TZ = 'America/New_York';

// calendar.js reads localStorage + defines DOM-bound handlers; stub the globals before import.
const _store = new Map([['cal-view', 'month']]);
globalThis.localStorage = {
  getItem: k => (_store.has(k) ? _store.get(k) : null),
  setItem: (k, v) => _store.set(k, String(v)),
  removeItem: k => _store.delete(k),
};
const _noop = () => {};
const _el = new Proxy({}, { get: () => _noop });
globalThis.document = {
  getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
  createElement: () => _el, addEventListener: _noop,
  body: { classList: { toggle: _noop, contains: () => false, add: _noop, remove: _noop } },
  documentElement: { style: { setProperty: _noop } },
};
globalThis.window = {
  addEventListener: _noop,
  dispatchEvent: _noop,
  location: { hostname: 'calendar.localhost' },
};

const { configureLocalization } = await import('../../static/js/i18n.js');
const {
  addMonths,
  buildCopy,
  calendarPlacementDate,
  queueSearchRender,
  resolveCalendarWeekStart,
} = await import('../../static/js/calendar.js');

const ym = d => [d.getFullYear(), d.getMonth() + 1, d.getDate()];

test('May 31 + 1 month lands in June, not July', () => {
  assert.deepEqual(ym(addMonths(new Date(2026, 4, 31), 1)), [2026, 6, 30]); // June has 30 days
});

test('Jan 31 + 1 month lands in February (clamped), not March', () => {
  assert.deepEqual(ym(addMonths(new Date(2026, 0, 31), 1)), [2026, 2, 28]);
});

test('Mar 31 - 1 month lands in February, not skipping back to Jan-ish', () => {
  assert.deepEqual(ym(addMonths(new Date(2026, 2, 31), -1)), [2026, 2, 28]);
});

test('forward across year boundary keeps the day when valid', () => {
  assert.deepEqual(ym(addMonths(new Date(2026, 11, 15), 1)), [2027, 1, 15]); // Dec 15 -> Jan 15
});

test('mid-month days are unaffected', () => {
  assert.deepEqual(ym(addMonths(new Date(2026, 5, 10), 1)), [2026, 7, 10]);
  assert.deepEqual(ym(addMonths(new Date(2026, 5, 10), -1)), [2026, 5, 10]);
});

test('calendar search render is debounced', async () => {
  let renders = 0;
  queueSearchRender('a', () => { renders += 1; }, 5);
  queueSearchRender('ab', () => { renders += 1; }, 5);
  queueSearchRender('abc', () => { renders += 1; }, 5);

  assert.equal(renders, 0);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(renders, 1);
});

test('calendar week start follows the universal locale preference', () => {
  assert.equal(resolveCalendarWeekStart({ week_start: 'mon', region: 'US' }), 1);
  assert.equal(resolveCalendarWeekStart({ week_start: 'sun', region: 'FR' }), 0);
  assert.equal(resolveCalendarWeekStart({ week_start: 'auto', region: 'US' }), 0);
  assert.equal(resolveCalendarWeekStart({ week_start: 'auto', region: 'FR' }), 1);
  assert.equal(resolveCalendarWeekStart({ week_start: 'auto', cal_week_start: 'sun', region: 'FR' }), 1);
  assert.equal(resolveCalendarWeekStart({ cal_week_start: 'sun', region: 'FR' }), 0);
  assert.equal(resolveCalendarWeekStart({ weekStart: 'mon', effectiveRegion: 'US' }), 1);
  const afLocale = new Intl.Locale('en-AF');
  const afInfo = typeof afLocale.getWeekInfo === 'function' ? afLocale.getWeekInfo() : afLocale.weekInfo;
  if (afInfo) {
    assert.equal(resolveCalendarWeekStart({ week_start: 'auto', region: 'AF' }), afInfo.firstDay % 7);
  }
});

test('calendar recomputes week start when localization changes', async () => {
  const source = await import('node:fs').then(fs => fs.readFileSync(
    new URL('../../static/js/calendar.js', import.meta.url), 'utf8'));
  assert.match(
    source,
    /alles:localization-change[^]*?_weekStart = resolveCalendarWeekStart\(event\.detail \|\| \{\}\)[^]*?render\(\)/,
  );
  assert.match(source, /return info\.firstDay % 7/);
});

test('calendar placement follows the selected timezone and preserves naive wall times', async () => {
  configureLocalization({ language: 'en', region: 'NZ', timezone: 'Pacific/Auckland' });
  const auckland = calendarPlacementDate('2026-07-21T12:30:00Z');
  assert.deepEqual(
    [auckland.getFullYear(), auckland.getMonth() + 1, auckland.getDate(), auckland.getHours(), auckland.getMinutes()],
    [2026, 7, 22, 0, 30],
  );
  const wall = calendarPlacementDate('2026-07-21T09:15');
  assert.deepEqual(
    [wall.getFullYear(), wall.getMonth() + 1, wall.getDate(), wall.getHours(), wall.getMinutes()],
    [2026, 7, 21, 9, 15],
  );
  configureLocalization({ language: 'en', region: 'US', timezone: 'UTC' });
  const browserGap = calendarPlacementDate('2026-03-08T02:30:00Z');
  assert.deepEqual(
    [browserGap.getFullYear(), browserGap.getMonth() + 1, browserGap.getDate(), browserGap.getHours(), browserGap.getMinutes()],
    [2026, 3, 8, 2, 30],
  );
  const naiveGap = calendarPlacementDate('2026-03-08T02:30');
  assert.deepEqual(
    [naiveGap.getFullYear(), naiveGap.getMonth() + 1, naiveGap.getDate(), naiveGap.getHours(), naiveGap.getMinutes()],
    [2026, 3, 8, 2, 30],
  );
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Los_Angeles' });
  const losAngeles = calendarPlacementDate('2026-07-21T12:30:00Z');
  assert.deepEqual(
    [losAngeles.getFullYear(), losAngeles.getMonth() + 1, losAngeles.getDate(), losAngeles.getHours(), losAngeles.getMinutes()],
    [2026, 7, 21, 5, 30],
  );

  const source = await import('node:fs').then(fs => fs.readFileSync(
    new URL('../../static/js/calendar.js', import.meta.url), 'utf8'));
  assert.match(source, /calendarPlacementDate\(e\.start_dt\)/);
  assert.match(source, /timeShort = dt => formatTime\(dt,[\s\S]*?hour: 'numeric', minute: '2-digit',[\s\S]*?\}\);/);
  assert.match(source.match(/const timeShort[\s\S]*?\}\);/)?.[0] || '', /CalendarWallDate \? 'UTC' : _browserTimeZone\(\)/);
});

test('calendar no longer exposes a conflicting per-app week-start choice', async () => {
  const source = await import('node:fs').then(fs => fs.readFileSync(
    new URL('../../static/js/appsettings.js', import.meta.url), 'utf8'));
  assert.doesNotMatch(source, /\{ k: 'cal_week_start'/);
});

test('calendar recurrence bounds use the same wall-date representation as events', async () => {
  const source = await import('node:fs').then(fs => fs.readFileSync(
    new URL('../../static/js/calendar.js', import.meta.url), 'utf8'));
  assert.match(source, /expand\(_calendarWallDate\(year, 0, 1\), _calendarWallDate\(year \+ 1, 0, 1\)\)/);
  assert.match(source, /const rangeStart = _calendarWallDate\(year, month, 1 - startDay\)/);
  assert.match(source, /const rangeEnd = _calendarWallDate\(year, month, daysInMonth \+ 7\)/);
  assert.doesNotMatch(source, /_cursor = new Date\(c\.dataset\.date \+ 'T00:00:00'\)/);
});

test('recurring drag copy keeps the video link', () => {
  const copy = buildCopy({
    title: 'standup',
    calendar_id: 'cal',
    description: '',
    location: '',
    guests: '',
    all_day: false,
    color: '',
    meeting_url: 'https://meet.example/room',
    reminders: [],
    start_dt: '2026-07-02T09:00',
    end_dt: '2026-07-02T09:30',
    recurrence: 'weekly',
    recur_interval: 1,
    recur_byday: 'TH',
    recur_count: null,
    recur_until: null,
  }, {
    start_dt: '2026-07-09T10:00',
    end_dt: '2026-07-09T10:30',
    recurrence: '',
  });
  assert.equal(copy.meeting_url, 'https://meet.example/room');
});

test('editing recurrence end values selects the matching custom radio choice', async () => {
  const source = await import('node:fs').then(fs => fs.readFileSync(
    new URL('../../static/js/calendar.js', import.meta.url), 'utf8'));
  assert.match(source, /function selectEndsMode\(value\)/);
  assert.match(source, /getElementById\('cal-until'\)[\s\S]{0,320}selectEndsMode\('on'\)/);
  assert.match(source, /getElementById\('cal-count'\)[\s\S]{0,320}selectEndsMode\('after'\)/);
  assert.match(source, /choice\.tabIndex = selected \? 0 : -1/);
  assert.match(source, /event\.key === 'ArrowRight'[\s\S]{0,700}choices\[next\]\.focus\(\)/);
});
