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
  assert.match(source, /box\.querySelectorAll\('\[data-d\]'\)[\s\S]*?await navigateDay\(button\.dataset\.d\)/);
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
  assert.match(source, /journal could not refresh\. try again\./);
});

test('the year strip is a picture: no cell takes a click or a tab stop, the months are the way in', async () => {
  const { formatCalendarDate } = await import('../../static/js/i18n.js');
  const vm = await import('node:vm');
  const body = source.match(/function stopAt\([\s\S]*?\n}\n/)?.[0] + source.match(/async function loadHeatmap\(\) \{[\s\S]*?\n}\n/)?.[0];
  assert.ok(!body.includes('undefined'));
  assert.doesNotMatch(source, /grid_nav|wireGridNav/);
  const nodes = {}, days = [];
  const node = id => (nodes[id] ||= {
    id, textContent: '', disabled: false, html: '',
    set innerHTML(value) { this.html = value; }, get innerHTML() { return this.html; },
    contains: () => false, querySelectorAll: () => [], querySelector: () => null,
  });
  const context = vm.createContext({
    document: { getElementById: node, activeElement: null }, esc: s => String(s), formatCalendarDate,
    jget: async () => ({ year: 2026, days: { '2026-03-02': { level: 2, words: 120, mood: '' }, '2026-03-09': { level: 1, words: 20, mood: '' }, '2026-10-12': { level: 1, words: 30, mood: '' } } }),
    todayISO: () => '2026-10-23', _day: '2026-10-12', _heatYear: null, navigateDay: day => days.push(day),
  });
  vm.runInContext(body, context);
  await context.loadHeatmap();
  const html = nodes['jrnl-heatmap'].html;
  assert.match(html, /<div class="jrnl-heatgrid" role="img" aria-label="journal 2026: entries on 3 days, most in March"/);
  assert.doesNotMatch(html, /tabindex|role="gridcell"|role="row"|aria-owns/);
  assert.equal((html.match(/<span class="jrnl-hc[^"]*"[^>]*aria-hidden="true"/g) || []).length, (html.match(/<span class="jrnl-hc/g) || []).length);
  const months = [...html.matchAll(/<button type="button" class="jrnl-hm jrnl-heat-month"[^>]*data-month="([^"]+)"[^>]*>(\w+)<\/button>/g)];
  assert.equal(months.length, 12);
  assert.deepEqual([months[2][1], months[2][2]], ['2026-03-01', 'mar']);
  assert.match(months[2][0], /aria-label="mar 2026, 2 entries"/);
  // a month after today has nothing to open yet
  assert.match(months[10][0], /aria-disabled="true"/);
  assert.doesNotMatch(months[9][0], /aria-disabled/);
});

test('journal arrows are svg chevrons with names', () => {
  for (const id of ['jrnl-prev', 'jrnl-next', 'jrnl-heat-prev', 'jrnl-heat-next']) {
    assert.match(source, new RegExp(`id="${id}"[^>]*aria-label="[^"]+">\\$\\{_si\\('chevron-(left|right)'\\)\\}</button>`));
  }
});

test('a next arrow that turns disabled under focus hands focus to its opposite, not <body>', async () => {
  const vm = await import('node:vm');
  const fn = source.match(/function stopAt\([\s\S]*?\n}\n/)?.[0];
  assert.ok(fn);
  const next = { disabled: false }, prev = {};
  const document = { activeElement: next, getElementById: id => ({ 'jrnl-next': next, 'jrnl-prev': prev })[id] };
  prev.focus = () => { document.activeElement = prev; };
  const context = vm.createContext({ document });
  vm.runInContext(fn, context);
  context.stopAt('jrnl-next', 'jrnl-prev', false);
  assert.equal(document.activeElement, next);
  context.stopAt('jrnl-next', 'jrnl-prev', true);
  assert.equal(next.disabled, true);
  assert.equal(document.activeElement, prev);
  assert.match(source, /stopAt\('jrnl-next', 'jrnl-prev', _day >= todayISO\(\)\)/);
  assert.match(source, /stopAt\('jrnl-heat-next', 'jrnl-heat-prev', d\.year >= new Date\(\)\.getFullYear\(\)\)/);
});
