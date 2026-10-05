import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const money = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const i18n = readFileSync(new URL('../../static/js/i18n.js', import.meta.url), 'utf8')
  .replace(/^export /gm, '');
const catalogs = ['en', 'ar', 'ja', 'zh-Hans'].map(language => JSON.parse(
  readFileSync(new URL(`../../static/locales/${language}.json`, import.meta.url), 'utf8'),
));

function calendarHarness(instant, zone, language, query = '') {
  const RealDate = Date;
  class FixedDate extends RealDate {
    constructor(...args) { super(...(args.length ? args : [instant])); }
  }
  const context = vm.createContext({ Date: FixedDate, Intl, location: { search: query }, URLSearchParams });
  vm.runInContext(i18n, context);
  for (const catalog of catalogs) context.installCatalog(catalog);
  context.configureLocalization({ language, timezone: zone });
  vm.runInContext(money + `
    globalThis.subject = { today: _today, month: () => _month, addTxnRow, transferRow,
      _recurringForm, editTxnRow };
    _accounts = [{ id: 'owned', name: 'synthetic local account' },
      { id: 'second', name: 'synthetic transfer account' }];
  `, context);
  return context.subject;
}

test('Finance defaults follow configured calendar at day, month, year and daylight-saving boundaries', () => {
  const previous = process.env.TZ;
  try {
    for (const [browser, zone, instant, day] of [
      ['America/Toronto', 'UTC', '2026-11-01T02:00:00Z', '2026-11-01'],
      ['Asia/Tokyo', 'America/Toronto', '2026-11-01T02:00:00Z', '2026-10-31'],
      ['America/Toronto', 'UTC', '2027-01-01T02:00:00Z', '2027-01-01'],
      ['UTC', 'America/Toronto', '2026-03-08T06:59:00Z', '2026-03-08'],
      ['UTC', 'America/Toronto', '2026-03-08T07:01:00Z', '2026-03-08'],
      ['America/Toronto', '', '2026-11-01T02:00:00Z', '2026-10-31'],
    ]) {
      process.env.TZ = browser;
      for (const catalog of catalogs) {
        const h = calendarHarness(instant, zone, catalog.language);
        assert.equal(h.today(), day, `${browser}/${zone}/${catalog.language}`);
        assert.equal(h.month(), day.slice(0, 7));
        for (const form of [h.addTxnRow(), h.transferRow(), h._recurringForm()]) {
          assert.ok(form.includes(`data-value="${day}"`), form);
        }
      }
    }
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test('Finance explicit historical month and saved transaction date survive configured calendar defaults', () => {
  const h = calendarHarness('2027-01-01T02:00:00Z', 'UTC', 'ar', '?m=2025-06');
  assert.equal(h.month(), '2025-06');
  assert.equal(h.today(), '2027-01-01');
  const form = h.editTxnRow({ id: 'owned', account_id: 'owned', date: '2025-06-20', amount: -12.34 });
  assert.match(form, /data-value="2025-06-20"/);
});
