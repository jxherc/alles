import { toast } from './util.js';
import { confirm as confirmDialog } from './dialog.js';
import { t, tp } from './i18n.js';

let _images = [];
let _next = 0;
let _loading = false;
const _PAGE = 48;

export async function loadGallery(reset = true) {
  if (_loading) return;
  _loading = true;
  if (reset) { _images = []; _next = 0; renderGallery(t('gallery.loading')); }
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
      renderGallery(t('gallery.load_failed'), true);
    } else {
      toast(t('gallery.load_more_failed'), 'error');
    }
  } finally {
    _loading = false;
  }
}

function renderGallery(msg = '', retry = false) {
  const grid = document.getElementById('gallery-grid');
  if (!grid) return;

  if (msg) {
    grid.innerHTML = `<div class="page-empty" role="status">${esc(msg)}${retry ? ` <button type="button" class="btn" id="gallery-retry">${esc(t('common.retry'))}</button>` : ''}</div>`;
    document.getElementById('gallery-retry')?.addEventListener('click', () => loadGallery());
    return;
  }

  if (!_images.length) {
    grid.innerHTML = `<div class="page-empty">${esc(t('gallery.empty'))}</div>`;
    return;
  }

  grid.innerHTML = _images.map(img => {
    const prompt = String(img.prompt || '');
    const label = prompt || t('gallery.image');
    const ownedByPhotos = img.owner === 'photos';
    const removeLabel = ownedByPhotos ? t('gallery.move_to_trash') : t('gallery.delete_permanently');
    const removeAria = ownedByPhotos
      ? t('gallery.move_to_trash_named', { name: label })
      : t('gallery.delete_permanently_named', { name: label });
    return `
    <div class="gallery-item" data-id="${esc(img.id)}">
      <a class="gallery-open" href="${esc(img.url)}" target="_blank" rel="noopener" aria-label="${esc(t('gallery.open_named', { name: label }))}">
        <img src="${esc(img.thumb || img.url)}" alt="" loading="lazy" decoding="async">
      </a>
      <div class="gallery-info">
        ${prompt ? `<div class="gallery-prompt" title="${esc(prompt)}">${esc(prompt.slice(0, 80))}</div>` : ''}
        <button type="button" class="gallery-del act-btn" data-id="${esc(img.id)}" data-owner="${ownedByPhotos ? 'photos' : 'gallery'}" aria-label="${esc(removeAria)}">${esc(removeLabel)}</button>
      </div>
    </div>`;
  }).join('') + (_next != null ? `<button type="button" class="btn gallery-more" id="gallery-more-btn">${esc(t('gallery.load_more'))}</button>` : '');

  grid.querySelectorAll('.gallery-del').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const photo = btn.dataset.owner === 'photos';
      const message = photo
        ? t('gallery.trash_confirm')
        : t('gallery.delete_confirm');
      if (!await confirmDialog(message)) return;
      btn.disabled = true;
      try {
        const endpoint = photo ? '/api/photos/' : '/api/gallery/';
        const r = await fetch(endpoint + encodeURIComponent(btn.dataset.id), { method: 'DELETE' });
        if (!r.ok) throw new Error(`server returned ${r.status}`);
        await loadGallery();
        (document.querySelector('#gallery-grid .gallery-open') || document.getElementById('gallery-upload-btn'))?.focus();
        toast(photo ? t('gallery.moved_to_trash') : t('gallery.image_deleted'), 'success');
      } catch {
        btn.disabled = false;
        toast(t('gallery.remove_failed'), 'error');
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
      toast(tp('gallery.scan_added', d.added || 0), 'success');
      await loadGallery();
    } catch (e) {
      toast(t('gallery.scan_failed', { error: e.message }), 'error');
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
      toast(t('gallery.uploaded'), 'success');
      const promptInput = document.getElementById('gallery-prompt-input');
      if (promptInput?.value === prompt) promptInput.value = '';
      await loadGallery();
    } catch (e) {
      toast(t('gallery.upload_failed', { error: e.message }), 'error');
    }
    input.value = '';
  });
}

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
