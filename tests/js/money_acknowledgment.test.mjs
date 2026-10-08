import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

const source = readFileSync(new URL('../../static/js/money.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

function harness({ search = false, missing = false, quota = false } = {}) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', dataset: {}, textContent: '', hidden: false,
      querySelector: () => null, contains: () => false,
      removeAttribute() {}, setAttribute() {},
    });
    return elements.get(id);
  };
  const fields = { amount: 'amount', sign: 'sign', account_id: 'account', date: 'date', category: 'category', payee: 'payee' };
  const row = { dataset: { originalAccount:'account', originalAmount:'-10' }, contains: () => false,
    querySelector: selector => get(fields[selector.match(/data-f="([^"]+)"/)[1]]) };
  get('money-body').querySelector = () => row;
  get('amount').value = '20'; get('sign').dataset.value = '-';
  get('account').dataset.value = 'account'; get('date').dataset.value = '2026-10-06';
  for (const [id,value] of Object.entries({'tx-amt':'4.25','tx-payee':'exact 草稿','tx-cat':'food','tx-tags':'owned'})) get(id).value = value;
  get('tx-acct').dataset.value = 'account'; get('tx-sign').dataset.value = '-'; get('tx-date').dataset.value = '2026-10-06';
  let amount = -10;
  const writes = [], storage = new Map();
  const state = { quota };
  const context = vm.createContext({
    calendarDateKey: () => '2026-10-06', location: { search:'' }, URLSearchParams,
    crypto:webcrypto, TextEncoder, fetch:async () => {},
    document: { activeElement:null, getElementById:get },
    getDropdownValue: el => el.dataset.value, toast() {},
    sessionStorage: {
      getItem:key => storage.get(key) ?? null,
      setItem(key,value) { if (key==='alles:finance-saved-transactions' && state.quota) throw new Error('synthetic quota'); storage.set(key,value); },
      removeItem:key => storage.delete(key),
    },
    api:async (path,options) => {
      writes.push({path,body:JSON.parse(JSON.stringify(options.body))});
      if (options.method==='PATCH') {
        if ('amount' in options.body) amount = options.body.amount;
        return { id:'existing',account_id:'account',amount };
      }
      return {id:'created',account_id:'account',amount:-4.25,payee:'exact 草稿',undo:{request_id:options.body.request_id}};
    },
  });
  vm.runInContext(source + `
    _txns = ${missing ? '[]' : "[{id:'existing',account_id:'account',amount:-10}]"};
    _searchResults = ${search ? "[{id:'existing',account_id:'account',amount:-10}]" : 'null'};
    load = async () => false;
    renderSavedTransactions = () => {};
    syncMoneyLayout = () => {};
    globalThis.subject = { saveTxn,addTxn,snapshot:()=>({saved:_moneySaved,status:_transactionSaveStatus}) };
  `,context);
  return { ...context.subject,get,writes,storage,state,amount:()=>amount,row };
}

for (const options of [{},{search:true},{missing:true}]) {
  test(`acknowledged edit remains the baseline after refresh fails: ${JSON.stringify(options)}`,async () => {
    const h = harness(options);
    await h.saveTxn('existing');
    assert.equal(h.amount(),-20);
    h.get('amount').value = '10';
    await h.saveTxn('existing');
    assert.equal(h.writes[1].body.amount,-10);
    assert.equal(h.amount(),-10);
  });
}

test('receipt quota retains exact input and recovery identity until a durable retry succeeds',async () => {
  const h = harness({quota:true});
  await h.addTxn();
  const id = h.writes[0].body.request_id;
  assert.equal(JSON.parse(h.storage.get('alles:finance-create:transaction')).request_id,id);
  assert.equal(h.get('tx-payee').value,'exact 草稿');
  assert.equal(h.get('tx-amt').value,'4.25');
  assert.match(h.snapshot().status,/transaction saved.*could not keep undo for reload/);
  h.state.quota = false;
  await h.addTxn();
  assert.equal(h.writes[1].body.request_id,id);
  assert.equal(h.storage.has('alles:finance-create:transaction'),false);
  assert.deepEqual(JSON.parse(h.storage.get('alles:finance-saved-transactions')),[{id:'created',request_id:id,state:'ready'}]);
  assert.equal(h.snapshot().saved.length,1);
  assert.equal(h.get('tx-payee').value,'');
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function refreshHarness() {
  const frames = [], summaries = [], elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, { value: '', textContent: '' });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: get, activeElement: null },
    calendarDateKey: () => '2026-10-07', formatCalendarDate: () => 'october 2026',
    formatNumber: (number, options) => new Intl.NumberFormat('en-CA', options).format(number),
    location: { search: '' }, URLSearchParams, clearTimeout, fetch() {},
    sessionStorage: { setItem() {} }, frames,
    api: async path => {
      if (path.startsWith('/api/money/summary?')) {
        const pending = deferred();
        summaries.push(pending);
        return pending.promise;
      }
      if (path === '/api/money/currencies') return { codes: ['CAD'] };
      if (path === '/api/money/goals') return { goals: [] };
      return [];
    },
  });
  vm.runInContext(source + `
    _cur = 'CAD';
    _moneySaved = [{ id: 'synthetic', request_id: 'local', state: 'ready',
      saved: { payee: 'supplies', amount: -19.75, date: '2026-10-07' } }];
    _setMonthUrl = () => {};
    renderSavedTransactions = () => frames.push(savedTransactions());
    render = () => frames.push(savedTransactions());
    renderTxns = () => {};
    globalThis.subject = { load: () => load(fetch, true), html: savedTransactions };
  `, context);
  return { ...context.subject, frames, summaries };
}

