import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

function harness() {
  const classes = new Set();
  const content = { innerHTML: '', appendChild() {} };
  let document;
  const opener = { focus() { document.activeElement = this; } };
  const close = { focus() { document.activeElement = this; }, addEventListener() {} };
  const panel = {
    inert: true,
    classList: { contains: name => classes.has(name), add: name => classes.add(name), remove: name => classes.delete(name) },
    contains: node => node === close,
    querySelector: selector => selector === '.artifact-body' ? content : {},
  };
  document = {
    activeElement: opener,
    getElementById: id => id === 'artifact-panel' ? panel : close,
    querySelector: () => ({ classList: { add() {}, remove() {} } }),
    createElement: () => ({}), addEventListener() {},
  };
  const source = readFileSync(new URL('../../static/js/artifacts.js', import.meta.url), 'utf8')
    .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
  const context = vm.createContext({ document, mdToHtml: value => value, escapeHtml: value => value });
  vm.runInContext(source + '\nglobalThis.subject = { open: openArtifact, close: closeArtifactPanel };', context);
  return { ...context.subject, document, panel, opener, closeButton: close };
}

test('opening an artifact enables its controls and closing returns focus to the opener', () => {
  const h = harness();
  h.open('example', 'code', 'example');
  assert.equal(h.panel.inert, false);
  assert.equal(h.document.activeElement, h.closeButton);
  h.close();
  assert.equal(h.panel.inert, true);
  assert.equal(h.document.activeElement, h.opener);
});

test('replacing an open artifact keeps the original return focus', () => {
  const h = harness();
  h.open('one', 'code', 'one');
  h.open('two', 'code', 'two');
  h.close();
  assert.equal(h.document.activeElement, h.opener);
});

test('closing an artifact preserves focus already moved outside its panel', () => {
  const h = harness();
  h.open('example', 'code', 'example');
  const other = {};
  h.document.activeElement = other;
  h.close();
  assert.equal(h.panel.inert, true);
  assert.equal(h.document.activeElement, other);
});
