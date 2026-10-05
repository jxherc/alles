import { calendarDateKey } from '../../static/js/i18n.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

function harness() {
  const elements = new Map();
  let focused = '';
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', innerHTML: '', textContent: '', hidden: false, attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; },
      focus() { focused = id; },
    });
    return elements.get(id);
  };
  const requests = [];
  const context = vm.createContext({
    calendarDateKey,
    document: { getElementById: get }, location: { search: '' }, URLSearchParams,
    clearTimeout, toast() {},
    api: url => new Promise((resolve, reject) => requests.push({ url, resolve, reject })),
  });
  vm.runInContext(source + `
    _txns = [{id: 'month-row'}];
    txnList = () => (_searchResults ?? _txns).map(row => row.id).join(',');
    _wireTxnRows = () => {};
    globalThis.subject = { applySearch, toggleAmountRange, syncAmountRange,
      filterByTag, clearTagFilter, tag: () => _tagFilter };
  `, context);
  return { ...context.subject, get, requests, focused: () => focused };
}

test('clearing an amount range preserves text search and ignores the older range response', async () => {
  const h = harness();
  h.get('txn-search').value = 'garden 中文';
  h.toggleAmountRange();
  assert.equal(h.get('txn-amount-range').hidden, false);
  assert.equal(h.focused(), 'txn-min');
  h.get('txn-min').value = '10.25';
  h.get('txn-max').value = '30';
  h.syncAmountRange();
  assert.equal(h.get('txn-range-toggle').textContent, 'clear range');
  const oldSearch = h.applySearch();
  const oldQuery = new URL(h.requests[0].url, 'http://localhost').searchParams;
  assert.equal(oldQuery.get('min_amt'), '10.25');
  assert.equal(oldQuery.get('max_amt'), '30');

  h.toggleAmountRange();
  assert.equal(h.get('txn-amount-range').hidden, true);
  assert.equal(h.get('txn-range-toggle').attributes['aria-expanded'], 'false');
  assert.equal(h.get('txn-min').value, '');
  assert.equal(h.get('txn-max').value, '');
  assert.equal(h.get('txn-search').value, 'garden 中文');
  assert.equal(h.focused(), 'txn-range-toggle');
  const query = new URL(h.requests[1].url, 'http://localhost').searchParams;
  assert.equal(query.get('q'), 'garden 中文');
  assert.equal(query.has('min_amt'), false);
  assert.equal(query.has('max_amt'), false);
  h.requests[1].resolve([{id: 'text-match'}]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.get('txn-rows').innerHTML, 'text-match');
  h.requests[0].resolve([{id: 'old-range-match'}]);
  await oldSearch;
  assert.equal(h.get('txn-rows').innerHTML, 'text-match');
});

test('clearing the only filter immediately restores the month and an old failure cannot erase it', async () => {
  const h = harness();
  h.toggleAmountRange();
  h.get('txn-min').value = '10';
  const pending = h.applySearch();
  h.toggleAmountRange();
  assert.equal(h.requests.length, 1);
  assert.equal(h.get('txn-rows').innerHTML, 'month-row');
  h.requests[0].reject(new Error('old search failed'));
  await pending;
  assert.equal(h.get('txn-rows').innerHTML, 'month-row');
});

test('a slower text search cannot replace newer results', async () => {
  const h = harness();
  h.get('txn-search').value = 'garden';
  const first = h.applySearch();
  h.get('txn-search').value = 'groceries';
  const second = h.applySearch();
  h.requests[1].resolve([{id: 'groceries'}]);
  await second;
  h.requests[0].resolve([{id: 'garden'}]);
  await first;
  assert.equal(h.get('txn-rows').innerHTML, 'groceries');
});

test('a pending tag response cannot restore a filter after clearing the range', async () => {
  const h = harness();
  h.toggleAmountRange();
  const pending = h.filterByTag('garden');
  h.toggleAmountRange();
  assert.equal(h.get('txn-rows').innerHTML, 'month-row');
  h.requests[0].resolve([{id: 'tag-match'}]);
  await pending;
  assert.equal(h.tag(), '');
  assert.equal(h.get('txn-rows').innerHTML, 'month-row');
});

test('tag selection supersedes a pending amount search, and clearing supersedes a pending tag', async () => {
  const h = harness();
  h.get('txn-min').value = '10';
  const amount = h.applySearch();
  const tag = h.filterByTag('groceries');
  h.requests[1].resolve([{id: 'groceries-match'}]);
  await tag;
  h.requests[0].resolve([{id: 'old-amount-match'}]);
  await amount;
  assert.equal(h.tag(), 'groceries');
  assert.equal(h.get('txn-rows').innerHTML, 'groceries-match');
  const newerTag = h.filterByTag('garden');
  h.clearTagFilter();
  h.requests[2].resolve([{id: 'garden-match'}]);
  await newerTag;
  assert.equal(h.tag(), '');
  assert.equal(h.get('txn-rows').innerHTML, 'month-row');
});
