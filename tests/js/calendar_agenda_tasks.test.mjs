// overdue open tasks lead today in the calendar agenda, even on a day with nothing else on it
import { test } from 'node:test';
import assert from 'node:assert/strict';

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
globalThis.window = { addEventListener: _noop, dispatchEvent: _noop, location: { hostname: 'calendar.localhost' } };

const { agendaDays } = await import('../../static/js/calendar.js');

const later = { date: '2026-10-27', events: [{ id: 'e' }], tasks: [] };

test('overdue tasks bring today in at the top when it has nothing else', () => {
  const days = agendaDays({ today: '2026-10-24', overdue: [{ id: 't', due: '2026-10-20' }], days: [later] });
  assert.deepEqual(days.map(day => day.date), ['2026-10-24', '2026-10-27']);
  assert.deepEqual(days[0].events, []);
});

test('today is not doubled, and nothing overdue leaves the days alone', () => {
  const today = { date: '2026-10-24', events: [{ id: 'x' }], tasks: [] };
  assert.deepEqual(agendaDays({ today: '2026-10-24', overdue: [{ id: 't' }], days: [today, later] }), [today, later]);
  assert.deepEqual(agendaDays({ today: '2026-10-24', overdue: [], days: [later] }), [later]);
  assert.deepEqual(agendaDays({ days: [later] }), [later]);
  assert.deepEqual(agendaDays(null), []);
});

const { importFirstOnly } = await import('../../static/js/calendar.js');

test('the import receipt says how many series kept their first time only', () => {
  assert.equal(importFirstOnly(1), "1 event repeats in a way alles can't show yet; only its first time was imported");
  assert.equal(importFirstOnly(3), "3 events repeat in a way alles can't show yet; only their first time was imported");
});
