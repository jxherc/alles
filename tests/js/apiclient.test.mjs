// unit tests for the typed API client (static/js/apiclient.js).
// run: node --test tests/js/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createClient, validate } from '../../static/js/apiclient.js';

function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, opts = {}) => {
    calls.push({ url, opts });
    return handler(url, opts);
  };
  fn.calls = calls;
  return fn;
}

function jsonResponse(body, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

test('get builds url + parses json', async () => {
  const fetchFn = fakeFetch(() => jsonResponse({ hi: 1 }));
  const c = createClient({ base: '/api', fetchFn });
  const data = await c.get('/things');
  assert.deepEqual(data, { hi: 1 });
  assert.equal(fetchFn.calls[0].url, '/api/things');
});

test('query params appended', async () => {
  const fetchFn = fakeFetch(() => jsonResponse({}));
  const c = createClient({ base: '', fetchFn });
  await c.get('/x', { params: { a: 1, b: 'two', skip: undefined } });
  assert.equal(fetchFn.calls[0].url, '/x?a=1&b=two');
});

test('post sends json body', async () => {
  const fetchFn = fakeFetch(() => jsonResponse({ ok: true }));
  const c = createClient({ base: '', fetchFn });
  await c.post('/y', { body: { name: 'z' } });
  const opt = fetchFn.calls[0].opts;
  assert.equal(opt.method, 'POST');
  assert.equal(JSON.parse(opt.body).name, 'z');
  assert.equal(opt.headers['content-type'], 'application/json');
});

test('non-ok throws with status', async () => {
  const fetchFn = fakeFetch(() => jsonResponse({ detail: 'nope' }, false, 404));
  const c = createClient({ base: '', fetchFn });
  await assert.rejects(() => c.get('/missing'), (e) => e.status === 404);
});

test('validate: ok', () => {
  const r = validate({ a: 'x', n: 3, flag: true }, { a: 'string', n: 'number', flag: 'boolean' });
  assert.equal(r.ok, true);
  assert.deepEqual(r.errors, []);
});

test('validate: missing field', () => {
  const r = validate({ a: 'x' }, { a: 'string', n: 'number' });
  assert.equal(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('n')));
});

test('validate: wrong type', () => {
  const r = validate({ n: 'not-a-number' }, { n: 'number' });
  assert.equal(r.ok, false);
});

test('validate: optional field missing is ok', () => {
  const r = validate({ a: 'x' }, { a: 'string', note: '?string' });
  assert.equal(r.ok, true);
});

test('validate: array + object', () => {
  const r = validate({ items: [1], meta: {} }, { items: 'array', meta: 'object' });
  assert.equal(r.ok, true);
});

test('request with shape rejects a bad response', async () => {
  const fetchFn = fakeFetch(() => jsonResponse({ wrong: 1 }));
  const c = createClient({ base: '', fetchFn });
  await assert.rejects(() => c.get('/z', { shape: { expected: 'string' } }));
});
