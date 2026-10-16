import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = path => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');
const shared = read('static/kokuen.css');
const legacy = read('static/style.css');
const aide = read('static/aidecentral.css');
const coding = read('static/aidecoding.css');
const call = read('static/aidecall.css');
const rules = css => [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)]
  .map(([, selector, body]) => ({ selector: selector.trim(), body }));
function rule(css, selector) {
  const found = rules(css).filter(item => item.selector === selector);
  assert.ok(found.length, `missing rule: ${selector}`);
  return found[0].body;
}

// Source contracts complement the real-browser contour, focus and width checks.
test('shared focus geometry overlays the existing edge instead of drawing a detached frame', () => {
  assert.ok(/--k-focus-offset:\s*-2px/.test(shared), 'shared inset focus token');
  const primitive = rule(shared, 'html[data-kokuen-version="5"] [data-kokuen-primitive]:focus-visible');
  assert.match(primitive, /outline:\s*2px solid/);
  assert.match(primitive, /outline-offset:\s*var\(--k-focus-offset/);
  for (const css of [shared, legacy, aide, coding, call]) {
    for (const { selector, body } of rules(css)) {
      if (!/:focus(?:-visible|-within)?/.test(selector)) continue;
      assert.doesNotMatch(body, /outline-offset:\s*[1-9][\d.]*px/, `detached focus frame: ${selector}`);
    }
  }
});

test('Aide compositor focus belongs to text entry, not toolbar buttons', () => {
  assert.ok(!/\.composer-box:has\(:focus-visible\)/.test(aide), 'toolbar focus must not activate the text boundary');
  const owner = rule(aide, 'body.aide-central[data-space="aide"] .composer-box:has(> .composer-ta:focus-visible)');
  assert.match(owner, /outline:\s*2px solid var\(--focus\)/);
  assert.match(owner, /outline-offset:\s*var\(--k-focus-offset/);
  assert.match(rule(aide, 'body.aide-central[data-space="aide"] .composer-box:focus-within'), /border-color:\s*var\(--faint\)/);
});

test('wrapped text fields have one owner and do not inherit a second primitive outline', () => {
  const owners = rules(shared).find(({ selector }) => selector.includes('.mc-chipfield > .mc-chip-input') && selector.includes('.search-wrap > input'));
  assert.ok(owners, 'shared wrapper-owned input exception');
  assert.match(owners.body, /outline:\s*none/);
  assert.ok(owners.selector.includes('body.afterlife-aide-projects[data-space="aide"] .search-wrap > input:focus-visible'), 'archive suppression stays with its existing focus owner');
  assert.match(rule(legacy, '.mc-chipfield:has(> .mc-chip-input:focus-visible)'), /outline:\s*2px solid var\(--focus\)/);
  assert.match(rule(legacy, 'body.afterlife-aide-projects[data-space="aide"] .search-wrap:has(> input:focus-visible)'), /box-shadow:\s*inset 0 -1px 0 var\(--focus\)/);
  assert.doesNotMatch(shared, /\.search-command-head:focus-within/);
  assert.match(shared, /\.search-command-head:has\(> \.search-prompt-input:focus-visible\)/);
});

test('Archive retains its single wrapper-owned indicator when forced colors suppress shadows', () => {
  const forcedColors = shared.slice(shared.indexOf('@media (forced-colors: active)'), shared.indexOf('/* Shared text-entry sizing.'));
  const owner = rules(forcedColors).find(({ selector }) => selector.includes('body.afterlife-aide-projects[data-space="aide"] .search-wrap:has(> input:focus-visible)'));
  assert.ok(owner, 'forced-colors Archive focus owner');
  assert.match(owner.body, /outline:\s*2px solid Highlight/);
  assert.match(owner.body, /outline-offset:\s*var\(--k-focus-offset,\s*-2px\)/);
});

test('Aide uses the available workspace with aligned compact gutters', () => {
  assert.match(rule(aide, 'body.aide-central[data-space="aide"]'), /--aide-measure:\s*100%/);
  assert.match(aide, /--aide-gutter:\s*var\(--k-space-5,\s*24px\)/);
  assert.match(aide, /@media\s*\(max-width:\s*620px\)[\s\S]*--aide-gutter:\s*var\(--k-space-4,\s*16px\)/);
  for (const selector of ['.messages', '.composer-outer', '.aide-task-saved']) {
    assert.match(rule(aide, `body.aide-central[data-space="aide"] ${selector}`), /var\(--aide-gutter\)/);
  }
});

test('Aide prose retains a reading measure without capping tables and code', () => {
  const prose = rules(aide).find(({ selector }) => selector.includes('.ai-body > :where(p,'));
  assert.ok(prose, 'block-level prose measure');
  assert.ok(prose.selector.includes('.ai-content > :where(p,'), 'saved and streaming replies render prose inside .ai-content');
  assert.match(prose.body, /max-width:\s*68ch/);
  assert.doesNotMatch(prose.selector, /\b(?:pre|table)\b/);
  assert.match(rule(aide, 'body.aide-central[data-space="aide"] .user-bubble'), /max-width:\s*min\(88%,\s*68ch\)/);
});

test('Call text has intrinsic room without shrinking its target or hiding the label', () => {
  const call = rule(aide, '#aide-call-open');
  assert.match(call, /width:\s*auto/);
  assert.match(call, /flex-shrink:\s*0/);
  assert.match(call, /white-space:\s*nowrap/);
  assert.doesNotMatch(aide, /\.aide-call-label[^{}]*\{[^}]*display:\s*none/);
});

test('the narrow header wraps groups in DOM order instead of shrinking text into adjacent controls', () => {
  const narrow = aide.slice(aide.indexOf('@media (max-width: 359px)'), aide.indexOf('@media (prefers-reduced-motion: reduce)'));
  const header = rule(narrow, 'body.aide-central[data-space="aide"] .main > .topbar');
  assert.match(header, /height:\s*auto/);
  assert.match(header, /flex-wrap:\s*wrap/);
  assert.match(rule(narrow, 'body.aide-central[data-space="aide"] .topbar-left'), /flex:\s*0 0 100%/);
  assert.match(rule(narrow, '.aide-mode-nav'), /flex-shrink:\s*0/);
  const modes = rule(narrow, '.aide-mode-nav button');
  assert.match(modes, /flex-shrink:\s*0/);
  assert.match(modes, /white-space:\s*nowrap/);
  assert.doesNotMatch(narrow, /\border\s*:/);
});

test('Coding uses its detail-pane width while connection setup retains a form measure', () => {
  const content = rule(coding, '#aide-coding-workspace .acw-content');
  const error = rule(coding, '#aide-coding-workspace .acw-error');
  for (const declarations of [content, error]) {
    assert.match(declarations, /width:\s*100%/);
    assert.match(declarations, /max-width:\s*none/);
    assert.match(declarations, /var\(--aide-gutter,\s*var\(--k-space-5\)\)/);
  }
  assert.match(rule(coding, '#aide-coding-workspace .acw-connection'), /max-width:\s*620px/);
  assert.match(rule(call, '#aide-call-workspace .aide-call-body'), /width:\s*min\(100%,\s*680px\)/);
});
