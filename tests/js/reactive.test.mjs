// unit tests for the reactive store + SWR fetch cache (static/js/reactive.js).
// run: node --test tests/js/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createStore, createSWR } from '../../static/js/reactive.js';

test('store: get/set', () => {
  const s = createStore({ a: 1 });
  assert.equal(s.get('a'), 1);
  s.set('a', 2);
  assert.equal(s.get('a'), 2);
});

test('store: on() fires on change', () => {
  const s = createStore({ n: 0 });
  let seen = null;
  s.on('n', (v, old) => { seen = [v, old]; });
  s.set('n', 5);
  assert.deepEqual(seen, [5, 0]);
});

test('store: no notify when value unchanged', () => {
  const s = createStore({ n: 1 });
  let calls = 0;
  s.on('n', () => { calls++; });
  s.set('n', 1); // same value
  assert.equal(calls, 0);
});

test('store: unsubscribe', () => {
  const s = createStore({ n: 0 });
  let calls = 0;
  const off = s.on('n', () => { calls++; });
  s.set('n', 1);
  off();
  s.set('n', 2);
  assert.equal(calls, 1);
});

// ── SWR ──
function makeFetcher() {
  let count = 0;
  const fn = async (key) => { count++; return `data:${key}:${count}`; };
  fn.count = () => count;
  return fn;
}

test('SWR: first get awaits fetch + caches', async () => {
  const fetcher = makeFetcher();
  const swr = createSWR({ fetcher, ttl: 1000, now: () => 0 });
  const v = await swr.get('k');
  assert.equal(v, 'data:k:1');
  assert.equal(swr.peek('k'), 'data:k:1');
});

test('SWR: fresh hit returns cache, no refetch', async () => {
  const fetcher = makeFetcher();
  let clock = 0;
  const swr = createSWR({ fetcher, ttl: 1000, now: () => clock });
  await swr.get('k');
  clock = 500; // still fresh
  const v = await swr.get('k');
  assert.equal(v, 'data:k:1');
  assert.equal(fetcher.count(), 1); // not refetched
});

test('SWR: stale returns cached immediately + revalidates in background', async () => {
  const fetcher = makeFetcher();
  let clock = 0;
  const swr = createSWR({ fetcher, ttl: 1000, now: () => clock });
  await swr.get('k'); // count 1
  clock = 2000; // now stale
  const v = await swr.get('k');
  assert.equal(v, 'data:k:1'); // returns the stale cached value right away
  await new Promise((r) => setTimeout(r, 0)); // let the background revalidate settle
  assert.equal(fetcher.count(), 2); // revalidated
  assert.equal(swr.peek('k'), 'data:k:2');
});

test('SWR: concurrent gets dedup to one fetch', async () => {
  const fetcher = makeFetcher();
  const swr = createSWR({ fetcher, ttl: 1000, now: () => 0 });
  const [a, b] = await Promise.all([swr.get('k'), swr.get('k')]);
  assert.equal(a, b);
  assert.equal(fetcher.count(), 1);
});

test('SWR: invalidate forces refetch', async () => {
  const fetcher = makeFetcher();
  const swr = createSWR({ fetcher, ttl: 100000, now: () => 0 });
  await swr.get('k');
  swr.invalidate('k');
  const v = await swr.get('k');
  assert.equal(v, 'data:k:2');
  assert.equal(fetcher.count(), 2);
});

test('SWR: on() fires when fresh data lands', async () => {
  const fetcher = makeFetcher();
  const swr = createSWR({ fetcher, ttl: 1000, now: () => 0 });
  let got = null;
  swr.on('k', (d) => { got = d; });
  await swr.get('k');
  assert.equal(got, 'data:k:1');
});
