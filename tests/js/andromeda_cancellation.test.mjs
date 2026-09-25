import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '')
  .replace(/^export /gm, '');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const json = body => ({ ok: true, json: async () => body });
const preview = privacy => json({ endpoint_id: 'fixture', endpoint: 'fixture', model: 'fixture', privacy_class: privacy || 'local' });

function harness() {
  const elements = new Map();
  function element(id = '') {
    return {
      id, hidden: true, textContent: '', value: '', dataset: {}, handlers: new Map(),
      addEventListener(name, callback) { this.handlers.set(name, callback); },
      setAttribute() {}, replaceChildren() {}, focus() {},
      querySelectorAll: () => [], classList: { toggle() {} },
    };
  }
  const get = id => {
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  };
  const requests = [];
  const cancelledBodies = [];
  let intercept = () => undefined;
  let confirm = async () => true;
  const completed = (label = 'complete') => ({
    ok: true,
    body: {
      cancel: async () => { cancelledBodies.push(label); },
      getReader: () => ({ read: async () => ({ done: true }), cancel: async () => {} }),
    },
  });
  const translations = {
    'andromeda.checking_sources': 'checking sources…',
    'andromeda.reading_sources': 'reading sources…',
    'andromeda.overview_stopped': 'overview stopped. normal links are unchanged.',
    'andromeda.cancelled_unsent': 'cancelled before sending',
  };
  const context = vm.createContext({
    AbortController, URLSearchParams, TextDecoder, console,
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      const response = intercept(url, options);
      if (response !== undefined) return response;
      if (url.startsWith('/api/andromeda/overview/preview')) return preview();
      if (url === '/api/andromeda/overview') return completed();
      throw new Error(`unexpected request ${url}`);
    },
    document: { getElementById: get, querySelectorAll: () => [], addEventListener() {}, createElement: () => element() },
    window: { addEventListener() {} },
    initCustomDropdowns() {}, setControlState() {},
    confirmDialog: (...args) => confirm(...args),
    tr: key => translations[key] || key,
  });
  vm.runInContext(source + `
    bindOnce();
    _state.results = [{ url: 'https://example.test/normal', title: 'normal result' }];
    globalThis.subject = {
      start: query => startOverview(query, _state.results, _searchGeneration),
      results: () => JSON.stringify(_state.results),
      nextSearch: () => { _overviewAbort?.abort(); _searchGeneration += 1; },
    };
  `, context);
  return {
    ...context.subject, get, requests, completed, cancelledBodies,
    intercept: fn => { intercept = fn; },
    confirm: fn => { confirm = fn; },
    stop: () => get('andromeda-cancel-overview').handlers.get('click')(),
    posts: () => requests.filter(row => row.url === '/api/andromeda/overview'),
    feedback: () => get('andromeda-overview-state').textContent,
  };
}

test('stop during preview gives immediate feedback and discards a late successful preview', async () => {
  const h = harness();
  const pending = deferred();
  h.intercept(url => url.includes('/preview') ? pending.promise : undefined);
  const original = h.results();
  const run = h.start('first');
  h.stop();
  assert.equal(h.feedback(), 'overview stopped. normal links are unchanged.');
  assert.equal(h.get('andromeda-cancel-overview').hidden, true);
  assert.equal(h.get('andromeda-recovery').hidden, false);
  assert.equal(h.requests[0].options.signal.aborted, true);
  pending.resolve(preview());
  await run;
  assert.equal(h.posts().length, 0);
  assert.equal(h.results(), original);
});

test('stop while remote confirmation is pending prevents a late approval from sending', async () => {
  const h = harness();
  const entered = deferred(), approval = deferred();
  h.intercept(url => url.includes('/preview') ? preview('remote') : undefined);
  h.confirm(() => { entered.resolve(); return approval.promise; });
  const run = h.start('remote');
  await entered.promise;
  h.stop();
  assert.equal(h.feedback(), 'overview stopped. normal links are unchanged.');
  approval.resolve(true);
  await run;
  assert.equal(h.posts().length, 0);
  assert.equal(h.get('andromeda-cancel-overview').hidden, true);
});

