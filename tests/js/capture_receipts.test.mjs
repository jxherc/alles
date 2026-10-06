import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { captureSource, functionSource } from './helpers/mail_workflows_recovery.mjs';

const scopes = ['a'.repeat(64), 'b'.repeat(64)];
const key = scope => 'alles.capture.pending.v1:' + scope;
const receipt = (requestId, kind = 'task') => ({
  kind,
  body: { request_id: requestId, title: `synthetic ${requestId}`, source: { kind: 'mail', label: 'synthetic message' } },
});

function setup(entries = []) {
  const values = new Map(entries.map(([scope, raw]) => [key(scope), raw]));
  const context = vm.createContext({
    sessionStorage: {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
      removeItem: key => values.delete(key),
    },
    fetch: async (url, options) => {
      assert.equal(url, '/api/tasks/draft-scope');
      assert.equal(options.cache, 'no-store');
      return { ok: true, json: async () => ({ scopes }) };
    },
  });
  const prefix = captureSource.split('\n').find(line => line.startsWith('const PREFIX ='));
  assert.ok(prefix, 'load the production receipt namespace');
  vm.runInContext(prefix + '\n' + functionSource('pendingStore', captureSource), context);
  return { values, open: () => vm.runInContext('pendingStore()', context) };
}

const rawA = JSON.stringify(receipt('acceptance-a'));
const rawB = JSON.stringify(receipt('acceptance-b', 'event'));

test('resolving A preserves B byte-for-byte for the next recovery', async () => {
  const h = setup([[scopes[0], rawA], [scopes[1], rawB]]);
  const first = await h.open();
  assert.equal(first.pending.body.request_id, 'acceptance-a');
  first.clear();
  assert.equal(h.values.has(key(scopes[0])), false);
  assert.equal(h.values.get(key(scopes[1])), rawB);
  const next = await h.open();
  assert.equal(next.pending.kind, 'event');
  assert.equal(next.pending.body.request_id, 'acceptance-b');
  assert.equal(JSON.stringify(next.pending), rawB, 'recovery keeps the exact retry body');
  next.clear();
  assert.equal(h.values.size, 0);
});

test('a selected retained scope does not own a later primary-scope receipt', async () => {
  const h = setup([[scopes[1], rawB]]);
  const selected = await h.open();
  assert.equal(selected.pending.body.request_id, 'acceptance-b');
  h.values.set(key(scopes[0]), rawA);
  selected.clear();
  assert.equal(h.values.has(key(scopes[1])), false);
  assert.equal(h.values.get(key(scopes[0])), rawA);
  assert.equal((await h.open()).pending.body.request_id, 'acceptance-a');
});

for (const [label, replacement] of [
  ['new request identity', JSON.stringify(receipt('acceptance-new'))],
  ['changed body with the same request identity', JSON.stringify({ ...receipt('acceptance-a'), body: { ...receipt('acceptance-a').body, title: 'newer title' } })],
  ['different serialized text with the same parsed contents', JSON.stringify(receipt('acceptance-a'), null, 2)],
]) test(`an old clear retains a replacement with ${label}`, async () => {
  const h = setup([[scopes[0], rawA], [scopes[1], rawB]]);
  const old = await h.open();
  h.values.set(key(scopes[0]), replacement);
  old.clear();
  assert.equal(h.values.get(key(scopes[0])), replacement);
  assert.equal(h.values.get(key(scopes[1])), rawB);
  const current = await h.open();
  assert.equal(JSON.stringify(current.pending), JSON.stringify(JSON.parse(replacement)));
  current.clear();
  assert.equal(h.values.has(key(scopes[0])), false);
  assert.equal(h.values.get(key(scopes[1])), rawB);
});

test('a second clear after resolution retains a newer receipt', async () => {
  const h = setup([[scopes[0], rawA], [scopes[1], rawB]]);
  const old = await h.open();
  old.clear();
  const replacement = JSON.stringify(receipt('after-confirmation'));
  h.values.set(key(scopes[0]), replacement);
  old.clear();
  assert.equal(h.values.get(key(scopes[0])), replacement);
  assert.equal(h.values.get(key(scopes[1])), rawB);
});

test('canceling an empty review does not clear receipts it never owned', async () => {
  const h = setup();
  const empty = await h.open();
  assert.equal(empty.pending, null);
  h.values.set(key(scopes[0]), rawA);
  h.values.set(key(scopes[1]), rawB);
  empty.clear();
  assert.equal(h.values.get(key(scopes[0])), rawA);
  assert.equal(h.values.get(key(scopes[1])), rawB);
});

test('a newly stored acceptance is recoverable and clears only its own scope', async () => {
  const h = setup();
  const writer = await h.open();
  writer.put(receipt('acceptance-a'));
  assert.equal(h.values.get(key(scopes[0])), rawA);
  h.values.set(key(scopes[1]), rawB);
  const retry = await h.open();
  assert.equal(JSON.stringify(retry.pending), rawA);
  assert.equal(retry.pending.body.request_id, 'acceptance-a');
  writer.clear();
  assert.equal(h.values.has(key(scopes[0])), false);
  assert.equal(h.values.get(key(scopes[1])), rawB);
});

test('a newly stored acceptance cannot clear a later replacement', async () => {
  const h = setup();
  const writer = await h.open();
  writer.put(receipt('acceptance-a'));
  const replacement = JSON.stringify(receipt('newer-than-write'));
  h.values.set(key(scopes[0]), replacement);
  writer.clear();
  assert.equal(h.values.get(key(scopes[0])), replacement);
  assert.equal((await h.open()).pending.body.request_id, 'newer-than-write');
});
