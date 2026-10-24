import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { functionSource } from './helpers/mail_workflows_recovery.mjs';

const noop = () => {};
globalThis.localStorage = { getItem: () => null, setItem: noop };
globalThis.document = {
  getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, body: { classList: { toggle: noop, contains: () => false } },
  documentElement: { style: { setProperty: noop } },
};
globalThis.window = { addEventListener: noop, dispatchEvent: noop, location: { hostname: 'calendar.localhost' } };
const { configureLocalization } = await import('../../static/js/i18n.js');
const { expand, calendarPlacementDate, keptFrame, editorDates } = await import('../../static/js/calendar.js');
const zone = timezone => configureLocalization({ language: 'en', region: 'CA', timezone });
const pad = n => String(n).padStart(2, '0');
const wall = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const seen = (event, from = '2026-10-01T00:00', to = '2027-06-01T00:00') =>
  expand(calendarPlacementDate(from), calendarPlacementDate(to), [event]).map(o => wall(o._date));

// a tokyo sunday 09:00 series, its last day and a skipped day all in tokyo's own frame
const TOKYO_SUN = { id: 's', start_dt: '2026-10-25T09:00:00+09:00', end_dt: '2026-10-25T10:00:00+09:00',
  recurrence: 'weekly', recur_byday: 'SU', recur_until: '2026-11-22', recur_except: ['2026-11-08'] };

test('a kept offset repeats in its own frame and each start is read here', () => {
  zone('Asia/Tokyo');
  assert.deepEqual(seen(TOKYO_SUN), ['2026-10-25T09:00', '2026-11-01T09:00', '2026-11-15T09:00', '2026-11-22T09:00']);
  zone('America/Toronto');
  // saturdays, an hour earlier once the clocks go back; the skip hides the 7th, not the 8th
  assert.deepEqual(seen(TOKYO_SUN), ['2026-10-24T20:00', '2026-10-31T20:00', '2026-11-14T19:00', '2026-11-21T19:00']);
});

test('biweekly days count weeks in the frame, monthly keeps the frame\'s day', () => {
  zone('America/Toronto');
  const biweekly = { id: 'b', start_dt: '2026-10-26T08:00:00+09:00', end_dt: '2026-10-26T09:00:00+09:00',
    recurrence: 'weekly', recur_interval: 2, recur_byday: 'MO,SU', recur_count: 6 };
  assert.deepEqual(seen(biweekly), ['2026-10-25T19:00', '2026-10-31T19:00', '2026-11-08T18:00', '2026-11-14T18:00', '2026-11-22T18:00', '2026-11-28T18:00']);
  const monthly = { id: 'm', start_dt: '2026-12-01T09:00:00+09:00', end_dt: '2026-12-01T10:00:00+09:00', recurrence: 'monthly', recur_count: 5 };
  assert.deepEqual(seen(monthly), ['2026-11-30T19:00', '2026-12-31T19:00', '2027-01-31T19:00', '2027-02-28T19:00', '2027-03-31T20:00']);
  const utcDaily = { id: 'd', start_dt: '2026-10-30T07:00:00+09:00', end_dt: '2026-10-30T07:30:00+09:00',
    recurrence: 'daily', recur_until: '2026-11-05', recur_except: ['2026-11-02'] };
  assert.deepEqual(seen(utcDaily), ['2026-10-29T18:00', '2026-10-30T18:00', '2026-10-31T18:00', '2026-11-02T17:00', '2026-11-03T17:00', '2026-11-04T17:00']);
});

test('wall-time repeats expand exactly as before', () => {
  zone('America/Toronto');
  const naive = { id: 'n', start_dt: '2026-10-26T09:00', end_dt: '2026-10-26T10:00', recurrence: 'weekly',
    recur_byday: 'MO,TH', recur_until: '2026-11-12', recur_except: ['2026-11-05'] };
  assert.deepEqual(seen(naive), ['2026-10-26T09:00', '2026-10-29T09:00', '2026-11-02T09:00', '2026-11-09T09:00', '2026-11-12T09:00']);
  assert.equal(keptFrame(naive.start_dt), null);
  assert.equal(keptFrame('2026-10-25T09:00:00+09:00').offset, 9 * 3600000);
  assert.equal(keptFrame('2026-10-26T02:00:00Z').offset, 0);
});

test('an occurrence opens at its own moment', () => {
  zone('America/Toronto');
  assert.deepEqual(editorDates(TOKYO_SUN, '2026-11-14'), { start: '2026-11-14T19:00', end: '2026-11-14T20:00' });
});

test('the editor shows a kept offset\'s days as the days they land on here', () => {
  zone('America/Toronto');
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  const context = vm.createContext({ keptFrame, calendarPlacementDate,
    ymd: d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` });
  vm.runInContext(`${functionSource('frameShift', source)}\n${functionSource('shiftDay', source)}`, context);
  assert.equal(context.frameShift(TOKYO_SUN), -1, 'sunday in tokyo is saturday in toronto');
  assert.equal(context.frameShift({ ...TOKYO_SUN, start_dt: '2026-10-25T09:00' }), 0);
  assert.equal(context.shiftDay('2026-11-22', -1), '2026-11-21');
  // left as shown, the days go back as stored: a title-only save leaves the rule as it was
  assert.match(source, /if \(body\.recur_byday === _rulesShown\.byday\) body\.recur_byday = _rulesShown\.raw\.byday;/);
  assert.match(source, /storedDays \? storedDays\.map\(i => \(i \+ shift \+ 7\) % 7\)/);
});

test('the day view folds what doesn\'t fit at 44px into "+N", which lists them', () => {
  const source = readFileSync(new URL('../../static/js/calendar.js', import.meta.url), 'utf8');
  assert.match(source, /const fits = width => Math\.max\(2, Math\.floor\(\(colWidth\(width\) - 4\) \/ 44\)\);/);
  assert.match(source, /const folds = \(n, width\) => days\.length === 1 && n > fits\(width\);/);
  assert.match(source, /class="cal-tstack cal-tmore" role="button" tabindex="0" aria-label="\$\{esc\(name\)\}"/);
  assert.match(source, /const picked = await dlgChoose\(tr\('calendar\.overlap_pick'\), JSON\.parse\(stack\.dataset\.picks\)\);/);
});

test('an all-day row is its date wherever you are', () => {
  zone('America/Toronto');
  const once = { id: 'a', start_dt: '2026-10-30T00:00:00Z', end_dt: '2026-10-30T00:00:00Z', all_day: true };
  assert.deepEqual(seen(once).map(w => w.slice(0, 10)), ['2026-10-30']);
  const weekly = { id: 'w', start_dt: '2026-10-30T00:00:00+00:00', all_day: true, recurrence: 'weekly', recur_count: 2 };
  assert.deepEqual(seen(weekly).map(w => w.slice(0, 10)), ['2026-10-30', '2026-11-06']);
});
