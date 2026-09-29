import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

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

test('old Actual schedule repair chooses a category once and retries the saved choice', async () => {
  const source = moneySource.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  const calls = [];
  let choices = 0;
  const context = vm.createContext({
    location: { search: '' }, URLSearchParams,
    api: async (path, options) => { calls.push({ path, options }); return {}; },
    dlgChoose: async () => { choices += 1; return 'housing-id'; },
    toast: () => {},
  });
  vm.runInContext(source + `
    _canonicalLedger = true;
    _envelope = { categories: [{ category_id: 'housing-id', category: 'housing', group: 'bills' }] };
    _recurring = [{ id: 'old', payee: 'rent', category: 'housing', repair_needed: true }];
    retryRecurring = async () => {};
    globalThis.repair = repairRecurring;
  `, context);
  await context.repair({ dataset: { repairRec: 'old' }, disabled: false, textContent: '' });
  assert.equal(choices, 1);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/money/recurring/old/repair');
  assert.equal(calls[0].options.body.category_id, 'housing-id');

  vm.runInContext("_recurring[0].repair_pending = true; _recurring[0].repair_category_id = 'housing-id'; _envelope = null;", context);
  await context.repair({ dataset: { repairRec: 'old' }, disabled: false, textContent: '' });
  assert.equal(choices, 1);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.body.category_id, 'housing-id');
});

test('canonical recurring pause retries only the saved provider posting choice', async () => {
  const source = moneySource.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  const calls = [];
  const context = vm.createContext({
    location: { search: '' }, URLSearchParams,
    api: async (path, options) => { calls.push({ path, options }); return {}; },
    toast: () => {},
  });
  vm.runInContext(source + `
    _canonicalLedger = true;
    _recurring = [
      { id: 'linked', payee: 'rent', active: true, manageable: true },
      { id: 'native', payee: 'native', active: true, manageable: false },
    ];
    retryRecurring = async () => {};
    globalThis.toggle = toggleRecurring;
  `, context);
  await context.toggle({ dataset: { toggleRec: 'native' }, disabled: false });
  assert.equal(calls.length, 0);
  await context.toggle({ dataset: { toggleRec: 'linked' }, disabled: false, textContent: '' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/money/recurring/linked');
  assert.equal(calls[0].options.body.active, false);
  vm.runInContext('_recurring[0].active = false; _recurring[0].posting_pending = true; _recurring[0].posting_target_active = false;', context);
  await context.toggle({ dataset: { toggleRec: 'linked' }, disabled: false, textContent: '' });
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.body.active, false);
});

test('canonical recurring creation sends an exact category id and reuses its request after an uncertain response', async () => {
  const source = moneySource.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', dataset: {}, textContent: '', innerHTML: '', disabled: false,
      focus() {}, addEventListener() {}, querySelector: () => null,
    });
    return elements.get(id);
  };
  element('rc-payee').value = 'rent';
  element('rc-amt').value = '42.50';
  element('rc-sign').dataset.value = '-';
  element('rc-cycle').dataset.value = 'monthly';
  element('rc-acct').dataset.value = 'account-id';
  element('rc-next').dataset.value = '2026-10-01';
  element('rc-category-choice').dataset.categoryId = 'housing-id';
  const calls = [], storage = new Map();
  const context = vm.createContext({
    location: { search: '' }, URLSearchParams, crypto: webcrypto, TextEncoder,
    sessionStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    document: { getElementById: element, querySelectorAll: () => [] },
    getDropdownValue: el => el?.dataset.value || '',
    toast: () => {},
    api: async (path, options) => {
      calls.push({ path, body: { ...options?.body } });
      if (calls.length === 1) throw new Error('response lost');
      return {};
    },
  });
  vm.runInContext(source + `
    _canonicalLedger = true;
    readRecurring = async () => { _recurring = []; _recurringError = false; };
    load = async () => {};
    globalThis.add = addRecurring;
  `, context);
  await context.add();
  await context.add();
  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, '/api/money/recurring');
  assert.equal(calls[0].body.category_id, 'housing-id');
  assert.equal(calls[0].body.amount, -42.5);
  assert.match(calls[0].body.request_id, /^[0-9a-f-]{36}$/);
  assert.equal(calls[0].body.request_id, calls[1].body.request_id);
  assert.equal(storage.has('alles:finance-create:recurring'), false);
});

