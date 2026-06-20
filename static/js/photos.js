import { toast } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';
import { populateDropdown, getDropdownValue } from './dropdown.js';

let _album = '';     // current album filter
let _photos = [];    // flat list (for the lightbox)
let _cur = null;     // photo open in the lightbox
let _vaultTok = null;  // vault unlock token for the hidden/locked album (7a)
let _leafletMap = null;  // live Leaflet instance for the map view (7b)

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe
const _setFavBtn = fav => { const b = $('photos-fav-btn'); if (b) b.innerHTML = fav ? `${_si('heart-fill')} favorited` : `${_si('heart')} favorite`; };

// one grid cell — videos (7c) get a <video> poster + a play badge instead of an <img>
function _cellHtml(p) {
  const inner = p.is_video
    ? `<video class="photos-cellvid" src="${p.original}#t=0.1" preload="metadata" muted playsinline></video><span class="photos-vbadge">${_si('play')}</span>`
    : `<img loading="lazy" src="${p.thumb}" alt="">`;
  const favBadge = p.favorite ? `<span class="photos-fav-badge">${_si('heart-fill')}</span>` : '';
  return `<div class="photos-cell${p.favorite ? ' fav' : ''}${p.is_video ? ' video' : ''}" data-id="${p.id}">${inner}${favBadge}</div>`;
}

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
  if (_album === '__hidden__') { await loadHidden(); return; }
  if (_album === '__map__') { await loadMap(); return; }
  if (_album === '__memories__') { await loadMemories(); return; }
  const url = _album === '__fav__'
    ? '/api/photos/list?favorites=true'
    : '/api/photos/list' + (_album ? '?album=' + encodeURIComponent(_album) : '');
  const d = await fetch(url).then(r => r.json()).catch(() => ({ moments: [] }));
  _renderMoments(d, _album === '__fav__' ? 'no favorites yet' : 'gallery empty - upload something');
}

// the hidden/locked album — needs a vault unlock token; prompt for the master password if locked
async function loadHidden() {
  const grid = $('photos-grid');
  let r = await fetch('/api/photos/hidden', { headers: _vaultTok ? { 'X-Vault-Token': _vaultTok } : {} });
  if (r.status === 403) {
    const pw = await dlgPrompt('vault master password to view the hidden album:');
    if (!pw) { grid.innerHTML = `<div class="photos-empty">${_si('lock')} hidden album is locked</div>`; return; }
    try {
      const u = await fetch('/api/vault/unlock', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ password: pw }),
      });
      if (!u.ok) throw 0;
      _vaultTok = (await u.json()).token;
    } catch { toast('unlock failed', 'error'); grid.innerHTML = `<div class="photos-empty">${_si('lock')} unlock failed</div>`; return; }
    r = await fetch('/api/photos/hidden', { headers: { 'X-Vault-Token': _vaultTok } });
  }
  if (!r.ok) { grid.innerHTML = `<div class="photos-empty">${_si('lock')} hidden album is locked</div>`; return; }
  _renderMoments(await r.json(), 'no hidden photos');
}

// lazy-load the vendored Leaflet (css + js) the first time the map is opened
function ensureLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!document.getElementById('leaflet-css')) {
    const l = document.createElement('link');
    l.id = 'leaflet-css'; l.rel = 'stylesheet'; l.href = '/static/vendor/leaflet/leaflet.css';
    document.head.appendChild(l);
  }
  return new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = '/static/vendor/leaflet/leaflet.js';
    s.onload = () => res(window.L);
    s.onerror = rej;
    document.head.appendChild(s);
  });
}

function _killMap() { if (_leafletMap) { _leafletMap.remove(); _leafletMap = null; } }

// places map (7b) — OSM tiles + a marker per located photo; click → lightbox
async function loadMap() {
  _killMap();
  const grid = $('photos-grid');
  grid.innerHTML = '<div id="photos-mapview" class="photos-mapview"></div>';
  let L;
  try { L = await ensureLeaflet(); }
  catch { grid.innerHTML = '<div class="photos-empty">map failed to load</div>'; return; }
  const d = await fetch('/api/photos/map').then(r => r.json()).catch(() => ({ points: [] }));
  _photos = d.points || [];
  const map = L.map('photos-mapview', { attributionControl: true });
  _leafletMap = map;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '© OpenStreetMap',
  }).addTo(map);
  const pts = _photos.filter(p => p.lat != null && p.lon != null);
  if (!pts.length) { map.setView([20, 0], 2); setTimeout(() => map.invalidateSize(), 60); return; }
  const bounds = [];
  for (const p of pts) {
    const m = L.circleMarker([p.lat, p.lon],
      { radius: 7, color: '#818cf8', fillColor: '#818cf8', fillOpacity: 0.8, weight: 2 });
    m.on('click', () => openLightbox(p.id));
    m.addTo(map);
    bounds.push([p.lat, p.lon]);
  }
  map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
  setTimeout(() => map.invalidateSize(), 60);
}

