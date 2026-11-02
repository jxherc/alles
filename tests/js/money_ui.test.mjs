import { calendarDateKey, t, tp } from '../../static/js/i18n.js';
import { amountIn, bareSign, excludedNotes, totalsCurrency } from '../../static/js/money_currency.js';
import { assignHues, categoryHue } from '../../static/js/color.js';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { whenDay, whenFull, whenHtml } from '../../static/js/when.js';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

function harness() {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      innerHTML: '', value: '', dataset: {}, attributes: {}, textContent: '',
      contains() { return false; },
      addEventListener() {},
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      focus() { this.focused = true; },
    });
    return elements.get(id);
  };
  const requests = [];
  const context = vm.createContext({ whenDay, whenFull, whenHtml,
    t, tp,
    calendarDateKey,
    document: { getElementById: get }, location: { search: '' }, URLSearchParams,
    formatCalendarDate: () => 'october 2026',
    formatNumber: (value, options) => new Intl.NumberFormat('en-CA', options).format(value),
    toast() {}, tickNumbers() {}, api: async (...args) => { requests.push(args); return {}; },
    amountIn, bareSign, excludedNotes, totalsCurrency, wireCurrency() {}, assignHues, categoryHue,
  });
  vm.runInContext(source + `
    _cur = 'CAD';
    _accounts = [{ id: 'checking', name: 'checking', balance: 12345678.9 }, { id: 'savings', name: 'savings' }];
    wire = () => {};
    globalThis.subject = { render, addTxnRow, transferRow, editTxnRow, splitEditorRow,
      _accountForm, _budgetForm, _recurringForm, goalsCard, holdingsCard, reportsCard,
      moneyField, moneySection, toggleMoneySection, toggleTransactionDetails, fmt, summaryAmount, addTxn, transactionAmountError,
      _renderTxnMain, accountsList, summaryCards, catChart, trendChart, envelopeCard, networthCard, alertsStrip,
      budgetsList, totalsUnit, setBudgets: rows => { _budgets = rows; }, setGoals: (rows, currency) => { _goals = rows; _goalsCurrency = currency; },
      setCurrency: (accounts, summary, canonical = false) => { _accounts = accounts; _sum = summary; _canonicalLedger = canonical; _cur = summary.currency; },
      setTask: id => { _moneyPlanTask = id; },
      setEnvelope: value => { _envelope = value; },
      setAlerts: value => { _alerts = value; },
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
  assert.ok(html.indexOf('id="money-entry-fields"') < html.indexOf('class="money-summary"'));
  assert.ok(html.indexOf('id="money-entry-fields"') < html.indexOf('money-txns'));
});

test('optional transaction details disclose without changing the draft', () => {
  const h = harness();
  h.get('tx-cat').value = 'workshop';
  h.get('tx-tags').value = 'agenda';
  assert.match(h.addTxnRow(), /id="tx-details" hidden/);
  h.toggleTransactionDetails();
  assert.equal(h.get('tx-details').hidden, false);
  assert.equal(h.get('tx-details-toggle').attributes['aria-expanded'], 'true');
  assert.doesNotMatch(h.addTxnRow(), /id="tx-details" hidden/);
  h.toggleTransactionDetails();
  assert.equal(h.get('tx-details').hidden, true);
  assert.equal(h.get('tx-details-toggle').attributes['aria-expanded'], 'false');
  assert.equal(h.get('tx-cat').value, 'workshop');
  assert.equal(h.get('tx-tags').value, 'agenda');
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
  // one sign style: a true minus before the code, never a hyphen after it
  assert.equal(strip(h.summaryAmount(-12.34)), '−CAD\u00a012.34');
  assert.equal(h.fmt(-980098.43, 'USD'), '−USD\u00a0980,098.43');
  assert.equal(h.fmt(-0.001, 'USD'), 'USD\u00a00.00');
  // with no currency the label isn't the amount, so the minus stays on the number
  assert.equal(h.fmt(-93, 'XXX'), 'currency not set\u00a0−93.00');
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

test('a foreign account no longer turns analytics off: totals stay in the base currency and say what they left out', () => {
  const h = harness();
  h.setCurrency([{ id: 'c', name: 'everyday', currency_code: 'CAD' }, { id: 'u', name: 'us card', currency_code: 'USD' }], {
    currency: 'CAD', currency_status: 'partial', net_worth: 90, expense: 10, income: 0, net: -10, by_category: [['food', 10]], budgets: [], trend: [],
    base_currency: { code: 'CAD', fixed: false }, rates: [], complete: false,
    excluded: [{ currency: 'USD', accounts: 1, transactions: 1, net_worth: 90, income: 0, expense: 10 }],
    totals_by_currency: ['CAD', 'USD'].map(currency => ({ currency, net_worth: 90, expense: 10, income: 0, net: -10 })) });
  const strip = html => html.replace(/<[a-z/][^>]*>/gi, ' ').replace(/\s+/g, ' ');
  const html = h.summaryCards();
  assert.match(strip(html), /totals in CAD/);
  assert.match(strip(html), /1 account in USD isn't in these totals · USD 90\.00, spent USD 10\.00 this month add USD rate/);
  assert.match(strip(html), /net worth CAD 90\.00/);
  assert.doesNotMatch(strip(html), /CAD 180\.00|mixed currencies|no conversion has been applied/);
  for (const renderer of [h.catChart, h.envelopeCard, h.goalsCard, h.holdingsCard, h.reportsCard]) {
    assert.doesNotMatch(renderer(), /combined analytics need one known currency/);
  }
  assert.match(h.catChart(), /food/);
  h.setTask('budgets');
  h.render();
  assert.match(strip(h.get('money-body').innerHTML), /spending caps USD 10\.00 of spending isn't counted here yet add USD rate/);
});

test('a ledger with no currency set anywhere keeps its totals separate', () => {
  const h = harness();
  h.setCurrency([], { currency: '$', currency_status: 'unknown', net_worth: 180, expense: 20,
    totals_by_currency: [{ currency: 'XXX', account_id: 'a', account_name: 'a', net_worth: 90, expense: 10, income: 0, net: -10 },
      { currency: 'XXX', account_id: 'b', account_name: 'b', net_worth: 90, expense: 10, income: 0, net: -10 }] });
  const html = h.summaryCards();
  assert.match(html, /currency not set · totals stay separate/);
  for (const renderer of [h.catChart, h.trendChart, h.envelopeCard, h.networthCard, h.goalsCard, h.holdingsCard, h.reportsCard]) {
    assert.match(renderer(), /combined analytics need one known currency/);
  }
  assert.equal(h.alertsStrip(), '');
});

test('alerts keep an amount with no rate in its own currency', () => {
  const h = harness();
  h.setCurrency([], { currency: 'CAD', currency_status: 'partial' });
  h.setAlerts({ large_purchases: [{ payee: 'us shop', amount: -250, currency: 'USD' }, { payee: 'home', amount: -300 }],
    low_balance: [{ name: 'us card', balance: 5, threshold: 50, currency: 'USD' }] });
  const html = h.alertsStrip().replace(/<[a-z/][^>]*>/gi, '');
  assert.match(html, /us shop −USD\u00a0250\.00/);
  assert.match(html, /home −CAD\u00a0300\.00/);
  assert.match(html, /us card low: USD\u00a05\.00 < USD\u00a050\.00/);
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
    assert.match(html, /id="money-task-pick" data-value="goals" data-options="accounts\|accounts;budgets\|budgets;schedules\|schedules;goals\|goals"/);
    assert.doesNotMatch(html, /data-money-task="/);
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
  assert.match(html, /aria-pressed="true"><span aria-hidden="true">.*?<\/span> <span class="tx-clear-label">cleared<\/span><\/button>/);
  assert.match(html, /aria-label="cleared: owned &amp; exact/);
  assert.match(html, /<span class="tx-receipt-label">view receipt<\/span><\/a>/);
  assert.match(h._renderTxnMain({...row,transfer_id:'transfer'}, {checking:'checking'}), />delete transfer<\/button>/);
});

test('totals are labelled in the currency the summary added up in, not the first account', () => {
  const h = harness();
  // EUR account first, CAD second, reviewed EUR→CAD: the CAD total once read "EUR 200.00"
  h.setCurrency([{ id: 'e', currency_code: 'EUR' }, { id: 'c', currency_code: 'CAD' }], {
    currency: 'CAD', currency_status: 'single', base_currency: { code: 'CAD', fixed: false }, net_worth: 200,
    totals_by_currency: [{ currency: 'EUR', net_worth: 100 }, { currency: 'CAD', net_worth: 50 }] });
  assert.equal(h.totalsUnit(), 'CAD');
  // an older reply with no base currency keeps its one native group
  h.setCurrency([], { currency: '$', currency_status: 'single', totals_by_currency: [{ currency: 'EUR' }] });
  assert.equal(h.totalsUnit(), 'EUR');
});

test('caps saved in CAD show converted in USD totals, or stay in CAD with a note when no rate', () => {
  const h = harness();
  const strip = html => html.replace(/<[a-z/][^>]*>/gi, ' ').replace(/\s+/g, ' ');
  const base = { currency: 'USD', currency_status: 'converted', base_currency: { code: 'USD', fixed: false },
    ledger_currency: 'CAD', rates: [{ from: 'USD', to: 'CAD', rate: '1.25' }], excluded: [], included: true };
  h.setCurrency([{ id: 'c', currency_code: 'CAD' }], { ...base, budgets_currency: 'USD', budgets: [{ category: 'food', limit: 80, spent: 32 }] });
  h.setBudgets([{ id: 'b', category: 'food', limit_amt: 100 }]);
  assert.match(strip(h.budgetsList()), /USD 32\.00 \/ USD 80\.00/);
  h.setCurrency([{ id: 'c', currency_code: 'CAD' }], { ...base, rates: [], budgets_currency: 'CAD', budgets: [{ category: 'food', limit: 100, spent: 40 }] });
  assert.match(strip(h.budgetsList()), /CAD 40\.00 \/ CAD 100\.00/);
  h.setTask('budgets');
  h.render();
  const html = h.get('money-body').innerHTML;
  assert.match(strip(html), /spending caps are saved in CAD, so they're shown in CAD add CAD rate/);
  assert.match(html, /data-totals-rate="CAD:USD"/);
  assert.match(strip(html), /monthly cap \(CAD\)/);
  h.setGoals([{ id: 'g', name: 'trip', kind: 'savings', target: 800, current: 200, progress: 0.25, eta_months: null }], 'USD');
  assert.match(strip(h.goalsCard()), /USD 200\.00 \/ USD 800\.00/);
  assert.match(strip(h.goalsCard()), /target amount \(CAD\)/);
});

test('the envelope edits the saved number and names income it left out', () => {
  const h = harness();
  const strip = html => html.replace(/<[a-z/][^>]*>/gi, ' ').replace(/\s+/g, ' ');
  h.setCurrency([{ id: 'c', currency_code: 'CAD' }], { currency: 'USD', currency_status: 'converted',
    base_currency: { code: 'USD', fixed: false }, ledger_currency: 'CAD', rates: [], excluded: [], included: true });
  h.setEnvelope({ currency: 'USD', excluded_currency: 'CAD', income: 400, to_be_budgeted: 240, assigned_total: 160,
    excluded: [{ currency: 'EUR', accounts: 1, income: 1000, expense: 0 }],
    categories: [{ category: 'food', assigned: 160, assigned_saved: 200, spent: 32, available: 128, target: null }] });
  const html = h.envelopeCard();
  assert.match(html, /value="200"/);
  assert.match(html, /data-expected="200"/);
  assert.match(strip(html), /assigned \(CAD\)/);
  assert.match(strip(html), /USD 128\.00/);
  assert.match(strip(html), /EUR 1,000\.00 income isn't counted yet add EUR rate/);
  assert.match(html, /data-totals-rate="EUR:CAD"/);
});

test('an account with no currency is asked which one it is; Actual says its base is fixed', () => {
  const h = harness();
  const strip = html => html.replace(/<[a-z/][^>]*>/gi, ' ').replace(/\s+/g, ' ');
  h.setCurrency([{ id: 'old', name: 'old', currency_code: 'XXX', balance: 460 }, { id: 'c', currency_code: 'CAD' }], {
    currency: 'CAD', currency_status: 'partial', base_currency: { code: 'CAD', fixed: false }, ledger_currency: 'CAD',
    rates: [], included: true, excluded: [{ currency: 'XXX', accounts: 1, transactions: 1, net_worth: 460, income: 0, expense: 40 }] });
  const html = h.summaryCards();
  // the account that has no currency is asked about, with the dropdown right there, instead of listed as left out
  assert.match(strip(html), /which currency is old\?/);
  assert.match(html, /data-ask-currency="old"/);
  assert.doesNotMatch(strip(html), /has no currency set and isn't in these totals/);
  h.setCurrency([], { currency: 'CAD', ledger: 'actual' }, true);
  assert.match(strip(h.summaryCards()), /totals follow your Actual ledger in CAD/);
});

test('an account made with "$" reads as money and asks which currency it is, in one line with the dropdown', () => {
  const h = harness();
  const account = { id: 'a', name: 'td chequing', kind: 'checking', currency: '$', currency_code: 'XXX', balance: 735.46,
    balance_by_currency: [{ currency: 'XXX', balance: 735.46 }] };
  h.setCurrency([account], { currency: '$', currency_status: 'unknown', net_worth: 735.46, expense: 5.5, income: 0, net: -5.5,
    totals_by_currency: [{ currency: 'XXX', account_id: 'a', account_name: 'td chequing', net_worth: 735.46, expense: 5.5, income: 0, net: -5.5 }] });
  const strip = html => html.replace(/<[a-z/][^>]*>/gi, ' ').replace(/\s+/g, ' ');
  const cards = h.summaryCards();
  // the money screen never says "currency not set" next to the sign the account was made with
  assert.doesNotMatch(strip(cards), /currency not set|totals stay separate/);
  assert.match(strip(cards), /net worth \$\s*735\.46/);
  // one question, with the currency dropdown right there
  assert.match(strip(cards), /which currency is \$\?/);
  assert.match(cards, /class="settings-input custom-select money-currency-pick" data-ask-currency="a"/);
  const list = h.accountsList();
  assert.doesNotMatch(strip(list), /currency not set|xxx/i);
  assert.match(strip(list), /\$735\.46/);
  assert.match(strip(list), /checking · \$/);
  // the card has the same dropdown, empty until a currency is picked
  assert.match(list, /data-acct-currency="a" data-value=""/);
  assert.doesNotMatch(list, /data-currency-acct|change currency/);
  const row = { id: 't', account_id: 'a', amount: -10, date: '2026-10-01', payee: 'p', original_currency_code: 'XXX' };
  assert.match(h._renderTxnMain(row, { a: 'td chequing' }), /−\$10\.00/);
});

test('two accounts made with different signs each ask, naming themselves', () => {
  const h = harness();
  const accounts = [
    { id: 'a', name: 'cash', currency: '$', currency_code: 'XXX', balance: 5 },
    { id: 'b', name: 'trip', currency: '€', currency_code: 'XXX', balance: 7 },
  ];
  h.setCurrency(accounts, { currency: '$', currency_status: 'unknown', totals_by_currency: [
    { currency: 'XXX', account_id: 'a', account_name: 'cash', net_worth: 5, expense: 0, income: 0, net: 0 },
    { currency: 'XXX', account_id: 'b', account_name: 'trip', net_worth: 7, expense: 0, income: 0, net: 0 }] });
  const text = h.summaryCards().replace(/<[a-z/][^>]*>/gi, ' ').replace(/\s+/g, ' ');
  assert.match(text, /which currency is \$ in cash\?/);
  assert.match(text, /which currency is € in trip\?/);
  assert.match(text, /\$\s*5\.00/);
  assert.match(text, /€\s*7\.00/);
});

test('an account with no sign at all asks by name, and a fixed currency is a disabled dropdown with its reason', () => {
  const h = harness();
  h.setCurrency([{ id: 'a', name: 'old', currency: '', currency_code: 'XXX', balance: 1 }], { currency: '', currency_status: 'unknown', totals_by_currency: [
    { currency: 'XXX', account_id: 'a', account_name: 'old', net_worth: 1, expense: 0, income: 0, net: 0 }] });
  assert.match(h.summaryCards().replace(/<[a-z/][^>]*>/gi, ' '), /which currency is old\?/);
  h.setCurrency([{ id: 'c', name: 'fixed', currency: 'CAD', currency_code: 'CAD', balance: 3, currency_edit_reason: 'currency is fixed while an account has saved amounts.' }], { currency: 'CAD' });
  const list = h.accountsList();
  assert.match(list, /data-acct-currency="c" data-value="CAD"[^>]*aria-disabled="true"/);
  assert.match(list, /currency is fixed while an account has saved amounts/);
});
