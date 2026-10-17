import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/settings/credits.js', import.meta.url), 'utf8')
  .replace(/^import .*\n/gm, '').replace(/^export /gm, '');
const entries = JSON.parse(readFileSync(new URL('../../credits/manifest.json', import.meta.url))).entries;

function harness(compact = true) {
  const nodes = new Map(); const requests = []; const mediaListeners = [];
  const document = { activeElement: null, getElementById: id => nodes.get(id),
    querySelector: selector => list.querySelector(selector), querySelectorAll: () => [] };
  class Node {
    constructor(id = '', dataset = {}) { this.id = id; this.dataset = dataset; this.children = []; this.attrs = new Map(); this.listeners = {}; this.scrolls = []; if (id) nodes.set(id, this); }
    append(child) { child.remove(); this.children.push(child); child.parentElement = this; }
    remove() { if (this.parentElement) { const siblings = this.parentElement.children; siblings.splice(siblings.indexOf(this), 1); this.parentElement = null; } }
    insertAdjacentElement(position, child) { assert.equal(position, 'afterend'); const parent = this.parentElement; child.remove(); parent.children.splice(parent.children.indexOf(this) + 1, 0, child); child.parentElement = parent; }
    get nextElementSibling() { return this.parentElement?.children[this.parentElement.children.indexOf(this) + 1] || null; }
    contains(child) { return child === this || this.children.some(node => node.contains(child)); }
    setAttribute(k, v) { this.attrs.set(k, String(v)); }
    getAttribute(k) { return this.attrs.get(k); }
    addEventListener(k, fn) { this.listeners[k] = fn; }
    focus() { document.activeElement = this; }
    scrollIntoView(options) { this.scrolls.push(options); }
    closest(selector) { return selector === '[data-credit-id]' && this.dataset.creditId ? this : null; }
    querySelector(selector) {
      const id = selector.match(/data-credit-id="([^"]+)"/)?.[1];
      return this.children.find(n => id ? n.dataset.creditId === id : selector.includes('aria-current="true"') && n.getAttribute('aria-current') === 'true') || null;
    }
    querySelectorAll(selector) { return this.children.flatMap(n => [n, ...n.querySelectorAll(selector)]).filter(n => (selector.includes('data-credit-id') || selector === '.credits-row') && n.dataset.creditId); }
    set innerHTML(value) {
      this.html = value;
      for (const child of [...this.children]) child.remove();
      if (this.id === 'credits-list') for (const m of value.matchAll(/<button[^>]*data-credit-id="([^"]+)"[^>]*>/g)) {
        const row = new Node('', { creditId: m[1] });
        for (const attr of m[0].matchAll(/(aria-[\w-]+)="([^"]*)"/g)) row.setAttribute(attr[1], attr[2]);
        this.append(row);
      }
    }
    get innerHTML() { return this.html || ''; }
  }
  const pane = new Node('s-pane-credits'); const workbench = new Node('credits-settings-workbench');
  const controls = new Node('controls'); const list = new Node('credits-list'); const detail = new Node('credits-detail');
  pane.append(workbench); workbench.append(controls); controls.append(list); workbench.append(detail);
  for (const id of ['credits-search','credits-summary','credits-coverage','credits-settings-load-state']) controls.append(new Node(id));
  const media = { matches: compact, addEventListener: (_, fn) => mediaListeners.push(fn) };
  const pending = new Map();
  const context = vm.createContext({ document, window: { matchMedia: () => media }, matchMedia: () => media,
    CSS: { escape: value => value }, requestAnimationFrame: fn => fn(),
    createSettingsPane: value => value, t: value => value, tp: (value, n) => `${value} ${n}`, _esc: String,
    fetch: async url => { requests.push(url); if (pending.has(url)) return pending.get(url);
      return { ok: true, json: async () => url === '/api/credits' ? { entries, coverage: { complete: true } } : entries.find(e => url.endsWith('/' + encodeURIComponent(e.id))) }; } });
  vm.runInContext(source + '\nglobalThis.subject = creditsPane;', context);
  context.subject.init();
  return { pane, workbench, list, detail, document, requests, pending,
    async load() { await context.subject.load(); await new Promise(resolve => setImmediate(resolve)); },
    select(row) { row.focus(); pane.listeners.click({ target: row }); },
    search(value) { const input = nodes.get('credits-search'); input.focus(); input.listeners.input({ target: { value } }); return input; },
    resize(compact) { media.matches = compact; mediaListeners.forEach(fn => fn(media)); } };
}

test('full public manifest keeps compact detail immediately after the selected row', async () => {
  const h = harness(); await h.load(); assert.ok(entries.length >= 496);
  assert.equal(h.list.querySelectorAll('[data-credit-id]').length, entries.length);
  assert.equal(h.detail.parentElement?.id, 'credits-list');
  assert.ok(h.list.children[0].nextElementSibling === h.detail);
});

test('selecting a credit preserves the actual focused button and reveals adjacent detail', async () => {
  const h = harness(); await h.load(); const row = h.list.querySelectorAll('[data-credit-id]')[1]; h.select(row);
  assert.ok(h.document.activeElement === row);
  assert.ok(row.parentElement === h.list, 'do not replace the focused row');
  assert.ok(row.nextElementSibling === h.detail);
  assert.equal(row.getAttribute('aria-controls'), 'credits-detail');
  assert.equal(row.getAttribute('aria-current'), 'true');
  assert.equal(row.scrolls.length, 1);
});

test('filtering retains input focus and keeps no-match detail inside the compact list', async () => {
  const h = harness(); await h.load(); const input = h.search('xterm');
  assert.ok(h.document.activeElement === input); assert.equal(h.detail.parentElement?.id, 'credits-list');
  assert.ok(h.list.querySelectorAll('[data-credit-id]')[0].nextElementSibling === h.detail);
  h.search('no such dependency'); assert.equal(h.detail.parentElement?.id, 'credits-list');
  assert.match(h.detail.innerHTML, /credits.no_match/);
  h.search(''); assert.equal(h.list.querySelectorAll('[data-credit-id]').length, entries.length);
  assert.ok(h.list.children[0].nextElementSibling === h.detail);
});

test('responsive reflow reuses the detail and preserves focus within it', async () => {
  const h = harness(false); await h.load(); assert.equal(h.detail.parentElement?.id, 'credits-settings-workbench');
  h.detail.focus(); h.resize(true); assert.equal(h.detail.parentElement?.id, 'credits-list');
  assert.ok(h.document.activeElement === h.detail);
  h.resize(false); assert.equal(h.detail.parentElement?.id, 'credits-settings-workbench');
  assert.ok(h.document.activeElement === h.detail);
});
