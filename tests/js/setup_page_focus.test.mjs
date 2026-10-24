import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/setupwizard.js', import.meta.url), 'utf8');
const pageFocus = source.match(/^function _pageFocus\(\) \{[^]*?^\}/m)[0];

// a home page with the capture box and a heading, on a fine or a coarse pointer
function page({ coarse }) {
  const focused = [];
  const node = (name, attrs = {}) => ({
    name, attrs, tabIndex: 0,
    getClientRects: () => [1],
    hasAttribute: key => key in attrs,
    focus(options) { focused.push({ name, options }); },
  });
  const capture = node('capture');
  const heading = node('heading');
  const context = vm.createContext({
    $: id => (id === 'today-capture-input' ? capture : null),
    document: { querySelectorAll: () => [heading] },
    matchMedia: query => ({ matches: query === '(pointer: coarse)' && coarse }),
  });
  context.globalThis = context;
  vm.runInContext(`${pageFocus}; this.pageFocus = _pageFocus;`, context);
  return { run: context.pageFocus, focused, heading };
}

test('closing setup with a mouse or keyboard lands on the capture box', () => {
  const p = page({ coarse: false });
  p.run();
  assert.deepEqual(p.focused.map(f => f.name), ['capture']);
});

test('closing setup on a touch screen focuses the heading, so no keyboard pops open', () => {
  const p = page({ coarse: true });
  p.run();
  assert.deepEqual(p.focused.map(f => f.name), ['heading']);
  assert.equal(p.focused[0].options?.preventScroll, true);
  assert.equal(p.heading.tabIndex, -1);
});
