import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function readSlot() {
  return { ...deferred(), called: deferred() };
}

function harness() {
  const elements = new Map(), unexpected = [], writes = [];
  const currency = [readSlot(), readSlot()], goals = readSlot();
  let currencyIndex = 0, subject, renders = 0;
  const document = { activeElement: null, getElementById: id => elements.get(id) || null };
  const get = document.getElementById;
  function node(id) {
    let disabled = false;
    const element = {
      id, value: '', dataset: {}, attributes: {}, textContent: '', isConnected: true,
      closest: () => null, getClientRects: () => [{}],
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      get disabled() { return disabled; },
      set disabled(value) {
        disabled = value;
        if (value && document.activeElement === this) document.activeElement = document.body;
      },
      focus() {
        if (disabled || !this.isConnected || document.activeElement === this) return;
        document.activeElement = this;
        subject?.focusChanged();
      },
      remove() {
        this.isConnected = false;
        if (elements.get(id) === this) elements.delete(id);
        if (document.activeElement === this) document.activeElement = document.body;
      },
      querySelector: selector => get(selector.slice(1)),
    };
    elements.set(id, element);
    return element;
  }
  document.body = node('body');
  document.activeElement = document.body;
  const body = node('money-body');
  for (const [id, value] of Object.entries({
    'af-name': '  exact 草稿 account  ', 'af-open': '0012.30', 'af-low': '0002.50',
  })) node(id).value = value;
  node('af-kind').dataset.value = 'savings';
  const control = node('af-currency');
  control.dataset.value = '';
  control.dataset.options = '|choose currency';
  node('af-add');
  node('af-currency-error').textContent = 'currency choices could not be loaded.';
  node('af-currency-retry');
  const monthValues = {
    accounts: [], transactions: [], budgets: [{ category: 'rent', amount: 25 }],
    summary: { currency: 'CAD', income: 25 }, rules: [{ id: 'rule' }],
    envelope: { available: 25 }, 'age-of-money': { days: 3 }, forecast: { days: 7 },
    'networth-history': [{ value: 25 }], holdings: [{ id: 'holding' }],
    alerts: [{ id: 'alert' }], recurring: [{ id: 'schedule' }],
  };
  async function api(path, options = {}) {
    if (options.method && options.method !== 'GET') {
      writes.push({ path, options });
      throw new Error('unexpected write');
    }
    const key = path.replace('/api/money/', '').split('?')[0];
    if (key === 'currencies') {
      const slot = currency[currencyIndex++];
      assert.ok(slot, 'unexpected extra currency request');
      slot.called.resolve();
      return slot.promise;
    }
    if (key === 'goals') { goals.called.resolve(); return goals.promise; }
    if (Object.hasOwn(monthValues, key)) return monthValues[key];
    unexpected.push(path);
    throw new Error('unexpected request: ' + path);
  }
  function renderModel(codes, preserve) {
    // Model only the empty-ledger render's replacement of sibling status/retry nodes.
    // Retained form controls keep their identity. Browser coverage checks the real renderer.
    renders++;
    get('af-currency-error').remove();
    get('af-currency-retry')?.remove();
    node('af-currency-error').textContent = codes.length ? '' : 'currency choices could not be loaded.';
    if (!codes.length) node('af-currency-retry');
    if (preserve) subject.restore(body);
  }
  const context = vm.createContext({
    document, api, renderModel, URL, URLSearchParams, clearTimeout,
    location: { search: '?m=2026-10', href: 'http://owned.invalid/?m=2026-10' },
    replaceRouteUrl() {}, calendarDateKey: () => '2026-10-01',
    formatCalendarDate: () => 'october 2026',
    sessionStorage: { getItem: () => null, setItem() {} },
    fetch() { unexpected.push('raw fetch'); throw new Error('raw fetch forbidden'); },
    toast() {}, getDropdownValue: element => element?.dataset.value || '',
    populateDropdown(element, options, value) {
      element.dataset.options = options.map(option => `${option.value}|${option.label}`).join(';');
      element.dataset.value = value;
    },
  });
  vm.runInContext(source + `
    render = preserve => renderModel(_currencyCodes, preserve);
    syncMoneyLayout = () => {};
    applySearch = async () => {};
    globalThis.subject = {
      load: () => load(fetch, true, false), retry: retryCurrencyChoices, add: addAccount,
      focusChanged: () => { _moneyFocusChange++; },
      restore: body => restoreMoneyDrafts(body, {
        nodes: [], active: document.activeElement, control: null, focusVersion: _moneyFocusChange,
      }),
      state: () => JSON.stringify({ codes: _currencyCodes, accounts: _accounts, transactions: _txns,
        budgets: _budgets, summary: _sum, rules: _rules, envelope: _envelope,
        'age-of-money': _aom, forecast: _forecast, 'networth-history': _nwhist,
        holdings: _holdings, alerts: _alerts, recurring: _recurring, goals: _goals }),
    };
  `, context);
  subject = context.subject;
  return {
    ...subject, get, document, control, currency, goals, writes, unexpected,
    state: () => JSON.parse(subject.state()), renderCount: () => renders,
    expectedMonth: { ...monthValues, goals: [{ id: 'goal' }] },
  };
}

async function monthAtGoals(h, currencyIndex, codes = null) {
  const pending = h.load();
  await h.currency[currencyIndex].called.promise;
  if (codes) h.currency[currencyIndex].resolve({ codes });
  else h.currency[currencyIndex].reject(new Error('monthly currencies unavailable'));
  await h.goals.called.promise;
  return { pending };
}

