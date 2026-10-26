import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/dialog.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

// just enough of a dialog for _wireDialog: a field, cancel and confirm, plus the page behind it
function dialog() {
  const document = { body: { focus() {} }, activeElement: null };
  const node = name => ({
    name, disabled: false, hidden: false, listeners: {},
    focus() { document.activeElement = this; },
    addEventListener(type, fn) { this.listeners[type] = fn; },
  });
  const field = node('field'), cancel = node('cancel'), confirm = node('confirm'), card = node('card');
  const listeners = {};
  const overlay = {
    remove() {},
    addEventListener(type, fn) { listeners[type] = fn; },
    querySelector(selector) {
      if (selector.includes('dialog')) return card;
      if (selector === '[data-dialog-cancel]') return cancel;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === '[data-dialog-confirm]') return [confirm];
      return [field, cancel, confirm];
    },
  };
  const context = vm.createContext({ document, t, tp });
  vm.runInContext(source, context);
  let result;
  context._wireDialog(overlay, value => { result = value; }, () => true);
  const key = (name, extra = {}) => {
    let prevented = false;
    listeners.keydown({ key: name, shiftKey: false, altKey: false, ...extra, preventDefault() { prevented = true; }, stopPropagation() {} });
    return prevented;
  };
  return { document, field, cancel, confirm, key, result: () => result };
}

test('tab stays inside the dialog and cycles both ways, even where safari skips buttons', () => {
  const h = dialog();
  h.cancel.focus();
  // safari's plain tab would leave from cancel, so every tab is handled here
  assert.equal(h.key('Tab'), true);
  assert.equal(h.document.activeElement, h.confirm);
  assert.equal(h.key('Tab'), true);
  assert.equal(h.document.activeElement, h.field);
  assert.equal(h.key('Tab', { shiftKey: true }), true);
  assert.equal(h.document.activeElement, h.confirm);
  assert.equal(h.key('Tab', { shiftKey: true }), true);
  assert.equal(h.document.activeElement, h.cancel);
  // option+tab (safari's "every control" tab) gets the same treatment
  assert.equal(h.key('Tab', { altKey: true }), true);
  assert.equal(h.document.activeElement, h.confirm);
});

test('tab brings focus back in from outside, and skips what is disabled or hidden', () => {
  const h = dialog();
  h.document.activeElement = h.document.body;
  h.key('Tab');
  assert.equal(h.document.activeElement, h.field);
  h.document.activeElement = h.document.body;
  h.key('Tab', { shiftKey: true });
  assert.equal(h.document.activeElement, h.confirm);
  h.confirm.disabled = true;
  h.cancel.focus();
  h.key('Tab');
  assert.equal(h.document.activeElement, h.field);
  h.field.hidden = true;
  h.cancel.focus();
  h.key('Tab');
  assert.equal(h.document.activeElement, h.cancel);
});

test('escape still closes the dialog after tabbing around', () => {
  const h = dialog();
  h.cancel.focus();
  h.key('Tab');
  h.key('Escape');
  assert.equal(h.result(), null);
});

test('a dialog opened by a click safari never focused hands focus back to that button', () => {
  let pointerdown;
  const body = { focus() {} };
  const document = {
    body, activeElement: body,
    addEventListener(type, fn) { if (type === 'pointerdown') pointerdown = fn; },
  };
  const opener = { isConnected: true, focus() { document.activeElement = this; } };
  const node = () => ({ disabled: false, hidden: false, focus() { document.activeElement = this; }, addEventListener() {} });
  const card = node(), cancel = node(), confirm = node();
  const listeners = {};
  const overlay = {
    remove() {},
    addEventListener(type, fn) { listeners[type] = fn; },
    querySelector: selector => (selector.includes('dialog') ? card : cancel),
    querySelectorAll: selector => (selector === '[data-dialog-confirm]' ? [confirm] : [cancel, confirm]),
  };
  const context = vm.createContext({ document, t, tp });
  context.globalThis = context;
  vm.runInContext(source, context);
  // the press lands on the icon inside the button; <body> keeps focus, as in safari
  pointerdown({ target: { closest: () => opener } });
  context._wireDialog(overlay, () => {}, () => true);
  listeners.keydown({ key: 'Escape', preventDefault() {}, stopPropagation() {} });
  assert.equal(document.activeElement, opener);
});
