import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { filterMemoriesByCategory } from '../../static/js/memory.js';

const mems = [
  { id: '1', category: 'preference', text: 'likes dark mode' },
  { id: '2', category: 'fact', text: 'uses taipei time' },
  { id: '3', category: 'preference', text: 'prefers short answers' },
];

test('filterMemoriesByCategory keeps all category as pass-through', () => {
  assert.deepEqual(filterMemoriesByCategory(mems, 'all'), mems);
});

test('filterMemoriesByCategory returns only the active category', () => {
  assert.deepEqual(
    filterMemoriesByCategory(mems, 'preference').map(m => m.id),
    ['1', '3'],
  );
});

test('empty memory search rerenders the active category, not every memory', () => {
  const src = readFileSync(new URL('../../static/js/memory.js', import.meta.url), 'utf8');
  assert.match(
    src,
    /if \(!q\) \{ renderMemories\(filterMemoriesByCategory\(_memories\)\); return; \}/,
  );
});
