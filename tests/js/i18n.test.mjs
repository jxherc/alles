import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

import {
  calendarDateKey,
  cachedLocalizationSettings,
  configureLocalization,
  formatCalendarDate,
  formatCurrency,
  formatDateTime,
  formatList,
  formatNumber,
  formatRelativeTime,
  formatTime,
  installCatalog,
  loadCatalog,
  localeTag,
  localizationState,
  prepareLocalization,
  t,
  textDirection,
  tp,
} from '../../static/js/i18n.js';

test('locale combines the reviewed language and region', () => {
  assert.equal(localeTag('en', 'tw'), 'en-TW');
  assert.equal(localeTag('missing', 'US'), 'en-US');
});

test('direction helper is ready for future rtl catalogs', () => {
  assert.equal(textDirection('en'), 'ltr');
  assert.equal(textDirection('ar'), 'rtl');
});

test('unknown languages fall back to reviewed English messages', () => {
  configureLocalization({ language: 'fr', region: 'invalid', timezone: 'Taipei-ish' });
  assert.equal(localizationState().language, 'en');
  assert.equal(localizationState().region, '');
  assert.equal(localizationState().timezone, '');
  assert.equal(t('schedule.confirmed', { when: 'tomorrow' }), 'scheduled - aide will answer it tomorrow');
  assert.equal(t('missing.key'), 'missing.key');
});

test('date formatting honors the saved IANA timezone', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'Asia/Taipei' });
  const value = formatDateTime('2026-01-01T00:00:00Z', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23',
  });
  assert.match(value, /01\/01\/2026/);
  assert.match(value, /08/);
});

test('calendar date keys honor the saved IANA timezone', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'Pacific/Kiritimati' });
  assert.equal(calendarDateKey('2026-07-21T12:30:00Z'), '2026-07-22');
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Los_Angeles' });
  assert.equal(calendarDateKey('2026-07-22T02:30:00Z'), '2026-07-21');
});

test('date-only calendar labels do not shift through the saved timezone', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Los_Angeles' });
  assert.equal(
    formatCalendarDate('2026-07-01', { month: 'long', year: 'numeric' }),
    'July 2026',
  );
  configureLocalization({ language: 'en', region: 'US', timezone: 'Pacific/Kiritimati' });
  assert.equal(
    formatCalendarDate('2026-07-22', { month: 'short', day: 'numeric', year: 'numeric' }),
    'Jul 22, 2026',
  );
});

test('date-time formatting keeps the time when callers use the default', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'UTC', clock_format: '24' });
  const value = formatDateTime('2026-07-22T14:35:00Z');
  assert.match(value, /2026/);
  assert.match(value, /14:35/);
});

test('clock preference applies without overriding an explicit world-clock timezone', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'Asia/Taipei', clock_format: '24', week_start: 'mon' });
  const local = formatTime('2026-01-01T00:00:00Z', { hour: '2-digit', minute: '2-digit' });
  const world = formatTime('2026-01-01T00:00:00Z', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
  assert.match(local, /08:00/);
  assert.match(world, /24:00|00:00/);
  assert.equal(localizationState().clockFormat, '24');
  assert.equal(localizationState().weekStart, 'mon');
});

test('reviewed local catalogs translate messages and locale-specific plurals', async () => {
  const catalog = JSON.parse(await readFile(new URL('../../static/locales/ar.json', import.meta.url), 'utf8'));
  installCatalog(catalog);
  configureLocalization({ language: 'ar', region: 'TW' });
  assert.equal(t('locale.title'), 'اللغة والمنطقة');
  assert.match(tp('credits.item_count', 3), /3/);
  assert.equal(localizationState().direction, 'rtl');
});

test('catalog load failure keeps visible English fallback state', async () => {
  const result = await prepareLocalization(
    { language: 'fr', region: 'FR' },
    async () => ({ ok: false, json: async () => ({}) }),
  );
  assert.equal(result.fallback, true);
  assert.equal(localizationState().language, 'en');
  assert.equal(t('common.retry'), 'retry');
});

test('reviewed locale preferences are cached for a cold offline boot', async () => {
  const originalWindow = globalThis.window;
  const values = new Map();
  globalThis.window = {
    dispatchEvent: () => {},
    localStorage: {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    },
  };
  try {
    const catalog = JSON.parse(await readFile(new URL('../../static/locales/fr.json', import.meta.url), 'utf8'));
    await prepareLocalization(
      { language: 'fr', region: 'FR', timezone: 'Europe/Paris', currency: 'EUR', clock_format: '24', week_start: 'mon' },
      async () => ({ ok: true, json: async () => catalog }),
    );
    assert.deepEqual(cachedLocalizationSettings(), {
      language: 'fr',
      region: 'FR',
      timezone: 'Europe/Paris',
      clock_format: '24',
      week_start: 'mon',
      currency: 'EUR',
    });
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('number, currency, list, and relative-time helpers share locale preferences', () => {
  configureLocalization({ language: 'en', region: 'TW', currency: 'twd' });
  assert.match(formatNumber(1234), /1,234/);
  assert.match(formatCurrency(1234), /1,234/);
  assert.equal(localizationState().effectiveCurrency, 'TWD');
  assert.match(formatList(['a', 'b']), /a/);
  assert.match(formatRelativeTime(-1, 'day'), /yesterday|1 day ago/);
});

test('built-in English stays available offline without a fetch', async () => {
  let fetched = false;
  const catalog = await loadCatalog('en', async () => {
    fetched = true;
    throw new Error('offline');
  });
  assert.equal(catalog.language, 'en');
  assert.equal(fetched, false);
});

test('automatic currency follows the configured or browser region without a USD fallback', () => {
  for (const [region, expected] of Object.entries({ CA: 'CAD', GB: 'GBP', AU: 'AUD', DE: 'EUR', BG: 'EUR', SA: 'SAR', ZW: 'ZWG' })) {
    configureLocalization({ language: 'en', region, currency: '' });
    assert.equal(localizationState().effectiveCurrency, expected);
    assert.doesNotThrow(() => formatCurrency(1234));
  }
  configureLocalization({ language: 'en', region: 'ZZ', currency: '' });
  assert.equal(localizationState().effectiveCurrency, '');
});