// memories (7b) — "on this day" across prior years, with a make-collage button per group
async function loadMemories() {
  _killMap();
  const grid = $('photos-grid');
  const d = await fetch('/api/photos/memories').then(r => r.json()).catch(() => ({ groups: [] }));
  _photos = [];
  if (!d.groups?.length) {
    grid.innerHTML = '<div class="photos-empty">no memories for today — check back another day</div>';
    return;
  }
  let html = '';
  for (const g of d.groups) {
    const lbl = g.years_ago === 1 ? '1 year ago' : `${g.years_ago} years ago`;
    html += `<div class="photos-moment"><div class="photos-moment-label">${esc(lbl)} · ${esc(g.date)} `
      + `<button class="btn photos-collage-btn" data-ids="${g.items.map(i => i.id).join(',')}" `
      + `style="font-size:0.62rem;margin-left:6px">${_si('sparkles')} make collage</button></div><div class="photos-moment-grid">`;
    for (const p of g.items) {
      _photos.push(p);
      html += _cellHtml(p);
    }
    html += `</div></div>`;
  }
  grid.innerHTML = html;
  grid.querySelectorAll('.photos-cell').forEach(c => c.addEventListener('click', () => openLightbox(c.dataset.id)));
  grid.querySelectorAll('.photos-collage-btn').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    const ids = b.dataset.ids.split(',').filter(Boolean);
    if (!ids.length) return;
    toast('building collage…');
    try {
      const r = await fetch('/api/photos/collage', {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ids }),
      });
      if (!r.ok) throw 0;
      toast('collage saved to your gallery', 'success');
    } catch { toast('collage failed', 'error'); }
  }));
}

async function searchPhotos(q) {
  const d = await fetch('/api/photos/search?q=' + encodeURIComponent(q))
    .then(r => r.json()).catch(() => ({ moments: [] }));
  _renderMoments(d, 'no photos match');
}

function _renderMoments(d, emptyMsg) {
  _killMap();
  const grid = $('photos-grid');
  _photos = [];
  if (!d.moments?.length) { grid.innerHTML = `<div class="photos-empty">${emptyMsg}</div>`; return; }
  let html = '';
  for (const m of d.moments) {
    html += `<div class="photos-moment"><div class="photos-moment-label">${esc(m.label)}</div><div class="photos-moment-grid">`;
    for (const p of m.items) {
      _photos.push(p);
      html += _cellHtml(p);
    }
    html += `</div></div>`;
  }
  grid.innerHTML = html;
  grid.querySelectorAll('.photos-cell').forEach(c => c.addEventListener('click', () => openLightbox(c.dataset.id)));
}

async function loadAlbums() {
  const albums = await fetch('/api/photos/albums').then(r => r.json()).catch(() => []);
  const opts = [{ value: '', label: 'all gallery' }, { value: '__fav__', label: 'favorites' },
    { value: '__hidden__', label: 'hidden' },
    { value: '__map__', label: 'map' },
    { value: '__memories__', label: 'memories' },
    ...albums.map(a => ({ value: a.id, label: `${a.name} (${a.count})` }))];
  const el = $('photos-album');
  // per-option icons via the dropdown's icon map (replaces the old star/lock/map/sparkles label emoji)
  el._iconHtml = { __fav__: _si('star'), __hidden__: _si('lock'), __map__: _si('map-pin'), __memories__: _si('sparkles') };
  populateDropdown(el, opts, _album);
}

function openLightbox(id) {
  const p = _photos.find(x => x.id === id);
  if (!p) return;
  _cur = p;
  const imgEl = $('photos-lightbox-img'), vidEl = $('photos-lightbox-video');
  if (p.is_video) {
    imgEl.style.display = 'none'; imgEl.src = '';
    if (vidEl) { vidEl.style.display = ''; vidEl.src = p.original; }
  } else {
    if (vidEl) { vidEl.pause?.(); vidEl.src = ''; vidEl.style.display = 'none'; }
    imgEl.style.display = ''; imgEl.src = p.original;
  }
  if ($('photos-edit-btn')) {
    $('photos-edit-btn').style.display = p.is_video ? 'none' : '';
    $('photos-edit-btn').innerHTML = `${_si('edit')} edit`;
  }
  $('photos-dl-btn').href = p.original + '?download=1';
  $('photos-dl-btn').innerHTML = `${_si('download')} download`;
  if ($('photos-del-btn')) $('photos-del-btn').innerHTML = `${_si('trash')} delete`;
  if ($('photos-close-btn')) $('photos-close-btn').innerHTML = `${_si('close')} close`;
  _setFavBtn(p.favorite);
  if ($('photos-caption')) $('photos-caption').value = p.caption || '';
  if ($('photos-keywords')) $('photos-keywords').value = (p.keywords || []).join(', ');
  const hb = $('photos-hide-btn');
  if (hb) hb.innerHTML = p.hidden ? `${_si('eye')} unhide` : `${_si('eye-off')} hide`;
  const ex = { ...(p.exif || {}) };
  const lat = ex.lat, lon = ex.lon;
  delete ex.lat; delete ex.lon;   // shown as a map link, not raw rows
  const dims = (p.width && p.height) ? `${p.width} × ${p.height}` : '';
  const rows = [['taken', p.taken_at ? new Date(p.taken_at).toLocaleString() : ''], ['size', dims], ...Object.entries(ex)];
  let html = rows.filter(r => r[1]).map(([k, v]) =>
    `<div class="photos-exif-row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('');
  if (lat != null && lon != null) {
    html += `<div class="photos-exif-row"><span>location</span><span><a class="photos-map-link" href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=15/${lat}/${lon}" target="_blank" rel="noopener">${_si('map-pin')} ${lat.toFixed ? lat.toFixed(4) : lat}, ${lon.toFixed ? lon.toFixed(4) : lon}</a></span></div>`;
  }
  $('photos-exif').innerHTML = html;
  $('photos-lightbox').style.display = 'flex';
}

