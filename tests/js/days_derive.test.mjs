// _derive recomputes a days-event's mode/count against the viewer's local today.
// a recurring event resolved by the server to its next occurrence must never render as
// "N days since" just because the viewer's timezone is a day ahead of the server.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { _derive } from '../../static/js/days.js';

const JUN24 = new Date(2026, 5, 24);  // viewer's local "today"

test('recurring event the viewer is a day ahead of clamps to today, not "since"', () => {
  // server resolved the birthday to 2026-06-23 (its today); viewer is already on the 24th
  const r = _derive({ target: '2026-06-23', repeat: 'year' }, JUN24);
  assert.equal(r.mode, 'today');
  assert.equal(r.days, 0);
});

test('a non-recurring past event still reads "since"', () => {
  const r = _derive({ target: '2026-06-23', repeat: 'none' }, JUN24);
  assert.equal(r.mode, 'since');
  assert.equal(r.count, 1);
});

test('a future recurring event is unchanged (countdown)', () => {
  const r = _derive({ target: '2026-06-30', repeat: 'year' }, JUN24);
  assert.equal(r.mode, 'countdown');
  assert.equal(r.days, 6);
});

test('a recurring event on the viewer-server-aligned day is today', () => {
  const r = _derive({ target: '2026-06-24', repeat: 'month' }, JUN24);
  assert.equal(r.mode, 'today');
});
