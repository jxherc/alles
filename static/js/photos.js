import { toast } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';

let _view = '';      // current view: '' | __fav__ | __archive__ | __hidden__ | __map__ | __memories__ | __trash__ | <albumId>
let _photos = [];    // flat list (for the lightbox)
let _cur = null;     // photo open in the lightbox
let _albums = [];    // album list cache (for the sidebar)
let _vaultTok = null;  // vault unlock token for the hidden/locked album (7a)
let _leafletMap = null;  // live Leaflet instance for the map view (7b)
let _repaint = null;   // re-run the current justified layout on resize; null for map/trash
const _sel = new Set();  // selected photo ids (multi-select)
let _anchor = null;      // last-clicked id, for shift-range select
let _curIdx = -1;        // index of _cur within _lbPhotos, for prev/next stepping
let _lbPhotos = [];      // the set the lightbox steps through (timeline, or a stack's members)
let _drawerOpen = false; // info drawer toggle (remembered across photos)
const _filters = { type: '', camera: '', from: '', to: '' };  // structured timeline filters (phase 5)
let _facetsLoaded = false;
let _smart = false;       // smart (CLIP) search toggle (phase 7b)
let _clipAvail = false;
let _facesAvail = false;  // face recognition set up? gates the People view (phase 7a)
let _scrubDrag = false;  // date scrubber drag state
let _loadedGroups = [];  // accumulated date groups for the paged list view (phase 4)
let _nextOffset = null;  // next page offset, or null when fully loaded / on a non-paged view
let _loadingMore = false;
const _PAGE = 120;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe
const _setFavBtn = fav => { const b = $('photos-fav-btn'); if (b) b.innerHTML = fav ? `${_si('heart-fill')} favorited` : `${_si('heart')} favorite`; };

// justified (flickr-style) layout — pack a date bucket's photos into rows that fill the width,
// aspect ratios preserved, no square cropping. run per bucket so a date header never sits mid-row.
function _justify(items, containerW, targetH, gap) {
  const rows = [];
  let row = [], arSum = 0;
  const flush = stretch => {
    if (!row.length) return;
    const avail = containerW - gap * (row.length - 1);
    const h = stretch ? avail / arSum : targetH;
    rows.push(row.map(r => ({ it: r.it, w: Math.max(1, Math.round(r.ar * h)), h: Math.round(h) })));
    row = []; arSum = 0;
  };
  for (const it of items) {
    let ar = it.aspect_ratio || ((it.width && it.height) ? it.width / it.height : 1);
    if (!isFinite(ar) || ar <= 0) ar = 1;
    ar = Math.min(Math.max(ar, 0.45), 3);   // clamp wild panoramas/strips so one shot can't eat a whole row
    row.push({ it, ar }); arSum += ar;
    if (arSum * targetH + gap * (row.length - 1) >= containerW) flush(true);
  }
  flush(false);   // leftover row sits at target height, left-aligned (ragged edge, like google/immich)
  return rows;
}

// one grid cell — videos (7c) get a <video> poster + a play badge instead of an <img>.
// the cell's background is a tiny base64 preview (phase 4) so it shows a blur-up while the thumb loads.
function _cellHtml(p, w, h) {
  const bg = p.preview ? `;background-image:url(${p.preview})` : '';
  const dim = (w && h) ? ` style="width:${w}px;height:${h}px${bg}"` : (bg ? ` style="${bg.slice(1)}"` : '');
  const inner = p.is_video
    ? `<video class="photos-cellvid" src="${p.original}#t=0.1" preload="metadata" muted playsinline></video><span class="photos-vbadge">${_si('play')}</span>`
    : `<img class="photos-thumb" loading="lazy" src="${p.thumb}" alt="" onload="this.classList.add('loaded')">`;
  const favBadge = p.favorite ? `<span class="photos-fav-badge">${_si('heart-fill')}</span>` : '';
  const stackBadge = (p.stack_count > 1) ? `<span class="photos-stack-badge">${_si('copy')} ${p.stack_count}</span>` : '';
  const sel = _sel.has(p.id) ? ' sel' : '';
  return `<div class="photos-cell${p.favorite ? ' fav' : ''}${p.is_video ? ' video' : ''}${sel}" data-id="${p.id}"${dim}>`
    + `<button class="photos-check" data-id="${p.id}" aria-label="select">${_si('check')}</button>${inner}${favBadge}${stackBadge}</div>`;
}

// paint a set of {label, items} buckets as sticky-header justified rows; remembers itself for resize
function _paintGroups(groups, emptyMsg) {
  _killMap();
  const grid = $('photos-grid');
  _photos = [];
  if (!groups.length) { grid.innerHTML = `<div class="photos-empty">${emptyMsg}</div>`; _repaint = null; return; }
  const cw = grid.clientWidth || grid.offsetWidth || 800;
  const targetH = cw < 560 ? 116 : (cw < 900 ? 150 : 184);
  let html = '';
  for (const g of groups) {
    html += `<div class="photos-moment"><div class="photos-moment-label">${esc(g.label)}</div><div class="photos-rows">`;
    for (const r of _justify(g.items, cw, targetH, 3)) {
      html += '<div class="photos-row">';
      for (const c of r) { _photos.push(c.it); html += _cellHtml(c.it, c.w, c.h); }
      html += '</div>';
    }
    html += '</div></div>';
  }
  grid.innerHTML = html;
  grid.querySelectorAll('.photos-cell').forEach(c => {
    const id = c.dataset.id;
    c.querySelector('.photos-check')?.addEventListener('click', e => { e.stopPropagation(); _toggleSel(id, e.shiftKey); });
    c.addEventListener('click', e => {
      if (_sel.size > 0) { e.preventDefault(); _toggleSel(id, e.shiftKey); return; }   // select mode → toggle
      const p = _photos.find(x => x.id === id);
      if (p && p.stack_count > 1) _openStack(id);   // a stack cover → step through its members
      else openLightbox(id);
    });
  });
  _syncSelUI();
  _scrubThumb();
  _repaint = () => _paintGroups(groups, emptyMsg);
}

