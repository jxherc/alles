// u.05: a number with its change, and a quiet 30 day line
import test from 'node:test';
import assert from 'node:assert/strict';
import { balanceOn, balanceSeries, lastThirtyDays, monthBefore, signedFigure, sparkPath, sparkSvg, weekChange, weekChangeText } from '../../static/js/numbers.js';

const weight = [
  { date: '2026-10-19', value: 153.0, unit: 'lb' },
  { date: '2026-10-23', value: 152.6, unit: 'lb' },
  { date: '2026-10-25', value: 152.4, unit: 'lb' },
  { date: '2026-10-28', value: 151.9, unit: 'lb' },
  { date: '2026-11-01', value: 151.2, unit: 'lb' },
];

test('a measurement compares with the last reading a week or more earlier', () => {
  const change = weekChange(weight);
  assert.equal(change.from.date, '2026-10-25');
  assert.equal(weekChangeText(change, '2026-11-01', '2026-11-01'), '−1.2\u00a0lb this week');
});

test('a change is written in the places the readings were, with a true minus and a plus', () => {
  assert.equal(signedFigure(151.2 - 152.4, 1, 'lb'), '−1.2 lb');
  assert.equal(signedFigure(0.6, 1, 'h'), '+0.6 h');
  assert.equal(signedFigure(-34.99, 2), '−34.99');
});

test('no reading a week back, another unit, or no change says so quietly or nothing', () => {
  assert.equal(weekChange([{ date: '2026-11-01', value: 1, unit: 'lb' }]), null);
  assert.equal(weekChange([{ date: '2026-10-01', value: 150, unit: 'lb' }, { date: '2026-11-01', value: 151, unit: 'lb' }]), null);
  assert.equal(weekChange([{ date: '2026-10-25', value: 70, unit: 'kg' }, { date: '2026-11-01', value: 151, unit: 'lb' }]), null);
  assert.equal(weekChangeText(null, '2026-11-01', '2026-11-01'), '');
  const same = weekChange([{ date: '2026-10-25', value: 7, unit: 'h' }, { date: '2026-11-01', value: 7, unit: 'h' }]);
  assert.equal(weekChangeText(same, '2026-11-01', '2026-11-01'), 'no change this week');
});

test('a latest reading older than a week says that week, not this one', () => {
  const change = weekChange(weight);
  assert.equal(weekChangeText(change, '2026-11-01', '2026-11-20'), '−1.2\u00a0lb that week');
});

test('the last 30 days keep the days inside the window, oldest first', () => {
  const points = lastThirtyDays([{ date: '2026-09-01', value: 1 }, ...weight], '2026-11-01');
  assert.deepEqual(points.map(point => point.x), [16, 20, 22, 25, 29]);
  assert.deepEqual(lastThirtyDays(weight, 'nope'), []);
});

test('the line is a plain svg path, hidden from a screen reader, and absent when there is nothing to draw', () => {
  const svg = sparkSvg(lastThirtyDays(weight, '2026-11-01'));
  assert.match(svg, /^<svg [^>]*aria-hidden="true"[^>]*><path d="M[\d. ]+L/);
  assert.doesNotMatch(svg, /<script|on\w+=/);
  assert.equal(sparkSvg([{ x: 0, y: 5 }]), '');
  assert.equal(sparkPath([{ x: 0, y: 5 }, { x: 29, y: 5 }]), null, 'a flat line says nothing');
  const path = sparkPath([{ x: 0, y: 1 }, { x: 29, y: 3 }], 72, 20, 2);
  assert.equal(path, 'M2 18L70 2', 'low on the left, high on the right');
});

test('a balance walks back through its moves to the day asked for', () => {
  const moves = [{ date: '2026-10-30', amount: -25 }, { date: '2026-10-20', amount: -9.99 }, { date: '2026-12-01', amount: 500 }];
  assert.equal(balanceOn(735.46, moves, '2026-10-02', '2026-11-01'), 770.45, 'a move after today is not undone');
  assert.equal(balanceOn(735.46, moves, '2026-11-01', '2026-11-01'), 735.46);
  const series = balanceSeries(735.46, moves, '2026-11-01');
  assert.equal(series.length, 30);
  assert.equal(series.at(-1).value, 735.46);
  assert.equal(series[0].value, 770.45);
});

test('a month back keeps the day, held to the end of a shorter month', () => {
  assert.equal(monthBefore('2026-11-01'), '2026-10-01');
  assert.equal(monthBefore('2026-03-31'), '2026-02-28');
  assert.equal(monthBefore('2026-01-15'), '2025-12-15');
});
