import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const read = relative => readFileSync(new URL(`../../${relative}`, import.meta.url), 'utf8');
const html = read('static/index.html');
const app = read('static/js/app.js');
const runtime = read('static/js/kokuen.js');
const sessions = read('static/js/sessions.js');
const projects = read('static/js/projects.js');
const dropdown = read('static/js/dropdown.js');
const css = read('static/kokuen.css');
const legacyCss = read('static/style.css');
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

test('primary spaces keep one visible identity and clear the universal rail', () => {
  assert.match(html, /class="aide-mobile-name">aide<\/span>/);
  assert.match(css, /body\[data-space="aide"\] \.aide-mobile-name\s*\{[\s\S]*?display:\s*inline/);
  assert.match(
    css,
    /andromeda-settings-panel\s*\{[\s\S]*?left:\s*calc\(52px \+ var\(--k-space-3\)\)/,
  );
  assert.match(
    css,
    /andromeda-idle-footer\s*\{[\s\S]*?left:\s*calc\(52px \+ var\(--k-space-3\)\)/,
  );
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

test('shared choice groups expose selected state and the complete radio keyboard model', () => {
  assert.match(runtime, /export function wireChoiceGroup/);
  assert.match(runtime, /role="radio"/);
  assert.match(runtime, /aria-checked/);
  for (const key of ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End']) {
    assert.match(runtime, new RegExp(`'${key}'`), key);
  }
  for (const module of ['books.js', 'read.js', 'health.js']) {
    const source = read(`static/js/${module}`);
    assert.match(source, /wireChoiceGroup/);
    assert.match(source, /role="radiogroup"/);
    assert.match(source, /role="radio"/);
    assert.match(source, /aria-checked/);
  }
});

test('saved Aide sessions use the shared keyboard-complete context menu', () => {
  assert.match(runtime, /export function createMenuController/);
  assert.match(runtime, /matches\('\[role="button"\]'\)\) return 'action'/);
  for (const key of ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Escape']) {
    assert.match(runtime, new RegExp(`'${key}'`), key);
  }
  assert.match(sessions, /createMenuController/);
  assert.match(sessions, /<button type="button" class="session-open" aria-haspopup="menu"/);
  assert.equal((projects.match(/<button type="button" class="session-open" aria-haspopup="menu"/g) || []).length, 2);
  assert.doesNotMatch(sessions, /class="session-item[^\"]*"[^>]*role="button"/);
  assert.doesNotMatch(projects, /class="session-item[^\"]*"[^>]*role="button"/);
  assert.doesNotMatch(projects, /class="project-folder-head"[^>]*role="button"/);
  assert.match(sessions, /event\.key === 'ContextMenu'/);
  assert.match(sessions, /event\.shiftKey && event\.key === 'F10'/);
  assert.doesNotMatch(sessions, /<div class="ctx-item"/);
  assert.match(html, /id="ctx-menu" role="menu"[^>]*hidden/);
});

test('the runtime reconciles asynchronous control state mutations', () => {
  assert.match(runtime, /function syncControlState/);
  for (const attribute of [
    'disabled', 'aria-disabled', 'aria-busy', 'aria-invalid',
    'aria-checked', 'aria-selected', 'aria-pressed',
  ]) {
    assert.match(runtime, new RegExp(`'${attribute}'`), attribute);
  }
  assert.match(runtime, /record\.type === 'attributes'/);
  assert.match(runtime, /attributes: true/);
  assert.match(runtime, /attributeFilter:/);
});

test('v5 enforces targets, stable motion, focus, and state affordances', () => {
  assert.match(css, /min-height:\s*var\(--ui-control-height, 44px\) !important/);
  assert.match(css, /min-width:\s*var\(--ui-control-height, 44px\) !important/);
  assert.match(css, /data-kokuen-state="busy"/);
  assert.match(css, /data-kokuen-state="invalid"/);
  assert.match(css, /data-state="offline"/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /forced-colors:\s*active/);
  assert.doesNotMatch(css, /html\[data-kokuen-version="5"\][^}]*:hover[^}]*transform:\s*translate/);
});

test('busy state wins while a mutation disables its control to reject repeats', () => {
  const reflected = runtime.slice(
    runtime.indexOf('function syncControlState'),
    runtime.indexOf('function decorateRoot'),
  );
  assert.ok(
    reflected.indexOf("aria-busy') === 'true'")
      < reflected.indexOf("[aria-disabled=\"true\"]"),
  );
  assert.ok(
    reflected.indexOf("['error', 'offline', 'stale', 'partial', 'permission', 'empty']")
      < reflected.indexOf("aria-checked') === 'true'"),
  );
});

test('body-level dialogs clear the universal rail without clipping their content', () => {
  assert.match(css, /body\.afterlife-shell > :is\(\.modal-overlay, \.dialog-overlay\) \{\s*left: 52px/);
  assert.match(css, /body\.afterlife-shell > #setup-wizard \{[\s\S]*?padding-inline: var\(--k-space-4\)/);
  assert.match(css, /body\.afterlife-shell > #setup-wizard \.setup-card \{\s*max-width: 100%/);
});

test('the shipped document contains no forbidden native choice controls', () => {
  assert.doesNotMatch(html, /<select\b/i);
  assert.doesNotMatch(html, /<input\b[^>]*type=["'](?:checkbox|radio)["']/i);
  assert.match(app, /preventDefault\(\)[\s\S]*?openContextMenu|contextmenu/);
});

test('send-later context paths share a keyboard-complete custom dialog', () => {
  assert.match(app, /_sendBtn\.addEventListener\('contextmenu'[\s\S]*?openSendSchedule\(\)/);
  assert.match(app, /e\.key !== 'ContextMenu'[\s\S]*?e\.key === 'F10'[\s\S]*?openSendSchedule\(\)/);
  assert.match(app, /pop\.setAttribute\('role', 'dialog'\)/);
  assert.match(app, /createFocusBoundary\(pop, \{ trigger, onEscape: close \}\)/);
  assert.match(app, /focusBoundary\.activate\(\{ focus: when, source: trigger \}\)/);
  assert.match(app, /const finishBusy = beginBusy\(scheduleButton, 'scheduling'\)/);
  assert.match(app, /if \(!finishBusy\) return/);
  assert.match(app, /catch \(error\)[\s\S]*?finishBusy\(\{ state: 'error', text: 'retry schedule' \}\)/);
  assert.match(app, /setControlState\(scheduleButton, 'error'/);
});

test('model option buttons reset native chrome and retain a full hit target', () => {
  const modelRowRule = legacyCss.match(/\.model-row \{([\s\S]*?)\n\}/)?.[1] || '';
  assert.match(modelRowRule, /width:\s*100%/);
  assert.match(modelRowRule, /min-height:\s*44px/);
  assert.match(modelRowRule, /border:\s*0/);
  assert.match(modelRowRule, /appearance:\s*none/);
  assert.match(modelRowRule, /background:\s*transparent/);
  assert.match(modelRowRule, /font:\s*inherit/);
});
