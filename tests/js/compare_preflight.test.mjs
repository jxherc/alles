import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/compare.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

function harness(response = async () => ({ ok: true, json: async () => ({ compare_id: 'owned', count: 1 }) })) {
  const nodes = new Map();
  for (const id of ['compare-send-btn', 'compare-input']) {
    nodes.set(id, {
      value: '', disabled: false, dataset: {}, attributes: {}, events: {}, textContent: 'compare',
      addEventListener(name, callback) { (this.events[name] ||= []).push(callback); },
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      getClientRects() { return this.hidden ? [] : [{}]; },
      focus() { document.focus(this); },
      async fire(name) { await Promise.all((this.events[name] || []).map(callback => callback({}))); },
    });
  }
  const input = nodes.get('compare-input'), button = nodes.get('compare-send-btn');
  const selection = [{ dataset: { ep: 'owned', model: 'fixture' } }];
  const calls = [], messages = [];
  const listeners = new Set();
  const document = {
    getElementById: id => nodes.get(id), querySelectorAll: () => selection, activeElement: input,
    addEventListener(name, callback) { assert.equal(name, 'focusin'); listeners.add(callback); },
    removeEventListener(name, callback) { assert.equal(name, 'focusin'); listeners.delete(callback); },
    focus(node) { this.activeElement = node; for (const listener of listeners) listener({ target: node }); },
  };
  const context = vm.createContext({ document, window: {}, toast: (...args) => messages.push(args),
    fetch: async (...args) => { calls.push(args); return response(...args); } });
  vm.runInContext(source + '\nglobalThis.initialize = initCompareView;', context);
  context.initialize();
  return { input, button, selection, calls, messages, document, listeners, initialize: context.initialize };
}

test('missing model keeps the exact prompt and returns focus without a request', async () => {
  const h = harness(); h.selection.length = 0;
  h.input.value = '  retain this\nprompt exactly  ';
  await h.button.fire('click');
  assert.equal(h.input.value, '  retain this\nprompt exactly  ');
  assert.equal(h.calls.length, 0);
  assert.equal(h.document.activeElement, h.input);
});

for (const [name, response] of [
  ['HTTP failure', async () => ({ ok: false })],
  ['interrupted connection', async () => { throw new Error('owned connection lost'); }],
  ['invalid response', async () => ({ ok: true, json: async () => ({ count: 0 }) })],
]) {
  test(`${name} preserves the prompt and allows an explicit retry`, async () => {
    const h = harness(response); h.input.value = '  original prompt  ';
    await h.button.fire('click');
    assert.equal(h.input.value, '  original prompt  ');
    assert.equal(h.button.disabled, false);
    assert.match(h.messages.at(-1)[0], /could not start comparison/);
  });
}

test('accepted comparison clears only after the response and rejects repeat activation', async () => {
  let release;
  const h = harness(() => new Promise(resolve => { release = resolve; }));
  h.input.value = '  original prompt  ';
  const pending = h.button.fire('click');
  assert.equal(h.input.value, '  original prompt  ');
  assert.equal(h.button.disabled, true);
  await h.button.fire('click');
  assert.equal(h.calls.length, 1);
  release({ ok: true, json: async () => ({ compare_id: 'owned', count: 1 }) });
  await pending;
  assert.equal(h.input.value, '');
  assert.equal(h.button.disabled, false);
  assert.equal(JSON.parse(h.calls[0][1].body).message, 'original prompt');
});

test('a newer draft survives an earlier accepted request, even when edited back to the same text', async () => {
  let release;
  const h = harness(() => new Promise(resolve => { release = resolve; }));
  h.input.value = 'original';
  const pending = h.button.fire('click');
  h.input.value = 'new'; await h.input.fire('input');
  h.input.value = 'original'; await h.input.fire('input');
  release({ ok: true, json: async () => ({ compare_id: 'owned', count: 1 }) });
  await pending;
  assert.equal(h.input.value, 'original');
});

test('reopening Compare binds one submission handler', async () => {
  const h = harness(); h.initialize(); h.initialize(); h.input.value = 'original';
  await h.button.fire('click');
  assert.equal(h.calls.length, 1);
});

for (const hidden of [false, true]) {
  test(`a rejected request preserves a newer focus even when the prompt is ${hidden ? 'hidden' : 'visible'}`, async () => {
    let release;
    const h = harness(() => new Promise(resolve => { release = resolve; }));
    h.input.value = 'retain me'; h.button.focus();
    const pending = h.button.fire('click');
    const newer = {}; h.document.focus(newer); h.input.hidden = hidden;
    release({ ok: false }); await pending;
    assert.equal(h.document.activeElement, newer);
    assert.equal(h.input.value, 'retain me');
    assert.equal(h.listeners.size, 0);
  });
}

test('a newer focus remains authoritative after its control is removed', async () => {
  let release;
  const h = harness(() => new Promise(resolve => { release = resolve; }));
  h.input.value = 'retain me'; h.button.focus();
  const pending = h.button.fire('click');
  h.document.focus({}); h.document.activeElement = null;
  release({ ok: false }); await pending;
  assert.equal(h.document.activeElement, null);
});

test('failure restores owned submission focus only while the prompt is visible', async () => {
  for (const hidden of [false, true]) {
    let release;
    const h = harness(() => new Promise(resolve => { release = resolve; }));
    h.input.value = 'retain me'; h.button.focus();
    const pending = h.button.fire('click');
    h.document.activeElement = null; h.input.hidden = hidden;
    release({ ok: false }); await pending;
    assert.equal(h.document.activeElement, hidden ? null : h.input);
    assert.equal(h.listeners.size, 0);
  }
});

test('accepted requests also remove the temporary focus listener', async () => {
  const h = harness(); h.input.value = 'submitted';
  await h.button.fire('click');
  assert.equal(h.listeners.size, 0);
});
