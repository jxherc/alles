import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { configureLocalization } from '../../static/js/i18n.js';
import { localDay, whenDay } from '../../static/js/when.js';

// 23:30 on nov 1 in toronto is already nov 2 in utc: "today" read off toISOString() was tomorrow
// every evening after 7 or 8 pm. the clock is pinned, so the check holds whatever time the suite runs
const EVENING = Date.parse('2026-11-02T04:30:00Z');

test('an evening clock in toronto is still the same local day', t => {
  configureLocalization({ language: 'en', region: 'CA', timezone: 'America/Toronto' });
  t.mock.timers.enable({ apis: ['Date'], now: EVENING });
  assert.equal(new Date().toISOString().slice(0, 10), '2026-11-02');
  assert.equal(localDay(), '2026-11-01');
});

test('a note due today is not overdue in the evening', t => {
  configureLocalization({ language: 'en', region: 'CA', timezone: 'America/Toronto' });
  t.mock.timers.enable({ apis: ['Date'], now: EVENING });
  const source = readFileSync(new URL('../../static/js/notes.js', import.meta.url), 'utf8')
    .replace(/^import .*;\n/gm, '').replace(/^export /gm, '') + '\n;globalThis.isOverdue = _isOverdue;';
  const context = { Date, fetch: async () => ({}), localDay, whenDay, t: key => key, toast() {}, initDatePicker() {}, document: {}, window: {}, console };
  vm.createContext(context);
  vm.runInContext(source, context);
  assert.equal(context.isOverdue('2026-11-01'), false);
  assert.equal(context.isOverdue('2026-10-31'), true);
  assert.equal(context.isOverdue('2026-11-02'), false);
});