// ── multi-select ──
function _toggleSel(id, shift) {
  if (shift && _anchor) {
    const order = _photos.map(p => p.id);
    let a = order.indexOf(_anchor), b = order.indexOf(id);
    if (a > -1 && b > -1) {
      if (a > b) [a, b] = [b, a];
      for (let i = a; i <= b; i++) _sel.add(order[i]);   // shift = select the whole contiguous range
    }
  } else {
    if (_sel.has(id)) _sel.delete(id); else _sel.add(id);
    _anchor = id;
  }
  _syncSelUI();
}

function _clearSel() { _sel.clear(); _anchor = null; _syncSelUI(); }

function _syncSelUI() {
  document.querySelectorAll('#photos-grid .photos-cell').forEach(c => c.classList.toggle('sel', _sel.has(c.dataset.id)));
  const n = _sel.size;
  $('photos-view')?.classList.toggle('selecting', n > 0);
  const cnt = $('photos-sel-count'); if (cnt) cnt.textContent = `${n} selected`;
  const ab = $('photos-sel-archive'); if (ab) ab.innerHTML = `${_si('archive')} ${_view === '__archive__' ? 'unarchive' : 'archive'}`;
  const stk = $('photos-sel-stack');
  if (stk) {
    const one = n === 1 ? _photos.find(p => _sel.has(p.id)) : null;
    const isStack = !!(one && one.stack_count > 1);
    stk.style.display = (n >= 2 || isStack) ? '' : 'none';   // stacking one non-stack is a no-op
    stk.innerHTML = `${_si('copy')} ${isStack ? 'unstack' : 'stack'}`;
  }
}

async function _batch(action, extra = {}) {
  const ids = [..._sel];
  if (!ids.length) return;
  try {
    const r = await fetch('/api/photos/batch', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ids, action, ...extra }),
    });
    if (!r.ok) throw 0;
    const d = await r.json();
    toast(`${d.count} updated`, 'success');
  } catch { toast('action failed', 'error'); return; }
  _clearSel();
  loadPhotos();
}

// small album picker for the "add to album" bulk action
let _albMenuEl = null, _albMenuClose = null;
function _closeAlbumMenu() {
  if (_albMenuEl) { _albMenuEl.remove(); _albMenuEl = null; }
  if (_albMenuClose) { document.removeEventListener('click', _albMenuClose, true); _albMenuClose = null; }
}
function _openAlbumMenu(anchor) {
  _closeAlbumMenu();
  const menu = document.createElement('div');
  menu.className = 'photos-albmenu';
  let html = '';
  if (_view && !_view.startsWith('__')) html += `<button class="photos-albmenu-item" data-aid="">remove from album</button>`;
  for (const a of _albums) html += `<button class="photos-albmenu-item" data-aid="${esc(a.id)}">${_si('folder')} ${esc(a.name)}</button>`;
  html += `<button class="photos-albmenu-item" data-new="1">${_si('plus')} new album…</button>`;
  menu.innerHTML = html;
  document.body.appendChild(menu);
  _albMenuEl = menu;
  const r = anchor.getBoundingClientRect();
  menu.style.top = (r.bottom + 5) + 'px';
  menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)) + 'px';
  menu.addEventListener('click', async e => {
    const b = e.target.closest('.photos-albmenu-item'); if (!b) return;
    let aid = b.dataset.aid || '';
    if (b.dataset.new) {
      const name = await dlgPrompt('album name:');
      if (!name?.trim()) { _closeAlbumMenu(); return; }
      try { aid = (await fetch('/api/photos/albums', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: name.trim() }) }).then(r => r.json())).id; }
      catch { toast('failed', 'error'); _closeAlbumMenu(); return; }
    }
    _closeAlbumMenu();
    _batch('album', { album_id: aid });
  });
  _albMenuClose = ev => { if (_albMenuEl && !_albMenuEl.contains(ev.target) && ev.target !== anchor) _closeAlbumMenu(); };
  setTimeout(() => document.addEventListener('click', _albMenuClose, true), 0);
}

function _renderMoments(d, emptyMsg) {
  _paintGroups((d.moments || []).map(m => ({ label: m.label, items: m.items })), emptyMsg);
}

