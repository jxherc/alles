import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { t, tp } from '../../static/js/i18n.js';

const runtime = readFileSync(new URL('../../static/js/kokuen.js', import.meta.url), 'utf8');

// Exercise the shipped decorator with node identity and text aggregation, rather
// than a source-pattern assertion. Full DOM/MutationObserver coverage is browser-side.
class Element {
  constructor(tag = 'button', text = '', attributes = {}, children = []) {
    this.tagName = tag.toUpperCase();
    this.ownText = text;
    this.attributes = { ...attributes };
    this.children = children;
    this.dataset = {};
    this.id = attributes.id || '';
    this.className = attributes.class || '';
  }
  get childElementCount() { return this.children.length; }
  get textContent() { return this.ownText + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.ownText = value; this.children = []; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  setAttribute(name, value) { this.attributes[name] = value; }
  matches() {
    return this.tagName === 'BUTTON'
      || (this.tagName === 'A' && 'href' in this.attributes)
      || this.attributes.role === 'button';
  }
  querySelector(selector) {
    assert.equal(selector, ':scope > svg.ic');
    return this.children.find(child => child.tagName === 'SVG' && child.className === 'ic') || null;
  }
  replaceChildren(...children) { this.ownText = ''; this.children = children; }
}

function harness() {
  const icons = [];
  const context = vm.createContext({
    t,
    iconEl(name) {
      const icon = new Element('svg', '', { class: 'ic' });
      icon.name = name;
      icons.push(icon);
      return icon;
    },
  });
  vm.runInContext(runtime.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, ''), context);
  return { decorate: context.decorateIconControl, icons };
}

test('an initially empty image-model chip retains its model-owned children', () => {
  const { decorate, icons } = harness();
  const provider = new Element('span', '', { id: 'image-slot-ic' });
  const label = new Element('span', '', { id: 'image-slot-label' });
  const remove = new Element('span', '×', { class: 'img-slot-x' });
  const button = new Element('button', '', {
    id: 'image-slot-btn', 'aria-label': 'remove selected image model',
  }, [provider, label, remove]);
  decorate(button);
  assert.deepEqual(button.children, [provider, label, remove]);
  assert.equal(button.dataset.kokuenIcon, undefined, 'composite control must not acquire icon-only layout');

  label.textContent = 'owned image model';
  provider.replaceChildren(new Element('svg', '', { class: 'provider-logo' }));
  decorate(button);
  label.textContent = '';
  provider.replaceChildren();
  decorate(button);
  assert.deepEqual(button.children, [provider, label, remove], 'loading/reset decoration retains the same child nodes');
  assert.equal(icons.length, 0);
});

test('glyph inference leaves nested labels and existing icons under their owner', () => {
  for (const [tag, attributes] of [['button', {}], ['a', { href: '#owned' }], ['div', { role: 'button' }]]) {
    const { decorate } = harness();
    const label = new Element('span', '×');
    const button = new Element(tag, '', attributes, [label]);
    decorate(button);
    assert.equal(button.children[0], label);
    assert.equal(button.dataset.kokuenIcon, undefined);
  }
  const { decorate } = harness();
  const logo = new Element('svg', '', { class: 'owned-logo' });
  const button = new Element('button', '↑', { title: 'send' }, [logo]);
  decorate(button);
  assert.equal(button.children[0], logo);
  assert.equal(button.ownText, '↑');
});

test('plain glyph controls still receive semantic SVGs and accessible names once', () => {
  for (const [text, attributes, name, label] of [
    ['×', {}, 'close', 'close'],
    ['×', { title: 'remove attachment' }, 'trash', 'remove attachment'],
    ['↑', { title: 'send message' }, 'send', 'send message'],
    ['↑', { id: 'files-up-btn' }, 'chevron-up', 'move up'],
    ['‹', { title: 'previous month' }, 'chevron-left', 'previous month'],
    ['‹', {}, 'chevron-left', 'previous'],
    ['›', {}, 'chevron-right', 'next'],
  ]) {
    const { decorate, icons } = harness();
    const button = new Element('button', text, attributes);
    decorate(button);
    decorate(button);
    assert.equal(button.dataset.kokuenIcon, name);
    assert.equal(button.getAttribute('aria-label'), label);
    assert.equal(button.children[0].name, name);
    assert.equal(icons.length, 1, 'observer redecoration must not replace an existing icon');
  }
});

test('explicit icon ownership still renders and updates the requested icon', () => {
  const { decorate, icons } = harness();
  const button = new Element('button', '', { 'aria-labelledby': 'owned-label' }, [new Element('span', 'close')]);
  button.dataset.kokuenIcon = 'close';
  decorate(button);
  assert.equal(button.children[0].name, 'close');
  assert.equal(button.getAttribute('aria-label'), null, 'preserve the supplied accessible name');
  button.dataset.kokuenIcon = 'chevron-down';
  decorate(button);
  decorate(button);
  assert.equal(button.children[0].name, 'chevron-down');
  assert.equal(icons.length, 2);
});
