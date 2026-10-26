import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const apiSource = readFileSync(new URL('../../static/js/util.js', import.meta.url), 'utf8')
  .split('export async function api(')[1].split('export function toast(')[0];
const uploadId = 'e34e62ae-90bd-4acf-830e-4103e597d101';

function harness() {
  const elements = new Map(), requests = [], messages = [];
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      id, value: '', dataset: {}, innerHTML: '', attributes: {}, listeners: {},
      contains: () => false, querySelector: () => null, querySelectorAll: () => [],
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener(event, handler) { this.listeners[event] = handler; },
      focus() {}, click() {},
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    t, tp,
    calendarDateKey: () => '2026-10-16', formatNumber: number => String(number),
    document: { getElementById: get, activeElement: null }, location: { search: '' },
    URLSearchParams, clearTimeout, Response, initCustomDropdown() {}, initDatePicker() {},
    FormData: class { append() {} },
    toast: (message, type) => messages.push({ message, type }),
    fetch: (url, options = {}) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })),
  });
  vm.runInContext(`async function api(${apiSource}\n${source}\n
    _txns = [{id: 'txn', payee: 'previous transaction', amount: -5, tags: 'garden'}];
    load = async () => true;
    syncMoneyLayout = () => {};
    globalThis.subject = { applySearch, filterByTag, clearTagFilter, attachReceipt,
      html: txnList, state: () => ({ results: _searchResults, tag: _tagFilter }) };
  `, context);
  get('money-receipt-input').files = [{ name: 'synthetic.pdf' }];
  const respond = (index, body, status = 200) => requests[index].resolve(new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json' },
  }));
  return { ...context.subject, get, requests, messages, respond };
}

async function reach(h, count) {
  for (let turn = 0; turn < 20 && h.requests.length < count; turn++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.requests.length, count);
}

for (const [name, body, status] of [
  ['HTTP failure', { detail: 'synthetic unavailable' }, 503],
  ['HTTP failure with an id', { id: uploadId }, 503],
  ['missing id', {}, 200],
  ['blank id', { id: ' ' }, 200],
  ['object id', { id: {} }, 200],
  ['invalid id', { id: '../synthetic' }, 200],
  ['null payload', null, 200],
]) {
  test(`receipt ${name} never PATCHes the transaction or announces success`, async () => {
    const h = harness();
    h.attachReceipt('txn');
    const pending = h.get('money-receipt-input').onchange();
    h.respond(0, body, status);
    // A bad implementation continues to PATCH; finish it so failure is an assertion.
    await new Promise(resolve => setImmediate(resolve));
    if (h.requests[1]) h.respond(1, { id: 'txn' });
    await pending;
    assert.equal(h.requests.length, 1);
    assert.equal(h.messages.at(-1).type, 'error');
    assert.equal(h.messages.some(item => item.type === 'success'), false);
  });
}

for (const [name, acknowledgment, status] of [
  ['rejected attachment', { detail: 'synthetic unavailable' }, 503],
  ['missing acknowledgment', null, 200],
  ['missing receipt', { id: 'txn' }, 200],
  ['wrong receipt', { id: 'txn', receipt_id: 'other' }, 200],
  ['wrong transaction', { id: 'other', receipt_id: uploadId }, 200],
  ['confirmed attachment', { id: 'txn', receipt_id: uploadId }, 200],
]) {
  test(`receipt ${name} reports the acknowledged result`, async () => {
    const h = harness();
    h.attachReceipt('txn');
    const pending = h.get('money-receipt-input').onchange();
    h.respond(0, { id: uploadId });
    await reach(h, 2);
    assert.deepEqual(JSON.parse(h.requests[1].options.body), { receipt_id: uploadId });
    assert.equal(h.messages.some(item => item.type === 'success'), false);
    h.respond(1, acknowledgment, status);
    await pending;
    assert.equal(h.messages.at(-1).type, name === 'confirmed attachment' ? 'success' : 'error');
  });
}

