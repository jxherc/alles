import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const read = name => readFileSync(new URL(`../../static/js/${name}.js`, import.meta.url), 'utf8');
const helper = read('response_actions').replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
const menus = read('kokuen').replace(/^export /gm, '');
const rewrite = read('sessions').match(/^export function wireRewriteButtons\([^]*?^}/m)[0].replace(/^export /, '');

function harness({ central = true } = {}) {
  const observers = [], requests = [], notices = [];
  class Target {
    constructor() { this.listeners = new Map(); }
    addEventListener(type, callback, capture = false) {
      const rows = this.listeners.get(type) || [];
      if (!rows.some(row => row.callback === callback && row.capture === Boolean(capture))) rows.push({ callback, capture: Boolean(capture) });
      this.listeners.set(type, rows);
    }
    removeEventListener(type, callback, capture = false) {
      this.listeners.set(type, (this.listeners.get(type) || []).filter(row => row.callback !== callback || row.capture !== Boolean(capture)));
    }
    count(type) { return (this.listeners.get(type) || []).length; }
  }
  const document = new Target(), window = new Target();
  document.activeElement = null;
  window.innerHeight = 640;
  class Node extends Target {
    constructor(tagName = 'div') {
      super(); this.tagName = tagName.toUpperCase(); this.children = []; this.parentNode = null;
      this.attributes = {}; this.style = {}; this.dataset = {}; this.hidden = false; this.disabled = false;
      this.textContent = ''; this.tabIndex = 0; this.rect = { left: 20, top: 80, bottom: 124, width: 44, height: 44 };
      this.scrollTop = 0; this.focusOptions = null;
      this.className = '';
      this.classList = {
        contains: value => this.className.split(/\s+/).includes(value),
        add: value => { if (!this.classList.contains(value)) this.className = `${this.className} ${value}`.trim(); },
      };
    }
    get isConnected() { return this === document.body || Boolean(this.parentNode?.isConnected); }
    append(...nodes) { for (const node of nodes) this.appendChild(node); }
    appendChild(node) { node.remove(); node.parentNode = this; this.children.push(node); return node; }
    remove() {
      if (!this.parentNode) return;
      const parent = this.parentNode; parent.children.splice(parent.children.indexOf(this), 1); this.parentNode = null;
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    hasAttribute(name) { return name in this.attributes; }
    matches(selector) {
      if (selector === 'button') return this.tagName === 'BUTTON';
      if (selector === '[role^="menuitem"]') return (this.getAttribute('role') || '').startsWith('menuitem');
      if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
      throw new Error(`unsupported selector ${selector}`);
    }
    closest(selector) { for (let node = this; node; node = node.parentNode) if (node.matches(selector)) return node; return null; }
    contains(node) { for (let item = node; item; item = item.parentNode) if (item === this) return true; return false; }
    descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
    querySelectorAll(selector) { return this.descendants().filter(node => node.matches(selector)); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    get clientTop() { return this.classList.contains('msg-actions-menu') ? 1 : 0; }
    get clientHeight() { return this.getBoundingClientRect().height - 2 * this.clientTop; }
    getBoundingClientRect() {
      if (this.parentNode?.classList.contains('msg-actions-menu')) {
        const menu = this.parentNode;
        const offset = menu.children.slice(0, menu.children.indexOf(this)).reduce((sum, child) => sum + child.rect.height, 0);
        const top = menu.getBoundingClientRect().top + 5 + offset - menu.scrollTop;
        return { ...this.rect, top, bottom: top + this.rect.height };
      }
      if (!this.classList.contains('msg-actions-menu')) return this.rect;
      // Model the existing border-box menu CSS and the inline placement cap.
      // The real helper must remeasure after changing maxHeight, just as in a browser.
      const maxHeight = this.style.maxHeight ? parseFloat(this.style.maxHeight) : window.innerHeight - 32;
      const height = Math.min(this.rect.height, maxHeight);
      const left = parseFloat(this.style.left) || this.rect.left || 0;
      const top = parseFloat(this.style.top) || this.rect.top || 0;
      return { ...this.rect, left, top, height, bottom: top + height, right: left + this.rect.width };
    }
    focus(options) {
      if (this.disabled || !this.isConnected) return;
      for (let node = this; node; node = node.parentNode) if (node.hidden) return;
      this.focusOptions = options;
      document.activeElement = this;
    }
  }
  document.body = new Node('body');
  if (central) document.body.className = 'aide-central';
  document.documentElement = { clientWidth: 360 };
  document.createElement = tag => new Node(tag);
  const context = vm.createContext({ document, window,
    icon: name => `<svg data-icon="${name}"></svg>`,
    getComputedStyle: () => ({ getPropertyValue: name => name === '--k-space-4' ? '16px' : '4px' }),
    MutationObserver: class {
      constructor(callback) { this.callback = callback; this.active = false; observers.push(this); }
      observe(target, options) { this.target = target; this.options = options; this.active = true; }
      disconnect() { this.active = false; }
    },
    fetch: async (url, options) => { requests.push({ url, ...options }); return { ok: true, json: async () => ({ content: 'rewritten reply' }) }; },
    _md: text => `rendered ${text}`, toast: message => notices.push(message),
  });
  vm.runInContext(menus + '\nglobalThis.createMenuController = createMenuController;', context);
  vm.runInContext(helper + '\nglobalThis.compact = compactResponseActions;', context);
  vm.runInContext(`let _activeId = 'owned-session';\n${rewrite}\nglobalThis.wireRewrite = wireRewriteButtons;`, context);
  function dispatch(target, type, values = {}) {
    const event = { target, type, defaultPrevented: false, stopped: false, promises: [], ...values,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; } };
    if (type === 'click' && target.closest?.('button')?.disabled) return event;
    const path = [];
    if (target instanceof Node) {
      for (let node = target; node; node = node.parentNode) path.push(node);
      path.push(document, window);
    } else path.push(target);
    const invoke = (node, capture) => {
      for (const row of [...(node.listeners.get(type) || [])]) if (row.capture === capture) {
        const value = row.callback(event); if (value?.then) event.promises.push(value);
      }
    };
    for (const node of [...path].reverse()) { invoke(node, true); if (event.stopped) return event; }
    for (const node of path) { invoke(node, false); if (event.stopped) break; }
    return event;
  }
  const button = (label, attrs = {}) => {
    const node = new Node('button'); node.textContent = label; node.className = 'act-btn';
    for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
    return node;
  };
  const row = (labels = ['note', 'shorter']) => {
    const node = new Node(); node.className = 'msg-row'; node.dataset.msgId = 'owned-reply';
    const wrap = new Node(); wrap.className = 'ai-wrap';
    const content = new Node(); content.className = 'ai-content'; content.innerHTML = 'original reply';
    const actions = new Node(); actions.className = 'msg-actions';
    const copy = button('copy', { onclick: 'copyMsg(this)' });
    const buttons = labels.map(label => button(label));
    actions.append(copy, ...buttons); wrap.append(content, actions); node.append(wrap); document.body.append(node);
    return { node, wrap, content, actions, copy, buttons,
      get trigger() { return actions.querySelector('.msg-more-trigger'); },
      get menu() { return actions.querySelector('.msg-actions-menu'); } };
  };
  return { document, window, context, requests, notices, observers, button, row, dispatch,
    compact: context.compact, wireRewrite: context.wireRewrite,
    flushMutations: () => { for (const observer of observers) if (observer.active) observer.callback([{ type: 'childList' }]); },
    activeObservers: () => observers.filter(observer => observer.active).length,
  };
}

function assertClosed(h, row) {
  assert.equal(row.menu.hidden, true);
  assert.equal(row.trigger.getAttribute('aria-expanded'), 'false');
  assert.equal(h.document.count('pointerdown'), 0);
  assert.equal(h.window.count('scroll'), 0);
  assert.equal(h.window.count('resize'), 0);
  assert.equal(h.activeObservers(), 0);
}

test('compaction is scoped to the central Aide surface', () => {
  const h = harness({ central: false }), row = h.row();
  const children = [...row.actions.children];
  h.compact(null); h.compact(row.actions);
  assert.deepEqual(row.actions.children, children);
  assert.equal(row.trigger, null);
});

test('compaction moves original buttons without losing listeners, identity or message ancestry', () => {
  const h = harness(), row = h.row();
  const [note] = row.buttons;
  const dialog = h.button('dialog'); h.document.body.append(dialog);
  let calls = 0;
  note.addEventListener('click', () => {
    calls++;
    assert.equal(note.closest('.msg-row'), row.node);
    assert.equal(note.closest('.ai-wrap'), row.wrap);
    assert.equal(row.menu.hidden, true, 'close before the existing callback opens its own surface');
    dialog.focus();
  });
  h.compact(row.actions);
  assert.deepEqual(row.actions.children, [row.copy, row.trigger, row.menu]);
  assert.deepEqual(row.menu.children, row.buttons);
  assert.equal(row.copy.getAttribute('onclick'), 'copyMsg(this)');
  assert.equal(row.copy.getAttribute('aria-label'), 'copy reply');
  assert.equal(row.trigger.getAttribute('aria-controls'), row.menu.id);
  h.dispatch(row.trigger, 'click'); h.dispatch(note, 'click');
  assert.equal(calls, 1);
  assert.equal(h.document.activeElement, dialog, 'the original action owns focus after dismissal');
  assertClosed(h, row);
});

test('actual rewrite callbacks retain session and message ids after moving into the menu', async () => {
  const h = harness(), row = h.row(['shorter']);
  const rewrite = row.buttons[0]; rewrite.classList.add('msg-rewrite-btn'); rewrite.dataset.style = 'shorter';
  h.wireRewrite(row.actions); h.compact(row.actions);
  h.dispatch(row.trigger, 'click');
  await Promise.all(h.dispatch(rewrite, 'click').promises);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/chat/rewrite');
  assert.deepEqual(JSON.parse(h.requests[0].body), { session_id: 'owned-session', style: 'shorter', msg_id: 'owned-reply' });
  assert.equal(row.content.innerHTML, 'rendered rewritten reply');
  assert.equal(rewrite.disabled, false);
  assertClosed(h, row);
});

test('repeated compaction and late branch actions reuse one trigger and preserve action order', () => {
  const h = harness(), row = h.row();
  h.compact(row.actions); const trigger = row.trigger, menu = row.menu;
  h.compact(row.actions);
  const branch = h.button('branch'); row.actions.append(branch); h.compact(row.actions);
  assert.equal(row.trigger, trigger); assert.equal(row.menu, menu);
  assert.deepEqual(menu.children, [...row.buttons, branch]);
  assert.equal(branch.getAttribute('role'), 'menuitem');
  assert.equal(branch.tabIndex, -1);
  assert.equal(trigger.count('click'), 1);
  assert.equal(menu.count('click'), 1);
});

test('a copy-only row hides its empty menu trigger until a late action is appended', () => {
  const h = harness(), row = h.row([]);
  h.compact(row.actions); assert.equal(row.trigger.hidden, true);
  row.actions.append(h.button('branch')); h.compact(row.actions);
  assert.equal(row.trigger.hidden, false);
});

test('toggle click and Escape close the menu and restore its trigger without escaping to another surface', () => {
  const h = harness(), row = h.row(); h.compact(row.actions);
  let outerEscape = 0; h.document.addEventListener('keydown', () => { outerEscape++; });
  h.dispatch(row.trigger, 'click'); assert.equal(row.menu.hidden, false);
  h.dispatch(row.trigger, 'click'); assertClosed(h, row);
  h.dispatch(row.trigger, 'click');
  const escape = h.dispatch(row.buttons[0], 'keydown', { key: 'Escape' });
  assert.equal(escape.defaultPrevented, true);
  assert.equal(outerEscape, 0);
  assert.equal(h.document.activeElement, row.trigger);
  assertClosed(h, row);
});

test('Arrow keys, Home and End follow enabled menu items and Tab dismisses without cancelling native traversal', () => {
  const h = harness(), row = h.row(['note', 'disabled', 'shorter']);
  row.buttons[1].disabled = true; h.compact(row.actions);
  assert.equal(h.dispatch(row.trigger, 'keydown', { key: 'ArrowDown' }).defaultPrevented, true);
  assert.equal(h.document.activeElement, row.buttons[0]);
  h.dispatch(row.buttons[0], 'keydown', { key: 'ArrowDown' }); assert.equal(h.document.activeElement, row.buttons[2]);
  h.dispatch(row.buttons[2], 'keydown', { key: 'ArrowDown' }); assert.equal(h.document.activeElement, row.buttons[0]);
  h.dispatch(row.buttons[0], 'keydown', { key: 'End' }); assert.equal(h.document.activeElement, row.buttons[2]);
  h.dispatch(row.buttons[2], 'keydown', { key: 'Home' }); assert.equal(h.document.activeElement, row.buttons[0]);
  const tab = h.dispatch(row.buttons[0], 'keydown', { key: 'Tab' });
  assert.equal(tab.defaultPrevented, false); assertClosed(h, row);
  h.dispatch(row.trigger, 'keydown', { key: 'ArrowUp' });
  assert.equal(h.document.activeElement, row.buttons[2]);
});

test('native disabled actions cannot run and are refreshed after re-enabling', () => {
  const h = harness(), row = h.row(); row.buttons[0].disabled = true;
  let calls = 0; row.buttons[0].addEventListener('click', () => calls++);
  h.compact(row.actions); h.dispatch(row.trigger, 'click');
  assert.equal(h.document.activeElement, row.buttons[1]);
  h.dispatch(row.buttons[0], 'click'); assert.equal(calls, 0); assert.equal(row.menu.hidden, false);
  h.dispatch(row.trigger, 'click'); row.buttons[0].disabled = false; h.dispatch(row.trigger, 'click');
  assert.equal(h.document.activeElement, row.buttons[0]);
});

test('a native button disabled while open is skipped by subsequent keyboard navigation', () => {
  const h = harness(), row = h.row(['note', 'shorter', 'simpler']);
  h.compact(row.actions); h.dispatch(row.trigger, 'click');
  row.buttons[1].disabled = true;
  h.dispatch(row.buttons[0], 'keydown', { key: 'ArrowDown' });
  assert.equal(h.document.activeElement, row.buttons[2]);
});

test('outside pointer, outer scroll and resize close without stealing destination focus', () => {
  for (const [targetName, type] of [['document', 'pointerdown'], ['window', 'scroll'], ['window', 'resize']]) {
    const h = harness(), row = h.row(); h.compact(row.actions); h.dispatch(row.trigger, 'click');
    const destination = h.button('destination'); h.document.body.append(destination); destination.focus();
    h.dispatch(type === 'pointerdown' ? destination : h[targetName], type);
    assert.equal(h.document.activeElement, destination); assertClosed(h, row);
  }
});

test('pointer or scrolling inside the menu does not close it', () => {
  const h = harness(), row = h.row(); h.compact(row.actions); h.dispatch(row.trigger, 'click');
  h.dispatch(row.buttons[0], 'pointerdown'); h.dispatch(row.menu, 'scroll');
  assert.equal(row.menu.hidden, false); assert.equal(h.activeObservers(), 1);
});

test('opening another reply closes the previous menu and leaves one set of global listeners', () => {
  const h = harness(), first = h.row(), second = h.row();
  h.compact(first.actions); h.compact(second.actions);
  h.dispatch(first.trigger, 'click'); h.dispatch(second.trigger, 'click');
  assert.equal(first.menu.hidden, true); assert.equal(first.trigger.getAttribute('aria-expanded'), 'false');
  assert.equal(second.menu.hidden, false); assert.equal(h.document.activeElement, second.buttons[0]);
  assert.equal(h.document.count('pointerdown'), 1); assert.equal(h.window.count('scroll'), 1); assert.equal(h.activeObservers(), 1);
  h.dispatch(second.trigger, 'click'); assertClosed(h, second);
});

test('removing a reply while its menu is open releases global listeners and its observer', () => {
  const h = harness(), row = h.row(); h.compact(row.actions); h.dispatch(row.trigger, 'click');
  row.node.remove(); h.flushMutations(); assertClosed(h, row);
  assert.equal(h.observers[0].target, h.document.body);
  assert.equal(h.observers[0].options.subtree, true);
});

test('reopening an already open trigger does not orphan removal observers', () => {
  const h = harness(), row = h.row(); h.compact(row.actions);
  h.dispatch(row.trigger, 'keydown', { key: 'ArrowDown' });
  row.trigger.focus(); h.dispatch(row.trigger, 'keydown', { key: 'ArrowUp' });
  assert.equal(h.activeObservers(), 1);
  h.dispatch(row.buttons[1], 'keydown', { key: 'Escape' }); assertClosed(h, row);
});

test('pre-existing aria-disabled actions keep their disabled semantics when opened', () => {
  const h = harness(), row = h.row(); row.buttons[0].setAttribute('aria-disabled', 'true');
  h.compact(row.actions); h.dispatch(row.trigger, 'click');
  assert.equal(row.buttons[0].getAttribute('aria-disabled'), 'true');
  assert.equal(h.document.activeElement, row.buttons[1]);
});

test('an all-disabled menu focuses its surface so Escape still closes it and returns to More', () => {
  const h = harness(), row = h.row();
  row.buttons[0].disabled = true; row.buttons[1].setAttribute('aria-disabled', 'true');
  h.compact(row.actions); h.dispatch(row.trigger, 'click');
  assert.equal(h.document.activeElement, row.menu);
  assert.equal(row.menu.tabIndex, -1);
  const escape = h.dispatch(row.menu, 'keydown', { key: 'Escape' });
  assert.equal(escape.defaultPrevented, true);
  assert.equal(h.document.activeElement, row.trigger);
  assertClosed(h, row);
});

test('menu positioning uses viewport bounds and opens upward near the bottom edge', () => {
  const h = harness(), row = h.row(); h.compact(row.actions);
  row.trigger.rect = { left: 330, top: 610, bottom: 640, height: 30, width: 30 };
  row.menu.rect = { width: 208, height: 300 };
  h.dispatch(row.trigger, 'click');
  assert.equal(row.menu.style.left, '136px');
  assert.equal(row.menu.style.top, '306px');
});

function assertMenuOutsideTrigger(row, viewportHeight) {
  const menu = row.menu.getBoundingClientRect(), trigger = row.trigger.getBoundingClientRect();
  assert.ok(menu.bottom <= trigger.top - 4 || menu.top >= trigger.bottom + 4,
    `menu ${menu.top}..${menu.bottom} must not cover trigger ${trigger.top}..${trigger.bottom}`);
  assert.ok(menu.top >= 16 && menu.bottom <= viewportHeight - 16, 'menu retains viewport gutters');
}

test('placement prefers below whenever the whole menu fits, even when above has more room', () => {
  const h = harness(), row = h.row(); h.compact(row.actions);
  row.trigger.rect = { left: 20, top: 360, bottom: 404, height: 44, width: 44 };
  row.menu.rect = { width: 208, height: 120 };
  h.dispatch(row.trigger, 'click');
  assert.equal(row.menu.getBoundingClientRect().top, 408);
  assert.equal(row.menu.getBoundingClientRect().height, 120);
  assertMenuOutsideTrigger(row, h.window.innerHeight);
});

test('placement chooses above when the whole menu fits there but not below', () => {
  const h = harness(), row = h.row(); h.compact(row.actions); h.window.innerHeight = 450;
  row.trigger.rect = { left: 20, top: 230, bottom: 274, height: 44, width: 44 };
  row.menu.rect = { width: 208, height: 200 };
  h.dispatch(row.trigger, 'click');
  assert.equal(row.menu.getBoundingClientRect().top, 26);
  assert.equal(row.menu.getBoundingClientRect().height, 200);
  assertMenuOutsideTrigger(row, h.window.innerHeight);
});

test('short zoom viewport constrains a tall menu above More without covering its pointer target', () => {
  const h = harness(), row = h.row(['note', 'task', 'shorter', 'longer', 'simpler', 'branch']);
  h.compact(row.actions); h.window.innerHeight = 450;
  row.trigger.rect = { left: 20, top: 230, bottom: 274, height: 44, width: 44 };
  row.menu.rect = { width: 208, height: 273 };
  h.dispatch(row.trigger, 'click');
  assertMenuOutsideTrigger(row, h.window.innerHeight);
  assert.equal(row.menu.style.maxHeight, '210px');
  assert.equal(row.menu.getBoundingClientRect().height, 210);
  assert.ok(row.menu.rect.height > row.menu.getBoundingClientRect().height, 'content scrolls inside the cap');
  for (const button of row.buttons) assert.equal(button.getBoundingClientRect().height, 44, 'rows stay full sized');
  h.dispatch(row.trigger, 'click'); assertClosed(h, row);
});

test('when neither side fits, placement uses the roomier lower side with internal scrolling', () => {
  const h = harness(), row = h.row(); h.compact(row.actions); h.window.innerHeight = 450;
  row.trigger.rect = { left: 20, top: 160, bottom: 204, height: 44, width: 44 };
  row.menu.rect = { width: 208, height: 300 };
  h.dispatch(row.trigger, 'click');
  assertMenuOutsideTrigger(row, h.window.innerHeight);
  assert.equal(row.menu.style.maxHeight, '226px');
  assert.equal(row.menu.getBoundingClientRect().top, 208);
  assert.equal(row.menu.getBoundingClientRect().height, 226);
});

test('reopening clears the old cap before choosing a side and restores the full menu height', () => {
  const h = harness(), row = h.row(); h.compact(row.actions); h.window.innerHeight = 450;
  row.trigger.rect = { left: 20, top: 230, bottom: 274, height: 44, width: 44 };
  row.menu.rect = { width: 208, height: 273 };
  h.dispatch(row.trigger, 'click');
  assert.equal(row.menu.getBoundingClientRect().height, 210);
  h.dispatch(row.trigger, 'click');
  h.window.innerHeight = 700;
  row.trigger.rect = { left: 20, top: 400, bottom: 444, height: 44, width: 44 };
  h.dispatch(row.trigger, 'click');
  assert.equal(row.menu.getBoundingClientRect().top, 123, 'natural height selects the roomy upper side');
  assert.equal(row.menu.getBoundingClientRect().height, 273, 'prior210px cap must not survive');
  assertMenuOutsideTrigger(row, h.window.innerHeight);
});

function assertFocusedItemExposed(h, row, expected) {
  assert.equal(h.document.activeElement, expected);
  assert.equal(expected.focusOptions.preventScroll, true, 'initial focus must not scroll the conversation');
  const item = expected.getBoundingClientRect(), menu = row.menu.getBoundingClientRect();
  assert.ok(item.top >= menu.top + row.menu.clientTop, 'focused item starts inside the visible menu');
  assert.ok(item.bottom <= menu.top + row.menu.clientTop + row.menu.clientHeight, 'focused item ends inside the visible menu');
}

test('ArrowUp exposes the last enabled item by scrolling only the capped menu', () => {
  const h = harness(), row = h.row(['note', 'task', 'shorter', 'longer', 'simpler', 'branch']);
  h.compact(row.actions); h.window.innerHeight = 450;
  row.trigger.rect = { left: 20, top: 230, bottom: 274, height: 44, width: 44 };
  row.menu.rect = { width: 208, height: 274 };
  row.buttons.at(-1).disabled = true;
  h.dispatch(row.trigger, 'keydown', { key: 'ArrowUp' });
  assert.ok(row.menu.scrollTop > 0, 'last enabled row needs internal scrolling');
  assertFocusedItemExposed(h, row, row.buttons.at(-2));
  assertMenuOutsideTrigger(row, h.window.innerHeight);
  assert.equal(row.menu.hidden, false);
});

test('reopening after internal scrolling exposes the first enabled row without scrolling the page', () => {
  const h = harness(), row = h.row(['note', 'task', 'shorter', 'longer', 'simpler', 'branch']);
  h.compact(row.actions); h.window.innerHeight = 450;
  row.trigger.rect = { left: 20, top: 230, bottom: 274, height: 44, width: 44 };
  row.menu.rect = { width: 208, height: 274 };
  row.buttons[0].setAttribute('aria-disabled', 'true');
  h.dispatch(row.trigger, 'click');
  row.menu.scrollTop = 64;
  h.dispatch(row.trigger, 'click'); h.dispatch(row.trigger, 'click');
  assert.ok(row.menu.scrollTop < 64, 'retained scroll must not hide the initial row');
  assertFocusedItemExposed(h, row, row.buttons[1]);
  assertMenuOutsideTrigger(row, h.window.innerHeight);
  assert.equal(row.menu.hidden, false);
});
