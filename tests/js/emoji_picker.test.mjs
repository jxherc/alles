import assert from 'node:assert/strict';
import test from 'node:test';
import { searchEmoji } from '../../static/js/emoji_picker.js';

test('the habit emoji list is curated, unique and searchable by english words', () => {
  const all = searchEmoji('');
  assert.ok(all.length >= 120 && all.length <= 200, `expected a compact list, got ${all.length}`);
  assert.equal(new Set(all.map(item => item.glyph)).size, all.length);
  assert.ok(all.every(item => item.name && item.words.startsWith(item.name)));
});

test('a search matches the start of a word and every typed word', () => {
  assert.equal(searchEmoji('run')[0].glyph, '🏃');
  assert.ok(searchEmoji('book').some(item => item.glyph === '📚'));
  assert.ok(searchEmoji('  BOOK ').some(item => item.glyph === '📚'));
  assert.deepEqual(searchEmoji('cold shower').map(item => item.glyph), ['🧊']);
  assert.ok(!searchEmoji('unning').some(item => item.glyph === '🏃'));
  assert.deepEqual(searchEmoji('zzzz'), []);
});
