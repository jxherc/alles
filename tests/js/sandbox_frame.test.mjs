// the sandbox frame for artifacts and "run" (static/js/util.js sandboxFrame): html goes to the
// frame on every ready while it's on the page, a removed frame lets go of its html, and a frame
// that never answers (offline) turns into a note with a retry
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

class Node {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.parent = null; this.listeners = {};
    this.style = {}; this.attributes = {}; this.className = ''; this.textContent = '';
  }
  get isConnected() { return this.parent === doc.body || Boolean(this.parent?.isConnected); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  click() { for (const fn of this.listeners.click || []) fn({ target: this }); }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  appendChild(node) { this.append(node); return node; }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; }
  replaceWith(node) { const p = this.parent; p.children[p.children.indexOf(this)] = node; node.parent = p; this.parent = null; }
  querySelector(sel) {
    for (const child of this.children) {
      if (sel === 'button' && child.tagName === 'BUTTON') return child;
      const hit = child.querySelector(sel); if (hit) return hit;
    }
    return null;
  }
  focus() { doc.activeElement = this; }
}

const sent = [];
const listeners = [];
const doc = {
  body: new Node('body'), activeElement: null,
  createElement(tag) {
    const node = new Node(tag);
    if (tag === 'iframe') node.contentWindow = { postMessage: (data, origin) => sent.push({ frame: node, data, origin }) };
    return node;
  },
  addEventListener() {},
};
globalThis.document = doc;
globalThis.window = { addEventListener: (type, fn) => listeners.push(fn) };
Object.defineProperty(globalThis, 'navigator', { value: { onLine: true }, configurable: true });

mock.timers.enable({ apis: ['setTimeout'] });
const { sandboxFrame } = await import('../../static/js/util.js');
const ready = source => { for (const fn of listeners) fn({ source, data: { sandbox: 'ready' } }); };

test('the html goes to the frame on its first ready and again after it reloads', () => {
  sent.length = 0;
  const frame = doc.body.appendChild(sandboxFrame('<p>game</p>', 'artifact-iframe'));
  assert.equal(frame.src, '/static/sandbox.html');
  assert.equal(frame.sandbox, 'allow-scripts');
  assert.equal(frame.referrerPolicy, 'no-referrer');
  ready(frame.contentWindow);
  ready(frame.contentWindow);   // "play again" reloaded the sandbox page
  assert.deepEqual(sent.map(s => [s.frame, s.data.html, s.origin]), [[frame, '<p>game</p>', '*'], [frame, '<p>game</p>', '*']]);
  mock.timers.tick(3000);
  assert.equal(frame.isConnected, true, 'a frame that answered stays');
  frame.remove();
});

test('another window saying ready gets nothing', () => {
  sent.length = 0;
  const frame = doc.body.appendChild(sandboxFrame('secret', 'code-iframe'));
  ready({ postMessage() {} });
  ready(undefined);
  assert.equal(sent.length, 0);
  ready(frame.contentWindow);
  assert.equal(sent.length, 1);
  frame.remove();
});

test('a frame removed before it was ready lets go of its html and is never written to', () => {
  sent.length = 0;
  const frame = doc.body.appendChild(sandboxFrame('gone', 'code-iframe'));
  frame.remove();
  mock.timers.tick(3000);
  ready(frame.contentWindow);
  assert.equal(sent.length, 0);
  assert.equal(doc.body.children.length, 0, 'no note for a frame nobody shows');
});

test('no answer in time: the frame turns into a note with a 44px retry, and retry tries again', () => {
  sent.length = 0;
  const frame = doc.body.appendChild(sandboxFrame('<p>x</p>', 'code-iframe', { noteClass: 'code-output', offline: 'running this needs a connection' }));
  frame.focus();
  mock.timers.tick(2999);
  assert.equal(doc.body.children[0], frame);
  mock.timers.tick(1);
  const note = doc.body.children[0];
  assert.equal(note.tagName, 'DIV');
  assert.equal(note.className, 'code-output');
  assert.equal(note.attributes.role, 'status');
  assert.equal(note.children[0].textContent, 'running this needs a connection');
  const retry = note.querySelector('button');
  assert.equal(retry.textContent, 'retry');
  assert.equal(retry.type, 'button');
  assert.match(retry.style.cssText, /min-height:44px/);
  assert.equal(doc.activeElement, retry, 'focus moves to retry, not the page');
  ready(frame.contentWindow);
  assert.equal(sent.length, 0, 'the replaced frame gets nothing');
  retry.click();
  const again = doc.body.children[0];
  assert.equal(again.tagName, 'IFRAME');
  assert.equal(doc.activeElement, again);
  ready(again.contentWindow);
  assert.equal(sent.at(-1).data.html, '<p>x</p>');
  again.remove();
});

test('offline it shows the note straight away', () => {
  navigator.onLine = false;
  try {
    const note = sandboxFrame('<p>x</p>', 'artifact-iframe', { noteClass: 'artifact-content', offline: 'artifacts need a connection to run' });
    assert.equal(note.tagName, 'DIV');
    assert.equal(note.className, 'artifact-content');
    assert.equal(note.children[0].textContent, 'artifacts need a connection to run');
    doc.body.appendChild(note);
    navigator.onLine = true;
    note.querySelector('button').click();
    assert.equal(doc.body.children[0].tagName, 'IFRAME');
    doc.body.children[0].remove();
  } finally { navigator.onLine = true; }
});
