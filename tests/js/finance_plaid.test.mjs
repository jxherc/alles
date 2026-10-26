import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/finance_plaid.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const key = 'alles:finance-plaid-link';
const origin = 'https://alles.example';
const redirect = origin + '/api/finance/connections/plaid/return';
const received = redirect + '?oauth_state_id=synthetic-state';
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness({ sdk = true, storage = new Map(), update = false } = {}) {
  const scripts = [], calls = [], handlers = [];
  const Plaid = { create(config) {
    const handler = { config, opened: false, destroyed: false,
      open() { this.opened = true; }, destroy() { this.destroyed = true; } };
    handlers.push(handler); return handler;
  } };
  const context = vm.createContext({
    t,
    window: sdk ? { Plaid } : {}, URL, Date, setTimeout, clearTimeout, DOMException,
    location: { origin, href: received }, fetch() {},
    requestWithRecentOwner: async () => ({ ok: true, json: async () => ({}) }),
    sessionStorage: { getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    document: { createElement: () => ({ dataset: {}, remove() { this.removed = true; } }),
      head: { append: script => scripts.push(script) } },
  });
  vm.runInContext(source + '\nglobalThis.subject = { openPlaidLink, plaidSdk, plaidReturnBinding };', context);
  const request = async (path, options) => {
    calls.push({ path, ...options });
    return path.endsWith('/link-token') ? {
      link_token: 'original-link', expiration: new Date(Date.now() + 60000).toISOString(),
      redirect_uri: redirect, update_mode: update,
    } : { id: 'connection-1', status: 'connected' };
  };
  return { ...context.subject, scripts, calls, handlers, storage, Plaid, context, request,
    start: options => context.subject.openPlaidLink({ id: 'connection-1' }, { request, ...options }) };
}

test('a failed SDK load removes its script and the next attempt can finish', async () => {
  const h = harness({ sdk: false });
  const first = h.plaidSdk();
  assert.equal(h.plaidSdk(), first);
  h.scripts[0].onerror();
  await assert.rejects(first, /did not load/);
  assert.equal(h.scripts[0].removed, true);
  const retry = h.plaidSdk();
  assert.equal(h.scripts.length, 2);
  h.context.window.Plaid = h.Plaid;
  h.scripts[1].onload();
  assert.equal(await retry, h.Plaid);
});

test('success exchanges once, destroys Link, and removes the return binding', async () => {
  const h = harness(); const pending = h.start(); await tick();
  assert.equal(h.handlers[0].opened, true);
  assert.equal(JSON.parse(h.storage.get(key)).connection_id, 'connection-1');
  const callback = h.handlers[0].config.onSuccess;
  await Promise.all([callback('public-token'), callback('public-token')]);
  assert.equal((await pending).connection.status, 'connected');
  assert.equal(h.calls.filter(call => call.path.endsWith('/exchange')).length, 1);
  assert.equal(h.handlers[0].destroyed, true);
  assert.equal(h.storage.has(key), false);
});

test('update mode confirms the existing item without a public-token exchange', async () => {
  const h = harness({ update: true }); const pending = h.start(); await tick();
  await h.handlers[0].config.onSuccess(null);
  await pending;
  assert.equal(h.calls.at(-1).path.endsWith('/update-complete'), true);
  assert.equal(h.calls.some(call => call.path.endsWith('/exchange')), false);
});

test('same-session redirect resumes with the original Link token and full received URI', async () => {
  const first = harness(); const opening = first.start(); await tick();
  const returned = harness({ storage: new Map(first.storage) });
  const binding = returned.plaidReturnBinding();
  const completion = returned.start({ binding, receivedRedirectUri: received }); await tick();
  assert.equal(returned.calls.length, 0);
  assert.equal(returned.handlers[0].config.token, 'original-link');
  assert.equal(returned.handlers[0].config.receivedRedirectUri, received);
  await returned.handlers[0].config.onSuccess('returned-public'); await completion;
  first.handlers[0].config.onExit(null); await opening;
});

test('cancel leaves the configured connection for retry and clears the temporary token', async () => {
  const h = harness(); const pending = h.start(); await tick();
  h.handlers[0].config.onExit(null);
  assert.equal((await pending).cancelled, true);
  assert.equal(h.calls.length, 1);
  assert.equal(h.storage.has(key), false);
  assert.equal(h.handlers[0].destroyed, true);
});

test('closing during SDK loading never opens Link', async () => {
  const h = harness({ sdk: false }); const controller = new AbortController();
  const pending = h.start({ signal: controller.signal }); await tick();
  controller.abort();
  h.context.window.Plaid = h.Plaid; h.scripts[0].onload();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(h.handlers.length, 0);
  assert.equal(h.storage.has(key), false);
});

test('an expired, missing, mismatched, or altered return cannot start Link', async () => {
  const valid = { connection_id: 'connection-1', link_token: 'original', expires_at: Date.now() + 60000, redirect_uri: redirect };
  for (const [binding, href] of [
    [null, received], [{ ...valid, expires_at: 0 }, received],
    [{ ...valid, redirect_uri: 'https://other.example' + new URL(redirect).pathname }, received],
    [valid, received + '#extra'], [valid, received + '&extra=1'],
    [valid, received + '&oauth_state_id=other'], [valid, redirect],
    [valid, received.replace('/plaid/return', '/plaid/wrong')],
    [valid, received.replace(origin, 'https://other.example')],
  ]) {
    const h = harness({ storage: new Map([[key, JSON.stringify(binding)]]) });
    assert.throws(() => h.plaidReturnBinding(href), /missing or expired/);
    assert.equal(h.handlers.length, 0);
    assert.equal(h.storage.has(key), false);
  }
});

test('an SDK failure on return keeps the valid binding for retry', async () => {
  const binding = { connection_id: 'connection-1', link_token: 'original', expires_at: Date.now() + 60000, redirect_uri: redirect };
  const h = harness({ sdk: false, storage: new Map([[key, JSON.stringify(binding)]]) });
  const pending = h.start({ binding: h.plaidReturnBinding(), receivedRedirectUri: received });
  h.scripts[0].onerror(); await assert.rejects(pending, /did not load/);
  assert.equal(h.storage.has(key), true);
  const retry = h.start({ binding: h.plaidReturnBinding(), receivedRedirectUri: received });
  h.context.window.Plaid = h.Plaid; h.scripts[1].onload(); await tick();
  h.handlers[0].config.onExit(null); await retry;
  assert.equal(h.storage.has(key), false);
});
