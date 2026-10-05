import { calendarDateKey } from '../../static/js/i18n.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

function harness() {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      innerHTML: '', value: '', dataset: {}, attributes: {}, textContent: '',
      contains() { return false; },
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      focus() { this.focused = true; },
    });
    return elements.get(id);
  };
  const requests = [];
  const context = vm.createContext({
    calendarDateKey,
    document: { getElementById: get }, location: { search: '' }, URLSearchParams,
    formatCalendarDate: () => 'october 2026',
    formatNumber: (value, options) => new Intl.NumberFormat('en-CA', options).format(value),
    toast() {}, api: async (...args) => { requests.push(args); return {}; },
  });
  vm.runInContext(source + `
    _cur = 'CAD';
    _accounts = [{ id: 'checking', name: 'checking', balance: 12345678.9 }, { id: 'savings', name: 'savings' }];
    wire = () => {};
    globalThis.subject = { render, addTxnRow, transferRow, editTxnRow, splitEditorRow,
      _accountForm, _budgetForm, _recurringForm, goalsCard, holdingsCard, reportsCard,
      moneyField, moneySection, toggleMoneySection, fmt, summaryAmount, addTxn, transactionAmountError,
      _renderTxnMain, accountsList, summaryCards, catChart, trendChart, envelopeCard, networthCard, alertsStrip,
      setCurrency: (accounts, summary, canonical = false) => { _accounts = accounts; _sum = summary; _canonicalLedger = canonical; _cur = summary.currency; },
      setTask: id => { _moneyPlanTask = id; },
      setEnvelope: value => { _envelope = value; },
      setRecurring: (rows, error = false) => { _recurring = rows; _recurringError = error; } };
  `, context);
  return { ...context.subject, get, requests };
}

test('Money puts transaction entry before dashboard panels and exposes a direct entry action', () => {
  const h = harness();
  h.render();
  const html = h.get('money-body').innerHTML;
  assert.match(h.get('money-entry-slot').innerHTML, /btn primary money-entry-action/);
  assert.doesNotMatch(html, /id="money-entry-action"/);
  assert.match(html, /id="txn-amount-range" hidden/);
  assert.ok(html.indexOf('money-txns') < html.indexOf('money-grid'));
  assert.match(html, /id="tx-add">add transaction/);
  assert.match(html, /filter transactions/);
});

test('Money custom choices retain a purpose distinct from their selected value', () => {
  const h = harness();
  for (const [form, labels] of [
    [h.addTxnRow(), ['account', 'type', 'date']],
    [h.transferRow(), ['from account', 'to account', 'date']],
    [h._accountForm(), ['account type', 'currency']],
    [h._recurringForm(), ['account', 'type', 'repeat', 'next date']],
  ]) {
    for (const label of labels) {
      assert.ok(form.includes(`<span class="money-field-label">${label}</span>`), label);
      assert.ok(form.includes(`aria-label="${label}"`), label);
    }
  }
});

test('filled Money edit and split fields keep visible associated labels and exact draft values', () => {
  const h = harness();
  const html = h.editTxnRow({ id: 't', payee: 'coffee & lunch', category: 'food', amount: -12.34, account_id: 'checking', date: '2026-10-01' });
  for (const label of ['payee', 'category', 'amount']) {
    assert.match(html, new RegExp(`<label class="money-field"[^>]*><span class="money-field-label">${label}</span><input`));
  }
  assert.match(html, /value="coffee &amp; lunch"/);
  assert.match(html, /value="12.34"/);
  const split = h.splitEditorRow({ id: 't', amount: -12.34 });
  assert.match(split, /<label class="money-field"[^>]*><span class="money-field-label">category<\/span><input/);
  assert.match(split, /<label class="money-field"[^>]*><span class="money-field-label">amount<\/span><input/);
});

test('Money secondary forms retain purpose after their placeholders disappear', () => {
  const h = harness();
  for (const [html, labels] of [
    [h._accountForm(), ['account name', 'opening balance', 'low balance alert (0 = off)']],
    [h._budgetForm(), ['category', 'monthly cap']],
    [h.goalsCard(), ['goal name', 'target amount', 'current amount', 'monthly amount']],
    [h.holdingsCard(), ['symbol', 'quantity', 'cost per share', 'price per share']],
    [h.reportsCard(), ['start date', 'end date']],
  ]) for (const label of labels) assert.ok(html.includes(`<span class="money-field-label">${label}</span>`), label);
});

