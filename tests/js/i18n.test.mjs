import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  configureLocalization,
  formatDateTime,
  localeTag,
  localizationState,
  t,
  textDirection,
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
  assert.equal(t('schedule.confirmed', { when: 'tomorrow' }), 'scheduled — aide will answer it tomorrow');
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
