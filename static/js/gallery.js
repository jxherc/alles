import { toast } from './util.js';

let _images = [];
let _next = 0;
let _loading = false;
const _PAGE = 48;

export async function loadGallery(reset = true) {
  if (_loading) return;
  _loading = true;
  if (reset) { _images = []; _next = 0; renderGallery('loading…'); }
  try {
    const r = await fetch(`/api/gallery?offset=${_next || 0}&limit=${_PAGE}`);
    if (!r.ok) throw new Error(`server returned ${r.status}`);
    const d = await r.json();
    const items = Array.isArray(d) ? d : (d.items || []);
    if (!Array.isArray(items)) throw new Error('bad gallery response');
    _images = reset ? items : _images.concat(items);
    _next = Array.isArray(d) ? null : d.next;
    renderGallery();
  } catch {
    if (reset) _images = [];
    renderGallery('gallery failed to load');
  } finally {
    _loading = false;
  }
}

function renderGallery(msg = '') {
  const grid = document.getElementById('gallery-grid');
  if (!grid) return;

  if (msg) {
    grid.innerHTML = `<div class="page-empty">${esc(msg)}</div>`;
    return;
  }

  if (!_images.length) {
    grid.innerHTML = '<div class="page-empty">ai gallery empty - upload an image</div>';
    return;
  }

  grid.innerHTML = _images.map(img => `
    <div class="gallery-item" data-id="${img.id}">
      <img src="${img.thumb || img.url}" alt="${esc(img.prompt)}" loading="lazy" decoding="async" data-full="${img.url}">
      <div class="gallery-overlay">
        ${img.prompt ? `<div class="gallery-prompt">${esc(img.prompt.slice(0, 80))}</div>` : ''}
        <button class="gallery-del act-btn" data-id="${img.id}">delete</button>
      </div>
    </div>`).join('') + (_next != null ? '<button class="btn gallery-more" id="gallery-more-btn">load more</button>' : '');

  grid.querySelectorAll('.gallery-item img').forEach(img => {
    img.addEventListener('click', () => {
      window.open(img.dataset.full || img.src, '_blank');
    });
  });

  grid.querySelectorAll('.gallery-del').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      await fetch(`/api/gallery/${btn.dataset.id}`, { method: 'DELETE' });
      await loadGallery();
    });
  });

  document.getElementById('gallery-more-btn')?.addEventListener('click', () => loadGallery(false));
}

let _wired = false;
export function initGalleryUpload() {
  if (_wired) return;
  _wired = true;
  const input = document.getElementById('gallery-file-input');
  const btn   = document.getElementById('gallery-upload-btn');

  btn?.addEventListener('click', () => input?.click());
  document.getElementById('gallery-scan-btn')?.addEventListener('click', async () => {
    try {
      const r = await fetch('/api/gallery/rescan', { method: 'POST' });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast(`scan added ${d.added || 0}`, 'success');
      await loadGallery();
    } catch (e) {
      toast('scan failed: ' + e.message, 'error');
    }
  });

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

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
