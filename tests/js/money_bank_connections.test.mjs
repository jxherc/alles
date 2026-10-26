import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const deferred = () => {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
};

function harness() {
  const nodes = new Map(), writes = [], pending = [], links = [];
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      value: '', textContent: '', dataset: {}, isConnected: true, disabled: false,
      listeners: {}, classList: { toggle() {} },
      addEventListener(event, fn) { this.listeners[event] = fn; },
      setAttribute() {}, removeAttribute() {}, focus() {},
      querySelector: get, querySelectorAll() { return []; },
      remove() { this.isConnected = false; },
    });
    return nodes.get(selector);
  };
  const overlay = get('overlay');
  overlay.querySelectorAll = selector => selector === 'button:not([data-bank-close])'
    ? [get('[data-bank-simplefin]'), get('[data-bank-plaid]')] : [];
  const request = async (path, options) => {
    if (!options) return { connections: [] };
    writes.push({ path, ...options });
    const next = deferred(); pending.push(next);
    return next.promise;
  };
  const context = vm.createContext({
    t, tp,
    calendarDateKey: () => '2026-10-16', location: { search: '' }, URLSearchParams,
    AbortController, fetch() {}, document: { activeElement: null, getElementById: get, body: { append() {} } },
    createFocusBoundary: () => ({ activate() {}, deactivate() {}, destroy() {} }),
    openPlaidLink: async (...args) => { links.push(args); return { cancelled: true }; },
    bankRequest: request,
  });
  vm.runInContext(source + `
    _bankDialog = () => overlay;
    _ownerFetch = request;
    globalThis.subject = { openBankConnections };
  `, Object.assign(context, { overlay, request }));
  return { ...context.subject, get, writes, pending, links,
    click: selector => get(selector).listeners.click() };
}

test('a pending SimpleFIN claim submits once and preserves a newer token', async () => {
  const h = harness(); await h.openBankConnections();
  h.get('#finance-simplefin-token').value = 'original-token';
  const first = h.click('[data-bank-simplefin]');
  const repeat = h.click('[data-bank-simplefin]');
  assert.equal(h.writes.length, 1);
  h.get('#finance-simplefin-token').value = 'newer-token';
  h.pending[0].resolve({ id: 'simplefin-1', provider: 'simplefin', status: 'connected' });
  await first; await repeat;
  assert.equal(h.get('#finance-simplefin-token').value, 'newer-token');
});

test('a malformed claim acknowledgment keeps the exact token and reports uncertainty', async () => {
  for (const payload of [{}, { id: 'simplefin-1', provider: 'simplefin', status: 'error' }]) {
    const h = harness(); await h.openBankConnections();
    h.get('#finance-simplefin-token').value = '  exact-token  ';
    const save = h.click('[data-bank-simplefin]');
    h.pending[0].resolve(payload); await save;
    assert.equal(h.get('#finance-simplefin-token').value, '  exact-token  ');
    assert.match(h.get('.finance-bank-status').textContent, /not confirmed/);
  }
});

test('closing while Plaid configuration saves prevents Link opening and preserves newer secret', { timeout: 500 }, async () => {
  const h = harness(); await h.openBankConnections();
  h.get('#finance-plaid-client').value = 'client';
  h.get('#finance-plaid-secret').value = 'first-secret';
  const save = h.click('[data-bank-plaid]');
  h.get('#finance-plaid-secret').value = 'newer-secret';
  h.click('[data-bank-close]');
  h.pending[0].resolve({ id: 'plaid-1', provider: 'plaid', status: 'link_required' });
  await save;
  assert.equal(h.links.length, 0);
  assert.equal(h.get('#finance-plaid-secret').value, 'newer-secret');
});
