// unit tests for the offline outbox queue logic (static/js/outbox.js).
// run: node --test tests/js/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isQueueable, dedupe, summarize } from '../../static/js/outbox.js';

test('isQueueable: mutating api writes', () => {
  assert.equal(isQueueable('POST', '/api/notes'), true);
  assert.equal(isQueueable('PATCH', '/api/notes/1'), true);
  assert.equal(isQueueable('DELETE', '/api/notes/1'), true);
});

test('isQueueable: GET is not queued', () => {
  assert.equal(isQueueable('GET', '/api/notes'), false);
});

test('isQueueable: non-api not queued', () => {
  assert.equal(isQueueable('POST', '/login'), false);
});

test('isQueueable: streaming/agent endpoints excluded', () => {
  assert.equal(isQueueable('POST', '/api/agent/run'), false);
  assert.equal(isQueueable('POST', '/api/chat/stream'), false);
});

test('dedupe: last write wins on same url', () => {
  const q = [
    { method: 'PATCH', url: '/api/notes/1', body: { t: 'a' } },
    { method: 'PATCH', url: '/api/notes/1', body: { t: 'b' } },
  ];
  const out = dedupe(q);
  assert.equal(out.length, 1);
  assert.equal(out[0].body.t, 'b');
});

test('dedupe: delete supersedes prior writes to same url', () => {
  const q = [
    { method: 'PATCH', url: '/api/notes/1', body: { t: 'a' } },
    { method: 'DELETE', url: '/api/notes/1' },
  ];
  const out = dedupe(q);
  assert.equal(out.length, 1);
  assert.equal(out[0].method, 'DELETE');
});

test('dedupe: unrelated urls kept', () => {
  const q = [
    { method: 'PATCH', url: '/api/notes/1', body: {} },
    { method: 'PATCH', url: '/api/notes/2', body: {} },
  ];
  assert.equal(dedupe(q).length, 2);
});

test('dedupe: order preserved for distinct resources', () => {
  const q = [
    { method: 'POST', url: '/api/a', body: {} },
    { method: 'POST', url: '/api/b', body: {} },
    { method: 'POST', url: '/api/c', body: {} },
  ];
  assert.deepEqual(dedupe(q).map((x) => x.url), ['/api/a', '/api/b', '/api/c']);
});

test('dedupe: two POSTs to same collection stay separate (creates)', () => {
  const q = [
    { method: 'POST', url: '/api/tasks', body: { t: 'a' } },
    { method: 'POST', url: '/api/tasks', body: { t: 'b' } },
  ];
  const out = dedupe(q);
  assert.equal(out.length, 2); // both creates survive
  assert.deepEqual(out.map((o) => o.body.t), ['a', 'b']);
});

test('summarize: count', () => {
  assert.equal(summarize([{ method: 'POST', url: '/api/x' }]).count, 1);
  assert.equal(summarize([]).count, 0);
});
