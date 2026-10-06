import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8')
  .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];\r?\n/g, '')
  .replace(/^export /gm, '');
const groups = (...ids) => ({ today: ids.map(id => ({ id, name: id })), yesterday: [], earlier: [] });
const response = (body, ok = true) => ({ ok, json: async () => body });
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function harness() {
  const nodes = new Map();
  const document = { activeElement: null, getElementById: id => nodes.get(id) };
  for (const id of ['session-list-state', 'session-list-message', 'session-list-retry', 'session-list', 'session-search']) {
    nodes.set(id, { hidden: id === 'session-list-retry', attributes: {}, value: '',
      setAttribute(key, value) { this.attributes[key] = value; },
      focus() { document.activeElement = this; },
    });
  }
  const requests = [], opens = [], fresh = [], renders = [];
  const context = vm.createContext({
    window: { addEventListener() {} }, document, navigator: { onLine: false },
    fetch: () => { const request = deferred(); requests.push(request); return request.promise; },
    localStorage: { getItem: () => null }, URLSearchParams,
    location: { hash: '#linked-task', search: '' },
    loadAnswerNoteRecovery() {}, loadAnswerTaskRecovery() {},
    opens, fresh, renders,
  });
  vm.runInContext(source + `
    renderSidebar = () => renders.push(_allSessions.map(item => item.id));
    selectSession = async (...args) => { opens.push(args); return true; };
    newChat = options => fresh.push(options);
    globalThis.subject = { load: loadSessions, init: initSessions,
      active: id => { _activeId = id; },
      state: () => ({ids: _allSessions.map(item => item.id), active: _activeId, loaded: _sessionsLoaded, status: _sessionLoadState}) };
  `, context);
  return { ...context.subject, requests, opens, fresh, renders, nodes, document,
    state: () => JSON.parse(JSON.stringify(context.subject.state())) };
}

for (const [label, value] of [
  ['http failure', response({ detail: 'unavailable' }, false)],
  ['missing group', response({ today: [] })],
  ['invalid row', response({ ...groups(), today: [null] })],
]) {
  test(`${label} keeps previously loaded tasks and current conversation`, async () => {
    const h = harness();
    let pending = h.load(); h.requests[0].resolve(response(groups('saved'))); await pending;
    h.active('saved');
    pending = h.load(); h.requests[1].resolve(value); assert.equal(await pending, false);
    assert.deepEqual(h.state(), { ids: ['saved'], active: 'saved', loaded: true, status: 'error' });
    assert.match(h.nodes.get('session-list-message').textContent, /last loaded list/);
    assert.equal(h.nodes.get('session-list-retry').hidden, false);
  });
}

test('cold failure is unavailable; only a successful empty response establishes no tasks', async () => {
  const h = harness(); let pending = h.load();
  assert.match(h.nodes.get('session-list-message').textContent, /loading aide tasks/);
  h.requests[0].resolve(response({}, false)); await pending;
  assert.equal(h.state().loaded, false);
  assert.match(h.nodes.get('session-list-message').textContent, /could not load aide tasks/);
  pending = h.load(); h.requests[1].resolve(response(groups())); assert.equal(await pending, true);
  assert.deepEqual(h.state(), { ids: [], active: null, loaded: true, status: 'ready' });
  assert.equal(h.nodes.get('session-list-state').hidden, true);
});

for (const old of [response(groups('old')), response({}, false)]) {
  test(`a superseded ${old.ok ? 'success' : 'failure'} cannot replace the latest list`, async () => {
    const h = harness(); const first = h.load(); const second = h.load();
    h.requests[1].resolve(response(groups('new'))); await second;
    h.requests[0].resolve(old); assert.equal(await first, false);
    assert.deepEqual(h.state().ids, ['new']); assert.equal(h.state().status, 'ready');
  });
}

test('retry keeps keyboard focus through failure, prevents overlap and returns focus on success', async () => {
  const h = harness(); const initial = h.load(); h.requests[0].resolve(response({}, false)); await initial;
  const retry = h.nodes.get('session-list-retry'); retry.focus(); retry.onclick();
  assert.equal(retry.hidden, false); assert.equal(retry.attributes['aria-disabled'], 'true');
  retry.onclick(); assert.equal(h.requests.length, 2);
  h.requests[1].resolve(response({}, false)); await new Promise(r => setImmediate(r));
  assert.equal(h.document.activeElement, retry);
  retry.onclick(); h.requests[2].resolve(response(groups('saved'))); await new Promise(r => setImmediate(r));
  assert.equal(h.document.activeElement, h.nodes.get('session-search'));
});

test('background refresh does not steal focus', async () => {
  const h = harness(); const elsewhere = {}; h.document.activeElement = elsewhere;
  const pending = h.load(); h.requests[0].resolve(response(groups('saved'))); await pending;
  assert.equal(h.document.activeElement, elsewhere);
});

test('a deep link loads its exact history even when the list is unavailable', async () => {
  const h = harness(); const pending = h.init();
  h.requests[0].resolve(response({}, false)); await pending;
  assert.equal(h.opens[0][0], 'linked-task'); assert.equal(h.fresh.length, 0);
  const refresh = h.load(); h.requests[1].resolve(response(groups('linked-task'))); await refresh;
  assert.equal(h.opens.length, 1, 'sidebar retry must not navigate again');
});

test('successful list still rejects a missing deep-link target', async () => {
  const h = harness(); const pending = h.init();
  h.requests[0].resolve(response(groups('other'))); await pending;
  assert.equal(h.opens.length, 0); assert.equal(h.fresh.length, 1);
});

test('an app-owned hash never becomes a conversation after list failure', async () => {
  const h = harness(); const pending = h.init({ hashOwner: 'app' });
  h.requests[0].resolve(response({}, false)); await pending;
  assert.equal(h.opens.length, 0); assert.equal(h.fresh[0].preserveHash, true);
});

test('startup uses a newer confirmed index when its own request was superseded', async () => {
  const h = harness(); const initial = h.init(); const refresh = h.load();
  h.requests[1].resolve(response(groups('other'))); await refresh;
  h.requests[0].resolve(response(groups('linked-task'))); await initial;
  assert.equal(h.opens.length, 0, 'old index must not restore an excluded target');
  assert.equal(h.fresh.length, 1);
  assert.deepEqual(h.state().ids, ['other']);
});
