import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/sw.js', import.meta.url), 'utf8');
const request = () => new Request('http://localhost/api/health', {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ value: 74.312, kind: 'weight' }),
});

function harness({ enqueue = async () => {}, notify = async () => {}, online } = {}) {
  const calls = [];
  const context = vm.createContext({
    self: { addEventListener() {} }, Request, Response,
    fetch: async () => {
      if (online) return online;
      throw new TypeError('network unavailable');
    },
    enqueue: async req => { calls.push('enqueue'); return enqueue(req); },
    notify: async () => { calls.push('notify'); return notify(); },
  });
  vm.runInContext(source + `
    queueRequest = enqueue;
    notifyClients = notify;
    globalThis.write = handleWrite;
  `, context);
  return { write: context.write, calls };
}

for (const name of ['SecurityError', 'AbortError']) {
  test(`offline ${name} reports failure instead of queued success`, async () => {
    const h = harness({ enqueue: async () => { throw new DOMException('storage failed', name); } });
    const response = await h.write(request());
    assert.equal(response.status, 503);
    const body = await response.json();
    assert.equal(body.queued, false);
    assert.equal(body.offline, true);
    assert.match(body.detail, /could not store.*reconnect/);
    assert.deepEqual(h.calls, ['enqueue']);
  });
}

test('offline acceptance waits until the queue transaction commits', async () => {
  let commit;
  let started;
  const entered = new Promise(resolve => { started = resolve; });
  const pending = new Promise(resolve => { commit = resolve; });
  const h = harness({ enqueue: async () => { started(); await pending; } });
  let resolved = false;
  const response = h.write(request()).then(result => { resolved = true; return result; });
  await entered;
  await Promise.resolve();
  assert.equal(resolved, false);
  assert.deepEqual(h.calls, ['enqueue']);
  commit();
  assert.deepEqual(await (await response).json(), { queued: true, offline: true });
  assert.deepEqual(h.calls, ['enqueue', 'notify']);
});

test('notification failure does not reject an already committed queue item', async () => {
  const h = harness({ notify: async () => { throw new Error('page closed'); } });
  const response = await h.write(request());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { queued: true, offline: true });
  assert.deepEqual(h.calls, ['enqueue', 'notify']);
});

test('online responses pass through without an offline queue write', async () => {
  const online = new Response('{"id":17}', { status: 201 });
  const h = harness({ online });
  assert.equal(await h.write(request()), online);
  assert.deepEqual(h.calls, []);
});