async function finishMonth(h, month) {
  h.goals.resolve({ goals: [{ id: 'goal' }] });
  assert.equal(await month.pending, true);
  const { codes, ...rest } = h.state();
  assert.deepEqual(rest, h.expectedMonth, 'non-currency monthly results still commit');
  assert.equal(h.renderCount(), 1);
  assert.deepEqual(h.unexpected, []);
}

function exactDraft(h) {
  assert.equal(h.get('af-name').value, '  exact 草稿 account  ');
  assert.equal(h.get('af-open').value, '0012.30');
  assert.equal(h.get('af-low').value, '0002.50');
  assert.equal(h.get('af-kind').dataset.value, 'savings');
  assert.equal(h.get('af-currency'), h.control);
  assert.deepEqual(h.writes, []);
}

test('newer retry choices survive an older failed monthly completion', { timeout: 3000 }, async () => {
  const h = harness();
  const month = await monthAtGoals(h, 0);
  h.get('af-currency-retry').focus();
  const retry = h.retry();
  await h.currency[1].called.promise;
  h.currency[1].resolve({ codes: ['CAD', 'USD'] });
  await retry;
  assert.deepEqual(h.state().codes, ['CAD', 'USD']);
  assert.equal(h.get('af-currency-retry'), null);
  await finishMonth(h, month);
  assert.deepEqual(h.state().codes, ['CAD', 'USD']);
  assert.equal(h.get('af-currency-retry'), null);
  assert.match(h.control.dataset.options, /CAD\|CAD/);
  await h.add();
  assert.match(h.get('af-currency-error').textContent, /choose a currency/);
  exactDraft(h);
});

for (const focus of ['body', 'replacement', 'newer-input', 'newer-input-then-body']) {
  test(`retry removes a month's replacement button; focus owner ${focus}`, { timeout: 3000 }, async () => {
    const h = harness();
    const month = await monthAtGoals(h, 0);
    const original = h.get('af-currency-retry');
    original.focus();
    const retry = h.retry();
    await h.currency[1].called.promise;
    await finishMonth(h, month);
    const replacement = h.get('af-currency-retry');
    assert.ok(replacement);
    assert.notEqual(replacement, original);
    assert.equal(original.isConnected, false);
    const input = h.get('af-name');
    if (focus === 'replacement') replacement.focus();
    if (focus.startsWith('newer-input')) {
      input.focus();
      input.selectionStart = 2; input.selectionEnd = 8; input.selectionDirection = 'backward';
      if (focus === 'newer-input-then-body') h.document.activeElement = h.document.body;
    }
    const beforeFocus = h.document.activeElement;
    h.currency[1].resolve({ codes: ['CAD', 'USD'] });
    await retry;
    assert.deepEqual(h.state().codes, ['CAD', 'USD']);
    assert.equal(h.get('af-currency-retry'), null);
    assert.equal(replacement.isConnected, false);
    assert.equal(h.get('af-currency-error').textContent, '');
    assert.equal(h.document.activeElement, focus.startsWith('newer-input') ? beforeFocus : h.control);
    if (focus.startsWith('newer-input')) {
      assert.deepEqual([input.selectionStart, input.selectionEnd, input.selectionDirection], [2, 8, 'backward']);
    }
    exactDraft(h);
  });
}

for (const outcome of ['success', 'failure']) for (const order of ['retry-first', 'month-first']) {
  test(`stale retry ${outcome} cannot change newer month UI; ${order}`, { timeout: 3000 }, async () => {
    const h = harness();
    h.get('af-currency-retry').focus();
    const retry = h.retry();
    await h.currency[0].called.promise;
    const month = await monthAtGoals(h, 1, ['CAD']);
    h.get('af-name').focus();
    if (order === 'month-first') await finishMonth(h, month);
    const before = {
      codes: h.state().codes, error: h.get('af-currency-error').textContent,
      button: h.get('af-currency-retry'), options: h.control.dataset.options,
    };
    if (outcome === 'success') h.currency[0].resolve({ codes: ['EUR'] });
    else h.currency[0].reject(new Error('older retry unavailable'));
    await retry;
    assert.deepEqual(h.state().codes, before.codes);
    assert.equal(h.get('af-currency-error').textContent, before.error);
    assert.equal(h.get('af-currency-retry'), before.button);
    assert.equal(h.control.dataset.options, before.options);
    assert.equal(h.document.activeElement, h.get('af-name'));
    if (order === 'retry-first') await finishMonth(h, month);
    assert.deepEqual(h.state().codes, ['CAD']);
    assert.equal(h.get('af-currency-error').textContent, '');
    exactDraft(h);
  });
}

for (const outcome of ['request-failure', 'empty-codes']) {
  test(`current retry ${outcome} remains available and preserves newer input`, { timeout: 3000 }, async () => {
    const h = harness();
    const button = h.get('af-currency-retry');
    button.focus();
    const retry = h.retry();
    await h.currency[0].called.promise;
    h.get('af-name').focus();
    if (outcome === 'empty-codes') h.currency[0].resolve({ codes: [] });
    else h.currency[0].reject(new Error('retry unavailable'));
    await retry;
    assert.equal(h.get('af-currency-retry'), button);
    assert.equal(button.disabled, false);
    assert.match(h.get('af-currency-error').textContent, /could not be loaded.*retry/);
    assert.deepEqual(h.state().codes, []);
    assert.equal(h.document.activeElement, h.get('af-name'));
    exactDraft(h);
  });
}
