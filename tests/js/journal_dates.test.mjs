import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

globalThis.sessionStorage = {
  getItem() { return null; },
  setItem() {},
  removeItem() {},
};
globalThis.location = { search: '' };

const { formatJournalDay, localISODate, shiftLocalISO } = await import('../../static/js/journal.js');
const { configureLocalization } = await import('../../static/js/i18n.js');
const source = readFileSync(new URL('../../static/js/journal.js', import.meta.url), 'utf8');

test('journal dates use local calendar components instead of UTC slicing', () => {
  const localMidnight = new Date(2026, 6, 22, 0, 5, 0);
  assert.equal(localISODate(localMidnight), '2026-07-22');
});

test('journal day navigation stays on calendar dates across DST boundaries', () => {
  assert.equal(shiftLocalISO('2026-03-08', 1), '2026-03-09');
  assert.equal(shiftLocalISO('2026-11-01', -1), '2026-10-31');
});

test('journal date-only headings do not shift through the configured timezone', () => {
  configureLocalization({ language: 'en', region: 'US', timezone: 'America/Los_Angeles' });
  assert.match(formatJournalDay('2026-07-23'), /July 23, 2026/);
  assert.doesNotMatch(formatJournalDay('2026-07-23'), /July 22, 2026/);
});

test('journal discards a response after the selected day changes', () => {
  assert.match(source, /const generation = \+\+_loadGeneration/);
  assert.match(source, /const requestedDay = _day/);
  assert.match(source, /generation !== _loadGeneration \|\| requestedDay !== _day/);
  assert.match(source, /jget\('\/api\/journal\/' \+ requestedDay\)/);
});

test('journal saves to the day captured before the request starts', () => {
  assert.match(source, /const savedDay = _day/);
  assert.match(source, /jput\('\/api\/journal\/' \+ savedDay/);
  assert.match(source, /if \(savedDay !== _day\) return/);
});

test('journal flushes edits before migration and preserves drafts across a lock transition', () => {
  const migration = source.match(/async function openMarkdownCopy\(\)[\s\S]*?\n}\n\nasync function/)?.[0] || '';
  assert.match(migration, /while \(_dirty \|\| _saveTimer !== null \|\| _saveInFlight !== null\)/);
  assert.match(migration, /if \(!await save\(false\)\)/);
  assert.ok(migration.indexOf('await save(false)') < migration.indexOf("'/api/journal-migration/plan'"));
  const lock = source.match(/function showLock\(mode\)[\s\S]*?\n}\n\nfunction curMood/)?.[0] || '';
  assert.match(lock, /_lockedDraft = draft/);
  assert.match(lock, /clearTimeout\(_saveTimer\)/);
  assert.match(lock, /_loadGeneration \+= 1/);
  assert.match(source, /const current = snapshotEditor\(\)/);
  assert.match(source, /const saved = document\.getElementById\('jrnl-saved'\)/);
});

test('journal flushes pending text before switching calendar days', () => {
  assert.match(source, /async function navigateDay\(nextDay\)/);
  assert.match(source, /while \(_dirty \|\| _saveTimer !== null \|\| _saveInFlight !== null\)[\s\S]*?if \(!await save\(false\)\)[\s\S]*?_day = nextDay/);
  assert.match(source, /jrnl-prev'\)\.onclick = \(\) => navigateDay/);
  assert.match(source, /jrnl-otd-row'[\s\S]*?navigateDay\(x\.dataset\.d\)/);
  assert.doesNotMatch(source, /_day\s*=.*;\s*load\(\)/);
});

test('failed or overlapping autosaves keep the entry dirty for navigation retry', () => {
  assert.match(source, /let _saveInFlight = null/);
  assert.match(source, /let _dirty = false/);
  assert.match(source, /if \(_saveInFlight !== null\)[\s\S]*?await _saveInFlight/);
  assert.match(source, /const previousSaved = await _saveInFlight;\s*if \(!_dirty\) return previousSaved/);
  assert.doesNotMatch(source, /if \(!previousSaved \|\| !_dirty\)/);
  assert.match(source, /if \(unchanged\) \{[\s\S]*?_dirty = false/);
  assert.match(source, /catch \(e\)[\s\S]*?return false/);
  assert.match(source, /jrnl-tags'\)\.addEventListener\('input', scheduleAutosave\)/);
});

test('journal hydration failures stay visible and immediately retryable', () => {
  assert.match(source, /catch \(error\) \{\s*_lastHydratedAt = 0/);
  assert.match(source, /Journal could not refresh\. Try again\./);
});
