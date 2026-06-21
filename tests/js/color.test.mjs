// unit tests for the pure colour math (static/js/color.js).
// run: node --test tests/js/   (or: alles test:js)
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { generateHarmony, hexToHSL, hexToRgb, hslToHex, lum, mix } from '../../static/js/color.js';

test('hexToRgb parses 6-digit hex', () => {
  assert.deepEqual(hexToRgb('#818cf8'), { r: 129, g: 140, b: 248 });
});

test('hexToRgb expands 3-digit shorthand', () => {
  assert.deepEqual(hexToRgb('#fff'), { r: 255, g: 255, b: 255 });
});

test('hexToRgb returns black on garbage', () => {
  assert.deepEqual(hexToRgb('not-a-color'), { r: 0, g: 0, b: 0 });
  assert.deepEqual(hexToRgb(''), { r: 0, g: 0, b: 0 });
  assert.deepEqual(hexToRgb(null), { r: 0, g: 0, b: 0 });
});

test('hslToHex round-trips through hexToHSL', () => {
  for (const hex of ['#818cf8', '#0a0a0a', '#e8e6e3', '#ff6b9d']) {
    const [h, s, l] = hexToHSL(hex);
    assert.equal(hslToHex(h, s, l).toLowerCase(), hex.toLowerCase());
  }
});

test('mix(a,b,0)=a, mix(a,b,1)=b, midpoint between', () => {
  assert.equal(mix('#000000', '#ffffff', 0), '#000000');
  assert.equal(mix('#000000', '#ffffff', 1), '#ffffff');
  assert.equal(mix('#000000', '#ffffff', 0.5), '#808080');
});

test('lum is 0 for black, 1 for white, and orders by brightness', () => {
  assert.equal(lum('#000000'), 0);
  assert.equal(lum('#ffffff'), 1);
  assert.ok(lum('#f5f4f1') > 0.5, 'light paper reads as light');
  assert.ok(lum('#0a0a0a') < 0.5, 'near-black reads as dark');
});

test('generateHarmony returns the 5 theme tokens', () => {
  const p = generateHarmony('#818cf8', 'complementary', 'dark');
  assert.deepEqual(Object.keys(p).sort(), ['accent', 'bg', 'faint', 'panel', 'text']);
  assert.equal(p.accent, '#818cf8'); // accent is preserved verbatim
  for (const v of Object.values(p)) assert.match(v, /^#[0-9a-f]{6}$/i);
});

test('generateHarmony dark vs light flips background lightness', () => {
  const dark = generateHarmony('#818cf8', 'complementary', 'dark');
  const light = generateHarmony('#818cf8', 'complementary', 'light');
  assert.ok(lum(dark.bg) < lum(light.bg), 'dark bg is darker than light bg');
});