for (const kind of ['search', 'tag']) {
  test(`${kind} failure keeps the query and previous rows; its wired retry recovers`, async () => {
    const h = harness();
    h.get('txn-search').value = 'garden 中文';
    h.get('txn-min').value = '4.25';
    h.get('tx-payee').value = 'unsaved draft';
    const pending = kind === 'tag' ? h.filterByTag('garden 中文') : h.applySearch();
    h.respond(0, { detail: 'synthetic unavailable' }, 503);
    await pending;
    assert.match(h.html(), /couldn't load.*transactions/);
    assert.doesNotMatch(h.html(), /no matches/);
    assert.match(h.html(), /previous transaction/);
    assert.match(h.html(), /role="status"/);
    assert.match(h.html(), /id="txn-search-retry"/);
    assert.equal(h.get('txn-search').value, 'garden 中文');
    assert.equal(h.get('txn-min').value, '4.25');
    assert.equal(h.get('tx-payee').value, 'unsaved draft');
    const retry = h.get('txn-search-retry').listeners.click();
    assert.equal(h.requests[1].url, h.requests[0].url);
    assert.match(h.html(), /loading.*transactions/);
    h.respond(1, [{ id: 'match', payee: 'matching transaction', amount: -5 }]);
    await retry;
    assert.match(h.html(), /matching transaction/);
    assert.doesNotMatch(h.html(), /couldn't load|loading|txn-search-retry/);
  });

  test(`${kind} error can be cleared without losing entry drafts`, async () => {
    const h = harness();
    h.get('txn-search').value = 'garden';
    h.get('txn-min').value = '10';
    h.get('tx-payee').value = 'keep draft';
    const pending = kind === 'tag' ? h.filterByTag('garden') : h.applySearch();
    h.requests[0].reject(new Error('offline'));
    await pending;
    assert.match(h.html(), /id="txn-search-clear"/);
    h.get('txn-search-clear').listeners.click();
    assert.equal(h.get('txn-search').value, '');
    assert.equal(h.get('txn-min').value, '');
    assert.equal(h.state().tag, '');
    assert.equal(h.state().results, null);
    assert.equal(h.get('tx-payee').value, 'keep draft');
    assert.doesNotMatch(h.html(), /couldn't load|loading|no matches/);
  });

  test(`${kind} delayed failure cannot replace a newer successful result`, async () => {
    const h = harness();
    h.get('txn-search').value = 'old';
    const earlier = kind === 'tag' ? h.filterByTag('old') : h.applySearch();
    h.get('txn-search').value = 'new';
    const current = h.applySearch();
    h.respond(1, [{ id: 'new', payee: 'new result', amount: -2 }]);
    await current;
    h.requests[0].reject(new Error('old failure'));
    await earlier;
    assert.match(h.html(), /new result/);
    assert.doesNotMatch(h.html(), /couldn't load|loading|no matches/);
  });

  test(`${kind} distinguishes successful empty results from malformed results`, async () => {
    const h = harness();
    h.get('txn-search').value = 'garden';
    const start = () => kind === 'tag' ? h.filterByTag('garden') : h.applySearch();
    let pending = start();
    h.respond(0, []);
    await pending;
    assert.match(h.html(), /no matches/);
    pending = start();
    h.respond(1, { detail: 'not a transaction list' });
    await pending;
    assert.match(h.html(), /couldn't load.*transactions/);
    assert.doesNotMatch(h.html(), /no matches/);
  });
}

test('an invalid amount supersedes a pending read without leaving a permanent loading state', async () => {
  const h = harness();
  h.get('txn-search').value = 'garden';
  const pending = h.applySearch();
  h.get('txn-min').value = 'not an amount';
  await h.applySearch();
  assert.doesNotMatch(h.html(), /loading matching transactions/);
  h.respond(0, []);
  await pending;
  assert.match(h.html(), /previous transaction/);
  assert.equal(h.requests.length, 1);
});
