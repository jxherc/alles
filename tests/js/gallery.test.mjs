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
  assert.match(grid.innerHTML, /no images yet/);
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
  assert.match(grid.innerHTML, /could not load creations/);
  assert.match(grid.innerHTML, /id="gallery-retry"/);
  assert.doesNotMatch(grid.innerHTML, /gallery-item/);
});

test('loadGallery treats non-array json as an error body', async () => {
  const grid = setup(async () => ({ ok: true, json: async () => ({ detail: 'nope' }) }));
  await loadGallery();
  assert.match(grid.innerHTML, /could not load creations/);
});

test('loadGallery renders both image owners with keyboard-open links and distinct removal', async () => {
  const grid = setup(async () => ({
    ok: true,
    json: async () => ({ items: [
      { id: 'generated', owner: 'photos', url: '/api/photos/original/generated', prompt: 'red <square>' },
      { id: 'upload', owner: 'gallery', url: '/api/gallery/file/upload.png', prompt: 'blue square' },
    ], next: null }),
  }));
  await loadGallery();
  assert.match(grid.innerHTML, /href="\/api\/photos\/original\/generated"/);
  assert.match(grid.innerHTML, /data-owner="photos"[^>]*>move to trash/);
  assert.match(grid.innerHTML, /data-owner="gallery"[^>]*>delete permanently/);
  assert.match(grid.innerHTML, /red &lt;square&gt;/);
  assert.doesNotMatch(grid.innerHTML, /red <square>/);
});