// ── left rail (immich-style IA: browse / library / utilities) ──
function _renderSidebar() {
  const el = $('photos-sidebar');
  if (!el) return;
  const item = (view, ic, label, count) =>
    `<button class="photos-nav-item${_view === view ? ' active' : ''}" data-view="${esc(view)}">`
    + `<span class="photos-nav-ic">${_si(ic)}</span><span class="photos-nav-label">${esc(label)}</span>`
    + (count != null ? `<span class="photos-nav-count">${count}</span>` : '') + '</button>';
  const grp = t => `<div class="photos-nav-group">${t}</div>`;
  let html = grp('browse') + item('', 'image', 'photos') + item('__people__', 'users', 'people') + item('__map__', 'map-pin', 'map') + item('__places__', 'globe', 'places') + item('__memories__', 'sparkles', 'memories');
  html += grp('library');
  for (const a of _albums) html += item(a.id, 'folder', a.name, a.count);
  html += `<button class="photos-nav-item photos-nav-add" id="photos-newalbum-btn"><span class="photos-nav-ic">${_si('plus')}</span><span class="photos-nav-label">new album</span></button>`;
  html += grp('utilities') + item('__fav__', 'heart', 'favorites') + item('__archive__', 'archive', 'archive') + item('__hidden__', 'lock', 'hidden') + item('__dupes__', 'copy', 'duplicates') + item('__trash__', 'trash', 'trash');
  el.innerHTML = html;
  el.querySelectorAll('.photos-nav-item[data-view]').forEach(b => b.addEventListener('click', () => _selectView(b.dataset.view)));
  $('photos-newalbum-btn')?.addEventListener('click', newAlbum);
  // people only shows once face recognition is set up
  const pn = el.querySelector('.photos-nav-item[data-view="__people__"]');
  if (pn) pn.style.display = _facesAvail ? '' : 'none';
}

function _selectView(v) {
  _view = v;
  _clearSel();
  const s = $('photos-search'); if (s) s.value = '';
  _renderSidebar();
  loadPhotos();
}

function _updateHeadTitle() {
  const el = $('photos-head-title');
  if (!el) return;
  const names = { '': 'photos', '__people__': 'people', '__fav__': 'favorites', '__archive__': 'archive', '__hidden__': 'hidden', '__map__': 'map', '__places__': 'places', '__memories__': 'memories', '__dupes__': 'duplicates', '__trash__': 'trash' };
  let t = names[_view];
  if (t === undefined) { const a = _albums.find(x => x.id === _view); t = a ? a.name : 'photos'; }
  el.textContent = t;
}

async function _loadAlbums() {
  _albums = await fetch('/api/photos/albums').then(r => r.json()).catch(() => []);
  _renderSidebar();
}

export async function loadPhotos() {
  await _loadAlbums();
  _updateHeadTitle();
  // filters only apply to the /list-backed views (photos, favorites, albums)
  const fbtn = $('photos-filter-btn');
  if (fbtn) fbtn.style.display = _isListView() ? '' : 'none';
  if (!_isListView() && $('photos-filterbar')) $('photos-filterbar').hidden = true;
  if (_view === '__people__') { await loadPeople(); return; }
  if (_view === '__hidden__') { await loadHidden(); return; }
  if (_view === '__archive__') { await loadArchive(); return; }
  if (_view === '__map__') { await loadMap(); return; }
  if (_view === '__places__') { await loadPlaces(); return; }
  if (_view === '__memories__') { await loadMemories(); return; }
  if (_view === '__trash__') { await openPhotoTrash(); return; }
  if (_view === '__dupes__') { await loadDuplicates(); return; }
  // paged list views (photos / favorites / albums): fetch the first page, more loads on scroll
  if ($('photos-scroll')) $('photos-scroll').scrollTop = 0;
  _loadedGroups = [];
  _nextOffset = 0;
  _loadingMore = false;
  await _loadListPage();
}

function _listUrl() {
  let url = _view === '__fav__'
    ? '/api/photos/list?favorites=true'
    : '/api/photos/list' + (_view && !_view.startsWith('__') ? '?album=' + encodeURIComponent(_view) : '');
  const qs = _filterQS();
  if (qs) url += (url.includes('?') ? '&' : '?') + qs;
  return url;
}

function _listEmpty() {
  return _view === '__fav__' ? 'no favorites yet'
    : (_filtersActive() ? 'no photos match these filters' : 'gallery empty — upload something');
}

// append a page's date buckets, merging into the last group when the date matches
function _mergeGroups(into, incoming) {
  for (const g of incoming) {
    const last = into[into.length - 1];
    if (last && last.date === g.date) last.items.push(...g.items);
    else into.push({ date: g.date, label: g.label, items: [...g.items] });
  }
}

async function _loadListPage() {
  if (_loadingMore || _nextOffset == null) return;
  _loadingMore = true;
  const sep = _listUrl().includes('?') ? '&' : '?';
  const d = await fetch(`${_listUrl()}${sep}offset=${_nextOffset}&limit=${_PAGE}`)
    .then(r => r.json()).catch(() => ({ moments: [], next: null }));
  _mergeGroups(_loadedGroups, d.moments || []);
  _nextOffset = (d.next == null) ? null : d.next;
  _paintGroups(_loadedGroups, _listEmpty());
  _loadingMore = false;
}

