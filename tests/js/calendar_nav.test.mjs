// F17 — month navigation must not skip a month when the cursor is on the 29th-31st.
// plain Date.setMonth() overflows short months (May 31 + 1mo -> Jul 1). addMonths clamps;
// shift() now routes month paging through it instead of setMonth(). run: node --test this file.
import { test } from 'node:test';
import assert from 'node:assert/strict';

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
globalThis.window = { addEventListener: _noop, location: { hostname: 'calendar.localhost' } };

const { addMonths, buildCopy, queueSearchRender } = await import('../../static/js/calendar.js');

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