test('pending canonical creation offers one retry action and holds the new form', async () => {
  const source = moneySource.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  const calls = [];
  const context = vm.createContext({
    location: { search: '' }, URLSearchParams,
    api: async (path, options) => { calls.push({ path, options }); return {}; },
    formatNumber: value => String(value),
    toast: () => {},
  });
  vm.runInContext(source + `
    _canonicalLedger = true;
    _accounts = [{ id: 'account-id', name: 'checking' }];
    _recurring = [{ id: 'saved-id', payee: 'rent', amount: -42.5, cycle: 'monthly',
      next_date: '2026-10-01', create_pending: true, create_needs_review: false }];
    retryRecurring = async () => {};
    globalThis.list = recurringList;
    globalThis.form = _recurringForm;
    globalThis.retryCreate = retryRecurringCreate;
  `, context);
  assert.match(context.list(), /data-retry-create-rec="saved-id"/);
  assert.match(context.form(), /finish the pending schedule/);
  await context.retryCreate({ dataset: { retryCreateRec: 'saved-id' }, disabled: false, textContent: '' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/money/recurring/saved-id/retry');
  vm.runInContext('_recurring[0].create_needs_review = true;', context);
  assert.doesNotMatch(context.list(), /data-retry-create-rec/);
});

test('pending recurring edit stays visible and retries only the saved edit', async () => {
  const source = moneySource.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  const calls = [];
  const context = vm.createContext({
    location: { search: '' }, URLSearchParams,
    api: async (path, options) => { calls.push({ path, options }); return {}; },
    formatNumber: value => String(value),
  });
  vm.runInContext(source + `
    _canonicalLedger = true;
    _recurring = [{ id: 'saved-id', payee: 'rent', amount: -42.5, cycle: 'monthly',
      next_date: '2026-10-01', active: false, manageable: true,
      edit_pending: true, edit_needs_review: false }];
    retryRecurring = async () => {};
    globalThis.list = recurringList;
    globalThis.retryEdit = retryRecurringEdit;
  `, context);
  assert.match(context.list(), /data-retry-edit-rec="saved-id"/);
  assert.match(context.list(), /edit not confirmed/);
  assert.doesNotMatch(context.list(), /data-toggle-rec/);
  assert.doesNotMatch(context.list(), />inactive</);
  await context.retryEdit({ dataset: { retryEditRec: 'saved-id' }, disabled: false, textContent: '' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/money/recurring/saved-id/edit/retry');
  assert.equal(calls[0].options.method, 'POST');
  vm.runInContext('_recurring[0].edit_needs_review = true;', context);
  assert.match(context.list(), /review the schedule there/);
  assert.doesNotMatch(context.list(), /data-retry-edit-rec/);
  await context.retryEdit({ dataset: { retryEditRec: 'saved-id' }, disabled: false, textContent: '' });
  assert.equal(calls.length, 1);
});

test('recurring edit stays scoped to one eligible linked schedule', () => {
  const source = moneySource.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  const context = vm.createContext({
    location: { search: '' }, URLSearchParams,
    formatNumber: value => String(value),
  });
  vm.runInContext(source + `
    _canonicalLedger = true;
    _recurring = [
      { id: 'linked', payee: 'rent', amount: -5, amount_kind: 'exact', cycle: 'monthly',
        next_date: '2026-10-01', active: false, manageable: true, editable: true },
      { id: 'native', payee: 'native', amount: -3, cycle: 'monthly',
        next_date: '2026-10-01', active: true, manageable: false, editable: false },
    ];
    _recurringEdit = { id: 'linked', options: {
      accounts: [{ id: 'account-id', name: 'checking' }],
      payees: [{ id: 'payee-id', name: 'rent' }],
      categories: [{ id: 'category-id', name: 'housing' }],
    }, draft: {
      account_id: 'account-id', payee_id: 'payee-id', category_id: 'category-id',
      amountText: '5', sign: '-', cycle: 'monthly', cycle_days: 30,
      next_date: '2026-10-01', active: false, notes: 'lease',
    }, status: '', saving: false, blocked: false };
    globalThis.list = recurringList;
  `, context);
  const open = context.list();
  assert.match(open, /data-edit-rec="linked"/);
  assert.doesNotMatch(open, /data-edit-rec="native"/);
  assert.match(open, /id="rce-panel"/);
  assert.match(open, /data-choice-id="category-id"/);
  assert.match(open, /role="switch" aria-checked="false"/);
  assert.doesNotMatch(open, /data-toggle-rec="linked"/);
  vm.runInContext('_recurring[0].editable = false; _recurring[0].edit_pending = true;', context);
  const pending = context.list();
  assert.doesNotMatch(pending, /id="rce-panel"/);
  assert.doesNotMatch(pending, /data-edit-rec="linked"/);
  assert.match(pending, /data-retry-edit-rec="linked"/);
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
    'remove this spending cap',
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
