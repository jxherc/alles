import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { configureLocalization, installCatalog } from '../../static/js/i18n.js';
import { addDays, dayKey, when, whenDay, whenFull, whenHtml, whenTime } from '../../static/js/when.js';

// today comes from the real clock, so every expected day is worked out from it (mistakes.md:
// never a fixed calendar date in a today based check)
const now = new Date();
const today = dayKey(now);

test('days near today read as words', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto', clock_format: '12' });
  const key = dayKey(new Date());
  assert.equal(whenDay(key), 'today');
  assert.equal(whenDay(addDays(key, 1)), 'tomorrow');
  assert.equal(whenDay(addDays(key, -1)), 'yesterday');
  assert.equal(whenDay(addDays(key, 9)), 'in 9 days');
  assert.equal(whenDay(addDays(key, -3)), '3 days ago');
});

test('inside the next week a day is its weekday, past two weeks the short date', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto' });
  const key = addDays(dayKey(new Date()), 4);
  const weekday = new Date(`${key}T12:00:00Z`).toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' }).toLowerCase();
  assert.equal(whenDay(key), weekday);
  const far = addDays(dayKey(new Date()), 30);
  const expect = new Date(`${far}T12:00:00Z`).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', timeZone: 'UTC', ...(far.slice(0, 4) === today.slice(0, 4) ? {} : { year: 'numeric' }),
  }).toLowerCase();
  assert.equal(whenDay(far), expect);
  assert.doesNotMatch(whenDay(far), /\d{4}-\d{2}-\d{2}/);
});

test('times follow the 12 or 24 hour setting, lowercase', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto', clock_format: '12' });
  assert.equal(whenTime('15:30'), '3:30 pm');
  assert.equal(when(addDays(dayKey(new Date()), 1), { time: '09:00' }), 'tomorrow 9:00 am');
  assert.equal(when(`${addDays(dayKey(new Date()), 1)}T09:00:00`), 'tomorrow 9:00 am');
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto', clock_format: '24' });
  assert.equal(whenTime('15:30'), '15:30');
});

test('the full date is there for hover and long press', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto', clock_format: '12' });
  assert.match(whenFull('2026-11-01'), /^sunday, november 1, 2026$/);
  const html = whenHtml(dayKey(new Date()));
  assert.match(html, /^<time datetime="\d{4}-\d{2}-\d{2}" data-when title="[^"]+">today<\/time>$/);
});

test('other languages get their own words', () => {
  installCatalog(JSON.parse(readFileSync(new URL('../../static/locales/fr.json', import.meta.url))));
  configureLocalization({ language: 'fr', region: 'FR', timezone: 'Europe/Paris' });
  assert.equal(whenDay(addDays(dayKey(new Date()), 1)), 'demain');
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto' });
});
