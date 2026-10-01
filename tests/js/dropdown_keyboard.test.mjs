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
