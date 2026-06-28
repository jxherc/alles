// models.js reads 'aide-image-model' from localStorage at MODULE LOAD. a corrupt value there
// used to throw during import and take down app boot. this pins the guarded parse.
// run: node --test tests/js/models_imageslot.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

const _store = new Map();
_store.set('aide-image-model', '{ this is not json');  // poison BEFORE import
globalThis.localStorage = {
  getItem: k => (_store.has(k) ? _store.get(k) : null),
  setItem: (k, v) => _store.set(k, String(v)),
  removeItem: k => _store.delete(k),
};
const _noop = () => {};
const _el = new Proxy({}, { get: () => _noop });
globalThis.document = {
  getElementById: () => null,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: () => _el,
  addEventListener: _noop,
  body: { classList: { toggle: _noop, contains: () => false, add: _noop, remove: _noop } },
  documentElement: { style: { setProperty: _noop } },
};
globalThis.window = { addEventListener: _noop, location: { hostname: 'aide.localhost' } };

// import must NOT throw even though the stored slot is garbage
const mod = await import('../../static/js/models.js');

test('corrupt aide-image-model does not break module load', () => {
  assert.equal(typeof mod.getImageSlot, 'function');
  assert.equal(mod.getImageSlot(), null);  // garbage slot → treated as none
});
