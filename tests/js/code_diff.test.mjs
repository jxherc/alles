import test from 'node:test';
import assert from 'node:assert/strict';

const { lineDiff } = await import('../../static/js/aidecoding.js');

test('only changed lines are marked; the rest stays the same', () => {
  const rows = lineDiff('def add(a, b):\n    return a - b\n', 'def add(a, b):\n    return a + b\n');
  assert.deepEqual(rows, [
    ['same', 'def add(a, b):'],
    ['del', '    return a - b'],
    ['add', '    return a + b'],
    ['same', ''],
  ]);
});

test('a pure insert keeps every old line', () => {
  const rows = lineDiff('a\nb', 'a\nx\nb');
  assert.deepEqual(rows.map(([kind]) => kind), ['same', 'add', 'same']);
});