// the hidden/locked album — needs a vault unlock token; prompt for the master password if locked
async function loadHidden() {
  const grid = $('photos-grid');
  _killMap(); _repaint = null;
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

// the archive — assets kept but pushed out of the main timeline
async function loadArchive() {
  const d = await fetch('/api/photos/archive').then(r => r.json()).catch(() => ({ moments: [] }));
  _renderMoments(d, 'nothing archived — select photos and hit archive to tuck them away');
}

// duplicate review — byte-identical sets; keep the oldest, trash the rest (phase 6)
async function loadDuplicates() {
  _killMap(); _repaint = null;
  const sb = $('photos-scrubber'); if (sb) sb.style.display = 'none';
  const grid = $('photos-grid');
  _photos = [];
  const d = await fetch('/api/photos/duplicates').then(r => r.json()).catch(() => ({ groups: [] }));
  if (!d.groups?.length) { grid.innerHTML = '<div class="photos-empty">no duplicates — your library is clean</div>'; return; }
  const total = d.groups.reduce((n, g) => n + g.items.length - 1, 0);
  let html = `<div class="photos-dupbar"><span>${d.groups.length} duplicate set${d.groups.length > 1 ? 's' : ''} · ${total} extra cop${total === 1 ? 'y' : 'ies'}</span>`
    + `<button class="btn primary" id="photos-dupes-all">resolve all — keep oldest</button></div>`;
  for (const g of d.groups) {
    const extras = g.items.slice(1).map(i => i.id).join(',');
    html += `<div class="photos-moment"><div class="photos-moment-label">${g.items.length} copies`
      + ` <button class="btn photos-dup-resolve" data-ids="${extras}" style="font-size:0.62rem;margin-left:6px">${_si('trash')} trash the other ${g.items.length - 1}</button></div>`
      + '<div class="photos-rows"><div class="photos-row">';
    g.items.forEach((p, i) => {
      _photos.push(p);
      const bg = p.preview ? `;background-image:url(${p.preview})` : '';
      const keep = i === 0 ? '<span class="photos-dup-keep">keep</span>' : '';
      html += `<div class="photos-cell" data-id="${p.id}" style="width:150px;height:150px${bg}"><img class="photos-thumb" loading="lazy" src="${p.thumb}" alt="" onload="this.classList.add('loaded')">${keep}</div>`;
    });
    html += '</div></div></div>';
  }
  grid.innerHTML = html;
  grid.querySelectorAll('.photos-cell').forEach(c => c.addEventListener('click', () => openLightbox(c.dataset.id)));
  const _trash = async ids => {
    if (!ids.length) return;
    try {
      await fetch('/api/photos/batch', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ids, action: 'delete' }) });
      toast('duplicates moved to trash', 'success');
    } catch { toast('failed', 'error'); return; }
    loadDuplicates();
  };
  $('photos-dupes-all')?.addEventListener('click', async () => {
    const ids = d.groups.flatMap(g => g.items.slice(1).map(i => i.id));
    if (ids.length && await dlgConfirm(`trash ${ids.length} duplicate${ids.length > 1 ? 's' : ''}?`)) _trash(ids);
  });
  grid.querySelectorAll('.photos-dup-resolve').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    _trash(b.dataset.ids.split(',').filter(Boolean));
  }));
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
// explore / places (phase 7c) — geotagged photos grouped by nearest city, offline
async function loadPlaces() {
  _killMap(); _repaint = null;
  const sb = $('photos-scrubber'); if (sb) sb.style.display = 'none';
  const grid = $('photos-grid');
  _photos = [];
  const d = await fetch('/api/photos/places').then(r => r.json()).catch(() => ({ places: [] }));
  if (!d.places?.length) { grid.innerHTML = '<div class="photos-empty">no places yet — geotagged photos group by city here</div>'; return; }
  let html = '<div class="photos-places">';
  for (const pl of d.places) {
    html += `<button class="photos-place" data-cc="${esc(pl.cc)}" data-city="${esc(pl.city)}">`
      + `<img loading="lazy" src="${pl.cover}" alt="">`
      + `<span class="photos-place-meta"><span class="photos-place-name">${esc(pl.city)}</span>`
      + `<span class="photos-place-sub">${esc(pl.country)} · ${pl.count}</span></span></button>`;
  }
  grid.innerHTML = html + '</div>';
  grid.querySelectorAll('.photos-place').forEach(b => b.addEventListener('click', () => loadPlace(b.dataset.cc, b.dataset.city)));
}

async function loadPlace(cc, city) {
  const d = await fetch(`/api/photos/place?cc=${encodeURIComponent(cc)}&city=${encodeURIComponent(city)}`)
    .then(r => r.json()).catch(() => ({ moments: [] }));
  _paintGroups((d.moments || []).map(m => ({ label: m.label, items: m.items })), 'no photos here');
  const back = document.createElement('div');
  back.className = 'photos-place-back';
  back.innerHTML = `<a href="#" style="color:var(--accent)">${_si('chevron-left')} places</a> · ${esc(city)}`;
  back.querySelector('a').addEventListener('click', e => { e.preventDefault(); loadPlaces(); });
  $('photos-grid').prepend(back);
}

// people (phase 7a) — face clusters as round avatars; click → that person's timeline
async function loadPeople() {
  _killMap(); _repaint = null;
  const sb = $('photos-scrubber'); if (sb) sb.style.display = 'none';
  const grid = $('photos-grid');
  _photos = [];
  const d = await fetch('/api/photos/people').then(r => r.json()).catch(() => ({ people: [] }));
  if (!d.people?.length) {
    grid.innerHTML = '<div class="photos-empty">no people yet — faces are still being scanned, check back in a bit</div>';
    return;
  }
  let html = '<div class="photos-people">';
  for (const p of d.people) {
    html += `<button class="photos-person${p.name ? '' : ' unnamed'}" data-id="${esc(p.id)}">`
      + `<span class="photos-person-av">${p.cover ? `<img loading="lazy" src="${p.cover}" alt="">` : ''}</span>`
      + `<span class="photos-person-name">${esc(p.name || 'add name')}</span>`
      + `<span class="photos-person-sub">${p.count} photo${p.count !== 1 ? 's' : ''}</span></button>`;
  }
  grid.innerHTML = html + '</div>';
  grid.querySelectorAll('.photos-person').forEach(b => b.addEventListener('click', () => loadPerson(b.dataset.id)));
}

