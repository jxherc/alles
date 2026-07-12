import assert from 'node:assert/strict';
import test from 'node:test';

const { distanceFromBottom, shouldAutoFollow } = await import('../../static/js/scrollfollow.js');

test('distance from bottom never becomes negative', () => {
  assert.equal(distanceFromBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 200 }), 100);
  assert.equal(distanceFromBottom({ scrollHeight: 100, scrollTop: 50, clientHeight: 100 }), 0);
});

test('streaming follows only while the owner remains near the bottom', () => {
  assert.equal(shouldAutoFollow({ following: true, distance: 20 }), true);
  assert.equal(shouldAutoFollow({ following: true, distance: 300 }), false);
  assert.equal(shouldAutoFollow({ following: false, distance: 0 }), false);
});

test('typing and selecting keep scroll ownership with the owner', () => {
  assert.equal(shouldAutoFollow({ following: true, distance: 0, typing: true }), false);
  assert.equal(shouldAutoFollow({ following: true, distance: 0, selecting: true }), false);
});
