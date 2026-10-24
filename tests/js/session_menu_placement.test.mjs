import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/js/sessions.js', import.meta.url), 'utf8');
const place = source.match(/function placeCtxMenu\([^]*?\n}/)?.[0];

function placed(at, { width = 180, height = 300, viewport = [390, 700], rows = [] } = {}) {
  const menu = { style: {}, getBoundingClientRect: () => ({ width, height }), querySelectorAll: () => rows };
  const context = vm.createContext({ innerWidth: viewport[0], innerHeight: viewport[1], menu, at });
  vm.runInContext(`${place}\nplaceCtxMenu(menu, at);`, context);
  return { left: menu.style.left, top: menu.style.top, maxHeight: menu.style.maxHeight };
}

test('the row more button opens its menu on screen on a phone', () => {
  assert.ok(place);
  // a low row near the right edge of a 390px phone: flip left of and above the button
  const button = { left: 300, right: 344, top: 600, bottom: 644 };
  assert.deepEqual(placed(button), { left: '164px', top: '300px', maxHeight: '684px' });
  // room below and to the right: under the button, as before
  assert.deepEqual(placed({ left: 40, right: 84, top: 100, bottom: 144 }), { left: '40px', top: '144px', maxHeight: '684px' });
});

test('a right click near the corner keeps the menu inside the window', () => {
  assert.deepEqual(placed({ left: 380, right: 380, top: 690, bottom: 690 }), { left: '200px', top: '390px', maxHeight: '684px' });
});

test('a menu taller than the window scrolls instead of running off it', () => {
  const { top, maxHeight } = placed({ left: 40, right: 84, top: 200, bottom: 244 }, { height: 684, viewport: [390, 700] });
  assert.equal(top, '8px');
  assert.equal(maxHeight, '684px');
  assert.match(source, /function placeCtxMenu[^]*?overflowY = 'auto'/);
});

test('rows get their 44px before the menu is measured, not after', () => {
  const rows = [{ dataset: {} }, { dataset: {} }];
  placed({ left: 40, right: 84, top: 100, bottom: 144 }, { rows });
  assert.deepEqual(rows.map(row => row.dataset.kokuenPrimitive), ['menu-item', 'menu-item']);
});

test('the more button hands its own box to the menu', () => {
  assert.match(source, /openCtxMenu\(\{ anchor: more\.getBoundingClientRect\(\) \}, sid, more\)/);
  assert.match(source, /placeCtxMenu\(menu, e\.anchor \|\|/);
});
