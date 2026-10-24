import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { configureLocalization } from '../../static/js/i18n.js';

import {
  dailyRows,
  homeDayRequest,
  homeAidePreview,
  homeGreetingFor,
  homeScheduleRows,
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

test('home keeps the exact source identity and displayed occurrence for every daily row', () => {
  const rows = dailyRows({
    date: '2026-10-01',
    events: [{ id: 'event-1', title: 'repeat meeting' }],
    tasks: { overdue: [{ id: 'task-1', title: 'late' }], due_today: [{ id: 'task-2', title: 'due' }] },
    reminders: [{ id: 'reminder-1', text: 'call' }],
    renewing: [{ id: 'subscription-1', name: 'storage' }],
    day_events: [{ id: 'date-1', name: 'anniversary' }],
    habits: [{ id: 'habit-1', name: 'walk' }],
  });
  assert.deepEqual(rows.map(row => row.id), [
    'event-1', 'task-1', 'task-2', 'reminder-1', 'subscription-1', 'date-1', 'habit-1',
  ]);
  assert.equal(rows[0].occurrence, '2026-10-01');
});

test('unfinished habits become local daily rows', () => {
  const rows = dailyRows({ events: [], tasks: {}, reminders: [], renewing: [], day_events: [], habits: [{ name: 'stretch' }] });
  assert.deepEqual(rows[0], { view: 'habits', id: undefined, meta: 'not done', title: 'stretch', kind: 'habit' });
});

test('day request contains bounded visible context and stays a draft until the owner sends', () => {
  const request = homeDayRequest({
    needs_you: [{ title: 'review budget', summary: 'one item needs approval' }],
    today: { events: [{ time: '09:30', title: 'private calendar marker' }], tasks: {} },
  });
  assert.match(request, /review budget/);
  assert.match(request, /private calendar marker/);
  assert.match(request, /what matters first/);
  assert.ok(request.length < 20000);
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
  assert.match(app, /initToday\(\{ navigate: navigateTo, apps: HOME_PINNABLE_APPS, askAide: prepareHomeDayDraft, legacyShortcuts: readLegacyHomeShortcuts, openRecord: openHomeRecord \}\)/);
});

test('Home note confirmation precedes refresh and tasks use reviewed acceptance', () => {
  const today = readFileSync(new URL('../../static/js/today.js', import.meta.url), 'utf8');
  const submit = today.match(/form\.addEventListener\('submit'[\s\S]*?\n  }\);/)?.[0] || '';
  assert.match(submit, /await saveNote\(value, safeTitle\(value\)\);\s*homeNoteSaved\(result, value\)/);
  assert.match(submit, /preview: true, today: calendarDateKey\(\)/);
  assert.match(submit, /reviewed = await openCaptureReview\(proposal, submit, homeCaptureSaved\)/);
  assert.doesNotMatch(submit, /json\('\/api\/tasks'/);
  const confirmed = today.match(/function homeNoteSaved\([\s\S]*?\n}/)?.[0] || '';
  assert.ok(confirmed.indexOf('toast(') < confirmed.indexOf('void load()'));
  // on a phone the receipt sits in the page, so it never hides itself under the finger
  assert.match(confirmed, /if \(window\.matchMedia\?\.\('\(min-width: 761px\)'\)\.matches\) homeNoteSaved\.timer = setTimeout/);
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

test('daily rows keep every dated item no matter how many tasks are due', () => {
  const tasks = Array.from({ length: 15 }, (_, i) => ({ id: `t${i}`, title: `task ${i}` }));
  const rows = dailyRows({
    events: [], tasks: { overdue: tasks }, reminders: [{ id: 'r', text: 'call mom', at: '18:30' }],
    renewing: [], day_events: [{ id: 'd', name: 'birthday' }],
  });
  assert.ok(rows.some(row => row.id === 'r'));
  assert.ok(rows.some(row => row.id === 'd'));
  assert.equal(rows.length, 17);
});

test('home counts only hidden tasks as more in plan and always shows habits', () => {
  configureLocalization({ language: 'en' });
  const tasks = n => Array.from({ length: n }, (_, i) => ({ id: `t${i}`, title: `task ${i}` }));
  const habits = [{ id: 'h1', name: 'walk' }, { id: 'h2', name: 'stretch' }];
  const six = homeScheduleRows(dailyRows({ tasks: { overdue: tasks(6) }, habits }));
  assert.deepEqual(six.map(row => row.kind), [...Array(6).fill('task'), 'habit', 'habit']);
  const eight = homeScheduleRows(dailyRows({ tasks: { overdue: tasks(8) }, habits }));
  assert.equal(eight.filter(row => row.kind === 'habit').length, 2);
  assert.equal(eight.filter(row => row.kind === 'task').length, 6);
  assert.deepEqual(eight.at(-1), { view: 'plan', id: '', meta: '', title: '2 more tasks in plan', kind: 'more' });
});

test('home times read like the reminders list, in the owner\'s 12/24-hour choice', async () => {
  const { formatClock } = await import('../../static/js/i18n.js');
  try {
    configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto', clock_format: '12' });
    const rows = dailyRows({ date: '2026-10-23', events: [{ id: 'e', title: 'dentist', time: '14:05' }],
      reminders: [{ id: 'r', text: 'call mom', at: '19:30' }] });
    assert.equal(rows.find(row => row.kind === 'event').meta, '2:05 PM');
    assert.equal(rows.find(row => row.kind === 'reminder').meta, '7:30 PM');
    configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto', clock_format: '24' });
    assert.equal(formatClock('19:30'), '19:30');
    assert.equal(formatClock('not a time'), 'not a time');
  } finally {
    configureLocalization({});
  }
});

test('a reminder left over from an earlier day shows its date; today\'s keep the short time', async () => {
  const { formatDateTime } = await import('../../static/js/i18n.js');
  try {
    configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto', clock_format: '12' });
    const rows = dailyRows({ date: '2026-10-23', reminders: [
      { id: 'old', text: 'pay rent', at: '19:30', trigger_at: '2026-10-21T19:30:00-04:00' },
      { id: 'now', text: 'call mom', at: '08:15', trigger_at: '2026-10-23T08:15:00-04:00' },
      { id: 'legacy', text: 'no date', at: '09:00' },
      { id: 'last-year', text: 'renew', at: '10:00', trigger_at: '2025-12-30T10:00:00-05:00' },
    ] });
    const row = id => rows.find(item => item.id === id);
    // the full text is the reminders list's own (reminderTimeLabel); it feeds aide and the tooltip
    assert.equal(row('old').meta, formatDateTime('2026-10-21T19:30:00-04:00', { dateStyle: 'medium', timeStyle: 'short' }));
    assert.match(row('old').meta, /^Oct 21, 2026, 7:30\sPM$/);
    assert.equal(row('old').lines[0], 'Oct 21');
    assert.match(row('old').lines[1], /^7:30\sPM$/);
    assert.match(row('now').meta, /^8:15\sAM$/);
    assert.equal(row('now').lines, undefined);
    assert.match(row('legacy').meta, /^9:00\sAM$/);
    assert.equal(row('legacy').lines, undefined);
    assert.equal(row('last-year').lines[0], '12/30/25');
    const old = { id: 'old', text: 'pay rent', at: '19:30', trigger_at: '2026-10-21T19:30:00-04:00' };
    assert.match(homeDayRequest({ today: { date: '2026-10-23', reminders: [old] } }), /reminder: Oct 21, 2026, 7:30 PM — pay rent/);
    configureLocalization({ language: 'en', region: 'US', timezone: 'America/Toronto', clock_format: '24' });
    const late = dailyRows({ date: '2026-10-23', reminders: [{ id: 'x', text: 'x', at: '23:45', trigger_at: '2026-10-22T23:45:00-04:00' }] });
    assert.deepEqual(late[0].lines, ['Oct 22', '23:45']);
  } finally {
    configureLocalization({});
  }
});

test('home draws a left-over reminder as day over time, escaped', () => {
  const today = readFileSync(new URL('../../static/js/today.js', import.meta.url), 'utf8');
  const row = today.match(/function dayRow\([\s\S]*?\n}/)?.[0] || '';
  assert.match(row, /item\.lines\.map\(esc\)\.join\('<br>'\)/);
  assert.match(row, /title="\$\{esc\(item\.meta\)\}"/);
});