async function loadPerson(pid) {
  _killMap(); _repaint = null;
  const d = await fetch('/api/photos/person/' + encodeURIComponent(pid)).then(r => r.json()).catch(() => ({ moments: [] }));
  _paintGroups((d.moments || []).map(m => ({ label: m.label, items: m.items })), 'no photos for this person');
  const per = d.person || { id: pid, name: '' };
  const bar = document.createElement('div');
  bar.className = 'photos-person-bar';
  bar.innerHTML = `<a href="#" class="photos-person-back" style="color:var(--accent)">${_si('chevron-left')} people</a>`
    + `<span class="photos-person-title">${esc(per.name || 'unnamed')}</span>`
    + `<span class="photos-person-actions">`
    + `<button class="btn" data-act="name">${_si('edit')} ${per.name ? 'rename' : 'add name'}</button>`
    + `<button class="btn" data-act="merge">${_si('users')} merge…</button>`
    + `<button class="btn" data-act="hide">${_si('eye-off')} not a person</button>`
    + `</span>`;
  $('photos-grid').prepend(bar);
  bar.querySelector('.photos-person-back').addEventListener('click', e => { e.preventDefault(); _selectView('__people__'); });
  bar.querySelector('[data-act="name"]').addEventListener('click', async () => {
    const name = await dlgPrompt('name this person:', per.name || '');
    if (name === null) return;
    try { await fetch(`/api/photos/person/${pid}/name`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name }) }); }
    catch { toast('failed', 'error'); return; }
    toast('saved', 'success'); loadPerson(pid);
  });
  bar.querySelector('[data-act="hide"]').addEventListener('click', async () => {
    if (!await dlgConfirm('hide this cluster from people? (the photos stay)')) return;
    try { await fetch(`/api/photos/person/${pid}/hide`, { method: 'POST' }); }
    catch { toast('failed', 'error'); return; }
    toast('hidden', 'success'); _selectView('__people__');
  });
  bar.querySelector('[data-act="merge"]').addEventListener('click', e => _openMergeMenu(e.currentTarget, pid));
}

// pick another cluster to fold into this one
async function _openMergeMenu(anchor, pid) {
  _closeAlbumMenu();
  const d = await fetch('/api/photos/people').then(r => r.json()).catch(() => ({ people: [] }));
  const others = (d.people || []).filter(p => p.id !== pid);
  if (!others.length) { toast('no other people to merge', ''); return; }
  const menu = document.createElement('div');
  menu.className = 'photos-albmenu';
  menu.innerHTML = others.map(p =>
    `<button class="photos-albmenu-item" data-id="${esc(p.id)}">`
    + `${p.cover ? `<img class="photos-merge-av" src="${p.cover}" alt="">` : ''}`
    + `${esc(p.name || 'unnamed')} · ${p.count}</button>`).join('');
  document.body.appendChild(menu);
  _albMenuEl = menu;
  const r = anchor.getBoundingClientRect();
  menu.style.top = (r.bottom + 5) + 'px';
  menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)) + 'px';
  menu.addEventListener('click', async e => {
    const b = e.target.closest('.photos-albmenu-item'); if (!b) return;
    const other = b.dataset.id;
    _closeAlbumMenu();
    try { await fetch('/api/photos/people/merge', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ids: [pid, other] }) }); }
    catch { toast('failed', 'error'); return; }
    toast('merged', 'success'); loadPerson(pid);
  });
  _albMenuClose = ev => { if (_albMenuEl && !_albMenuEl.contains(ev.target) && ev.target !== anchor) _closeAlbumMenu(); };
  setTimeout(() => document.addEventListener('click', _albMenuClose, true), 0);
}

// open a person's timeline straight from a face chip (keeps the back-to-people context)
function _goPerson(pid) {
  closeLightbox();
  _view = '__people__';
  _clearSel();
  _renderSidebar();
  _updateHeadTitle();
  loadPerson(pid);
}

// face chips in the lightbox info drawer — who's in this photo
function _loadFaceChips(p) {
  const box = $('photos-faces');
  if (!box) return;
  if (!_facesAvail) { box.innerHTML = ''; box.style.display = 'none'; return; }
  box.innerHTML = '';
  box.style.display = 'none';
  fetch(`/api/photos/photo/${p.id}/faces`).then(r => r.json()).then(d => {
    if (!_cur || _cur.id !== p.id) return;   // stepped to another photo before this landed
    if (!d.faces?.length) return;
    box.style.display = '';
    box.innerHTML = `<div class="photos-faces-h">people</div><div class="photos-faces-row">`
      + d.faces.map(f =>
        `<button class="photos-face-chip${f.person_id ? '' : ' nolink'}" data-pid="${esc(f.person_id || '')}" title="${esc(f.name || 'unnamed')}">`
        + `<img src="${f.thumb}" alt=""><span>${esc(f.name || 'unnamed')}</span></button>`).join('')
      + `</div>`;
    box.querySelectorAll('.photos-face-chip').forEach(c => c.addEventListener('click', () => {
      if (c.dataset.pid) _goPerson(c.dataset.pid);
    }));
  }).catch(() => { box.style.display = 'none'; });
}

async function _initFaces() {
  try {
    const d = await fetch('/api/photos/faces-status').then(r => r.json());
    _facesAvail = !!d.available;
  } catch { _facesAvail = false; }
  _renderSidebar();
}