function closeLightbox() {
  const v = $('photos-lightbox-video');
  if (v) { v.pause?.(); v.src = ''; }
  $('photos-lightbox').style.display = 'none';
  _cur = null;
}

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
  $('photos-share-album-btn')?.addEventListener('click', shareAlbum);
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
    _setFavBtn(fav);
    const cell = document.querySelector(`.photos-cell[data-id="${_cur.id}"]`);
    if (cell) {
      cell.classList.toggle('fav', fav);
      cell.querySelector('.photos-fav-badge')?.remove();
      if (fav) cell.insertAdjacentHTML('beforeend', `<span class="photos-fav-badge">${_si('heart-fill')}</span>`);
    }
  });
  $('photos-del-btn')?.addEventListener('click', async () => {
    if (!_cur || !await dlgConfirm('delete this image?')) return;
    await fetch('/api/photos/' + _cur.id, { method: 'DELETE' });
    closeLightbox(); loadPhotos();
  });
  $('photos-meta-save')?.addEventListener('click', async () => {
    if (!_cur) return;
    const caption = $('photos-caption').value;
    const keywords = $('photos-keywords').value.split(',').map(s => s.trim()).filter(Boolean);
    try {
      const r = await fetch('/api/photos/' + _cur.id, {
        method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ caption, keywords }),
      });
      const d = await r.json();
      _cur.caption = d.caption; _cur.keywords = d.keywords;
      const p = _photos.find(x => x.id === _cur.id); if (p) { p.caption = d.caption; p.keywords = d.keywords; }
      toast('saved', '');
    } catch { toast('save failed', 'error'); }
  });
  $('photos-hide-btn')?.addEventListener('click', async () => {
    if (!_cur) return;
    const hide = !_cur.hidden;
    await fetch('/api/photos/' + _cur.id, {
      method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ hidden: hide }),
    });
    _cur.hidden = hide;
    closeLightbox(); loadPhotos();
  });
  $('photos-trash-btn')?.addEventListener('click', openPhotoTrash);
}

async function openPhotoTrash() {
  let items;
  try { items = await fetch('/api/photos/trash').then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  const grid = $('photos-grid');
  let html = '<div class="photos-moment"><div class="photos-moment-label">'
    + `<a href="#" id="photos-trash-back" class="photos-trash-back" style="color:var(--accent)">${_si('chevron-left')} gallery</a> · recently deleted</div>`
    + '<div class="photos-moment-grid">';
  if (!items.length) html += '<div class="photos-empty" style="grid-column:1/-1">trash is empty</div>';
  for (const p of items) {
    html += `<div class="photos-cell" data-id="${p.id}" style="position:relative">`
      + `<img loading="lazy" src="${p.thumb}" alt="">`
      + `<button class="btn photos-restore" data-id="${p.id}" style="position:absolute;bottom:4px;left:4px;font-size:0.62rem">${_si('undo')} restore</button></div>`;
  }
  html += '</div></div>';
  grid.innerHTML = html;
  $('photos-trash-back')?.addEventListener('click', e => { e.preventDefault(); loadPhotos(); });
  grid.querySelectorAll('.photos-restore').forEach(b => b.addEventListener('click', async e => {
    e.stopPropagation();
    try { await fetch('/api/photos/' + b.dataset.id + '/restore', { method: 'POST' }); toast('restored', ''); }
    catch { toast('restore failed', 'error'); }
    openPhotoTrash();
  }));
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

// share the currently-selected album as a read-only /s/{token} link (7c)
async function shareAlbum() {
  if (!_album || _album.startsWith('__')) { toast('select an album to share first', ''); return; }
  try {
    const r = await fetch('/api/share', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kind: 'album', ref: _album }),
    });
    const d = await r.json();
    if (!r.ok || !d.url) throw 0;
    const url = location.origin + d.url;
    try { await navigator.clipboard.writeText(url); toast('album link copied', 'success'); }
    catch { toast(url, ''); }
  } catch { toast('share failed', 'error'); }
}

async function newAlbum() {
  const name = await dlgPrompt('album name:');
  if (!name?.trim()) return;
  await fetch('/api/photos/albums', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: name.trim() }) });
  loadAlbums();
}