const summary = { currency: 'CAD', currency_status: 'single', totals_by_currency: [] };

async function reachSummary(h, count = 1) {
  // load first awaits the schedule read; keep the controlled response pending.
  for (let turn = 0; turn < 10 && h.summaries.length < count; turn++) await Promise.resolve();
  assert.equal(h.summaries.length, count);
}

test('an acknowledged transaction keeps Undo while its list and balances refresh', async () => {
  const h = refreshHarness();
  const pending = h.load();
  assert.match(h.frames.at(-1) || '', /updating the list and balances/);
  assert.match(h.html(), /transaction saved/);
  assert.match(h.html(), /data-undo-saved="synthetic"/);
  await reachSummary(h);
  h.summaries[0].resolve(summary);
  assert.equal(await pending, true);
  assert.doesNotMatch(h.frames.at(-1), /updating the list and balances|could not be refreshed/);
  assert.match(h.frames.at(-1), /transaction saved/);
});

test('a failed refresh preserves the saved result and retry replaces the old failure with progress', async () => {
  const h = refreshHarness();
  const first = h.load();
  await reachSummary(h);
  h.summaries[0].reject(new Error('synthetic read failure'));
  assert.equal(await first, false);
  assert.match(h.html(), /could not be refreshed/);
  assert.doesNotMatch(h.html(), /updating the list and balances/);
  assert.match(h.html(), /data-undo-saved="synthetic"/);
  const retry = h.load();
  assert.match(h.frames.at(-1), /updating the list and balances/);
  assert.doesNotMatch(h.frames.at(-1), /could not be refreshed/);
  await reachSummary(h, 2);
  h.summaries[1].resolve(summary);
  assert.equal(await retry, true);
  assert.doesNotMatch(h.html(), /updating the list and balances|could not be refreshed/);
});

for (const outcome of ['resolve', 'reject']) {
  test(`a superseded ${outcome} cannot clear a newer refresh indicator`, async () => {
    const h = refreshHarness();
    const earlier = h.load();
    await reachSummary(h);
    const current = h.load();
    await reachSummary(h, 2);
    h.summaries[0][outcome](outcome === 'resolve' ? summary : new Error('old failure'));
    assert.equal(await earlier, false);
    assert.match(h.html(), /updating the list and balances/);
    assert.doesNotMatch(h.html(), /could not be refreshed/);
    h.summaries[1].resolve(summary);
    assert.equal(await current, true);
    assert.doesNotMatch(h.html(), /updating the list and balances/);
  });
}
