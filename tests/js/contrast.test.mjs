// unit tests for WCAG contrast helpers + adaptive muted (static/js/color.js).
// run: node --test tests/js/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { relLum, contrast, mutedFor, mix } from '../../static/js/color.js';

// representative theme {text,bg} pairs — the light ones are where muted broke (#39).
const LIGHT = {
  light: ['#111111', '#f5f4f1'], blossom: ['#4a2c34', '#faf4f6'], sakura: ['#5c3a44', '#fff0f3'],
  paper: ['#3b3836', '#faf8f5'], lavender: ['#3d3551', '#f3eef8'], solarlight: ['#586e75', '#fdf6e3'],
  sand: ['#4a4136', '#f3ecdf'], steel: ['#2a3038', '#eef1f4'], coral: ['#5a3a32', '#fff5f0'],
  ice: ['#24414f', '#eef6fb'], peach: ['#5a3e2a', '#fff3e8'], cute: ['#d4608a', '#fff0f5'],
};
const DARK = {
  dark: ['#e8e6e3', '#0a0a0a'], midnight: ['#c9d1d9', '#0d1117'], dracula: ['#f8f8f2', '#282a36'],
};

test('relLum: black 0, white 1', () => {
  assert.ok(relLum('#000000') < 0.001);
  assert.ok(relLum('#ffffff') > 0.999);
});

test('contrast: black-on-white is 21:1, identical is 1:1', () => {
  assert.ok(Math.abs(contrast('#000000', '#ffffff') - 21) < 0.1);
  assert.ok(Math.abs(contrast('#808080', '#808080') - 1) < 0.001);
});

test('contrast is symmetric', () => {
  assert.ok(Math.abs(contrast('#111111', '#f5f4f1') - contrast('#f5f4f1', '#111111')) < 1e-9);
});

test('the OLD 0.5 mix fails on the flagged light themes (the bug being fixed)', () => {
  // proves the regression existed: a flat midpoint is < 3.0 against these light bgs.
  // (plain `light` has near-black text so its midpoint already passed — not flagged.)
  const BROKEN = { ...LIGHT }; delete BROKEN.light;
  for (const [name, [text, bg]] of Object.entries(BROKEN)) {
    const old = mix(text, bg, 0.5);
    assert.ok(contrast(old, bg) < 3.0, `${name}: expected old muted to fail, got ${contrast(old, bg).toFixed(2)}`);
  }
});

test('mutedFor clears 3.0 contrast on EVERY light theme', () => {
  for (const [name, [text, bg]] of Object.entries(LIGHT)) {
    const m = mutedFor(text, bg);
    assert.ok(contrast(m, bg) >= 3.0, `${name}: muted ${m} only ${contrast(m, bg).toFixed(2)} vs bg`);
  }
});

test('mutedFor clears 3.0 on dark themes too', () => {
  for (const [name, [text, bg]] of Object.entries(DARK)) {
    const m = mutedFor(text, bg);
    assert.ok(contrast(m, bg) >= 3.0, `${name}: muted ${m} only ${contrast(m, bg).toFixed(2)}`);
  }
});

test('mutedFor leaves dark themes at the subtle 0.5 mix (no visual regression)', () => {
  // dark themes already pass at 0.5, so the adaptive fn must not touch them
  for (const [text, bg] of Object.values(DARK)) {
    assert.equal(mutedFor(text, bg), mix(text, bg, 0.5));
  }
});

test('muted stays distinct from text (still reads as secondary)', () => {
  for (const [text, bg] of [...Object.values(LIGHT), ...Object.values(DARK)]) {
    const m = mutedFor(text, bg);
    assert.notEqual(m.toLowerCase(), text.toLowerCase(), 'muted must not collapse onto text');
    // and it must sit between text and bg in luminance (still a blend, not darker than text)
    const lm = relLum(m), lt = relLum(text), lb = relLum(bg);
    assert.ok(lm >= Math.min(lt, lb) - 1e-6 && lm <= Math.max(lt, lb) + 1e-6, 'muted out of [text,bg] range');
  }
});

test('mutedFor is deterministic', () => {
  assert.equal(mutedFor('#4a2c34', '#faf4f6'), mutedFor('#4a2c34', '#faf4f6'));
});

// secondary text frequently sits on --panel, which on the palest themes is a touch
// darker than --bg. muted must clear the floor against the HARDER of the two surfaces.
const PANELS = {
  // text, bg, panel  (the themes where panel != bg luminance-wise)
  light: ['#111111', '#f5f4f1', '#efede9'], solarlight: ['#586e75', '#fdf6e3', '#eee8d5'],
  sakura: ['#5c3a44', '#fff0f3', '#ffe5ea'], lavender: ['#3d3551', '#f3eef8', '#faf7ff'],
  sand: ['#4a4136', '#f3ecdf', '#fbf6ec'], blossom: ['#4a2c34', '#faf4f6', '#ffffff'],
};

test('mutedFor(text,bg,panel) clears 3.0 against BOTH bg and panel', () => {
  for (const [name, [text, bg, panel]] of Object.entries(PANELS)) {
    const m = mutedFor(text, bg, panel);
    assert.ok(contrast(m, bg) >= 3.0, `${name}: muted ${m} only ${contrast(m, bg).toFixed(2)} vs bg`);
    assert.ok(contrast(m, panel) >= 3.0, `${name}: muted ${m} only ${contrast(m, panel).toFixed(2)} vs panel`);
  }
});

test('mutedFor panel arg defaults to bg (back-compat)', () => {
  assert.equal(mutedFor('#4a2c34', '#faf4f6'), mutedFor('#4a2c34', '#faf4f6', '#faf4f6'));
});
