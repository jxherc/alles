import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { configureLocalization } from '../../static/js/i18n.js';

import {
  dailyRows,
  homeAidePreview,
  homeGreetingFor,
  orderedVisibleHomeSections,
  normalizeTodayPreferences,
} from '../../static/js/today.js';

test('needs you stays visible and malformed preferences are repaired', () => {
  const value = normalizeTodayPreferences({ order: ['briefs', 'briefs', 'bad'], visible: [], density: 'huge', shortcuts: ['tasks', 'bad'] }, ['plan']);
  assert.deepEqual(value.order, ['briefs', 'needs_you', 'today', 'in_progress', 'shortcuts']);
  assert.deepEqual(value.visible, ['needs_you']);
  assert.equal(value.density, 'comfortable');
  assert.deepEqual(value.shortcuts, ['plan']);
});

test('saved Home order and visibility drive the five rendered sections', () => {
  const preferences = normalizeTodayPreferences({
    order: ['shortcuts', 'briefs', 'needs_you', 'today', 'in_progress'],
    visible: ['shortcuts', 'needs_you', 'in_progress'],
    density: 'compact',
    shortcuts: ['files'],
  }, ['files']);
  assert.deepEqual(orderedVisibleHomeSections(preferences), ['shortcuts', 'needs_you', 'in_progress']);
  assert.equal(preferences.density, 'compact');
  assert.deepEqual(preferences.shortcuts, ['files']);
});

test('an intentionally empty shortcut list stays empty', () => {
  const preferences = normalizeTodayPreferences({ shortcuts: [] }, ['plan', 'wiki', 'files']);
  assert.deepEqual(preferences.shortcuts, []);
});

test('retired Home shortcut routes collapse onto canonical Phase 12 workbenches', () => {
  const preferences = normalizeTodayPreferences(
    { shortcuts: ['calendar', 'tasks', 'mail', 'journal', 'photos', 'watch'] },
    ['plan', 'inbox', 'wiki', 'files', 'system'],
  );
  assert.deepEqual(preferences.shortcuts, ['plan', 'inbox', 'wiki', 'files', 'system']);
});

test('daily rows keep urgent work before ordinary due work', () => {
  const rows = dailyRows({ events: [], tasks: { overdue: [{ title: 'late' }], due_today: [{ title: 'now' }] }, reminders: [], renewing: [], day_events: [] });
  assert.equal(rows[0].title, 'late');
  assert.equal(rows[0].urgent, true);
  assert.equal(rows[1].title, 'now');
});

test('unfinished habits become local daily rows', () => {
  const rows = dailyRows({ events: [], tasks: {}, reminders: [], renewing: [], day_events: [], habits: [{ name: 'stretch' }] });
  assert.deepEqual(rows[0], { view: 'habits', meta: 'not done', title: 'stretch', kind: 'habit' });
});

test('home aide preview removes markdown and stays brief', () => {
  const preview = homeAidePreview(`*Baby don't hurt me.* But seriously — **love** is an emotion.\n\n- first point\n- second point ${'more words '.repeat(30)}`);
  assert.ok(!preview.includes('*'));
  assert.ok(!preview.includes('\n'));
  assert.ok(preview.length <= 181);
  assert.match(preview, /love is an emotion/);
  assert.ok(preview.endsWith('…'));
});

test('home copy is varied by time period and can stay fixed while the clock updates', () => {
  const morning = homeGreetingFor(new Date('2026-07-14T08:00:00'), () => 0.99);
  const evening = homeGreetingFor(new Date('2026-07-14T20:00:00'), () => 0.99);
  assert.equal(morning.period, 'morning');
  assert.equal(evening.period, 'evening');
  assert.notEqual(morning.text, 'good morning');
  assert.notEqual(evening.text, 'good evening');
});

test('home greeting follows the configured timezone hour', () => {
  configureLocalization({ language: 'en', region: 'TW', timezone: 'Asia/Taipei' });
  const greeting = homeGreetingFor(new Date('2026-07-14T00:00:00Z'), () => 0);
  assert.equal(greeting.period, 'morning');
});

test('Home presents configured destinations as pinned apps without an unexplained count', () => {
  const today = readFileSync(new URL('../../static/js/today.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../../static/js/app.js', import.meta.url), 'utf8');
  assert.match(today, /<h2>\$\{esc\(t\('home\.pinned_apps'\)\)\}<\/h2>/);
  assert.match(today, /data-home-pinned-edit aria-label="\$\{esc\(t\('home\.edit_pinned_apps'\)\)\}"/);
  assert.doesNotMatch(today, /'shortcuts',\s*preferences\?\.shortcuts\?\.length/);
  for (const view of ['plan', 'inbox', 'wiki', 'files', 'library', 'health', 'finance', 'vault', 'system']) {
    assert.match(app, new RegExp(`HOME_PINNABLE_APPS[\\s\\S]*?view: '${view}'`));
  }
  assert.doesNotMatch(app.match(/const HOME_PINNABLE_APPS = \[[\s\S]*?\n\];/)?.[0] || '', /view: '(?:calendar|tasks|mail|money|photos|watch|activity)'/);
  assert.match(app, /initToday\(\{ navigate: navigateTo, apps: HOME_PINNABLE_APPS \}\)/);
});

test('a successful Home capture is confirmed independently of a partial refresh', () => {
  const today = readFileSync(new URL('../../static/js/today.js', import.meta.url), 'utf8');
  const submit = today.match(/form\.addEventListener\('submit'[\s\S]*?\n  }\);/)?.[0] || '';
  assert.match(submit, /toast\(asTask \? t\('home\.task_added'\) : t\('home\.note_saved'\), 'success'\)/);
  assert.ok(submit.indexOf('toast(') < submit.indexOf('await load()'));
  assert.doesNotMatch(submit, /if \(refreshed\)/);
});

test('a stale Home refresh cannot overwrite the latest date or status', () => {
  const today = readFileSync(new URL('../../static/js/today.js', import.meta.url), 'utf8');
  const load = today.match(/async function load\(\) \{[\s\S]*?\n}\n\nfunction safeTitle/)?.[0] || '';
  assert.match(today, /let loadGeneration = 0;/);
  assert.match(load, /const generation = \+\+loadGeneration;/);
  assert.ok((load.match(/generation !== loadGeneration/g) || []).length >= 5);
  assert.ok(load.indexOf('generation !== loadGeneration') < load.indexOf('data = today.sections'));
  assert.ok(load.lastIndexOf('generation !== loadGeneration') < load.lastIndexOf('showStatus'));
});
