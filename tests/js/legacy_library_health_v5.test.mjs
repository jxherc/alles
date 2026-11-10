import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = relative => readFileSync(new URL(relative, import.meta.url), 'utf8');
const books = source('../../static/js/books.js');
const read = source('../../static/js/read.js');
const health = source('../../static/js/health.js');
const kokuen = source('../../static/js/kokuen.js');
const css = source('../../static/kokuen.css');

test('Library and Health choices use the shared KOKUEN radio model', () => {
  for (const module of [books]) {
    assert.match(module, /import \{ initKokuenPrimitives, wireChoiceGroup \} from '\.\/kokuen\.js(\?v=\d+)?';/);
  }
  assert.match(books, /id="book-status" role="radiogroup" aria-label="\$\{esc\(t\('books\.shelf_label'\)\)\}"/);
  assert.match(books, /class="k-number-row book-rate" data-kokuen-choice="rating"/);
  assert.match(read, /class="settings-input custom-select read-filter" id="read-filter" data-value="\$\{_filter\}"[\s\S]*?aria-label="\$\{esc\(t\('read\.filter_label'\)\)\}"/);
  assert.match(read, /id="read-feeds-btn" aria-pressed="\$\{_showFeeds\}"/);
  // four history ranges are a dropdown, not a wall of chips
  assert.match(health, /class="settings-input custom-select health-range" id="health-range" data-value="\$\{_days\}"[\s\S]*?aria-label="\$\{esc\(t\('health\.history_range'\)\)\}"/);
  assert.doesNotMatch(health, /health-chip|health-ranges/);
  assert.match(books, /class="k-pill-switch book-move" data-kokuen-choice="switch" aria-label="\$\{esc\(t\('books\.shelf_for', \{ title: b\.title \}\)\)\}"/);
  assert.match(books, /aria-checked="\$\{k === b\.status\}" data-move="\$\{k\}"/);
  assert.match(books, /initKokuenPrimitives\(body\);\s*body\.querySelectorAll\('#book-status'\)\.forEach\(group => wireChoiceGroup\(group\)\)/);
  assert.match(read, /initCustomDropdown\(filter\);/);
  assert.match(health, /initCustomDropdown\(range\)/);
});

test('the shared radio model supports roving focus and selected state', () => {
  const choice = kokuen.match(/export function wireChoiceGroup\([\s\S]*?\n}\n/)?.[0] || '';
  assert.match(choice, /\['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'\]/);
  assert.match(choice, /choice\.setAttribute\('aria-checked', String\(active\)\)/);
  assert.match(choice, /choice\.tabIndex = active \? 0 : -1/);
  assert.match(choice, /setControlState\(choice, active \? 'selected' : 'resting'\)/);
  assert.match(choice, /options\[next\]\.focus\(\);\s*activate\(options\[next\]\)/);
});

test('v5 preserves a 44px target for dynamically rendered discrete choices', () => {
  assert.match(css, /\[role="radio"\],[\s\S]*?\)\[data-kokuen-primitive\] \{[\s\S]*?min-height: var\(--ui-control-height, 44px\)/);
  assert.match(css, /\[data-kokuen-primitive="choice"\][\s\S]*?min-width: var\(--ui-control-height, 44px\)/);
});

test('legacy screens retain loaded data and expose a persistent retryable KOKUEN load state', () => {
  for (const module of [books, read, health]) {
    assert.match(module, /data-kokuen-state="\$\{_loadState\.state\}"/);
    assert.match(module, /data-act="retry-load"/);
    assert.match(module, /querySelector\('\[data-act="retry-load"\]'\)\?\.addEventListener\('click'/);
    assert.match(module, /_loadState = \{ state: 'loading'/);
    assert.match(module, /navigator\.onLine === false/);
  }
  assert.match(read, /Promise\.allSettled\(/);
  assert.match(health, /Promise\.allSettled\(/);
  assert.match(read, /state: 'partial'/);
  assert.match(health, /state: 'partial'/);
  assert.doesNotMatch(books, /catch \{ _data = _EMPTY\(\); \}/);
  assert.doesNotMatch(read, /catch \{ _items = \[\]; \}/);
  assert.doesNotMatch(health, /catch \{ _data = \{ kinds: \[\]/);
});
