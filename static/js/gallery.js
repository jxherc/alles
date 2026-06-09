import { toast } from './util.js';

let _images = [];

export async function loadGallery() {
  const r = await fetch('/api/gallery');
  _images = await r.json();
  renderGallery();
}

function renderGallery() {
  const grid = document.getElementById('gallery-grid');
  if (!grid) return;

  if (!_images.length) {
    grid.innerHTML = '<div class="page-empty">ai gallery empty - upload an image</div>';
    return;
  }

  grid.innerHTML = _images.map(img => `
    <div class="gallery-item" data-id="${img.id}">
      <img src="${img.url}" alt="${esc(img.prompt)}" loading="lazy">
      <div class="gallery-overlay">
        ${img.prompt ? `<div class="gallery-prompt">${esc(img.prompt.slice(0, 80))}</div>` : ''}
        <button class="gallery-del act-btn" data-id="${img.id}">delete</button>
      </div>
    </div>`).join('');

  grid.querySelectorAll('.gallery-item img').forEach(img => {
    img.addEventListener('click', () => {
      window.open(img.src, '_blank');
    });
  });

  grid.querySelectorAll('.gallery-del').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await fetch(`/api/gallery/${btn.dataset.id}`, { method: 'DELETE' });
      await loadGallery();
    });
  });
}

export function initGalleryUpload() {
  const input = document.getElementById('gallery-file-input');
  const btn   = document.getElementById('gallery-upload-btn');
  if (!btn) return;

  btn.addEventListener('click', () => input?.click());

  input?.addEventListener('change', async () => {
    const file = input.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    const prompt = document.getElementById('gallery-prompt-input')?.value || '';
    fd.append('prompt', prompt);
    try {
      const r = await fetch('/api/gallery/upload', { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      toast('uploaded', 'success');
      if (document.getElementById('gallery-prompt-input'))
        document.getElementById('gallery-prompt-input').value = '';
      await loadGallery();
    } catch (e) {
      toast('upload failed: ' + e.message, 'error');
    }
    input.value = '';
  });
}

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
