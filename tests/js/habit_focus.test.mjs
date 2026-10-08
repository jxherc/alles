import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/habits.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

// Run the real operation and busy-control logic. Both native blur-to-body and
// retained-active-element models must work; neither is browser verification.
function harness(disableFocus = 'body') {
  const document = { body: {}, activeElement: null }, controls = [], calls = [], notices = [];
  const element = (id, dataset = {}, inside = true) => {
    let disabled = false;
    const node = { id, dataset, isConnected: true,
      closest: selector => selector === '.habit-card' && inside ? card : null,
      focus() {
        if (!this.disabled && this.isConnected) { document.activeElement = this; calls.push(id); }
      },
      get disabled() { return disabled; },
      set disabled(value) {
        disabled = value;
        if (value && disableFocus === 'body' && document.activeElement === this) document.activeElement = document.body;
      },
    };
    if (inside) controls.push(node);
    return node;
  };
  let replacement;
  const card = { dataset: { id: 'habit-1' },
    querySelector: selector => selector.includes('data-toggle') ? replacement : null };
  const initial = element('initial', { toggle: '2026-10-06' });
  const shell = element('app-drawer-btn', {}, false);
  const destination = element('saved-habit-name', { f: 'name' });
  const addToggle = element('habits-add-toggle');
  const archiveView = element('archive-view', { act: 'archive-view' });
  let cardPresent = true, showAdd = true;
  const body = { offsetParent: {}, attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    querySelectorAll: () => controls.filter(node => node.isConnected),
    querySelector: selector => {
      if (selector === '[data-id="habit-1"]') return cardPresent ? card : null;
      if (selector.startsWith('.habit-add')) return initial.isConnected && !initial.disabled ? initial : null;
      if (selector === '.habit-card.editing [data-f="name"]') return destination.isConnected ? destination : null;
      if (selector === '[data-act="archive-view"]') return archiveView;
      return null;
    },
  };
  document.getElementById = id => id === 'habits-body' ? body : id === 'habits-add-toggle' && showAdd ? addToggle : null;
  document.activeElement = initial;
  const context = vm.createContext({ document, console,
    CSS: { escape: String }, calendarDateKey: () => '2026-10-06',
    toast: (...args) => notices.push(args),
  });
  vm.runInContext(source + `
    _render = () => setBusy();
    globalThis.subject = {
      write: writeHabit,
      navigate: () => ++_navigation,
      deletedDraft: () => { _adding = true; _creation = { deleted: true }; },
      interruptLoad: () => { _loading = true; },
    };
  `, context);
  return { ...context.subject, document, body, initial, shell, destination, addToggle, archiveView, calls, notices,
    replaceDay() {
      initial.isConnected = false;
      replacement = element('replacement-day', { ...initial.dataset });
      document.activeElement = document.body;
      return replacement;
    },
    removeCard() { initial.isConnected = false; destination.isConnected = false; cardPresent = false; document.activeElement = document.body; },
    hideAdd() { showAdd = false; },
  };
}

for (const disableFocus of ['body', 'retained']) {
  for (const outcome of ['success', 'failure', 'result-focus', 'interrupted-load-failure']) {
    test(`${disableFocus}: pending ${outcome} preserves newer enabled shell focus in the same view`, async () => {
      const h = harness(disableFocus), gate = deferred();
      if (outcome === 'interrupted-load-failure') h.interruptLoad();
      const writing = h.write(() => gate.promise);
      assert.equal(h.initial.disabled, true);
      assert.equal(h.shell.disabled, false);
      assert.equal(h.body.attrs['aria-busy'], 'true');
      if (disableFocus === 'body') {
        assert.equal(h.document.activeElement, h.document.body);
        h.initial.focus();
        assert.equal(h.document.activeElement, h.document.body, 'disabled controls cannot regain focus');
      }
      h.shell.focus();
      if (outcome.endsWith('failure')) gate.reject(new Error('synthetic write failure'));
      else gate.resolve(outcome === 'result-focus' ? h.destination : undefined);
      await writing;
      assert.equal(h.body.attrs['aria-busy'], 'false');
      assert.equal(h.initial.disabled, false);
      assert.equal(h.document.activeElement, h.shell);
      assert.deepEqual(h.calls, ['app-drawer-btn']);
      assert.equal(h.notices.length, outcome.endsWith('failure') ? 1 : 0);
    });
  }
}

for (const disableFocus of ['body', 'retained']) {
  for (const fails of [false, true]) {
    test(`${disableFocus}: an owned ${fails ? 'failed' : 'successful'} write restores its reenabled control`, async () => {
      const h = harness(disableFocus), gate = deferred();
      const writing = h.write(() => gate.promise);
      if (fails) gate.reject(new Error('synthetic unavailable')); else gate.resolve();
      await writing;
      assert.equal(h.initial.disabled, false);
      assert.equal(h.document.activeElement, h.initial);
      assert.deepEqual(h.calls, ['initial']);
    });
  }
}

test('body fallback finds the replacement day after a successful render removes its original', async () => {
  const h = harness(), gate = deferred();
  const writing = h.write(() => gate.promise);
  const replacement = h.replaceDay();
  gate.resolve(); await writing;
  assert.equal(h.document.activeElement, replacement);
  assert.equal(replacement.disabled, false);
});

test('body fallback follows an explicit connected result target', async () => {
  const h = harness(), gate = deferred();
  const writing = h.write(() => gate.promise);
  gate.resolve(h.destination); await writing;
  assert.equal(h.document.activeElement, h.destination);
});

test('a permanently disabled create action falls back to its retained editable name', async () => {
  const h = harness(), gate = deferred();
  h.initial.dataset = { act: 'create' }; h.deletedDraft();
  const writing = h.write(() => gate.promise);
  gate.reject(new Error('synthetic deleted receipt')); await writing;
  assert.equal(h.initial.disabled, true);
  assert.equal(h.destination.disabled, false);
  assert.equal(h.document.activeElement, h.destination);
});

test('body fallback keeps the existing toolbar targets when a card disappears', async () => {
  for (const archivedView of [false, true]) {
    const h = harness(), gate = deferred();
    const writing = h.write(() => gate.promise);
    h.removeCard(); if (archivedView) h.hideAdd();
    gate.resolve(); await writing;
    assert.equal(h.document.activeElement, archivedView ? h.archiveView : h.addToggle);
  }
});

test('navigation or a hidden view still prevents restoration even from the body', async () => {
  for (const hidden of [false, true]) {
    const h = harness(), gate = deferred();
    const writing = h.write(() => gate.promise);
    if (hidden) h.body.offsetParent = null; else h.navigate();
    gate.resolve(h.destination); await writing;
    assert.equal(h.document.activeElement, h.document.body);
    assert.deepEqual(h.calls, []);
  }
});
