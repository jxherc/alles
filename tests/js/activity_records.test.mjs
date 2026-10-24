import assert from 'node:assert/strict';
import test from 'node:test';

// a doc row whose file is gone names the path and stays in activity; a live one opens its record
const toasts = [];
let rows = [];
const body = {
  innerHTML: '',
  querySelector() { return null; },
  querySelectorAll(selector) { return selector === '.activity-row' ? rows : []; },
};
const nodes = {
  'activity-body': body,
  'activity-summary': { innerHTML: '' },
  'toast-container': {
    querySelectorAll() { return []; },
    appendChild(el) { toasts.push(el); },
  },
};
globalThis.window = {};
globalThis.document = {
  documentElement: {},
  getElementById: id => nodes[id],
  createElement: () => ({ className: '', textContent: '', remove() {} }),
};
globalThis.location = { search: '' };
globalThis.localStorage = { getItem() { return null; } };

const { initActivity } = await import('../../static/js/activity.js');

const path = 'cooking/meal #2 & 文.md';

async function clickDoc(exists) {
  const handlers = [];
  rows = [{
    dataset: { type: 'doc', view: 'wiki', id: path },
    isConnected: true,
    getClientRects: () => [{}],
    addEventListener: (_type, handler) => handlers.push(handler),
  }];
  const fileReads = [];
  await initActivity(async url => {
    if (url.startsWith('/api/vault-md/file')) {
      fileReads.push(url);
      return { ok: true, json: async () => ({ path, exists }) };
    }
    return {
      ok: true,
      json: async () => url.includes('/summary')
        ? { total: 1, by_type: [], busiest: null }
        : { events: [{ ts: '2026-10-04T12:00:00', type: 'doc', view: 'wiki', title: 'meal', id: path }] },
    };
  });
  const opened = [];
  window._openRecord = async (view, id) => { opened.push([view, id]); return true; };
  toasts.length = 0;
  await handlers[0]();
  assert.deepEqual(fileReads, ['/api/vault-md/file?path=' + encodeURIComponent(path)]);
  return opened;
}

test('a deleted doc names its path and does not open', async () => {
  const opened = await clickDoc(false);
  assert.deepEqual(opened, []);
  assert.equal(toasts.length, 1);
  assert.match(toasts[0].className, /error/);
  assert.equal(toasts[0].textContent, `could not open ${path}: it was moved or deleted`);
});

test('a doc that exists opens its exact record', async () => {
  const opened = await clickDoc(true);
  assert.deepEqual(opened, [['wiki', path]]);
  assert.equal(toasts.length, 0);
});

test.after(() => {
  delete globalThis.window;
  delete globalThis.document;
  delete globalThis.location;
  delete globalThis.localStorage;
});