test('invalid transaction amount preserves the draft and connects a persistent recovery message', async () => {
  const h = harness();
  h.get('tx-payee').value = 'coffee';
  h.get('tx-amt').value = '12.34garbage';
  await h.addTxn();
  assert.equal(h.requests.length, 0);
  assert.equal(h.get('tx-payee').value, 'coffee');
  assert.equal(h.get('tx-amt').value, '12.34garbage');
  assert.equal(h.get('tx-amt').attributes['aria-invalid'], 'true');
  assert.equal(h.get('tx-amt').attributes['aria-describedby'], 'tx-amt-error');
  assert.match(h.get('tx-amt-error').textContent, /1234\.56/);
  assert.equal(h.get('tx-amt').focused, true);
  h.transactionAmountError('');
  assert.equal(h.get('tx-amt-error').textContent, '');
  assert.equal(h.get('tx-amt').attributes['aria-invalid'], undefined);
});

test('Money currency-code amounts keep grouping and exactly two cents', () => {
  const h = harness();
  assert.equal(h.fmt(12345678.9), 'CAD\u00a012,345,678.90');
  assert.equal(h.fmt(0), 'CAD\u00a00.00');
});

test('Money summary can wrap its currency prefix while preserving one complete numeric token', () => {
  const h = harness();
  const strip = html => html.replace(/<[^>]*>/g, '');
  const amount = h.summaryAmount(12345678.9);
  assert.match(amount, /^CAD\u00a0<wbr><span class="ms-number">12,345,678\.90<\/span>$/);
  assert.equal(strip(amount), h.fmt(12345678.9));
  assert.equal(strip(h.summaryAmount(-12345678.9, true)), '−CAD\u00a012,345,678.90');
  assert.equal(strip(h.summaryAmount(0, true)), '+CAD\u00a00.00');
  assert.equal(strip(h.summaryAmount(-12.34)), 'CAD\u00a0-12.34');
});

test('native rows use historical currency and unknown evidence stays unknown', () => {
  const h = harness();
  h.setCurrency([{ id: 'a', name: 'changed account', currency_code: 'CAD' }], { currency: 'CAD' });
  const row = { id: 'old', account_id: 'a', amount: -10, date: '2026-10-01', payee: 'old' };
  assert.match(h._renderTxnMain({ ...row, original_currency_code: 'USD' }, { a: 'changed account' }), /−USD\u00a010\.00/);
  for (const code of ['', 'XXX']) {
    const html = h._renderTxnMain({ ...row, original_currency_code: code }, { a: 'changed account' });
    assert.match(html, /−currency not set\u00a010\.00/);
    assert.doesNotMatch(html, /−CAD/);
  }
  h.setCurrency([{ id: 'a', name: 'migrated', currency_code: 'USD', currency: 'CAD', balance: 13.5 }], { currency: 'CAD' }, true);
  assert.match(h.accountsList(), /CAD\u00a013\.50/);
  assert.doesNotMatch(h.accountsList(), /USD\u00a013\.50/);
  assert.match(h._renderTxnMain({ ...row, original_currency_code: 'USD' }, { a: 'migrated' }), /−CAD\u00a010\.00/);
});

test('mixed-currency summary stays separate and combined analytics cannot present raw sums as a conversion', () => {
  const h = harness();
  h.setCurrency([], { currency: 'CAD', currency_status: 'mixed', net_worth: 180, expense: 20,
    totals_by_currency: ['CAD', 'USD'].map(currency => ({ currency, net_worth: 90, expense: 10, income: 0, net: -10 })) });
  const strip = html => html.replace(/<[^>]*>/g, '');
  const html = h.summaryCards();
  assert.match(html, /mixed currencies/);
  assert.match(strip(html), /CAD\u00a090\.00/);
  assert.match(strip(html), /USD\u00a090\.00/);
  assert.doesNotMatch(strip(html), /CAD\u00a0180\.00|CAD\u00a020\.00/);
  for (const renderer of [h.catChart, h.trendChart, h.envelopeCard, h.networthCard, h.goalsCard, h.holdingsCard, h.reportsCard]) {
    assert.match(renderer(), /combined analytics need one known currency/);
  }
  assert.equal(h.alertsStrip(), '');
});

