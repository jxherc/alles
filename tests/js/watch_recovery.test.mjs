import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/watch.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(fetcher = async () => response({})) {
  const nodes = new Map(), toasts = [];
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
      id, disabled: false, isConnected: true, listeners: {}, dataset: {}, attrs: {},
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener(name, listener) { this.listeners[name] = listener; },
      setAttribute(name, value) { this.attrs[name] = value; },
      removeAttribute(name) { delete this.attrs[name]; }, focus() {}, querySelector() { return null; },
    });
    return nodes.get(id);
  }
  const remove = node('delete'); remove.dataset.act = 'del';
  const card = { dataset: { id: 'monitor-1' }, isConnected: true, querySelectorAll: () => [remove] };
  const body = {
    querySelector: () => null,
    querySelectorAll: selector => selector === '.watch-card[data-id]' ? [card] : [],
  };
  const context = vm.createContext({
    fetch: (...args) => fetcher(...args),
    document: { getElementById: node, activeElement: null },
    window: {}, CSS: { escape: String }, initCustomDropdown() {}, formatNumber: String,
    toast: (...args) => toasts.push(args), dlgConfirm: async () => true,
    setInterval() {}, clearInterval() {},
  });
  vm.runInContext(source + `
    let renders = 0;
    _render = () => { renders++; };
    globalThis.subject = {
      loadWatch,
      wire: body => _wire(body),
      seed: monitors => { _mons = monitors; _statusCfg = { enabled: false }; _statusLoaded = true; },
      state: () => ({ monitors: _mons, config: _statusCfg, renders }),
    };
  `, context);
  context.subject.seed([{ id: 'monitor-1', name: 'retained monitor' }]);
  context.subject.wire(body);
  return { ...context.subject, node, remove, toasts };
}

test('failed monitor deletion retains the record and never reports removed', async () => {
  for (const reply of [response({ detail: 'delete unavailable' }, 503), response({})]) {
    const h = harness(async () => reply);
    await h.remove.listeners.click();
    assert.equal(h.state().monitors.length, 1);
    assert.equal(h.toasts.some(([message, kind]) => message === 'removed' && kind === 'success'), false);
    assert.equal(h.toasts.at(-1)[1], 'error');
    assert.equal(h.remove.disabled, false);
  }
});

test('failed public status save preserves known state and permits a deliberate retry', async () => {
  let fail = true;
  const h = harness(async (path, options) => {
    assert.equal(path, '/api/status/config'); assert.equal(options.method, 'PUT');
    return fail ? response({ detail: 'status unavailable' }, 503) : response({ enabled: true });
  });
  await h.node('watch-status-toggle').listeners.click();
  assert.equal(h.state().config.enabled, false);
  assert.equal(h.toasts.at(-1)[1], 'error');
  assert.equal(h.toasts.some(([message]) => message.includes('is now public')), false);
  fail = false;
  await h.node('watch-status-toggle').listeners.click();
  assert.equal(h.state().config.enabled, true);
  assert.equal(h.node('watch-status-toggle').disabled, false);
});

test('pending delete and status mutations submit once across repeated activation', async () => {
  for (const kind of ['delete', 'status']) {
    const held = deferred(); let calls = 0;
    const h = harness(async () => { calls++; return held.promise; });
    const button = kind === 'delete' ? h.remove : h.node('watch-status-toggle');
    const first = button.listeners.click(); await tick();
    const second = button.listeners.click(); await tick();
    assert.equal(calls, 1);
    assert.equal(button.disabled, true);
    held.resolve(response({ detail: 'try again' }, 503));
    await first; await second;
    assert.equal(button.disabled, false);
  }
});

test('failed or malformed overview keeps previously loaded monitors', async () => {
  const h = harness();
  for (const reply of [response({ detail: 'unavailable' }, 503), response({}), response({ monitors: {} })]) {
    await h.loadWatch(async path => path === '/api/watch/overview' ? reply
      : response(path === '/api/status/config' ? { enabled: false } : {}));
    assert.equal(h.state().monitors[0].id, 'monitor-1');
  }
});

test('a late overview cannot replace a newer navigation load', async () => {
  const old = deferred();
  const h = harness();
  const loading = h.loadWatch(async path => path === '/api/watch/overview' ? old.promise
    : response(path === '/api/status/config' ? { enabled: false } : {}));
  await h.loadWatch(async path => response(path === '/api/watch/overview'
    ? { monitors: [{ id: 'newer', name: 'newer monitor' }] }
    : path === '/api/status/config' ? { enabled: true } : {}));
  old.resolve(response({ monitors: [{ id: 'older' }] })); await loading;
  assert.equal(h.state().monitors[0].id, 'newer');
  assert.equal(h.state().config.enabled, true);
});
