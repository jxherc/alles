import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { HABIT_CATALOG, HABIT_GROUPS, catalogOptions } from '../../static/js/habit_catalog.js';
import { durationText, hasLogger, logSummary, matchExercises } from '../../static/js/habit_loggers.js';

const KINDS = ['check', 'workout', 'reading', 'count', 'duration', 'distance'];
const LANGUAGES = ['en', 'fr', 'es', 'zh-Hans', 'zh-Hant', 'ja', 'ko', 'ar'];

test('the catalog is a real choice: ~50 unique habits, every kind valid, grouped in order', () => {
  assert.ok(HABIT_CATALOG.length >= 45, `only ${HABIT_CATALOG.length} habits`);
  assert.equal(new Set(HABIT_CATALOG.map(entry => entry.id)).size, HABIT_CATALOG.length);
  assert.equal(new Set(HABIT_CATALOG.map(entry => entry.icon)).size, HABIT_CATALOG.length);
  for (const entry of HABIT_CATALOG) {
    assert.ok(KINDS.includes(entry.kind), entry.id);
    assert.ok(HABIT_GROUPS.includes(entry.group), entry.id);
    assert.equal(Boolean(entry.unit), entry.kind === 'count' || entry.kind === 'distance', entry.id);
  }
  // dialog.pick() draws a heading each time the group changes, so groups must not repeat
  const order = HABIT_CATALOG.map(entry => entry.group).filter((group, at, all) => group !== all[at - 1]);
  assert.deepEqual(order, HABIT_GROUPS);
  const workout = catalogOptions().find(option => option.value === 'workout');
  assert.equal(workout.icon, '🏋️');
  assert.match(workout.words, /gym/);
});

test('every catalog name, group and unit has a translation in all eight languages', async () => {
  const keys = [
    ...HABIT_CATALOG.map(entry => `habits.cat_${entry.id}`),
    ...HABIT_GROUPS.map(group => `habits.group_${group}`),
  ];
  const plurals = ['sets', 'reps', 'steps', 'glasses', 'servings', 'words', 'cards', 'pages', 'chapters'].map(unit => `habits.n_${unit}`);
  const english = JSON.parse(await readFile(new URL('../../static/locales/en.json', import.meta.url), 'utf8'));
  for (const language of LANGUAGES) {
    const catalog = JSON.parse(await readFile(new URL(`../../static/locales/${language}.json`, import.meta.url), 'utf8'));
    for (const key of keys) {
      assert.ok(catalog.messages[key], `${language} ${key}`);
      if (language !== 'en' && !['habits.cat_yoga', 'habits.cat_squats', 'habits.cat_gratitude', 'habits.cat_journal', 'habits.cat_sleep'].includes(key)) {
        assert.notEqual(catalog.messages[key], english.messages[key], `${language} ${key} is still english`);
      }
    }
    for (const key of plurals) assert.ok(catalog.plurals[key]?.other?.includes('{n}'), `${language} ${key}`);
  }
});

test('only typed habits get a logger', () => {
  assert.equal(hasLogger({ kind: 'check' }), false);
  assert.equal(hasLogger({}), false);
  for (const kind of ['workout', 'reading', 'count', 'duration', 'distance']) assert.equal(hasLogger({ kind }), true);
});

test('today summaries read like the owner writes them', () => {
  const workout = { kind: 'workout' };
  assert.equal(logSummary(workout, { rows: [{ exercise: 'lat pulldown', weight: 70, reps: 10, sets: 3 }] }), 'lat pulldown 70 × 10 · 3 sets');
  assert.equal(logSummary(workout, { rows: [{ exercise: 'push-ups', weight: null, reps: 20, sets: 1 }] }), 'push-ups × 20');
  assert.equal(logSummary(workout, { rows: [
    { exercise: 'squat', weight: 135, reps: 10, sets: 1 },
    { exercise: 'bench', weight: 95, reps: 8, sets: 2 },
    { exercise: 'row', weight: 60, reps: 10, sets: 1 },
  ] }), 'squat 135 × 10 +2 more');
  assert.equal(logSummary({ kind: 'reading' }, { amount: 24, unit: 'pages', book: 'dune' }), '24 pages · dune');
  assert.equal(logSummary({ kind: 'reading' }, { amount: 1, unit: 'chapters', book: '' }), '1 chapter');
  assert.equal(logSummary({ kind: 'count', unit: 'glasses' }, { amount: 6 }), '6 glasses');
  assert.equal(logSummary({ kind: 'count', unit: 'steps' }, { amount: 10500 }), '10,500 steps');
  assert.equal(logSummary({ kind: 'duration' }, { minutes: 45 }), '45 min');
  assert.equal(logSummary({ kind: 'distance' }, { distance: 5, unit: 'km', minutes: 28 }), '5 km · 28 min');
  assert.equal(logSummary({ kind: 'distance' }, { distance: 3.1, unit: 'mi', minutes: null }), '3.1 mi');
  assert.equal(logSummary({ kind: 'check' }, { amount: 1 }), '');
  assert.equal(logSummary(workout, null), '');
  assert.equal(durationText(480), '8 h');
  assert.equal(durationText(75), '1 h 15 min');
});

test('exercise suggestions put names that start with the typed text first', () => {
  const names = ['lat pulldown', 'bench press', 'leg press', 'squat', 'lateral raise'];
  assert.deepEqual(matchExercises(names, ''), names);
  assert.deepEqual(matchExercises(names, 'la'), ['lat pulldown', 'lateral raise']);
  assert.deepEqual(matchExercises(names, 'press'), ['bench press', 'leg press']);
  assert.deepEqual(matchExercises(names, 'squat'), [], 'an exact match has nothing left to suggest');
  assert.equal(matchExercises(Array.from({ length: 20 }, (_, at) => `move ${at}`), 'move').length, 8);
});
