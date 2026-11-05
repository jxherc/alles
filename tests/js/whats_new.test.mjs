import test from 'node:test';
import assert from 'node:assert/strict';

const { unseen } = await import('../../static/js/whatsnew.js');
const list = [{ id: 'c' }, { id: 'b' }, { id: 'a' }];

// u.11: a fresh install opens setup, not release notes
test('a first visit shows no release notes', () => {
  assert.deepEqual(unseen(list, ''), []);
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

// nov 5: each address, browser and home-screen app kept its own record, so the notes kept
// coming back; the newer of this browser's record and alles's own one counts
test('the newer of two seen records wins, whichever place holds it', async () => {
  const { newestSeen } = await import('../../static/js/whatsnew.js');
  assert.equal(newestSeen(list, 'a', 'c'), 'c');
  assert.equal(newestSeen(list, 'c', 'a'), 'c');
  assert.equal(newestSeen(list, '', 'b'), 'b');
  assert.equal(newestSeen(list, 'gone', 'a'), 'a');
  assert.equal(newestSeen(list, '', ''), '');
});