test('declining remote confirmation preserves normal results and permits retry', async () => {
  const h = harness();
  h.intercept(url => url.includes('/preview') ? preview('remote') : undefined);
  h.confirm(async () => false);
  const original = h.results();
  await h.start('remote');
  assert.equal(h.feedback(), 'cancelled before sending');
  assert.equal(h.posts().length, 0);
  assert.equal(h.results(), original);
  assert.equal(h.get('andromeda-recovery').hidden, false);
  h.confirm(async () => true);
  await h.start('remote retry');
  assert.equal(h.posts().length, 1);
  const body = JSON.parse(h.posts()[0].options.body);
  assert.equal(body.confirmed_endpoint_id, 'fixture');
  assert.equal(body.confirmed_model, 'fixture');
});

test('an older preview cannot submit or hide the stop control for a newer attempt', async () => {
  const h = harness();
  const old = deferred(), fresh = deferred();
  let calls = 0;
  h.intercept(url => url.includes('/preview') ? (++calls === 1 ? old.promise : fresh.promise) : undefined);
  const first = h.start('old');
  const second = h.start('new');
  old.resolve(preview());
  await first;
  assert.equal(h.posts().length, 0);
  assert.equal(h.get('andromeda-cancel-overview').hidden, false);
  assert.equal(h.feedback(), 'checking sources…');
  fresh.resolve(preview());
  await second;
  assert.deepEqual(h.posts().map(row => JSON.parse(row.options.body).query), ['new']);
});

test('an older remote approval cannot replace a newer attempt in the same search', async () => {
  const h = harness();
  const entered = deferred(), approval = deferred(), fresh = deferred();
  let calls = 0;
  h.intercept(url => url.includes('/preview') ? (++calls === 1 ? preview('remote') : fresh.promise) : undefined);
  h.confirm(() => { entered.resolve(); return approval.promise; });
  const first = h.start('old');
  await entered.promise;
  const second = h.start('new');
  approval.resolve(true);
  await first;
  assert.equal(h.posts().length, 0);
  assert.equal(h.get('andromeda-cancel-overview').hidden, false);
  fresh.resolve(preview());
  await second;
  assert.deepEqual(h.posts().map(row => JSON.parse(row.options.body).query), ['new']);
});

for (const failure of [false, true]) {
  test(`a late ${failure ? 'error' : 'response'} cannot change a newer overview`, async () => {
    const h = harness();
    const response = deferred(), fresh = deferred(), requested = deferred();
    let previews = 0;
    h.intercept(url => {
      if (url.includes('/preview')) return ++previews === 1 ? preview() : fresh.promise;
      if (url === '/api/andromeda/overview') { requested.resolve(); return response.promise; }
    });
    const first = h.start('old');
    await requested.promise;
    const second = h.start('new');
    if (failure) response.reject(new Error('old provider error'));
    else response.resolve(h.completed('old body'));
    await first;
    assert.equal(h.feedback(), 'checking sources…');
    assert.equal(h.get('andromeda-cancel-overview').hidden, false);
    if (!failure) assert.deepEqual(h.cancelledBodies, ['old body']);
    h.stop();
    fresh.resolve(preview());
    await second;
    assert.equal(h.posts().length, 1);
  });
}

test('stop during stream reading rejects late output and leaves results intact', async () => {
  const h = harness();
  const chunk = deferred(), reading = deferred();
  let cancelled = false;
  h.intercept(url => url === '/api/andromeda/overview' ? {
    ok: true, body: { getReader: () => ({
      read: () => { reading.resolve(); return chunk.promise; },
      cancel: async () => { cancelled = true; },
    }) },
  } : undefined);
  const original = h.results();
  const run = h.start('stream');
  await reading.promise;
  h.stop();
  assert.equal(h.feedback(), 'overview stopped. normal links are unchanged.');
  chunk.resolve({ done: false, value: new TextEncoder().encode('data: {"type":"overview","overview":{"status":"ready"}}\n\n') });
  await run;
  assert.equal(cancelled, true);
  assert.equal(h.feedback(), 'overview stopped. normal links are unchanged.');
  assert.equal(h.results(), original);
});

test('a new search invalidates pending work, and retry after stop can submit normally', async () => {
  const h = harness();
  const pending = deferred();
  h.intercept(url => url.includes('/preview') ? pending.promise : undefined);
  const first = h.start('old query');
  h.nextSearch();
  pending.resolve(preview());
  await first;
  assert.equal(h.posts().length, 0);
  h.intercept(() => undefined);
  const second = h.start('cancelled');
  h.stop();
  await second;
  await h.start('retry');
  assert.deepEqual(h.posts().map(row => JSON.parse(row.options.body).query), ['retry']);
  assert.equal(h.get('andromeda-cancel-overview').hidden, true);
});
