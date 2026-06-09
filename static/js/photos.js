import { toast } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';
import { populateDropdown } from './dropdown.js';

let _album = '';     // current album filter
let _photos = [];    // flat list (for the lightbox)
let _cur = null;     // photo open in the lightbox

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export async function loadPhotos() {
  await loadAlbums();
  const d = await fetch('/api/photos/list' + (_album ? '?album=' + encodeURIComponent(_album) : ''))
    .then(r => r.json()).catch(() => ({ moments: [] }));
  const grid = $('photos-grid');
  _photos = [];
  if (!d.moments?.length) { grid.innerHTML = '<div class="photos-empty">gallery empty - upload something</div>'; return; }
  let html = '';
  for (const m of d.moments) {
    html += `<div class="photos-moment"><div class="photos-moment-label">${esc(m.label)}</div><div class="photos-moment-grid">`;
    for (const p of m.items) {
      _photos.push(p);
      html += `<div class="photos-cell${p.favorite ? ' fav' : ''}" data-id="${p.id}"><img loading="lazy" src="${p.thumb}" alt=""></div>`;
    }
    html += `</div></div>`;
  }
  grid.innerHTML = html;
  grid.querySelectorAll('.photos-cell').forEach(c => c.addEventListener('click', () => openLightbox(c.dataset.id)));
}

async function loadAlbums() {
  const albums = await fetch('/api/photos/albums').then(r => r.json()).catch(() => []);
  const opts = [{ value: '', label: 'all gallery' },
    ...albums.map(a => ({ value: a.id, label: `${a.name} (${a.count})` }))];
  populateDropdown($('photos-album'), opts, _album);
}

function openLightbox(id) {
  const p = _photos.find(x => x.id === id);
  if (!p) return;
  _cur = p;
  $('photos-lightbox-img').src = p.original;
  $('photos-dl-btn').href = p.original + '?download=1';
  $('photos-fav-btn').textContent = p.favorite ? '♥ favorited' : '♡ favorite';
  const ex = p.exif || {};
  const dims = (p.width && p.height) ? `${p.width} × ${p.height}` : '';
  const rows = [['taken', p.taken_at ? new Date(p.taken_at).toLocaleString() : ''], ['size', dims], ...Object.entries(ex)];
  $('photos-exif').innerHTML = rows.filter(r => r[1]).map(([k, v]) =>
    `<div class="photos-exif-row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('');
  $('photos-lightbox').style.display = 'flex';
}

function closeLightbox() { $('photos-lightbox').style.display = 'none'; _cur = null; }

let _inited = false;
export function initPhotos() {
  if (_inited) return;
  _inited = true;
  $('photos-album')?.addEventListener('change', e => { _album = e.target.value; loadPhotos(); });
  $('photos-upload-btn')?.addEventListener('click', () => $('photos-upload-input')?.click());
  $('photos-upload-input')?.addEventListener('change', e => { uploadPhotos(e.target.files); e.target.value = ''; });
  $('photos-newalbum-btn')?.addEventListener('click', newAlbum);
  $('photos-close-btn')?.addEventListener('click', closeLightbox);
  $('photos-lightbox')?.addEventListener('click', e => { if (e.target === $('photos-lightbox')) closeLightbox(); });
  $('photos-fav-btn')?.addEventListener('click', async () => {
    if (!_cur) return;
    const fav = !_cur.favorite;
    await fetch('/api/photos/' + _cur.id, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ favorite: fav }) });
    _cur.favorite = fav;
    $('photos-fav-btn').textContent = fav ? '♥ favorited' : '♡ favorite';
    document.querySelector(`.photos-cell[data-id="${_cur.id}"]`)?.classList.toggle('fav', fav);
  });
  $('photos-del-btn')?.addEventListener('click', async () => {
    if (!_cur || !await dlgConfirm('delete this image?')) return;
    await fetch('/api/photos/' + _cur.id, { method: 'DELETE' });
    closeLightbox(); loadPhotos();
  });
}

async function uploadPhotos(files) {
  let n = 0;
  for (const f of files) {
    const fd = new FormData();
    if (_album) fd.append('album_id', _album);
    fd.append('file', f);
    const r = await fetch('/api/photos/upload', { method: 'POST', body: fd });
    if (r.ok) n++; else toast('upload failed: ' + f.name, 'error');
  }
  if (n) { toast(`added ${n} image${n > 1 ? 's' : ''}`, 'success'); loadPhotos(); }
}

async function newAlbum() {
  const name = await dlgPrompt('album name:');
  if (!name?.trim()) return;
  await fetch('/api/photos/albums', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: name.trim() }) });
  loadAlbums();
}
