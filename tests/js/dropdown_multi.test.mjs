import test from 'node:test';
import assert from 'node:assert/strict';

const panels = [];
globalThis.document ??= {};
Object.assign(globalThis.document, {
  querySelectorAll: () => [],
  removeEventListener() {},
  addEventListener() {},
  createElement() {
    const attrs = {};
    const panel = {
      attrs, dataset: {}, innerHTML: '', style: {},
      setAttribute(name, value) { attrs[name] = String(value); },
      querySelector: () => null,
      querySelectorAll: () => [],
      getBoundingClientRect: () => ({ top: 0, left: 0, width: 100, height: 100, bottom: 100, right: 100 }),
      remove() {},
    };
    panels.push(panel);
    return panel;
  },
  body: { appendChild() {} },
  documentElement: { clientHeight: 800, clientWidth: 1200 },
});
globalThis.window ??= {};
Object.assign(globalThis.window, { removeEventListener() {}, addEventListener() {}, innerHeight: 800, innerWidth: 1200 });

const { initCustomDropdown, populateMultiDropdown, getDropdownValues } = await import('../../static/js/dropdown.js');

function fakeTrigger() {
  const listeners = {};
  const attrs = {};
  const events = [];
  const el = {
    dataset: {}, innerHTML: '', tabIndex: -1, listeners, events,
    classList: { add() {}, remove() {} },
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return attrs[name] ?? null; },
    removeAttribute(name) { delete attrs[name]; },
    hasAttribute(name) { return name === 'tabindex' || name in attrs; },
    addEventListener(name, fn) { listeners[name] = fn; },
    dispatchEvent(event) { events.push(event.type); },
    closest: () => null,
    focus() {},
    getBoundingClientRect: () => ({ top: 0, left: 0, width: 200, height: 40, bottom: 40, right: 200 }),
  };
  return el;
}

const options = [
  { value: 'chest', label: 'chest' },
  { value: 'back', label: 'back' },
  { value: 'legs', label: 'legs' },
];

test('pick several: the picks read as text in the trigger, in list order', () => {
  const el = fakeTrigger();
  populateMultiDropdown(el, options, ['legs', 'chest', 'gone']);
  assert.deepEqual(el.values, ['chest', 'legs'], 'unknown values drop, order follows the list');
  assert.deepEqual(getDropdownValues(el), ['chest', 'legs']);
  assert.match(el.innerHTML, /chest, legs/);
  assert.equal(el.getAttribute('role'), 'combobox');
});

test('pick several: enter toggles the active option and the list stays open', () => {
  const el = fakeTrigger();
  populateMultiDropdown(el, options, []);
  const press = key => el.listeners.keydown({ key, preventDefault() {}, stopPropagation() {} });
  press('ArrowDown');                     // opens and steps to the second option, like a single list
  const panel = panels.at(-1);
  assert.equal(panel.attrs['aria-multiselectable'], 'true');
  press('Enter');
  assert.deepEqual(el.values, ['back']);
  assert.equal(el.getAttribute('aria-expanded'), 'true', 'still open after a pick');
  press('ArrowDown');
  press('Enter');
  assert.deepEqual(el.values, ['back', 'legs']);
  assert.match(panel.innerHTML, /aria-selected="true"[^>]*>\s*<svg class="custom-dropdown-check"/);
  press('ArrowUp');
  press('Enter');                         // toggles back off again
  assert.deepEqual(el.values, ['legs']);
  assert.equal(el.events.filter(type => type === 'change').length, 3);
  press('Escape');
  assert.equal(el.getAttribute('aria-expanded'), 'false');
});

test('pick several: nothing picked shows the placeholder, and values can be set as an array', () => {
  const el = fakeTrigger();
  el.dataset.placeholder = 'any muscle';
  populateMultiDropdown(el, options);
  assert.deepEqual(el.values, []);
  assert.match(el.innerHTML, /any muscle/);
  el.values = ['back'];
  assert.match(el.innerHTML, /back/);
});

test('a single dropdown still picks one and closes', () => {
  const el = fakeTrigger();
  el.dataset.options = 'a|a;b|b';
  initCustomDropdown(el);
  const press = key => el.listeners.keydown({ key, preventDefault() {}, stopPropagation() {} });
  press('ArrowDown');
  press('Enter');
  assert.equal(el.value, 'b');
  assert.equal(el.getAttribute('aria-expanded'), 'false');
});
