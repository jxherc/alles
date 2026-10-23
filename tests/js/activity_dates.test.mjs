import assert from 'node:assert/strict';
import test from 'node:test';
import { initActivity } from '../../static/js/activity.js';
import { configureLocalization } from '../../static/js/i18n.js';

const RealDate = Date;
const originalTimezone = process.env.TZ;
let now;
globalThis.Date = class extends RealDate {
  constructor(...args) { super(...(args.length ? args : [now])); }
  static now() { return new RealDate(now).valueOf(); }
};
const nodes = Object.fromEntries(['activity-body', 'activity-summary'].map(id => [id, {
  innerHTML: '', querySelector() { return null; }, querySelectorAll() { return []; },
}]));
globalThis.document = { documentElement: {}, getElementById: id => nodes[id] };
globalThis.location = { search: '' };
globalThis.localStorage = { getItem() { return null; } };

test.after(() => {
  globalThis.Date = RealDate;
  if (originalTimezone === undefined) delete process.env.TZ;
  else process.env.TZ = originalTimezone;
  delete globalThis.document;
  delete globalThis.location;
  delete globalThis.localStorage;
});

async function expectDay({ browserZone, timezone, clock, date, label, language = 'en' }) {
  process.env.TZ = browserZone;
  now = clock;
  configureLocalization({ language, region: 'US', timezone });
  await initActivity(async url => ({
    ok: true,
    json: async () => url.includes('/summary') ? {
      total: 2, by_type: [{ type: 'task', count: 1 }, { type: 'money', count: 1 }],
      busiest: { date, count: 2 },
    } : {
      events: [
        { ts: date + 'T12:00:00', type: 'task', title: 'synthetic task', id: 'task' },
        { ts: date + 'T00:00:00', type: 'money', title: 'synthetic expense', id: 'expense' },
      ],
    },
  }));
  assert.ok(nodes['activity-summary'].innerHTML.includes(`busiest · ${label} (2)`),
    nodes['activity-summary'].innerHTML);
  assert.deepEqual([...nodes['activity-body'].innerHTML.matchAll(/class="activity-day">([^<]+)</g)]
    .map(match => match[1]), [label]);
}

test('date-only summary and timestamp rows agree in Toronto and UTC', async () => {
  for (const timezone of ['America/Toronto', 'UTC']) {
    await expectDay({ browserZone: timezone, timezone, clock: '2026-10-04T20:00:00Z',
      date: '2026-10-04', label: 'today' });
    await expectDay({ browserZone: timezone, timezone, clock: '2026-10-04T20:00:00Z',
      date: '2026-10-03', label: 'yesterday' });
  }
});

test('relative days change at the configured midnight, independent of browser timezone', async () => {
  for (const browserZone of ['UTC', 'Asia/Tokyo']) {
    await expectDay({ browserZone, timezone: 'America/Toronto', clock: '2026-10-05T03:59:00Z',
      date: '2026-10-04', label: 'today' });
    await expectDay({ browserZone, timezone: 'America/Toronto', clock: '2026-10-05T04:01:00Z',
      date: '2026-10-04', label: 'yesterday' });
  }
});

test('calendar-day differences survive short and long daylight-saving days', async () => {
  for (const [clock, date] of [
    ['2026-03-09T04:05:00Z', '2026-03-08'],
    ['2026-11-02T05:05:00Z', '2026-11-01'],
  ]) {
    await expectDay({ browserZone: 'America/Toronto', timezone: 'America/Toronto',
      clock, date, label: 'yesterday' });
  }
});

test('older dates keep their stored day, weekday and year in the selected locale', async () => {
  await expectDay({ browserZone: 'UTC', timezone: 'America/Toronto',
    clock: '2026-10-04T20:00:00Z', date: '2026-10-02', label: 'Friday' });
  await expectDay({ browserZone: 'Asia/Tokyo', timezone: 'America/Toronto',
    clock: '2026-10-04T20:00:00Z', date: '2025-12-31', label: 'Dec 31, 2025' });
});
