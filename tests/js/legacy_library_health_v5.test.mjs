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
  for (const module of [books, read, health]) {
    assert.match(module, /import \{ wireChoiceGroup \} from '\.\/kokuen\.js';/);
  }
  assert.match(books, /id="book-status" role="radiogroup" aria-label="book shelf"/);
  assert.match(books, /class="book-stars"[^>]*role="radiogroup"/);
  assert.match(books, /role="radio" aria-checked="\$\{i === b\.rating\}"/);
  assert.match(read, /class="read-filter-choices" role="radiogroup" aria-label="saved reading filter"/);
  assert.match(read, /role="radio" aria-checked="\$\{_filter === k\}"/);
  assert.match(read, /id="read-feeds-btn" aria-pressed="\$\{_showFeeds\}"/);
  assert.match(health, /class="health-ranges" role="radiogroup" aria-label="health history range"/);
  assert.match(health, /role="radio" aria-checked="\$\{_days === d\}"/);
  assert.match(books, /querySelectorAll\('\.book-stars, #book-status'\)\.forEach\(group => wireChoiceGroup\(group\)\)/);
  assert.match(read, /wireChoiceGroup\(body\.querySelector\('\.read-filter-choices'\)\)/);
  assert.match(health, /wireChoiceGroup\(body\.querySelector\('\.health-ranges'\)\)/);
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
