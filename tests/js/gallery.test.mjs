import assert from 'node:assert/strict';
import { test } from 'node:test';

import { loadGallery } from '../../static/js/gallery.js';

function setup(fetcher) {
  const grid = {
    innerHTML: '',
    querySelectorAll() { return []; },
  };
  globalThis.document = {
    getElementById(id) { return id === 'gallery-grid' ? grid : null; },
  };
  globalThis.fetch = fetcher;
  return grid;
}

test('loadGallery renders empty state for an empty list', async () => {
  const grid = setup(async () => ({ ok: true, json: async () => [] }));
  await loadGallery();
  assert.match(grid.innerHTML, /ai gallery empty/);
});

test('loadGallery clears stale images on fetch failure', async () => {
  const grid = setup(async () => ({
    ok: true,
    json: async () => [{ id: 'one', url: '/img.png', prompt: 'hi' }],
  }));
  await loadGallery();
  assert.match(grid.innerHTML, /gallery-item/);

  globalThis.fetch = async () => ({ ok: false, status: 500 });
  await loadGallery();
  assert.match(grid.innerHTML, /gallery failed to load/);
  assert.doesNotMatch(grid.innerHTML, /gallery-item/);
});

test('loadGallery treats non-array json as an error body', async () => {
  const grid = setup(async () => ({ ok: true, json: async () => ({ detail: 'nope' }) }));
  await loadGallery();
  assert.match(grid.innerHTML, /gallery failed to load/);
});
