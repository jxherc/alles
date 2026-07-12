import test from 'node:test';
import assert from 'node:assert/strict';

import { initCustomDropdown } from '../../static/js/dropdown.js';

test('escape stays inside a custom dropdown', () => {
  const listeners = {};
  const attrs = {};
  const el = {
    dataset: { options: 'auto|automatic', value: '' },
    innerHTML: '',
    tabIndex: -1,
    setAttribute(name, value) { attrs[name] = String(value); },
    hasAttribute(name) { return name === 'tabindex' || name in attrs; },
    addEventListener(name, fn) { listeners[name] = fn; },
  };
  initCustomDropdown(el);

  let stopped = false;
  listeners.keydown({
    key: 'Escape',
    stopPropagation() { stopped = true; },
  });

  assert.equal(stopped, true);
});
