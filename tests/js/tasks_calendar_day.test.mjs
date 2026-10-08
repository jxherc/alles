import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const i18n = readFileSync(new URL('../../static/js/i18n.js', import.meta.url), 'utf8')
  .replace(/^export /gm, '');
const tasks = readFileSync(new URL('../../static/js/tasks.js', import.meta.url), 'utf8')
  .replace(/^import .*;$/gm, '').replace(/^export /gm, '');

function harness(instant, zone) {
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : [instant])); }
  }
  const requests = [];
  const context = vm.createContext({ Date: FixedDate, Intl,
    fetch: async (url, options) => { requests.push({ url, body: JSON.parse(options.body) }); },
  });
  vm.runInContext(i18n, context);
  context.configureLocalization({ language: 'en', timezone: zone });
  context.tr = context.t;
  vm.runInContext(tasks + `
    loadTasks = async () => {};
    globalThis.subject = { today: _todayISO, badge: _dueBadge, shift: _shift,
      reschedule: _reschedDate, addTask };
  `, context);
  return { ...context.subject, requests };
}

for (const [zone, instant, day, tomorrow, saturday] of [
  ['America/Toronto', '2026-10-06T00:50:00Z', '2026-10-05', '2026-10-06', '2026-10-10'],
  ['America/Toronto', '2026-10-06T04:01:00Z', '2026-10-06', '2026-10-07', '2026-10-10'],
  ['Asia/Tokyo', '2026-10-05T23:30:00Z', '2026-10-06', '2026-10-07', '2026-10-10'],
  ['Pacific/Kiritimati', '2026-12-31T12:30:00Z', '2027-01-01', '2027-01-02', '2027-01-02'],
  ['America/Toronto', '2027-01-01T02:00:00Z', '2026-12-31', '2027-01-01', '2027-01-02'],
  ['America/Toronto', '2026-03-08T06:59:00Z', '2026-03-08', '2026-03-09', '2026-03-14'],
  ['America/Toronto', '2026-03-08T07:01:00Z', '2026-03-08', '2026-03-09', '2026-03-14'],
  ['America/Toronto', '2026-11-01T05:59:00Z', '2026-11-01', '2026-11-02', '2026-11-07'],
  ['America/Toronto', '2026-11-01T06:01:00Z', '2026-11-01', '2026-11-02', '2026-11-07'],
]) {
  test(`task urgency and rescheduling share the configured calendar: ${zone} at ${instant}`, () => {
    const h = harness(instant, zone);
    assert.equal(h.today(), day);
    assert.equal(h.badge(day), '<span class="task-due today">today</span>');
    assert.equal(h.badge(tomorrow), '<span class="task-due">tomorrow</span>');
    const yesterday = h.shift(day, -1);
    assert.equal(h.badge(yesterday), `<span class="task-due overdue">${yesterday}</span>`);
    assert.equal(h.badge('2030-01-02'), '<span class="task-due">2030-01-02</span>');
    assert.equal(h.badge(null), '');
    assert.equal(h.reschedule('today'), day);
    assert.equal(h.reschedule('tomorrow'), tomorrow);
    assert.equal(h.reschedule('next_week'), h.shift(day, 7));
    assert.equal(h.reschedule('weekend'), saturday);
  });
}

test('calendar-only shifts and browser-default dates do not depend on the browser UTC offset', () => {
  const original = process.env.TZ;
  try {
    for (const browser of ['UTC', 'America/Toronto', 'Asia/Tokyo']) {
      process.env.TZ = browser;
      const h = harness('2026-10-06T00:50:00Z', 'America/Toronto');
      assert.equal(h.today(), '2026-10-05');
      assert.equal(h.shift('2026-12-31', 1), '2027-01-01');
      assert.equal(h.shift('2028-02-28', 1), '2028-02-29');
      assert.equal(h.shift('2028-02-29', 1), '2028-03-01');
      assert.equal(h.shift('2026-03-08', 1), '2026-03-09');
      const automatic = harness('2026-10-06T00:50:00Z', '');
      assert.equal(automatic.today(), browser === 'America/Toronto' ? '2026-10-05' : '2026-10-06');
    }
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
});

test('Plan quick capture sends the same calendar day as Home for relative instructions', async () => {
  const h = harness('2026-10-06T00:50:00Z', 'America/Toronto');
  await h.addTask('review reading tomorrow');
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/tasks/quick');
  assert.deepEqual(h.requests[0].body, { text: 'review reading tomorrow', today: '2026-10-05' });
});
