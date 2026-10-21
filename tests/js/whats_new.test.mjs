import test from 'node:test';
import assert from 'node:assert/strict';

const { unseen } = await import('../../static/js/whatsnew.js');
const list = [{ id: 'c' }, { id: 'b' }, { id: 'a' }];

test('a first visit shows only the newest release', () => {
  assert.deepEqual(unseen(list, '').map(r => r.id), ['c']);
});

test('a returning visit shows what came out since, and nothing once seen', () => {
  assert.deepEqual(unseen(list, 'a').map(r => r.id), ['c', 'b']);
  assert.deepEqual(unseen(list, 'c'), []);
  assert.deepEqual(unseen([], 'a'), []);
});

test('an unknown last-seen id shows the latest few, not the whole history', () => {
  const long = Array.from({ length: 9 }, (_, i) => ({ id: String(9 - i) }));
  assert.equal(unseen(long, 'gone').length, 3);
});