async function loadMap() {
  _killMap(); _repaint = null;
  const sb = $('photos-scrubber'); if (sb) sb.style.display = 'none';
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

// memories (7b) — "on this day" across prior years
async function loadMemories() {
  _killMap(); _repaint = null;
  const d = await fetch('/api/photos/memories').then(r => r.json()).catch(() => ({ groups: [] }));
  if (!d.groups?.length) {
    $('photos-grid').innerHTML = '<div class="photos-empty">no memories for today — check back another day</div>';
    _photos = []; return;
  }
  const groups = d.groups.map(g => ({
    label: `${g.years_ago === 1 ? '1 year ago' : g.years_ago + ' years ago'} · ${g.date}`,
    items: g.items,
  }));
  _paintGroups(groups, 'no memories yet');
}

async function searchPhotos(q) {
  _nextOffset = null;   // search is its own (unpaged) result set
  const d = await fetch('/api/photos/search?q=' + encodeURIComponent(q))
    .then(r => r.json()).catch(() => ({ moments: [] }));
  _renderMoments(d, 'no photos match');
}

// smart (CLIP) search — results come back in relevance order (phase 7b)
async function semanticSearch(q) {
  _nextOffset = null;
  const d = await fetch('/api/photos/semantic?q=' + encodeURIComponent(q))
    .then(r => r.json()).catch(() => ({ moments: [] }));
  _renderMoments(d, d.unavailable ? 'smart search isn’t set up yet' : 'nothing matches');
}

async function _initClip() {
  try {
    const d = await fetch('/api/photos/clip-status').then(r => r.json());
    _clipAvail = !!d.available;
    const b = $('photos-smart-btn');
    if (b) {
      b.hidden = !_clipAvail;
      b.title = _clipAvail ? `smart search — ${d.indexed}/${d.total} indexed` : 'smart search';
    }
  } catch { /* feature just stays hidden */ }
}

function openLightbox(id, src) {
  _lbPhotos = src || _photos;   // a stack opens its own members; the grid opens the timeline
  _curIdx = _lbPhotos.findIndex(x => x.id === id);
  if (_curIdx < 0) return;
  const lb = $('photos-lightbox');
  lb.classList.toggle('drawer-open', _drawerOpen);
  lb.style.display = 'flex';
  _showCurrent();
}

// expand a stack into the viewer — arrows step through its members, cover first
async function _openStack(coverId) {
  const d = await fetch('/api/photos/stack/' + coverId).then(r => r.json()).catch(() => ({ items: [] }));
  if (d.items?.length) openLightbox(d.items[0].id, d.items);
  else openLightbox(coverId);
}

// render _lbPhotos[_curIdx] into the open lightbox — reused by prev/next stepping
function _showCurrent() {
  const p = _lbPhotos[_curIdx];
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
  if ($('photos-info-btn')) $('photos-info-btn').innerHTML = `${_si('info')} info`;
  _setFavBtn(p.favorite);
  const ab = $('photos-archive-btn');
  if (ab) ab.innerHTML = p.archived ? `${_si('archive')} unarchive` : `${_si('archive')} archive`;
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
  const prevB = $('photos-prev-btn'), nextB = $('photos-next-btn');
  if (prevB) prevB.disabled = _curIdx <= 0;
  if (nextB) nextB.disabled = _curIdx >= _lbPhotos.length - 1;
  _loadFaceChips(p);
}

function _step(d) {
  const n = _curIdx + d;
  if (n < 0 || n >= _lbPhotos.length) return;
  _curIdx = n;
  _showCurrent();
}

function _toggleDrawer(force) {
  _drawerOpen = (force != null) ? force : !_drawerOpen;
  $('photos-lightbox')?.classList.toggle('drawer-open', _drawerOpen);
}

function _toggleHelp(force) {
  const el = $('photos-lb-help');
  if (!el) return;
  el.hidden = (force != null) ? !force : !el.hidden;
}

function closeLightbox() {
  const v = $('photos-lightbox-video');
  if (v) { v.pause?.(); v.src = ''; }
  _toggleHelp(false);
  $('photos-lightbox').style.display = 'none';
  _cur = null; _curIdx = -1; _lbPhotos = [];
}

function _isListView() { return !_view.startsWith('__') || _view === '__fav__'; }

// ── filters (phase 5) ──
function _filterQS() {
  const p = new URLSearchParams();
  for (const k of ['type', 'camera', 'from', 'to']) if (_filters[k]) p.set(k, _filters[k]);
  return p.toString();
}
function _filtersActive() { return !!(_filters.type || _filters.camera || _filters.from || _filters.to); }
function _applyFilters() {
  $('photos-filter-btn')?.classList.toggle('on', _filtersActive());
  loadPhotos();
}
async function _loadFacets() {
  if (_facetsLoaded) return;
  _facetsLoaded = true;
  try {
    const d = await fetch('/api/photos/facets').then(r => r.json());
    const sel = $('photos-filt-camera');
    for (const c of (d.cameras || [])) {
      const o = document.createElement('option');
      o.value = c; o.textContent = c;
      sel?.appendChild(o);
    }
  } catch { _facetsLoaded = false; }
}

// ── date scrubber (phase 5) — drag the right edge to fly through the timeline ──
function _scrubInit() {
  const bar = $('photos-scrubber'), sc = $('photos-scroll');
  if (!bar || !sc || bar._wired) return;
  bar._wired = true;
  bar.setAttribute('tabindex', '0');
  bar.addEventListener('pointerdown', e => {
    _scrubDrag = true; bar.classList.add('dragging');
    bar.setPointerCapture?.(e.pointerId);
    _scrubTo(e.clientY); e.preventDefault();
  });
  bar.addEventListener('pointermove', e => { if (_scrubDrag) _scrubTo(e.clientY); });
  const end = () => { _scrubDrag = false; bar.classList.remove('dragging'); _scrubPill(false); };
  bar.addEventListener('pointerup', end);
  bar.addEventListener('pointercancel', end);
  bar.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { _scrubJump(e.key === 'ArrowDown' ? 1 : -1); e.preventDefault(); }
  });
  sc.addEventListener('scroll', () => {
    _scrubThumb();
    // load the next page as the bottom approaches (phase 4 paging)
    if (_nextOffset != null && !_loadingMore && sc.scrollTop + sc.clientHeight > sc.scrollHeight - 600) _loadListPage();
  });
}
function _scrubTo(clientY) {
  const sc = $('photos-scroll'), bar = $('photos-scrubber');
  const r = bar.getBoundingClientRect();
  const frac = Math.min(1, Math.max(0, (clientY - r.top) / r.height));
  sc.scrollTop = frac * (sc.scrollHeight - sc.clientHeight);
  _scrubPill(true, clientY);
}
function _scrubThumb() {
  const sc = $('photos-scroll'), bar = $('photos-scrubber'), thumb = $('photos-scrub-thumb');
  if (!sc || !bar || !thumb) return;
  const max = sc.scrollHeight - sc.clientHeight;
  if (max <= 4) { bar.style.display = 'none'; return; }
  bar.style.display = '';
  thumb.style.top = ((sc.scrollTop / max) * (bar.clientHeight - thumb.offsetHeight)) + 'px';
}
function _scrubPill(show, clientY) {
  const pill = $('photos-scrub-pill'); if (!pill) return;
  if (!show) { pill.hidden = true; return; }
  const sc = $('photos-scroll'), r = $('photos-scrubber').getBoundingClientRect();
  pill.textContent = _scrubLabelAt(sc.scrollTop);
  pill.hidden = false;
  pill.style.top = Math.min(Math.max(clientY ?? r.top, r.top + 12), r.bottom - 12) + 'px';
}
function _scrubLabelAt(scrollTop) {
  const sc = $('photos-scroll'), scTop = sc.getBoundingClientRect().top;
  const moms = [...document.querySelectorAll('#photos-grid .photos-moment')];
  let label = moms[0]?.querySelector('.photos-moment-label')?.textContent || '';
  for (const m of moms) {
    const top = m.getBoundingClientRect().top - scTop + sc.scrollTop;
    if (top <= scrollTop + 12) label = m.querySelector('.photos-moment-label')?.textContent || label;
    else break;
  }
  return label;
}
function _scrubJump(dir) {
  const sc = $('photos-scroll'), scTop = sc.getBoundingClientRect().top;
  const tops = [...document.querySelectorAll('#photos-grid .photos-moment')]
    .map(m => m.getBoundingClientRect().top - scTop + sc.scrollTop);
  const cur = sc.scrollTop;
  const target = dir > 0 ? tops.find(t => t > cur + 2) : [...tops].reverse().find(t => t < cur - 2);
  if (target != null) sc.scrollTop = target;
}

