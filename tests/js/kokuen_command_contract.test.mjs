import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/kokuen.css', import.meta.url), 'utf8');
const search = readFileSync(new URL('../../static/js/search.js', import.meta.url), 'utf8');

test('universal command uses one labelled dialog, input, and listbox', () => {
  const modal = html.match(/<div class="modal-overlay" id="search-modal"[^>]*>/)?.[0] || '';
  const input = html.match(/<input type="text" id="search-input"[\s\S]*?aria-expanded="false">/)?.[0] || '';
  const results = html.match(/<div class="modal-body" id="search-results"[^>]*>/)?.[0] || '';
  assert.match(modal, /data-kokuen-surface="command"/);
  assert.match(modal, /role="dialog"/);
  assert.match(modal, /aria-modal="true"/);
  assert.match(modal, /aria-labelledby="search-dialog-title"/);
  assert.match(input, /role="combobox"/);
  assert.match(input, /inputmode="search"/);
  assert.match(input, /aria-controls="search-results"/);
  assert.match(results, /role="listbox"/);
  assert.match(html, /id="search-close"[^>]*aria-label="close search"/);
});

test('universal command implements the complete active-option keyboard model', () => {
  assert.match(search, /role="option" aria-selected="false" tabindex="-1"/);
  assert.match(search, /setAttribute\('aria-activedescendant', active\.id\)/);
  assert.match(search, /key === 'ArrowDown'/);
  assert.match(search, /key === 'ArrowUp'/);
  assert.match(search, /key === 'Home'/);
  assert.match(search, /key === 'End'/);
  assert.match(search, /event\.key === 'Enter'/);
  assert.match(search, /event\.key === 'Escape'/);
  assert.match(search, /event\.key !== 'Tab'/);
  assert.match(search, /opener\?\.isConnected/);
});

test('universal command keeps honest states and stable KOKUEN geometry', () => {
  for (const state of ['idle', 'loading', 'error', 'unavailable', 'permission']) {
    assert.match(search, new RegExp(`['\"]${state}['\"]`), state);
  }
  assert.match(search, /search-state--empty/);
  const commandCss = css.slice(
    css.indexOf('#search-modal[data-kokuen-surface="command"]'),
    css.indexOf('/* Stage 8 specialist groups.'),
  );
  assert.match(commandCss, /#search-modal\[data-kokuen-surface="command"\]/);
  assert.match(css, /--k-space-7:\s*48px/);
  assert.match(css, /--k-space-8:\s*64px/);
  assert.match(css, /--ui-control-height:\s*var\(--k-control\)/);
  assert.doesNotMatch(css, /padding(?:-[a-z]+)?:\s*28px/);
  assert.doesNotMatch(commandCss, /backdrop-filter/);
  for (const match of commandCss.matchAll(/box-shadow:\s*([^;]+);/g)) {
    assert.equal(match[1].trim(), 'none');
  }
});
