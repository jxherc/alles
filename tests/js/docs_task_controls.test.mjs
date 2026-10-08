import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const bundle = readFileSync(new URL('../../static/vendor/cm6.bundle.js', import.meta.url), 'utf8');
const widgetSource = bundle.match(/Mh=class extends le\{[\s\S]*?ignoreEvent\(\)\{return!0\}\}/)?.[0];
assert.ok(widgetSource, 'the shipped task widget must be exercised');

function setup(text = '- [ ] bring the blue cup 草稿', checked = false, label = 'bring the blue cup 草稿') {
  const ownerDocument = { activeElement: null };
  const document = {
    createElement(tagName) {
      return {
        tagName, ownerDocument, attributes: {}, events: {}, children: [],
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(name, handler) { this.events[name] = handler; },
        appendChild(child) { this.children.push(child); },
      };
    },
  };
  const context = vm.createContext({ document, le: class {} });
  vm.runInContext(`const Widget = ${widgetSource}; globalThis.TaskWidget = Widget;`, context);
  const Widget = context.TaskWidget;
  const state = { text, changes: [], focuses: [], selector: null };
  const from = text.indexOf('['), to = from + 3;
  const view = {
    state: { sliceDoc: (start, end) => state.text.slice(start, end) },
    dispatch({ changes }) {
      state.changes.push(JSON.parse(JSON.stringify(changes)));
      state.text = state.text.slice(0, changes.from) + changes.insert + state.text.slice(changes.to);
    },
    dom: {
      querySelector(selector) {
        state.selector = selector;
        return { focus: options => state.focuses.push(JSON.parse(JSON.stringify(options))) };
      },
    },
  };
  const widget = new Widget(checked, from, to, label);
  const button = widget.toDOM(view).children[0];
  return { Widget, widget, button, view, state, ownerDocument, from, to };
}

test('task control exposes completion and the exact Unicode task label', () => {
  const h = setup();
  assert.equal(h.button.tagName, 'button');
  assert.equal(h.button.type, 'button');
  assert.equal(h.button.attributes.role, 'checkbox');
  assert.equal(h.button.attributes['aria-checked'], 'false');
  assert.equal(h.button.attributes['aria-label'], 'bring the blue cup 草稿');
  assert.equal(setup('- [x] done', true, 'done').button.attributes['aria-checked'], 'true');
  assert.equal(setup('- [ ] ', false, '').button.attributes['aria-label'], 'task');
});

test('toggle replaces only the intended marker and follows the current document state', () => {
  const h = setup('- [ ] bring the blue cup 草稿\n- [x] keep the saved note');
  h.button.events.click();
  assert.equal(h.state.text, '- [x] bring the blue cup 草稿\n- [x] keep the saved note');
  h.button.events.click();
  assert.equal(h.state.text, '- [ ] bring the blue cup 草稿\n- [x] keep the saved note');
  assert.deepEqual(h.state.changes, [
    { from: h.from, to: h.to, insert: '[x]' },
    { from: h.from, to: h.to, insert: '[ ]' },
  ]);
  const uppercase = setup('- [X] keep the saved note', true, 'keep the saved note');
  uppercase.button.events.click();
  assert.equal(uppercase.state.text, '- [ ] keep the saved note');
});

test('widget replacement retains owned keyboard focus without taking other focus', () => {
  const h = setup();
  h.ownerDocument.activeElement = h.button;
  h.button.events.click();
  assert.equal(h.state.selector, `[data-doc-task-from="${h.from}"]`);
  assert.deepEqual(h.state.focuses, [{ preventScroll: true }]);
  h.ownerDocument.activeElement = { unrelated: true };
  h.button.events.click();
  assert.equal(h.state.focuses.length, 1);
});

test('renaming a task invalidates the widget so its accessible label updates', () => {
  const h = setup();
  assert.equal(h.widget.eq(new h.Widget(false, h.from, h.to, 'bring the blue cup 草稿')), true);
  assert.equal(h.widget.eq(new h.Widget(false, h.from, h.to, 'bring the red cup 草稿')), false);
  assert.equal(h.widget.eq(new h.Widget(true, h.from, h.to, 'bring the blue cup 草稿')), false);
});