test('Money supporting sections start closed and preserve deliberate expansion through refresh', () => {
  const h = harness();
  h.render();
  assert.match(h.get('money-body').innerHTML, /id="money-section-analytics" hidden/);
  const button = { dataset: { moneySection: 'analytics' }, disabled: false, attributes: {}, setAttribute(name, value) { this.attributes[name] = value; } };
  h.toggleMoneySection(button);
  assert.equal(button.attributes['aria-expanded'], 'true');
  assert.equal(h.get('money-section-analytics').hidden, false);
  h.render();
  assert.match(h.get('money-body').innerHTML, /data-money-section="analytics" aria-expanded="true"/);
  assert.doesNotMatch(h.get('money-body').innerHTML, /id="money-section-analytics" hidden/);
  h.toggleMoneySection(button);
  h.render();
  assert.match(h.get('money-body').innerHTML, /id="money-section-analytics" hidden/);
});

test('pending schedule recovery opens plans and prevents hiding the unresolved state', () => {
  const h = harness();
  h.setRecurring([{ id: 'pending', payee: 'rent', amount: -10, create_pending: true }]);
  h.render();
  const html = h.get('money-body').innerHTML;
  assert.match(html, /data-money-section="plans" aria-expanded="true"[^>]* disabled/);
  assert.match(html, /schedules & goals · needs attention/);
  assert.doesNotMatch(html, /id="money-section-plans" hidden/);
  const button = { dataset: { moneySection: 'plans' }, disabled: true };
  h.toggleMoneySection(button);
  h.render();
  assert.doesNotMatch(h.get('money-body').innerHTML, /id="money-section-plans" hidden/);
});


test('chosen management task survives refresh while other forms remain disclosed by choice', () => {
  const h = harness();
  h.setTask('goals');
  for (let n = 0; n < 2; n++) {
    h.render();
    const html = h.get('money-body').innerHTML;
    assert.match(html, /data-money-task="goals" aria-pressed="true"/);
    assert.match(html, /data-money-task-panel="accounts" hidden/);
    assert.match(html, /data-money-task-panel="budgets" hidden/);
    assert.match(html, /data-money-task-panel="schedules" hidden/);
    assert.match(html, /data-money-task-panel="goals">/);
    assert.doesNotMatch(html, /id="money-entry-close"/);
  }
});

test('pending schedules and envelope writes stay visible alongside the chosen task', () => {
  const h = harness();
  h.setTask('accounts');
  h.setRecurring([{ id: 'pending', payee: 'rent', amount: -10, create_pending: true }]);
  h.setEnvelope({ pending_assignments: [{ category_id: 'rent', assigned: 10 }] });
  h.render();
  const html = h.get('money-body').innerHTML;
  for (const id of ['schedules', 'budgets']) {
    assert.match(html, new RegExp(`data-money-task-panel="${id}" data-attention="true">`));
    assert.doesNotMatch(html, new RegExp(`data-money-task-panel="${id}"[^>]* hidden`));
  }
  assert.match(html, /data-card="recurring" data-attention="true"/);
  assert.match(html, /data-card="envelope" data-attention="true"/);
});

test('transaction action text explains effects and cleared keeps a stable toggle name', () => {
  const h = harness();
  const row = {id: 't', account_id: 'checking', amount: -12.5, payee: 'owned & exact', date: '2026-10-01', original_currency_code:'CAD'};
  let html = h._renderTxnMain(row, {checking:'checking'});
  for (const text of ['edit', 'split', 'attach receipt', 'delete']) assert.ok(html.includes(`>${text}</`), text);
  assert.match(html, /aria-label="cleared: owned &amp; exact/);
  html = h._renderTxnMain({...row,cleared:true,receipt_id:'owned-local'}, {checking:'checking'});
  assert.match(html, /aria-pressed="true"><span aria-hidden="true">✓<\/span> cleared<\/button>/);
  assert.match(html, /aria-label="cleared: owned &amp; exact/);
  assert.match(html, />view receipt<\/a>/);
  assert.match(h._renderTxnMain({...row,transfer_id:'transfer'}, {checking:'checking'}), />delete transfer<\/button>/);
});
