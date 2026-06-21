// unit tests for the command-palette fuzzy matcher (static/js/palette.js).
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { filterCommands, fuzzyMatch } from '../../static/js/palette.js';

test('fuzzyMatch returns -1 when chars are not a subsequence', () => {
  assert.equal(fuzzyMatch('books', 'xyz'), -1);
  assert.equal(fuzzyMatch('books', 'bookss'), -1); // too many chars
});

test('fuzzyMatch matches a subsequence (case-insensitive)', () => {
  assert.ok(fuzzyMatch('Books', 'bk') >= 0);
  assert.ok(fuzzyMatch('health log', 'hl') >= 0);
});

test('empty query matches everything with a neutral score', () => {
  assert.ok(fuzzyMatch('anything', '') >= 0);
});

test('a contiguous prefix scores higher than a scattered match', () => {
  assert.ok(fuzzyMatch('books', 'boo') > fuzzyMatch('notebook', 'boo'));
});

test('word-start match scores higher than mid-word', () => {
  // "lw" hits the start of both words in "log weight" vs buried in "flowery"
  assert.ok(fuzzyMatch('log weight', 'lw') > fuzzyMatch('flowery', 'lw'));
});

const CMDS = [
  { id: 'books', label: 'books', hint: 'reading list' },
  { id: 'health', label: 'health', hint: 'weight, sleep' },
  { id: 'habits', label: 'habits', hint: 'streaks' },
  { id: 'newbook', label: 'add a book', hint: 'books' },
];

test('filterCommands returns everything for empty query (original order)', () => {
  const r = filterCommands(CMDS, '');
  assert.equal(r.length, 4);
  assert.equal(r[0].id, 'books');
});

test('filterCommands drops non-matches and ranks best first', () => {
  const r = filterCommands(CMDS, 'book');
  const ids = r.map(c => c.id);
  assert.ok(ids.includes('books'));
  assert.ok(ids.includes('newbook'));
  assert.ok(!ids.includes('health'));
  assert.equal(r[0].id, 'books'); // exact-prefix label beats "add a book"
});

test('filterCommands also matches against the hint', () => {
  const r = filterCommands(CMDS, 'sleep');
  assert.equal(r.length, 1);
  assert.equal(r[0].id, 'health');
});
