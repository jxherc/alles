import assert from 'node:assert/strict';
import { test } from 'node:test';

function fakeEl(value = '') {
  return {
    value,
    dataset: {},
    innerHTML: '',
    querySelectorAll: () => [],
    addEventListener: () => {},
  };
}

function json(data) {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

test('money text search clears stale tag banner', async () => {
  const rows = fakeEl();
  const els = {
    'txn-search': fakeEl('coffee'),
    'txn-min': fakeEl(),
    'txn-max': fakeEl(),
    'txn-rows': rows,
  };

  globalThis.location = { search: '', href: 'http://money.localhost/' };
  globalThis.history = { replaceState: () => {} };
  globalThis.document = {
    getElementById: id => els[id] || null,
    createElement: () => fakeEl(),
    body: { appendChild: () => {} },
  };
  globalThis.fetch = async url => {
    const u = String(url);
    if (u.includes('/api/money/transactions?tag=')) {
      return json([{ id: 't1', date: '2026-06-01', amount: -7, payee: 'tagged', category: 'food', tags: 'food' }]);
    }
    if (u.includes('/api/money/transactions/search?')) {
      return json([{ id: 's1', date: '2026-06-02', amount: -5, payee: 'coffee', category: 'drinks', tags: '' }]);
    }
    return json([]);
  };

  const money = await import(`../../static/js/money.js?case=${Date.now()}`);
  await money.filterByTag('food');
  assert.match(rows.innerHTML, /filtered by tag/);

  await money.applySearch();
  assert.doesNotMatch(rows.innerHTML, /filtered by tag/);
  assert.match(rows.innerHTML, /coffee/);
});
