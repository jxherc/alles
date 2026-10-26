import assert from 'node:assert/strict';
import test from 'node:test';

function el() {
  return {
    textContent: '',
    innerHTML: '',
    dataset: {},
    querySelectorAll: () => [],
  };
}

globalThis.document = {
  getElementById(id) {
    if (id === 'subs-summary') return this.summary;
    if (id === 'subs-list') return this.list;
    return null;
  },
  summary: el(),
  list: el(),
};

const { loadSubs } = await import('../../static/js/subs.js');

const dataFor = url => ({
  '/api/subscriptions': { subscriptions: [], summary: {} },
  '/api/subscriptions/analytics': { count: 0, by_category: [] },
  '/api/subscriptions/upcoming?days=7': { count: 0, items: [] },
  '/api/subscriptions/forecast?months=6': { forecast: [], total: 0 },
  '/api/subscriptions/duplicates': { groups: [] },
  '/api/money/accounts': [],
  '/api/subscriptions/unused?cycles=2': { unused: [] },
  '/api/subscriptions/detect': { candidates: [] },
})[url];

const resp = data => ({ ok: true, status: 200, headers: new Headers({ 'content-type': 'application/json' }), json: async () => data });

test('loadSubs starts panel requests together', async () => {
  const calls = [];
  let releaseMain;
  const mainWait = new Promise(resolve => { releaseMain = resolve; });

  globalThis.fetch = url => {
    calls.push(url);
    if (url === '/api/subscriptions') {
      return mainWait.then(() => resp(dataFor(url)));
    }
    return Promise.resolve(resp(dataFor(url)));
  };

  const loading = loadSubs();
  await Promise.resolve();

  assert.equal(calls.length, 8);
  assert.deepEqual(calls, [
    '/api/subscriptions',
    '/api/subscriptions/analytics',
    '/api/subscriptions/upcoming?days=7',
    '/api/subscriptions/forecast?months=6',
    '/api/subscriptions/duplicates',
    '/api/money/accounts',
    '/api/subscriptions/unused?cycles=2',
    '/api/subscriptions/detect',
  ]);

  releaseMain();
  await loading;
});

test('history keeps loading after an undo until the refreshed list lands', async () => {
  const { readFileSync } = await import('node:fs');
  const subs = readFileSync(new URL('../../static/js/subs.js', import.meta.url), 'utf8');
  const undo = subs.slice(subs.indexOf(`pop.querySelector('[data-act="undo-last"]')?.addEventListener`), subs.indexOf('function esc('));
  // the empty "no payments yet" used to show mid-refresh while every button was still disabled.
  // the open panel says "payment undone" itself: a toast covered its rows on a phone
  assert.match(undo, /state\.pays = state\.pays\.filter\(p => p\.id !== payment\.id\); state\.error = ''; state\.loading = true;\r?\n\s+await loadSubs\(\);\r?\n\s+if \(_history === state\) await showHistory\(state\.id, t\('subs\.payment_undone'\)\);\r?\n\s+else toast\(t\('subs\.payment_undone'\), 'success'\);/);
  assert.match(subs, /\(state\.status \? '<div class="sub-hist-status" role="status"><\/div>' : ''\)/);
  assert.match(subs, /payment = !state\.loading && state\.pays\.find\(p => p\.can_undo\)/);
  assert.match(subs, /\(!state\.loading && !state\.error && !state\.pays\.length \? `<div class="sub-hist-empty">\$\{t\('subs\.no_payments'\)\}<\/div>` : ''\)/);
});

test('a currency with no rate stays out of every total, named with its own subtotal', async () => {
  const summary = {
    active: 3, monthly_total: 20, yearly_total: 240, currency: 'CAD', totals_available: true,
    base_currency: { code: 'CAD', fixed: false }, rates: [], complete: false,
    excluded: [{ currency: 'USD', count: 2, total: 19.49, monthly_total: 19.49, yearly_total: 233.88 }],
  };
  const data = {
    '/api/subscriptions': { subscriptions: [{ id: 'a', name: 'local', price: 20, currency: 'CAD', cycle: 'monthly', next_due: '2026-11-01', active: true, days_until: 8 }], summary },
    '/api/subscriptions/analytics': { count: 3, monthly_total: 20, yearly_total: 240, currency: 'CAD', by_category: [{ name: 'media', monthly: 20 }], excluded: summary.excluded },
    '/api/subscriptions/upcoming?days=7': { days: 7, count: 0, items: [], total: 0, currency: 'CAD', excluded: [] },
    '/api/subscriptions/forecast?months=6': { months: 6, currency: 'CAD', total: 120, forecast: [{ month: '2026-11', total: 120 }], excluded: [{ currency: 'USD', count: 2, total: 116.94 }] },
  };
  globalThis.fetch = url => Promise.resolve(resp(data[url] || dataFor(url)));
  const { loadSubs } = await import('../../static/js/subs.js');
  await loadSubs();
  const html = document.list.innerHTML.replace(/<[a-z/][^>]*>/gi, ' ').replace(/\s+/g, ' ');
  assert.match(document.summary.textContent, /3 active · CAD 20\.00\/mo \+ USD\u00a019\.49\/mo · CAD 240\.00\/yr \+ USD\u00a0233\.88\/yr/);
  assert.match(html, /totals in CAD/);
  assert.match(html, /2 subscriptions in USD aren't in the total · USD 19\.49\/mo add USD rate/);
  assert.match(document.list.innerHTML, /data-totals-rate="USD:CAD"/);
  assert.match(html, /CAD 120\.00 \+ USD 116\.94 projected/);
  // some CAD is in the total, so switching the whole base isn't offered
  assert.doesNotMatch(html, /show totals in USD/);
});
