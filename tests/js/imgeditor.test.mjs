import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

class FakeEl {
  constructor(doc, id = '', cls = '') {
    this.doc = doc;
    this.id = id;
    this.className = cls;
    this.style = {};
    this.children = [];
    this.listeners = new Map();
    this._qs = new Map();
    this._all = new Map();
  }

  appendChild(el) {
    this.children.push(el);
    if (el.id) this.doc.ids.set(el.id, el);
  }

  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(fn);
  }

  removeEventListener(type, fn) {
    this.listeners.get(type)?.delete(fn);
  }

  querySelector(sel) {
    return this._qs.get(sel) || null;
  }

  querySelectorAll(sel) {
    return this._all.get(sel) || [];
  }

  getBoundingClientRect() {
    return { left: 0, top: 0, width: 100, height: 100 };
  }

  remove() {}

  set innerHTML(v) {
    this._innerHTML = String(v);
    if (this.id === 'imgeditor-modal') this._buildEditor();
  }

  get innerHTML() {
    return this._innerHTML || '';
  }

  _buildEditor() {
    const canvas = new FakeCanvas(this.doc, 'ie-canvas');
    const crop = new FakeEl(this.doc, 'ie-crop-rect');
    const tools = new FakeEl(this.doc, '', 'ie-tools');
    const right = new FakeEl(this.doc, '', 'ie-right');
    const panel = new FakeEl(this.doc, 'ie-panel');
    const wrap = new FakeEl(this.doc, 'ie-canvas-wrap');
    for (const el of [canvas, crop, panel, wrap]) this.doc.ids.set(el.id, el);
    this._qs = new Map([
      ['#ie-canvas', canvas],
      ['#ie-crop-rect', crop],
      ['.ie-tools', tools],
      ['.ie-right', right],
      ['#ie-panel', panel],
      ['#ie-canvas-wrap', wrap],
    ]);
    this._all = new Map([['.ie-tool', []]]);
  }
}

class FakeCanvas extends FakeEl {
  getContext() {
    return {
      beginPath() {},
      clearRect() {},
      drawImage() {},
      lineTo() {},
      moveTo() {},
      stroke() {},
    };
  }
}

function makeWindow() {
  const listeners = new Map();
  return {
    location: { hostname: 'gallery.localhost' },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
    },
    removeEventListener(type, fn) {
      listeners.get(type)?.delete(fn);
    },
    count(type) {
      return listeners.get(type)?.size || 0;
    },
    handlers(type) {
      return [...(listeners.get(type) || [])];
    },
  };
}

function setupDom() {
  const doc = {
    ids: new Map(),
    body: null,
    createElement(tag) {
      return tag === 'canvas' ? new FakeCanvas(this) : new FakeEl(this);
    },
    getElementById(id) {
      return this.ids.get(id) || null;
    },
  };
  doc.body = new FakeEl(doc, 'body');
  doc.ids.set('toast-container', new FakeEl(doc, 'toast-container'));
  const win = makeWindow();
  globalThis.document = doc;
  globalThis.window = win;
  globalThis.Image = class {
    set src(v) { this._src = v; }
  };
  return { doc, win };
}

setupDom();
const { closeEditor, openEditor } = await import('../../static/js/imgeditor.js');

afterEach(() => closeEditor());

test('closeEditor removes window drag handlers', () => {
  const { win } = setupDom();
  openEditor('/photo.png');
  assert.equal(win.count('mousemove'), 1);
  assert.equal(win.count('mouseup'), 1);

  closeEditor();
  assert.equal(win.count('mousemove'), 0);
  assert.equal(win.count('mouseup'), 0);
});

test('stale drag handlers do not read cleared editor state', () => {
  const { win } = setupDom();
  openEditor('/photo.png');
  const move = win.handlers('mousemove')[0];
  const up = win.handlers('mouseup')[0];

  closeEditor();
  assert.doesNotThrow(() => move({ clientX: 10, clientY: 10 }));
  assert.doesNotThrow(() => up());
});

test('reopening the editor does not stack old window handlers', () => {
  const { win } = setupDom();
  openEditor('/one.png');
  const first = win.handlers('mousemove')[0];

  openEditor('/two.png');
  assert.equal(win.count('mousemove'), 1);
  assert.notEqual(win.handlers('mousemove')[0], first);
});
