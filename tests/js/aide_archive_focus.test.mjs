import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const centralSource = readFileSync(new URL('../../static/js/aidecentral.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const boundarySource = readFileSync(new URL('../../static/js/kokuen.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');

function harness({ withSession = true } = {}) {
  const document = { activeElement: null };
  const observers = [];
  class Node {
    constructor(id, { control = false, legacy = false, cssHidden = false } = {}) {
      this.id = id; this.control = control; this.legacy = legacy; this.cssHidden = cssHidden;
      this.hidden = false; this.inert = false; this.isConnected = true;
      this.children = []; this.attributes = {}; this.listeners = {};
    }
    append(...children) { for (const node of children) { node.parent = this; this.children.push(node); } }
    descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
    querySelectorAll(selector) {
      const items = this.descendants();
      return selector === '.sidebar-nav, .aide-sidebar-foot, .session-item .star'
        ? items.filter(item => item.legacy) : items.filter(item => item.control);
    }
    getAttribute(name) { return this.attributes[name] ?? null; }
    setAttribute(name, value) { this.attributes[name] = value; }
    hasAttribute(name) { return name in this.attributes; }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    removeEventListener(type) { delete this.listeners[type]; }
    closest() {
      for (let node = this; node; node = node.parent) if (node.hidden || node.inert) return node;
      return null;
    }
    focus() {
      for (let node = this; node; node = node.parent) if (node.hidden || node.inert || node.cssHidden) return;
      document.activeElement = this;
    }
  }
  const archive = new Node('aide-sidebar');
  const close = new Node('close', { control: true });
  const primary = new Node('primary', { control: true });
  const search = new Node('search', { control: true });
  const nav = new Node('nav', { legacy: true, cssHidden: true });
  const scheduled = new Node('scheduled', { control: true });
  nav.append(scheduled);
  const list = new Node('sessions');
  const footer = new Node('footer', { legacy: true, cssHidden: true });
  const tools = new Node('tools', { control: true });
  footer.append(tools);
  archive.append(close, primary, search, nav, list, footer);
  const addSession = () => {
    const row = new Node('row');
    const open = new Node('open', { control: true });
    const star = new Node('star', { control: true, legacy: true, cssHidden: true });
    row.append(open, star); list.append(row);
    return { row, open, star };
  };
  const session = withSession ? addSession() : null;
  document.getElementById = id => id === 'aide-sidebar' ? archive : null;
  const boundaryContext = vm.createContext({ document, t, tp });
  vm.runInContext(boundarySource + '\nglobalThis.factory = createFocusBoundary;', boundaryContext);
  const context = vm.createContext({
    document,
    MutationObserver: class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe(target, options) { this.target = target; this.options = options; }
    },
  });
  vm.runInContext(centralSource + '\nglobalThis.initialize = initArchiveFocusControls;', context);
  context.initialize();
  const boundary = boundaryContext.factory(archive);
  boundary.activate({ focus: close });
  const tab = shiftKey => {
    let prevented = false;
    archive.listeners.keydown({ key: 'Tab', shiftKey, preventDefault() { prevented = true; } });
    return prevented;
  };
  return { archive, close, primary, search, nav, scheduled, list, footer, tools, session,
    addSession, observers, document, tab };
}

test('archive Tab and Shift+Tab wrap across visible controls, excluding legacy CSS-hidden actions', () => {
  const h = harness();
  assert.equal(h.nav.hidden, true);
  assert.equal(h.nav.inert, true);
  assert.equal(h.footer.hidden, true);
  assert.equal(h.footer.inert, true);
  assert.equal(h.session.star.hidden, true);
  assert.equal(h.session.star.inert, true);
  assert.equal(h.tab(true), true);
  assert.equal(h.document.activeElement, h.session.open);
  assert.equal(h.tab(false), true);
  assert.equal(h.document.activeElement, h.close);
  for (const control of [h.close, h.primary, h.search, h.session.open]) {
    assert.equal(control.hidden, false);
    assert.equal(control.inert, false);
  }
});

test('an empty archive wraps back to its search control without trapping focus on hidden tools', () => {
  const h = harness({ withSession: false });
  assert.equal(h.tab(true), true);
  assert.equal(h.document.activeElement, h.search);
  assert.equal(h.tab(false), true);
  assert.equal(h.document.activeElement, h.close);
});

test('refreshed archive rows retain visible selection while newly inserted stars stay outside focus traversal', () => {
  const h = harness();
  assert.equal(h.observers.length, 1);
  assert.equal(h.observers[0].target, h.archive);
  assert.equal(h.observers[0].options.childList, true);
  assert.equal(h.observers[0].options.subtree, true);
  const latest = h.addSession();
  h.observers[0].callback([{ type: 'childList', target: h.list }]);
  assert.equal(latest.star.hidden, true);
  assert.equal(latest.star.inert, true);
  latest.open.focus();
  assert.equal(h.tab(false), true);
  assert.equal(h.document.activeElement, h.close);
  assert.equal(h.tab(true), true);
  assert.equal(h.document.activeElement, latest.open);
});
