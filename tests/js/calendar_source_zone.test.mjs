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
const { expand, calendarPlacementDate, keptFrame, editorDates } = await import('../../static/js/calendar.js');
const zone = timezone => configureLocalization({ language: 'en', region: 'CA', timezone });
const pad = n => String(n).padStart(2, '0');
const wall = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const grid = (event, from, to) =>
  expand(calendarPlacementDate(`${from}T00:00`), calendarPlacementDate(`${to}T00:00`), [event]).map(o => wall(o._date));

// the expected lists are services.calendar_events.occurrence_starts for the same rows, read in
// america/toronto (the server's answer for the agenda, reminders and export)
const LONDON = { id: 'l', start_dt: '2026-10-05T09:00:00+01:00', end_dt: '2026-10-05T10:00:00+01:00', recurrence: 'weekly',
  recur_byday: 'MO,FR', source_zone: 'Europe/London', recur_except: ['2026-11-02'] };
const SYDNEY = { id: 's', start_dt: '2027-03-01T09:00:00+11:00', end_dt: '2027-03-01T10:00:00+11:00', recurrence: 'weekly',
  recur_byday: '', source_zone: 'Australia/Sydney', recur_except: [] };
const PLAIN = { id: 'p', start_dt: '2026-10-05T09:00:00+01:00', end_dt: '2026-10-05T10:00:00+01:00', recurrence: 'weekly',
  recur_byday: 'MO', source_zone: '' };

test('a london series stays 09:00 in london while the clocks change on different days', () => {
  zone('America/Toronto');
  assert.deepEqual(grid(LONDON, '2026-10-18', '2026-11-15'), [
    '2026-10-19T04:00', '2026-10-23T04:00', '2026-10-26T05:00', '2026-10-30T05:00',
    '2026-11-06T04:00', '2026-11-09T04:00', '2026-11-13T04:00']);
});

test('a sydney series moves an hour when sydney leaves daylight saving', () => {
  zone('America/Toronto');
  assert.deepEqual(grid(SYDNEY, '2027-03-28', '2027-05-02'), [
    '2027-03-28T18:00', '2027-04-04T19:00', '2027-04-11T19:00', '2027-04-18T19:00', '2027-04-25T19:00']);
});

test('without a source zone the series keeps its offset, as before', () => {
  zone('America/Toronto');
  assert.deepEqual(grid(PLAIN, '2026-10-18', '2026-11-15'),
    ['2026-10-19T04:00', '2026-10-26T04:00', '2026-11-02T03:00', '2026-11-09T03:00']);
  assert.equal(keptFrame(PLAIN.start_dt, '').offset, 3600000);
});

test('an hour the source zone skips or repeats reads like the server', () => {
  zone('America/Toronto');
  const skipped = { id: 'g', start_dt: '2027-03-26T01:30:00+00:00', end_dt: '2027-03-26T02:00:00+00:00',
    recurrence: 'daily', recur_count: 5, source_zone: 'Europe/London' };
  assert.deepEqual(grid(skipped, '2027-03-25', '2027-04-02'),
    ['2027-03-25T21:30', '2027-03-26T21:30', '2027-03-27T21:30', '2027-03-28T20:30', '2027-03-29T20:30']);
  const repeated = { id: 't', start_dt: '2026-10-24T01:30:00+01:00', end_dt: '2026-10-24T02:00:00+01:00',
    recurrence: 'daily', recur_count: 4, source_zone: 'Europe/London' };
  assert.deepEqual(grid(repeated, '2026-10-23', '2026-10-31'),
    ['2026-10-23T20:30', '2026-10-24T20:30', '2026-10-25T21:30', '2026-10-26T21:30']);
});

test('a skipped day is the source zone\'s date, not the viewer\'s', () => {
  zone('America/Toronto');
  // sydney monday the 5th is toronto's sunday the 4th
  assert.deepEqual(grid({ ...SYDNEY, recur_except: ['2027-04-05'] }, '2027-04-01', '2027-04-12'), ['2027-04-11T19:00']);
  assert.deepEqual(grid({ ...SYDNEY, recur_except: ['2027-04-04'] }, '2027-04-01', '2027-04-12'), ['2027-04-04T19:00', '2027-04-11T19:00']);
});

test('an occurrence opens at its own moment, and an unreadable zone name falls back to the offset', () => {
  zone('America/Toronto');
  assert.deepEqual(editorDates(SYDNEY, '2027-04-11'), { start: '2027-04-11T19:00', end: '2027-04-11T20:00' });
  assert.equal(keptFrame(LONDON.start_dt, 'Europe/London').zone, 'Europe/London');
  assert.equal(keptFrame(LONDON.start_dt, 'Not/AZone').offset, 3600000);
  assert.equal(keptFrame('2026-10-05T09:00', 'Europe/London'), null);
});
