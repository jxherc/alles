import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const source = readFileSync(new URL('../../static/js/andromeda.js', import.meta.url), 'utf8');
const prose = source.slice(source.indexOf('const CITE_GROUP'), source.indexOf('function renderCompleteOverview'))
  .replace(/^export /gm, '');

// just enough dom for renderProse: elements keep a parent and a child list
function node(tagName) {
  const listeners = new Map();
  return {
    tagName, children: [], parent: null, attrs: {}, dataset: {}, className: '', id: '', textContent: '',
    append(...items) { for (const item of items) { item.parent?.children.splice(item.parent.children.indexOf(item), 1); item.parent = this; this.children.push(item); } },
    after(item) { const list = this.parent.children; item.parent = this.parent; list.splice(list.indexOf(this) + 1, 0, item); },
    remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; },
    replaceChildren() { this.children = []; },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return this.attrs[name] ?? null; },
    removeAttribute(name) { delete this.attrs[name]; },
    addEventListener(name, listener) { listeners.set(name, listener); },
    click() { listeners.get('click')?.({}); },
    focus() {},
  };
}

function find(root, test) {
  if (test(root)) return root;
  for (const child of root.children || []) {
    const hit = find(child, test);
    if (hit) return hit;
  }
  return null;
}

test('a claim inside a table cell opens its sources under the table, not as a column', () => {
  const holder = node('DIV');
  const context = vm.createContext({ t, tp, tr: t, trp: tp,
    document: {
      createElement: tag => node(tag.toUpperCase()),
      createTextNode: text => ({ ...node('#text'), textContent: text }),
    },
    el: id => (id === 'andromeda-claims' ? holder : null),
    hostOf: url => new URL(url).hostname,
    safeUrl: url => new URL(url),
    _state: { evidence: [] },
    _sourceCardSeq: 0,
  });
  vm.runInContext(`${prose}\nglobalThis.renderProse = renderProse;`, context);
  context.renderProse('| version | note |\n|---|---|\n| 3.2 [1] | current |', [
    { url: 'https://example.com/release', title: 'release notes' },
  ], { done: true });

  const claim = find(holder, item => item.className === 'andromeda-prose-claim');
  assert.ok(claim, 'the cited cell is underlined');
  claim.click();
  const card = find(holder, item => item.className === 'andromeda-prose-card');
  assert.ok(card, 'the sources card opened');
  assert.equal(card.parent.className, 'andromeda-prose', 'the card sits beside the table, in the answer');
  const wrap = card.parent.children[card.parent.children.indexOf(card) - 1];
  assert.equal(wrap.className, 'andromeda-prose-table');
  const row = find(holder, item => item.tagName === 'TR' && item.children.some(cell => cell.tagName === 'TD'));
  assert.deepEqual(row.children.map(cell => cell.tagName), ['TD', 'TD']);
});
