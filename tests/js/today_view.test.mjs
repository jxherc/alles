import test from 'node:test';
import assert from 'node:assert/strict';

import { dailyRows, normalizeTodayPreferences } from '../../static/js/today.js';

test('needs you stays visible and malformed preferences are repaired', () => {
  const value = normalizeTodayPreferences({ order: ['briefs', 'briefs', 'bad'], visible: [], density: 'huge', shortcuts: ['tasks', 'bad'] }, ['tasks']);
  assert.deepEqual(value.order, ['briefs', 'needs_you', 'today', 'in_progress', 'shortcuts']);
  assert.deepEqual(value.visible, ['needs_you']);
  assert.equal(value.density, 'comfortable');
  assert.deepEqual(value.shortcuts, ['tasks']);
});

test('daily rows keep urgent work before ordinary due work', () => {
  const rows = dailyRows({ events: [], tasks: { overdue: [{ title: 'late' }], due_today: [{ title: 'now' }] }, reminders: [], renewing: [], day_events: [] });
  assert.equal(rows[0].title, 'late');
  assert.equal(rows[0].urgent, true);
  assert.equal(rows[1].title, 'now');
});

test('unfinished habits become local daily rows', () => {
  const rows = dailyRows({ events: [], tasks: {}, reminders: [], renewing: [], day_events: [], habits: [{ name: 'stretch' }] });
  assert.deepEqual(rows[0], { view: 'habits', meta: 'not done', title: 'stretch' });
});
