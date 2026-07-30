import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const read = relative => readFileSync(new URL(`../../${relative}`, import.meta.url), 'utf8');
const html = read('static/index.html');
const app = read('static/js/app.js');
const runtime = read('static/js/kokuen.js');
const dropdown = read('static/js/dropdown.js');
const css = read('static/kokuen.css');
const contracts = JSON.parse(read('design-system/components/contracts.json'));

const requiredStates = [
  'resting', 'hover', 'pressed', 'selected', 'disabled', 'busy', 'invalid',
  'loading', 'empty', 'permission', 'offline', 'stale', 'partial', 'error',
];

test('KOKUEN v5 exposes one state vocabulary in code and component contracts', () => {
  for (const state of requiredStates) assert.match(runtime, new RegExp(`'${state}'`));
  assert.deepEqual(contracts.state_vocabulary, requiredStates);
  assert.match(app, /initKokuenPrimitives\(document\)/);
  assert.match(runtime, /document\.documentElement\.dataset\.kokuenVersion = '5'/);
});

test('the shell has exactly one global navigation trigger and no repeated home actions', () => {
  assert.equal((html.match(/id="app-drawer-btn"/g) || []).length, 1);
  assert.match(html, /id="app-drawer-btn"[^>]*aria-haspopup="dialog"[^>]*aria-controls="app-drawer"/);
  assert.doesNotMatch(html, /class="space-link"|id="space-profile-btn"|data-specialist-home/);
  assert.doesNotMatch(html, /id="aide-home-button"|id="andromeda-(?:go|idle)-home"/);
  assert.match(app, /createFocusBoundary\(drawer/);
  assert.match(app, /document\.querySelector\('\.main'\)\?\.setAttribute\('inert', ''\)/);
  assert.match(app, /document\.querySelector\('\.sidebar'\)\?\.setAttribute\('inert', ''\)/);
});

test('the shell registry keeps three primary spaces and exactly nine specialist apps', () => {
  const block = app.match(/const SHELL_GROUPS = Object\.freeze\(\[[\s\S]*?\n\]\);/)?.[0] || '';
  assert.ok(block);
  const entries = [...block.matchAll(/\{ view: '([^']+)', name: '([^']+)'/g)]
    .map(([, view, name]) => ({ view, name }));
  assert.deepEqual(entries.slice(0, 3).map(entry => entry.name), ['home', 'aide', 'andromeda']);
  assert.deepEqual(
    entries.slice(3).map(entry => entry.name),
    ['plan', 'inbox', 'docs', 'files', 'library', 'health', 'finance', 'vault', 'server'],
  );
  assert.equal(entries.length, 12);
  assert.match(app, /window\._navCommands = SHELL_GROUPS\.flatMap/);
  assert.equal((html.match(/data-kokuen-surface="specialist"/g) || []).length, 9);
});

test('shared primitive contracts cover every required control family', () => {
  const ids = contracts.contracts.map(contract => contract.id);
  assert.deepEqual(ids, [
    'kokuen.action',
    'kokuen.icon-action',
    'kokuen.field',
    'kokuen.switch',
    'kokuen.select-listbox',
    'kokuen.tabs',
    'kokuen.menu',
    'kokuen.dialog',
    'kokuen.sheet',
    'kokuen.command',
    'kokuen.data-view',
    'kokuen.feedback',
  ]);
  for (const contract of contracts.contracts) {
    assert.equal(contract.status, 'stable', contract.id);
    assert.ok(contract.user_job, contract.id);
    assert.ok(contract.boundary_rationale, contract.id);
    assert.ok(contract.keyboard?.keys?.length, contract.id);
    assert.ok(contract.accessibility?.role, contract.id);
    assert.ok(contract.responsive_modes?.length, contract.id);
    assert.ok(contract.fixtures?.length, contract.id);
  }
});

test('custom select implements the complete single-select keyboard model', () => {
  assert.match(dropdown, /role', 'combobox'/);
  assert.match(dropdown, /aria-autocomplete', 'none'/);
  assert.match(dropdown, /aria-controls', panel\.id/);
  assert.match(dropdown, /aria-activedescendant/);
  for (const key of ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', 'Escape', 'Tab']) {
    assert.match(dropdown, new RegExp(`'${key}'`), key);
  }
  assert.match(dropdown, /role', 'listbox'/);
  assert.match(dropdown, /role="option"/);
  assert.match(dropdown, /aria-selected/);
});

test('v5 enforces targets, stable motion, focus, and state affordances', () => {
  assert.match(css, /min-height:\s*var\(--ui-control-height\)/);
  assert.match(css, /min-width:\s*var\(--ui-control-height\)/);
  assert.match(css, /data-kokuen-state="busy"/);
  assert.match(css, /data-kokuen-state="invalid"/);
  assert.match(css, /data-state="offline"/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /forced-colors:\s*active/);
  assert.doesNotMatch(css, /html\[data-kokuen-version="5"\][^}]*:hover[^}]*transform:\s*translate/);
});

test('the shipped document contains no forbidden native choice controls', () => {
  assert.doesNotMatch(html, /<select\b/i);
  assert.doesNotMatch(html, /<input\b[^>]*type=["'](?:checkbox|radio)["']/i);
  assert.match(app, /preventDefault\(\)[\s\S]*?openContextMenu|contextmenu/);
});
