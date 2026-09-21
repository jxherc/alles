import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import test from 'node:test';

const root = new URL('../../static/', import.meta.url);

test('legacy text and placeholders never use the structural border color', () => {
  const css = readFileSync(new URL('style.css', root), 'utf8');
  // These are the documented Server monitor's decorative branches and meter tracks.
  const decorations = new Set(['.nf-rule', '.nf-branch', '.m-track', '.m-empty', '.p-cpubar']);
  for (const [, selector, declarations] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (decorations.has(selector.trim())) continue;
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
