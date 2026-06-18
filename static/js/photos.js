import { toast } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';
import { populateDropdown, getDropdownValue } from './dropdown.js';

let _album = '';     // current album filter
let _photos = [];    // flat list (for the lightbox)
let _cur = null;     // photo open in the lightbox

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// fill the image-model picker from the configured endpoints' image-gen models.
// value = "endpointId::model" so we hit the right provider; "" = endpoint default.
function _fillImageModels() {
  const el = $('photos-model');
  if (!el) return;
  const eps = window._endpoints || [];
  const opts = [{ value: '', label: 'default model' }];
  for (const ep of eps) {
    for (const m of (ep.image_models || []))
      opts.push({ value: `${ep.id}::${m}`, label: eps.length > 1 ? `${m} · ${ep.name}` : m });
  }
  const saved = localStorage.getItem('alles-image-model') || '';
  populateDropdown(el, opts, opts.some(o => o.value === saved) ? saved : '');
}

export async function loadPhotos() {
  _fillImageModels();
  await loadAlbums();
  const url = _album === '__fav__'
    ? '/api/photos/list?favorites=true'
    : '/api/photos/list' + (_album ? '?album=' + encodeURIComponent(_album) : '');
  const d = await fetch(url).then(r => r.json()).catch(() => ({ moments: [] }));
  _renderMoments(d, _album === '__fav__' ? 'no favorites yet' : 'gallery empty - upload something');
}

async function searchPhotos(q) {
  const d = await fetch('/api/photos/search?q=' + encodeURIComponent(q))
    .then(r => r.json()).catch(() => ({ moments: [] }));
  _renderMoments(d, 'no photos match');
}

function _renderMoments(d, emptyMsg) {
  const grid = $('photos-grid');
  _photos = [];
  if (!d.moments?.length) { grid.innerHTML = `<div class="photos-empty">${emptyMsg}</div>`; return; }
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
  const opts = [{ value: '', label: 'all gallery' }, { value: '__fav__', label: '★ favorites' },
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
  const ex = { ...(p.exif || {}) };
  const lat = ex.lat, lon = ex.lon;
  delete ex.lat; delete ex.lon;   // shown as a map link, not raw rows
  const dims = (p.width && p.height) ? `${p.width} × ${p.height}` : '';
  const rows = [['taken', p.taken_at ? new Date(p.taken_at).toLocaleString() : ''], ['size', dims], ...Object.entries(ex)];
  let html = rows.filter(r => r[1]).map(([k, v]) =>
    `<div class="photos-exif-row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('');
  if (lat != null && lon != null) {
    html += `<div class="photos-exif-row"><span>location</span><span><a class="photos-map-link" href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=15/${lat}/${lon}" target="_blank" rel="noopener">📍 ${lat.toFixed ? lat.toFixed(4) : lat}, ${lon.toFixed ? lon.toFixed(4) : lon}</a></span></div>`;
  }
  $('photos-exif').innerHTML = html;
  $('photos-lightbox').style.display = 'flex';
}

function closeLightbox() { $('photos-lightbox').style.display = 'none'; _cur = null; }

let _inited = false;
export function initPhotos() {
  if (_inited) return;
  _inited = true;
  $('photos-album')?.addEventListener('change', e => { _album = e.target.value; loadPhotos(); });
  $('photos-model')?.addEventListener('change', () => {
    localStorage.setItem('alles-image-model', getDropdownValue($('photos-model')) || '');
  });
  _fillImageModels();
  $('photos-gen-btn')?.addEventListener('click', async () => {
    const p = await dlgPrompt('describe the image to generate:');
    if (!p) return;
    const sel = getDropdownValue($('photos-model')) || '';
    const [endpoint_id, model] = sel.includes('::') ? sel.split('::') : ['', sel];
    toast('generating… (this can take a bit)');
    try {
      const r = await fetch('/api/images/generate', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ prompt: p, model: model || '', endpoint_id: endpoint_id || '' }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'generation failed');
      toast(`generated ${d.images.length} image${d.images.length === 1 ? '' : 's'}`, 'success');
      loadPhotos();
    } catch (e) { toast(e.message || 'generation failed', 'error'); }
  });
  const psearch = $('photos-search');
  let _pt;
  psearch?.addEventListener('input', () => {
    clearTimeout(_pt);
    const q = psearch.value.trim();
    if (!q) { loadPhotos(); return; }
    _pt = setTimeout(() => searchPhotos(q), 300);
  });
  $('photos-upload-btn')?.addEventListener('click', () => $('photos-upload-input')?.click());
  $('photos-upload-input')?.addEventListener('change', e => { uploadPhotos(e.target.files); e.target.value = ''; });
  $('photos-newalbum-btn')?.addEventListener('click', newAlbum);
  $('photos-close-btn')?.addEventListener('click', closeLightbox);
  $('photos-edit-btn')?.addEventListener('click', async () => {
    if (!_cur) return;
    const { openEditor } = await import('./imgeditor.js');
    openEditor(_cur.original, {
      name: _cur.original_name || 'photo.png',
      onSaved: () => { closeLightbox(); loadPhotos(); },
    });
  });
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