let _inited = false;
export function initPhotos() {
  if (_inited) return;
  _inited = true;
  const psearch = $('photos-search');
  let _pt;
  psearch?.addEventListener('input', () => {
    clearTimeout(_pt);
    const q = psearch.value.trim();
    if (!q) { loadPhotos(); return; }
    _pt = setTimeout(() => (_smart ? semanticSearch(q) : searchPhotos(q)), _smart ? 450 : 300);
  });
  // smart (CLIP) search toggle
  if ($('photos-smart-btn')) $('photos-smart-btn').innerHTML = `${_si('sparkles')} smart`;
  $('photos-smart-btn')?.addEventListener('click', () => {
    _smart = !_smart;
    $('photos-smart-btn').classList.toggle('on', _smart);
    const q = psearch.value.trim();
    if (q) (_smart ? semanticSearch(q) : searchPhotos(q));
  });
  _initClip();
  _initFaces();
  $('photos-upload-btn')?.addEventListener('click', () => $('photos-upload-input')?.click());
  $('photos-upload-input')?.addEventListener('change', e => { uploadPhotos(e.target.files); e.target.value = ''; });
  $('photos-share-album-btn')?.addEventListener('click', shareAlbum);
  // selection action bar
  $('photos-sel-clear')?.addEventListener('click', _clearSel);
  $('photos-sel-fav')?.addEventListener('click', () => _batch('favorite'));
  $('photos-sel-archive')?.addEventListener('click', () => _batch(_view === '__archive__' ? 'unarchive' : 'archive'));
  $('photos-sel-album')?.addEventListener('click', e => _openAlbumMenu(e.currentTarget));
  $('photos-sel-del')?.addEventListener('click', async () => {
    if (await dlgConfirm(`delete ${_sel.size} photo${_sel.size > 1 ? 's' : ''}?`)) _batch('delete');
  });
  $('photos-sel-stack')?.addEventListener('click', async () => {
    const ids = [..._sel];
    try {
      if (ids.length === 1) {
        await fetch('/api/photos/unstack', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id: ids[0] }) });
        toast('unstacked', '');
      } else if (ids.length >= 2) {
        const r = await fetch('/api/photos/stack', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ids }) });
        if (!r.ok) throw 0;
        toast('stacked', 'success');
      } else return;
    } catch { toast('failed', 'error'); return; }
    _clearSel(); loadPhotos();
  });
  if ($('photos-sel-fav')) $('photos-sel-fav').innerHTML = `${_si('heart')} favorite`;
  if ($('photos-sel-album')) $('photos-sel-album').innerHTML = `${_si('folder')} add to album`;
  if ($('photos-sel-del')) $('photos-sel-del').innerHTML = `${_si('trash')} delete`;
  $('photos-close-btn')?.addEventListener('click', closeLightbox);
  $('photos-edit-btn')?.addEventListener('click', async () => {
    if (!_cur) return;
    const { openEditor } = await import('./imgeditor.js');
    openEditor(_cur.original, {
      name: _cur.original_name || 'photo.png',
      onSaved: () => { closeLightbox(); loadPhotos(); },
    });
  });
  $('photos-lightbox')?.addEventListener('click', e => {
    if (['photos-lightbox', 'photos-lb-stage', 'photos-lb-media'].includes(e.target.id)) closeLightbox();
  });
  // prev/next stepping, info drawer, archive, keyboard shortcuts
  $('photos-prev-btn')?.addEventListener('click', () => _step(-1));
  $('photos-next-btn')?.addEventListener('click', () => _step(1));
  if ($('photos-prev-btn')) $('photos-prev-btn').innerHTML = _si('chevron-left');
  if ($('photos-next-btn')) $('photos-next-btn').innerHTML = _si('chevron-right');
  $('photos-info-btn')?.addEventListener('click', () => _toggleDrawer());
  $('photos-archive-btn')?.addEventListener('click', async () => {
    if (!_cur) return;
    const arch = !_cur.archived;
    await fetch('/api/photos/' + _cur.id, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ archived: arch }) });
    _cur.archived = arch;
    toast(arch ? 'archived' : 'unarchived', '');
    closeLightbox(); loadPhotos();
  });
  document.addEventListener('keydown', e => {
    if ($('photos-lightbox')?.style.display !== 'flex') return;   // only while the viewer is open
    if (e.key === 'Escape') {
      if (!$('photos-lb-help')?.hidden) { _toggleHelp(false); return; }
      closeLightbox(); return;
    }
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea') return;   // don't hijack the caption / keywords fields
    let hit = true;
    switch (e.key) {
      case 'ArrowLeft': _step(-1); break;
      case 'ArrowRight': _step(1); break;
      case 'i': case 'I': _toggleDrawer(); break;
      case 'f': case 'F': $('photos-fav-btn')?.click(); break;
      case 'Delete': $('photos-del-btn')?.click(); break;
      case 'A': e.shiftKey ? $('photos-archive-btn')?.click() : (hit = false); break;
      case '?': _toggleHelp(); break;
      default: hit = false;
    }
    if (hit) e.preventDefault();
  });
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
  // filters
  if ($('photos-filter-btn')) $('photos-filter-btn').innerHTML = `${_si('filter')} filter`;
  $('photos-filter-btn')?.addEventListener('click', () => {
    const bar = $('photos-filterbar');
    if (bar) { bar.hidden = !bar.hidden; if (!bar.hidden) _loadFacets(); }
  });
  $('photos-filt-type')?.addEventListener('click', e => {
    const b = e.target.closest('button[data-type]'); if (!b) return;
    _filters.type = b.dataset.type;
    $('photos-filt-type').querySelectorAll('button').forEach(x => x.classList.toggle('active', x === b));
    _applyFilters();
  });
  $('photos-filt-camera')?.addEventListener('change', e => { _filters.camera = e.target.value; _applyFilters(); });
  $('photos-filt-from')?.addEventListener('change', e => { _filters.from = e.target.value; _applyFilters(); });
  $('photos-filt-to')?.addEventListener('change', e => { _filters.to = e.target.value; _applyFilters(); });
  $('photos-filt-clear')?.addEventListener('click', () => {
    _filters.type = _filters.camera = _filters.from = _filters.to = '';
    $('photos-filt-type')?.querySelectorAll('button').forEach((x, i) => x.classList.toggle('active', i === 0));
    if ($('photos-filt-camera')) $('photos-filt-camera').value = '';
    if ($('photos-filt-from')) $('photos-filt-from').value = '';
    if ($('photos-filt-to')) $('photos-filt-to').value = '';
    _applyFilters();
  });
  _scrubInit();
  // re-justify the current bucket layout when the window resizes (no-op on map/trash)
  let _rt;
  window.addEventListener('resize', () => { clearTimeout(_rt); _rt = setTimeout(() => { if (_repaint) _repaint(); }, 120); });
}

async function openPhotoTrash() {
  _killMap(); _repaint = null;
  const sb = $('photos-scrubber'); if (sb) sb.style.display = 'none';
  let items;
  try { items = await fetch('/api/photos/trash').then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  const grid = $('photos-grid');
  _photos = [];
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
  $('photos-trash-back')?.addEventListener('click', e => { e.preventDefault(); _selectView(''); });
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
    // virtual filters (__fav__/__hidden__/__map__/etc) aren't real albums — only attach a real album id
    if (_view && !_view.startsWith('__')) fd.append('album_id', _view);
    fd.append('file', f);
    const r = await fetch('/api/photos/upload', { method: 'POST', body: fd });
    if (r.ok) n++; else toast('upload failed: ' + f.name, 'error');
  }
  if (n) { toast(`added ${n} image${n > 1 ? 's' : ''}`, 'success'); loadPhotos(); }
}

// share the currently-selected album as a read-only /s/{token} link (7c)
async function shareAlbum() {
  if (!_view || _view.startsWith('__')) { toast('open an album to share it', ''); return; }
  try {
    const r = await fetch('/api/share', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kind: 'album', ref: _view }),
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
  _loadAlbums();
}
