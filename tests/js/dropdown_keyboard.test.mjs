import test from 'node:test';
import assert from 'node:assert/strict';

import { initCustomDropdown } from '../../static/js/dropdown.js';

test('a closed custom dropdown does not swallow unrelated escape keys', () => {
  const listeners = {};
  const attrs = {};
  const el = {
    dataset: { options: 'auto|automatic', value: '' },
    innerHTML: '',
    tabIndex: -1,
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return attrs[name] ?? null; },
    hasAttribute(name) { return name === 'tabindex' || name in attrs; },
    addEventListener(name, fn) { listeners[name] = fn; },
  };
  initCustomDropdown(el);

  let stopped = false;
  listeners.keydown({ key: 'Escape', stopPropagation() { stopped = true; } });
  assert.equal(stopped, false);
});

test('a closed custom dropdown picks by typed letters, like a native select', () => {
  const listeners = {};
  const attrs = {};
  const events = [];
  const el = {
    dataset: { options: 'USD|USD;CAD|CAD;CHF|CHF;EUR|EUR', value: 'USD' },
    innerHTML: '',
    tabIndex: -1,
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return attrs[name] ?? null; },
    hasAttribute(name) { return name === 'tabindex' || name in attrs; },
    addEventListener(name, fn) { listeners[name] = fn; },
    dispatchEvent(event) { events.push(event.type); },
    focus() {},
  };
  globalThis.document ??= { querySelectorAll: () => [], removeEventListener() {}, addEventListener() {} };
  globalThis.window ??= { removeEventListener() {}, addEventListener() {} };
  initCustomDropdown(el);
  const press = key => listeners.keydown({ key, preventDefault() {}, stopPropagation() {} });
  press('c');
  assert.equal(el.dataset.value, 'CAD');
  press('c');
  assert.equal(el.dataset.value, 'CHF', 'the same letter again steps to the next match');
  el._typeAhead = null;
  press('e');
  assert.equal(el.dataset.value, 'EUR');
  press('z');
  assert.equal(el.dataset.value, 'EUR', 'no match leaves the value alone');
  assert.ok(events.includes('change'));
});
