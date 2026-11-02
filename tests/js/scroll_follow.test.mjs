import assert from 'node:assert/strict';
import test from 'node:test';

const { distanceFromBottom, followAfterScroll } = await import('../../static/js/scrollfollow.js');

test('distance from bottom never becomes negative', () => {
  assert.equal(distanceFromBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 200 }), 100);
  assert.equal(distanceFromBottom({ scrollHeight: 100, scrollTop: 50, clientHeight: 100 }), 0);
});

test('only the view moving up leaves the end', () => {
  assert.equal(followAfterScroll({ following: true, top: 900, lastTop: 1000, distance: 300 }), false);
  assert.equal(followAfterScroll({ following: true, top: 995, lastTop: 1000, distance: 5 }), false);
});

test('content that grew under a still view keeps the follow, however much it grew', () => {
  assert.equal(followAfterScroll({ following: true, top: 1000, lastTop: 1000, distance: 536 }), true);
  assert.equal(followAfterScroll({ following: false, top: 1000, lastTop: 1000, distance: 536 }), false);
});

test('reaching the end, or moving down close to it, follows again', () => {
  assert.equal(followAfterScroll({ following: false, top: 1400, lastTop: 900, distance: 0 }), true);
  assert.equal(followAfterScroll({ following: false, top: 1350, lastTop: 900, distance: 50 }), true);
  assert.equal(followAfterScroll({ following: false, top: 1000, lastTop: 900, distance: 400 }), false);
  // a reply that got shorter clamps the view up to the new end: still the end
  assert.equal(followAfterScroll({ following: true, top: 1300, lastTop: 1400, distance: 0 }), true);
});
