import { toast } from './util.js';
import { confirm as confirmDialog } from './dialog.js';

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
    const items = Array.isArray(d) ? d : d && Array.isArray(d.items) ? d.items : null;
    if (!items) throw new Error('bad gallery response');
    _images = reset ? items : _images.concat(items);
    _next = Array.isArray(d) ? null : d.next;
    renderGallery();
  } catch {
    if (reset) {
      _images = [];
      renderGallery('could not load creations');
    } else {
      toast('could not load more images. try again.', 'error');
    }
  } finally {
    _loading = false;
  }
}

function renderGallery(msg = '') {
  const grid = document.getElementById('gallery-grid');
  if (!grid) return;

  if (msg) {
    grid.innerHTML = `<div class="page-empty" role="status">${esc(msg)}${msg === 'could not load creations' ? ' <button type="button" class="btn" id="gallery-retry">retry</button>' : ''}</div>`;
    document.getElementById('gallery-retry')?.addEventListener('click', () => loadGallery());
    return;
  }

  if (!_images.length) {
    grid.innerHTML = '<div class="page-empty">no images yet - generate one in Aide or upload one</div>';
    return;
  }

  grid.innerHTML = _images.map(img => {
    const prompt = String(img.prompt || '');
    const label = prompt || 'image';
    const ownedByPhotos = img.owner === 'photos';
    const removeLabel = ownedByPhotos ? 'move to trash' : 'delete permanently';
    return `
    <div class="gallery-item" data-id="${esc(img.id)}">
      <a class="gallery-open" href="${esc(img.url)}" target="_blank" rel="noopener" aria-label="open ${esc(label)}">
        <img src="${esc(img.thumb || img.url)}" alt="" loading="lazy" decoding="async">
      </a>
      <div class="gallery-info">
        ${prompt ? `<div class="gallery-prompt" title="${esc(prompt)}">${esc(prompt.slice(0, 80))}</div>` : ''}
        <button type="button" class="gallery-del act-btn" data-id="${esc(img.id)}" data-owner="${ownedByPhotos ? 'photos' : 'gallery'}" aria-label="${removeLabel} ${esc(label)}">${removeLabel}</button>
      </div>
    </div>`;
  }).join('') + (_next != null ? '<button type="button" class="btn gallery-more" id="gallery-more-btn">load more</button>' : '');

  grid.querySelectorAll('.gallery-del').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const photo = btn.dataset.owner === 'photos';
      const message = photo
        ? 'move this generated image to Photos trash? you can restore it there.'
        : 'delete this uploaded image permanently? it cannot be restored.';
      if (!await confirmDialog(message)) return;
      btn.disabled = true;
      try {
        const endpoint = photo ? '/api/photos/' : '/api/gallery/';
        const r = await fetch(endpoint + encodeURIComponent(btn.dataset.id), { method: 'DELETE' });
        if (!r.ok) throw new Error(`server returned ${r.status}`);
        await loadGallery();
        (document.querySelector('#gallery-grid .gallery-open') || document.getElementById('gallery-upload-btn'))?.focus();
        toast(photo ? 'moved to Photos trash' : 'image deleted', 'success');
      } catch {
        btn.disabled = false;
        toast('could not remove image. try again.', 'error');
      }
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
