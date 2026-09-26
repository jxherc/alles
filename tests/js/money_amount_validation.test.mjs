import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

function harness(values = {}) {
  const elements = new Map();
  const requests = [], notices = [];
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      value: values[id] ?? '', dataset: { value: values[id] ?? '' }, textContent: '',
      querySelector: () => null, querySelectorAll: () => [],
    });
    return elements.get(id);
  };
  const edits = { amount: 'edit-amount', sign: 'edit-sign', payee: 'edit-payee', category: 'edit-category', account_id: 'edit-account', date: 'edit-date' };
  get('money-body').querySelector = selector => selector.startsWith('.txn-edit')
    ? { querySelector: field => get(edits[field.match(/data-f="(.+)"/)[1]]) }
    : null;
  const context = vm.createContext({
    document: { getElementById: get }, location: { search: '' }, URLSearchParams,
    crypto: webcrypto, TextEncoder,
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    getDropdownValue: el => el?.dataset.value,
    toast: (...args) => notices.push(args),
    api: async (url, options = {}) => { requests.push({ url, ...options }); return {}; },
    dlgFields: async () => ({ amount: values['target-amount'] }),
  });
  vm.runInContext(source + `
    load = async () => {};
    globalThis.subject = { addAccount, addTxn, saveTxn, doTransfer, runReconcile,
      addGoal, addHolding, addBudget, addRecurring, assignEnvelope, setEnvTarget,
      applySearch, saveSplits, readSplits: _readSplitRows, decimal: _decimal };
  `, context);
  return { ...context.subject, requests, notices, get };
}

const valid = {
  'af-name': 'checking', 'af-kind': 'checking', 'tx-amt': '12.34',
  'tx-sign': '-', 'tx-acct': 'a', 'tx-payee': 'groceries', 'tx-cat': 'food',
  'edit-amount': '56.78', 'edit-sign': '-', 'edit-payee': 'corrected', 'edit-category': 'food', 'edit-account': 'a',
  'tr-from': 'a', 'tr-to': 'b', 'tr-amt': '23.45',
  'gl-name': 'rainy day', 'hd-sym': 'SYNTH', 'bf-cat': 'food', 'rc-payee': 'bill', 'rc-amt': '10',
};

for (const malformed of ['1,234.56', '12.34garbage', 'Infinity', '1e309', '0x10']) {
  test(`Finance refuses the complete malformed number ${malformed} before any request`, async () => {
    const cases = [
      ['af-open', h => h.addAccount()], ['af-low', h => h.addAccount()],
      ['tx-amt', h => h.addTxn()], ['edit-amount', h => h.saveTxn('t')],
      ['tr-amt', h => h.doTransfer()], ['gl-target', h => h.addGoal()],
      ['gl-current', h => h.addGoal()], ['gl-monthly', h => h.addGoal()],
      ['hd-qty', h => h.addHolding()], ['hd-cost', h => h.addHolding()], ['hd-price', h => h.addHolding()],
      ['bf-amt', h => h.addBudget()], ['rc-amt', h => h.addRecurring()],
      ['target-amount', h => h.setEnvTarget('food')],
      ['txn-min', h => h.applySearch()], ['txn-max', h => h.applySearch()],
    ];
    for (const [id, action] of cases) {
      const h = harness({ ...valid, [id]: malformed });
      await action(h);
      assert.equal(h.requests.length, 0, id);
      assert.match(h.notices[0]?.[0] || '', /decimal point/, id);
      assert.equal(h.get(id).value, malformed, id);
    }
    const h = harness(valid);
    assert.equal(await h.assignEnvelope('food', malformed), false);
    assert.equal(h.requests.length, 0);
  });
}

test('valid decimal create, edit, and transfer values reach the API unchanged', async () => {
  const h = harness(valid);
  await h.addTxn(); await h.saveTxn('t'); await h.doTransfer();
  assert.deepEqual(h.requests.map(r => r.body.amount), [-12.34, -56.78, 23.45]);
  assert.equal(h.requests[0].method, 'POST');
  assert.equal(h.requests[1].method, 'PATCH');
  assert.ok(h.requests[0].body.request_id);
  assert.ok(h.requests[2].body.request_id);
});

test('optional account numbers keep blank zero defaults and signed decimals', async () => {
  const blank = harness(valid); await blank.addAccount();
  assert.equal(blank.requests[0].body.opening, 0);
  assert.equal(blank.requests[0].body.low_balance, 0);
  const signed = harness({ ...valid, 'af-open': '-1234.56', 'af-low': '100.25' });
  await signed.addAccount();
  assert.equal(signed.requests[0].body.opening, -1234.56);
  assert.equal(signed.requests[0].body.low_balance, 100.25);
});

test('reconciliation does not query an incorrectly truncated statement', async () => {
  const h = harness({ 'rc-stmt-a': '1,234.56' });
  await h.runReconcile('a');
  assert.equal(h.requests.length, 0);
  assert.match(h.get('rc-out-a').textContent, /decimal point/);
  assert.equal(h.get('rc-stmt-a').value, '1,234.56');
});

test('split drafts preserve malformed amounts until correction', async () => {
  const h = harness();
  h.get('money-body').querySelector = () => ({
    querySelectorAll: () => [{ querySelector: selector => ({ value: selector === '.split-cat' ? 'food' : '12.34garbage' }) }],
  });
  assert.equal(h.readSplits()[0].amount, '12.34garbage');
  await h.saveSplits('t');
  assert.equal(h.requests.length, 0);
  assert.match(h.notices[0][0], /decimal point/);
});

test('decimal input supports signs, leading decimals, whitespace, and rejects overflow', () => {
  const h = harness();
  for (const [raw, expected] of [[' .5 ', 0.5], ['+12.34', 12.34], ['-12.34', -12.34], ['0', 0]]) {
    assert.equal(h.decimal(raw), expected);
  }
  for (const raw of ['', ' ', 'NaN', '--1', '1.2.3', '9'.repeat(400)]) {
    assert.ok(Number.isNaN(h.decimal(raw)));
  }
});
