import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { formatClock, t } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const cut = source.slice(source.indexOf('const cut = '), source.indexOf('async function loadDayStarts'));
assert.ok(cut.includes('export function dayStartsFrom'), 'exercise the real starter builder');

function startsFor(today, hour = '09:00') {
  const context = vm.createContext({
    t,
    formatClock,
    Date: class extends Date {
      toTimeString() { return `${hour}:00 GMT`; }
    },
  });
  vm.runInContext(`${cut.replace('export ', '')}\nglobalThis.dayStartsFrom = dayStartsFrom;`, context);
  return JSON.parse(JSON.stringify(context.dayStartsFrom(today)));
}

test('starts name the real things in the owner day', () => {
  const starts = startsFor({
    tasks: { overdue: [{ title: 'hand in lab report' }], due_today: [{ title: 'a' }, { title: 'b' }] },
    events: [{ title: 'chem unit test', time: '09:30', all_day: false }],
    habits: [{ name: 'gym' }],
  });
  assert.deepEqual(starts.map(([label]) => label), [
    'overdue: hand in lab report',
    'get ready for chem unit test',
    'log gym',
    'due today (2)',
  ]);
  assert.match(starts[1][1], /chem unit test today at/);
  assert.equal(starts[2][1], 'log gym for today.');
});

test('several overdue tasks collapse into one start with the count', () => {
  const starts = startsFor({ tasks: { overdue: [{ title: 'a' }, { title: 'b' }, { title: 'c' }] } });
  assert.deepEqual(starts.map(([label]) => label), ['overdue tasks (3)']);
});

test('an event that already went by is skipped, and a quiet day gives no starts', () => {
  const past = startsFor({ events: [{ title: 'standup', time: '08:00' }, { title: 'lunch', time: '12:30' }] });
  assert.deepEqual(past.map(([label]) => label), ['get ready for lunch']);
  assert.deepEqual(startsFor({}), []);
  assert.deepEqual(startsFor({ tasks: { overdue: [], due_today: [] }, events: [], habits: [] }), []);
});

test('a long name is cut for the label and kept whole in what is sent', () => {
  const title = 'write the full chemistry unit test study plan for friday morning';
  const [[label, text]] = startsFor({ tasks: { overdue: [{ title }] } });
  assert.ok(label.length < 'overdue: '.length + 29);
  assert.ok(label.endsWith('…'));
  assert.ok(text.includes(title));
});

test('the welcome row is drawn from the day, with the generic starts as the fallback', () => {
  assert.match(source, /list\.length \? list : STARTS\(\)/);
  assert.match(source, /void fillWelcomeStarts\(\)/);
  assert.match(source, /fetch\('\/api\/today'\)/);
});
