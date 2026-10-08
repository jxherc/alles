import test from 'node:test';
import assert from 'node:assert/strict';

const noop = () => {};
globalThis.localStorage = { getItem: () => null, setItem: noop };
globalThis.document = {
  getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, body: { classList: { toggle: noop, contains: () => false } },
  documentElement: { style: { setProperty: noop } },
};
globalThis.window = { addEventListener: noop, dispatchEvent: noop, location: { hostname: 'calendar.localhost' } };
const { configureLocalization } = await import('../../static/js/i18n.js');
const { editorDates, eventTimeValues, wallTimeForStorage } = await import('../../static/js/calendar.js');
const { dateTimeParts } = await import('../../static/js/datepick.js');
const zone = timezone => configureLocalization({ language: 'en', region: 'CA', timezone });

test('non-recurring overnight and inclusive all-day end dates survive opening', () => {
  zone('America/Toronto');
  const event = { start_dt: '2026-09-26T23:45', end_dt: '2026-09-27T00:30' };
  assert.deepEqual(editorDates(event, '2026-09-26'), { start: event.start_dt, end: event.end_dt });
  assert.equal(editorDates({ start_dt: '2026-09-27', end_dt: '2026-09-29', all_day: true }, '2026-09-27').end, '2026-09-29T00:00');
});

test('aware editor values display in selected zone and untouched values preserve exact instants', () => {
  zone('America/Toronto');
  const event = { start_dt: '2026-09-26T02:30:00Z', end_dt: '2026-09-26T03:30:15Z' };
  const initial = editorDates(event, '2026-09-25');
  assert.deepEqual(initial, { start: '2026-09-25T22:30', end: '2026-09-25T23:30' });
  assert.deepEqual(eventTimeValues(event, initial, initial), event);
});

test('all-series description edits retain origin; time edits apply a delta to that origin', () => {
  zone('America/Toronto');
  const event = { start_dt: '2026-09-25T23:45', end_dt: '2026-09-26T00:30', recurrence: 'weekly' };
  const initial = editorDates(event, '2026-10-02');
  assert.deepEqual(initial, { start: '2026-10-02T23:45', end: '2026-10-03T00:30' });
  assert.deepEqual(eventTimeValues(event, initial, initial), { start_dt: event.start_dt, end_dt: event.end_dt });
  assert.deepEqual(eventTimeValues(event, initial, { start: '2026-10-03T00:45', end: '2026-10-03T01:30' }), { start_dt: '2026-09-26T00:45', end_dt: '2026-09-26T01:30' });
});

test('single/following occurrences retain multi-day wall duration across DST', () => {
  zone('America/Toronto');
  const event = { start_dt: '2026-10-30T13:00:00Z', end_dt: '2026-10-31T14:00:00Z', recurrence: 'weekly' };
  const dates = editorDates(event, '2026-11-06');
  assert.deepEqual(dates, { start: '2026-11-06T09:00', end: '2026-11-07T10:00' });
  for (const scope of ['this', 'following']) {
    assert.deepEqual(eventTimeValues(event, dates, dates, scope), { start_dt: '2026-11-06T14:00:00.000Z', end_dt: '2026-11-07T15:00:00.000Z' });
  }
});

test('DST gap is rejected for aware events and both fold offsets are retained', () => {
  zone('America/Toronto');
  assert.throws(() => wallTimeForStorage('2026-03-08T02:30', '2026-03-01T07:30:00Z'), /does not exist/);
  assert.equal(wallTimeForStorage('2026-11-01T01:30', '2026-10-25T05:30:00Z'), '2026-11-01T05:30:00.000Z');
  assert.equal(wallTimeForStorage('2026-11-01T01:30', '2026-11-08T06:30:00Z'), '2026-11-01T06:30:00.000Z');
});

test('literal picker datetimes do not normalize a browser DST gap or change zones', () => {
  assert.deepEqual(dateTimeParts('2026-03-08T02:30'), { y: 2026, mo: 2, d: 8, h: 2, mi: 30 });
  assert.equal(dateTimeParts('2026-02-31T09:00'), null);
  assert.equal(dateTimeParts('2026-03-08T24:00'), null);
  assert.equal(dateTimeParts('2026-03-08T02:60'), null);
  assert.equal(dateTimeParts('2026-03-08T02:30Z'), null);
});

test('recurring aware events retain elapsed duration and precision through a clock change', () => {
  zone('America/Toronto');
  const event = { start_dt: '2026-11-01T03:30:05.123Z', end_dt: '2026-11-01T07:30:05.123Z', recurrence: 'weekly' };
  const initial = editorDates(event, '2026-11-07');
  assert.deepEqual(initial, { start: '2026-11-07T23:30', end: '2026-11-08T03:30' });
  const next = eventTimeValues(event, initial, initial, 'this');
  assert.deepEqual(next, { start_dt: '2026-11-08T04:30:05.123Z', end_dt: '2026-11-08T08:30:05.123Z' });
  assert.equal(new Date(next.end_dt) - new Date(next.start_dt), 4 * 3600000);
  const floating = { start_dt: '2026-10-31T23:30:05', end_dt: '2026-11-01T02:30:05', recurrence: 'weekly' };
  const dates = editorDates(floating, '2026-11-07');
  assert.deepEqual(eventTimeValues(floating, dates, dates, 'this'), { start_dt: '2026-11-07T23:30:05', end_dt: '2026-11-08T02:30:05' });
});

test('elapsed duration gives a valid end when the old wall-clock end falls in a spring gap', () => {
  zone('America/Toronto');
  const event = { start_dt: '2026-03-01T06:30:00Z', end_dt: '2026-03-01T07:30:00Z', recurrence: 'weekly' };
  const initial = editorDates(event, '2026-03-08');
  assert.deepEqual(initial, { start: '2026-03-08T01:30', end: '2026-03-08T03:30' });
  assert.deepEqual(eventTimeValues(event, initial, initial, 'this'), { start_dt: '2026-03-08T06:30:00.000Z', end_dt: '2026-03-08T07:30:00.000Z' });
});
