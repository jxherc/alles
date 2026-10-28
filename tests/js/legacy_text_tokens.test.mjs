import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

const root = new URL('../../static/', import.meta.url);

test('legacy text and placeholders never use the structural border color', () => {
  const css = readFileSync(new URL('style.css', root), 'utf8');
  // the server monitor's glyph tracks and branches are text too: they use the quiet token
  for (const [, selector, declarations] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    assert.doesNotMatch(declarations, /(?<![-\w])color:\s*var\(--faint\)/, selector.trim());
  }
  for (const name of readdirSync(new URL('js/', root)).filter(name => name.endsWith('.js'))) {
    assert.doesNotMatch(
      readFileSync(new URL(`js/${name}`, root), 'utf8'),
      /(?<![-\w])color:\s*var\(--faint\)/,
      `${name}: inline text must use a foreground token`,
    );
  }
});
