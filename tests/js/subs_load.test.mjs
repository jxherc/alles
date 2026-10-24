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
  // the empty "no payments yet" used to show mid-refresh while every button was still disabled
  assert.match(undo, /state\.pays = state\.pays\.filter\(p => p\.id !== payment\.id\); state\.error = ''; state\.loading = true;\r?\n\s+toast\('payment undone', 'success'\); await loadSubs\(\);\r?\n\s+if \(_history === state\) await showHistory\(state\.id\);/);
  assert.match(subs, /payment = !state\.loading && state\.pays\.find\(p => p\.can_undo\)/);
  assert.match(subs, /\(!state\.loading && !state\.error && !state\.pays\.length \? '<div class="sub-hist-empty">no payments yet<\/div>' : ''\)/);
});
