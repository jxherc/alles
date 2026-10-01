import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/sw.js', import.meta.url), 'utf8');
const entry = (id, extra = {}) => ({
  id, url: 'https://alles.test/api/health', method: 'POST',
  headers: { 'content-type': 'application/json' }, body: '{"value":73.875,"note":"保留"}', ...extra,
});
function harness(entries, send = async () => new Response('{}')) {
  const rows = new Map(entries.map(item => [item.id, structuredClone(item)]));
  const requests = [];
  const notices = [];
  const context = vm.createContext({
    URL, Response, Number,
    self: { addEventListener() {}, location: { origin: 'https://alles.test' },
      clients: { matchAll: async () => [{ postMessage: value => notices.push(value) }] } },
    getAll: async () => [...rows.values()].map(item => structuredClone(item)),
    remove: async id => rows.delete(id),
    put: async item => rows.set(item.id, structuredClone(item)),
    fetch: async (url, options) => { requests.push({ url, ...options }); return send(url, options); },
  });
  vm.runInContext(source + `
    _all = getAll; _del = remove; _put = put;
    globalThis.flush = flushOutbox;
    globalThis.discard = discardOutboxItem;
  `, context);
  return { rows, requests, notices, flush: context.flush, discard: context.discard };
}

for (const [status, reason] of [[401, 'auth_required'], [409, 'conflict'], [422, 'validation_failed'], [403, 'request_rejected']]) {
  test(`replay ${status} retains exact input and requires recovery instead of deleting it`, async () => {
    const original = entry(1);
    const h = harness([original], async () => new Response('{"detail":"try a valid value"}', { status }));
    await h.flush();
    const saved = h.rows.get(1);
    assert.equal(saved.body, original.body);
    assert.equal(saved.blocked_reason, reason);
    assert.equal(saved.response_status, status);
    assert.equal(saved.response_detail, 'try a valid value');
    assert.equal(h.notices.at(-1).blocked, 1);
    assert.equal(h.notices.at(-1).pending, 1);
    await h.flush();
    assert.equal(h.requests.length, 1);
  });
}

test('successful sign-in retry only unblocks authentication failures', async () => {
  const h = harness([entry(1, { blocked_reason: 'auth_required' }), entry(2, { blocked_reason: 'validation_failed' }), entry(3, { blocked_reason: 'conflict' })]);
  await h.flush({ retryAuth: true });
  assert.equal(h.requests.length, 1);
  assert.deepEqual([...h.rows.keys()], [2, 3]);
});

test('auth rejection stops the remaining queue without losing later entries', async () => {
  const h = harness([entry(1), entry(2)], async () => new Response('{}', { status: 401 }));
  await h.flush();
  assert.equal(h.requests.length, 1);
  assert.deepEqual([...h.rows.keys()], [1, 2]);
});

for (const status of [408, 429, 503]) {
  test(`${status} waits for a later drain, then persists once`, async () => {
    let attempts = 0;
    const h = harness([entry(1)], async () => new Response('{}', { status: ++attempts === 1 ? status : 200 }));
    await h.flush();
    assert.equal(h.rows.size, 1);
    assert.equal(h.rows.get(1).blocked_reason, null);
    await h.flush();
    await h.flush();
    assert.equal(h.rows.size, 0);
    assert.equal(h.requests.length, 2);
  });
}

test('explicit retry sends the retained input without force flags or replacement values', async () => {
  const original = entry(1, { blocked_reason: 'conflict' });
  const h = harness([original]);
  await h.flush({ retryId: 1 });
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].body, original.body);
  assert.deepEqual(h.requests[0].headers, original.headers);
  assert.equal(h.rows.size, 0);
});

test('retry never bypasses a changed replay policy', async () => {
  const h = harness([entry(1, { url: 'https://alles.test/api/money/transactions' })]);
  await h.flush({ retryId: 1, retryAuth: true });
  assert.equal(h.requests.length, 0);
  assert.equal(h.rows.get(1).blocked_reason, 'replay_policy_changed');
});

test('overlapping drains and manual retries send a queued row only once', async () => {
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  const h = harness([entry(1)], async () => { await waiting; return new Response('{}'); });
  const first = h.flush();
  const second = h.flush();
  const third = h.flush({ retryId: 1 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.requests.length, 1);
  release();
  await Promise.all([first, second, third]);
  assert.equal(h.requests.length, 1);
  assert.equal(h.rows.size, 0);
});

test('validation arrays and non-JSON errors never erase the payload', async () => {
  const response = new Response(JSON.stringify({ detail: [{ msg: 'value must be positive' }] }), { status: 422 });
  const h = harness([entry(1)], async () => response);
  await h.flush();
  assert.equal(h.rows.get(1).response_detail, 'value must be positive');
  const unknown = harness([entry(1)], async () => new Response('upstream error', { status: 400 }));
  await unknown.flush();
  assert.equal(unknown.rows.get(1).body, entry(1).body);
});

test('automatic replay preserves later dependent writes behind a rejected change', async () => {
  const h = harness([entry(1, { blocked_reason: 'conflict' }), entry(2)]);
  await h.flush();
  assert.equal(h.requests.length, 0);
  assert.equal(h.rows.size, 2);
  await h.flush({ retryId: 1 });
  assert.equal(h.requests.length, 1);
  assert.deepEqual([...h.rows.keys()], [2]);
  await h.flush();
  assert.equal(h.requests.length, 2);
  assert.equal(h.rows.size, 0);
});

for (const blocked_reason of [undefined, 'conflict', 'validation_failed', 'auth_required']) {
  test(`manual retry cannot bypass an earlier ${blocked_reason || 'pending'} change`, async () => {
    const h = harness([entry(1, { blocked_reason }), entry(2)]);
    await assert.rejects(h.flush({ retryId: 2 }), error => error.code === 'earlier_change_pending');
    assert.equal(h.requests.length, 0);
    assert.deepEqual([...h.rows.keys()], [1, 2]);
    await h.flush({ retryId: 1 });
    await h.flush({ retryId: 2 });
    assert.equal(h.requests.length, 2);
    assert.equal(h.rows.size, 0);
  });
}

test('manual retry still skips a retained replay-policy quarantine', async () => {
  const h = harness([
    entry(1, { url: 'https://alles.test/api/money/transactions', blocked_reason: 'replay_policy_changed' }),
    entry(2),
  ]);
  await h.flush({ retryId: 2 });
  assert.equal(h.requests.length, 1);
  assert.deepEqual([...h.rows.keys()], [1]);
});
