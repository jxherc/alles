// semantic color tokens (decision 0034): every link and categorical hue clears 4.5:1 on the page,
// panel and raised surfaces of its own theme, and a category name always gets the same hue.
// run: node --test tests/js/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { CATEGORY_HUES, assignHues, categoryHue, contrast } from '../../static/js/color.js';

const css = readFileSync(new URL('../../static/style.css', import.meta.url), 'utf8');
const block = selector => {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, `${selector} block missing`);
  const body = css.slice(start, css.indexOf('\n}', start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})\s*;/gi)].map(m => [m[1], m[2]]));
};
const dark = block(':root');
const light = { ...dark, ...block('[data-theme="light"]') };
const NAMES = ['link', 'link-visited', ...CATEGORY_HUES.map(hue => `cat-${hue}`)];

for (const [theme, tokens] of Object.entries({ dark, light })) {
  test(`${theme}: links and categorical hues read on every surface`, () => {
    for (const name of NAMES) {
      assert.ok(tokens[name], `--${name} is not set in ${theme}`);
      for (const surface of ['bg', 'panel', 'raised']) {
        const ratio = contrast(tokens[name], tokens[surface]);
        assert.ok(ratio >= 4.5, `${theme} --${name} on --${surface}: ${ratio.toFixed(2)}`);
      }
    }
  });
}

test('light overrides every link and categorical hue', () => {
  const own = block('[data-theme="light"]');
  for (const name of NAMES) assert.ok(own[name], `--${name} falls back to the dark value in light`);
});

test('six names shown together never share a hue, and the first group picks first', () => {
  const names = ['rent', 'groceries', 'dining', 'transport', 'fun', 'utilities'];
  const hues = assignHues(names);
  assert.equal(new Set(names.map(name => hues.get(name))).size, 6);
  assert.deepEqual(assignHues(names), hues, 'same names, same hues');
  const chartFirst = assignHues(['dining'], ['rent', 'groceries']);
  assert.equal(chartFirst.get('dining'), categoryHue('dining'));
  assert.equal(assignHues(['Rent ']).get('rent'), categoryHue('rent'));
});

test('categoryHue is stable, case-blind and spreads over the six hues', () => {
  assert.equal(categoryHue('Groceries'), categoryHue(' groceries '));
  assert.ok(CATEGORY_HUES.includes(categoryHue('')));
  const seen = new Set(['rent', 'groceries', 'dining', 'transport', 'fun', 'health', 'gifts', 'travel', 'utilities', 'pets'].map(categoryHue));
  assert.ok(seen.size >= 4, `only ${seen.size} hues for ten categories`);
});
