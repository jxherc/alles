import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const moneySource = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8');
const styleSource = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');

test('manual Finance creates reuse an identity only for the exact same payload', () => {
  for (const [kind, payload] of [
    ['account', 'accountPayload'],
    ['transaction', 'transactionPayload'],
    ['transfer', 'transferPayload'],
  ]) {
    assert.match(moneySource, new RegExp(`requestId = await _createRequestId\\('${kind}', ${payload}\\)`));
    assert.match(moneySource, new RegExp(`${payload}\\.request_id = requestId`));
    assert.match(moneySource, new RegExp(`_completeCreateRequest\\('${kind}', requestId\\)`));
    assert.match(moneySource, new RegExp(`_releaseCreateRequest\\('${kind}', requestId\\)`));
  }
  assert.match(moneySource, /async function _createRequestId\(kind, payload\)/);
  assert.match(moneySource, /pending\?\.fingerprint === fingerprint/);
  assert.match(moneySource, /if \(pending\?\.active\) throw new Error/);
  assert.match(moneySource, /pending\?\.requestId !== requestId/);
  assert.match(moneySource, /stored\?\.fingerprint === fingerprint/);
  assert.match(moneySource, /crypto\.subtle\.digest/);
  assert.match(moneySource, /persistable:\s*false/);
  assert.doesNotMatch(moneySource, /return `exact:\$\{canonical\}`/);
  assert.match(moneySource, /if \(persistable\) \{[\s\S]*?sessionStorage\.setItem/);
  assert.match(moneySource, /sessionStorage\.getItem\(_createRequestKey\(kind\)\)/);
  assert.match(moneySource, /globalThis\.crypto\?\.randomUUID/);
});

test('finance month headings format calendar months without local Date conversion', () => {
  assert.match(moneySource, /formatCalendarDate\(`\$\{m\}-01`/);
  assert.doesNotMatch(moneySource, /formatDate\(new Date\(y, mo - 1, 1\)/);
});

test('finance dialogs, rows, and destructive actions expose complete interaction boundaries', () => {
  assert.match(moneySource, /createFocusBoundary\(dialog/);
  assert.match(moneySource, /requestWithRecentOwner\(fetch, path, init\)/);
  assert.match(moneySource, /class="tx-edit" data-edit-txn=/);
  assert.match(moneySource, /<button type="button" class="tx-tag"/);
  assert.doesNotMatch(moneySource, /<span class="tx-tag" data-tag=/);
  for (const consequence of [
    'delete this transaction',
    'delete this goal',
    'delete this holding',
    'delete this monthly budget',
    'delete this categorization rule',
  ]) assert.match(moneySource, new RegExp(consequence));
  assert.match(styleSource, /#money-view :where\(button, a\.btn\)[\s\S]*?min-width: 44px;[\s\S]*?min-height: 44px;/);
  assert.match(styleSource, /#money-view :where\(input:not\(\[type="file"\]\), textarea, \.custom-select, \.date-input\)[\s\S]*?min-height: 44px;/);
});

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
