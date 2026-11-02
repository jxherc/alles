import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// u.02 in plan's agenda: the same time of day rule as home, checked at 9 am, 3 pm and 11 pm
const source = readFileSync(new URL('../../static/js/specialist_groups.js', import.meta.url), 'utf8');
const body = source.match(/export function agendaTimeline\(rows, hhmm\) \{[\s\S]*?\n\}/)[0].replace(/^export /, '');
const agendaTimeline = new Function(`${body}; return agendaTimeline;`)();

const rows = [
  { title: 'chem homework', type: 'task', overdue: true, time: '' },
  { title: 'class', type: 'event', time: '10:30', end: '11:45' },
  { title: 'gym', type: 'event', time: '17:30', end: '18:30' },
  { title: 'pack lunch', type: 'reminder', time: '21:00' },
  { title: 'read ch 4', type: 'task', time: '' },
];
const names = list => list.map(row => row.title);

test('at 9 am everything is still ahead, overdue first, the now line before the first timed row', () => {
  const { late, left, past, nowAt } = agendaTimeline(rows, '09:00');
  assert.deepEqual(names(late), ['chem homework']);
  assert.deepEqual(names(left), ['class', 'gym', 'pack lunch', 'read ch 4']);
  assert.deepEqual(past, []);
  assert.equal(nowAt, 0);
});

test('at 3 pm the class is over and drops under what is left', () => {
  const { left, past, nowAt } = agendaTimeline(rows, '15:00');
  assert.deepEqual(names(past), ['class']);
  assert.deepEqual(names(left), ['gym', 'pack lunch', 'read ch 4']);
  assert.equal(left[nowAt].title, 'gym');
});

test('an event in progress is not over until it ends', () => {
  const { past } = agendaTimeline(rows, '11:00');
  assert.deepEqual(past, []);
});

test('at 11 pm every timed row is over; the now line closes what is left', () => {
  const { left, past, nowAt } = agendaTimeline(rows, '23:00');
  assert.deepEqual(names(past), ['class', 'gym', 'pack lunch']);
  assert.deepEqual(names(left), ['read ch 4']);
  assert.equal(nowAt, left.length);
});
