import { toast, shareResource } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';
import { urlForApp } from './subdomain.js';

let _cwd = '';   // current relative dir
let _sort = 'name', _order = '';
let _view = 'list';          // 'list' | 'grid' (6b) — persisted in localStorage
let _rerender = null;        // re-runs the current view when the grid/list toggle flips

const $ = id => document.getElementById(id);
function _pathFromUrl() { return new URLSearchParams(location.search).get('p') || ''; }
function _writeUrl() {
  try {
    const u = new URL(location.href);
    if (_cwd) u.searchParams.set('p', _cwd); else u.searchParams.delete('p');
    if (_sort !== 'name') u.searchParams.set('sort', _sort); else u.searchParams.delete('sort');
    if (_order === 'asc' || _order === 'desc') u.searchParams.set('order', _order); else u.searchParams.delete('order');
    history.replaceState(null, '', u);
  } catch {}
}
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function fmtSize(n) {
  if (!n) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  return (n / 1024 / 1024 / 1024).toFixed(1) + ' GB';
}

function fmtAgo(ts) {
  const d = (Date.now() / 1000) - ts;
  if (d < 90) return 'just now';
  if (d < 3600) return Math.round(d / 60) + 'm ago';
  if (d < 86400) return Math.round(d / 3600) + 'h ago';
  if (d < 86400 * 30) return Math.round(d / 86400) + 'd ago';
  return new Date(ts * 1000).toLocaleDateString();
}

// grid only makes sense for a flat folder/image listing; group views force list
function _setGrid(on) {
  const list = $('files-list');
  if (list) list.classList.toggle('files-grid', !!on);
}

// thumbnail cell used in grid mode — real <img> for images, the icon otherwise
function _thumb(it) {
  if (it.type === 'file' && it.is_img)
    return `<div class="file-thumb"><img loading="lazy" src="/api/files/raw?path=${encodeURIComponent(it.path)}" alt=""></div>`;
  return `<div class="file-thumb file-thumb-ic">${it.type === 'dir' ? _ic('dir') : _ic(it.is_img ? 'img' : 'file')}</div>`;
}

function _syncViewToggle() {
  const b = $('files-view-toggle');
  if (b) b.innerHTML = _view === 'grid' ? `${_si('list')} list` : `${_si('grid')} grid`;
}

export async function loadFiles(path = _cwd) {
  let data;
  const qs = p => `/api/files/list?path=${encodeURIComponent(p)}&sort=${_sort}&order=${_order}`;
  try {
    data = await fetch(qs(path)).then(r => r.json());
  } catch { toast('failed to load files', 'error'); return; }
  if (data.detail) {  // server rejected the path — bounce to root
    _cwd = '';
    data = await fetch(qs('')).then(r => r.json());
  } else {
    _cwd = data.path || '';
  }
  _writeUrl();
  renderCrumb();
  renderSortBar();
  _renderQuota();
  renderList(data.items || []);
  if (!_cwd) { _injectSmartFolders(); _injectDocsShortcut(); }   // at root, surface smart views + the docs vault
}

let _quotaCache = null;   // {at, data} — disk free space barely moves between folder clicks
async function _renderQuota() {
  let host = $('files-quota');
  if (!host) {
    host = document.createElement('div');
    host.id = 'files-quota';
    host.className = 'files-quota';
    // sit on the same row as the sort controls (subhead), not on its own line above the list
    const sortbar = $('files-sortbar');
    if (sortbar) sortbar.parentNode.insertBefore(host, sortbar);
    else { const list = $('files-list'); list.parentNode.insertBefore(host, list); }
  }
  try {
    let q;
    if (_quotaCache && Date.now() - _quotaCache.at < 30000) q = _quotaCache.data;
    else { q = await fetch('/api/files/quota').then(r => r.json()); _quotaCache = { at: Date.now(), data: q }; }
    // bar = how full the DISK is (used = total-free), not the tiny vault footprint —
    // otherwise 89 B of a 2 TB disk reads as a permanently-empty bar.
    const diskUsed = Math.max(0, (q.total || 0) - (q.free || 0));
    const raw = q.total ? (diskUsed / q.total) * 100 : 0;
    const pct = q.total ? Math.min(100, Math.max(diskUsed > 0 ? 1 : 0, raw)) : 0;
    // free disk is the headline (Docker-aware: disk_usage() on the data dir's volume)
    const free = q.free ? `<b class="files-quota-free">${fmtSize(q.free)} free</b>` : '';
    const ofTotal = q.total ? ` of ${fmtSize(q.total)}` : '';
    // the vault's own footprint, shown separately so it's not confused with disk usage
    const vault = q.used ? ` · ${fmtSize(q.used)} in vault` : '';
    host.innerHTML = `<div class="files-quota-bar"><div class="files-quota-fill" style="width:${pct.toFixed(2)}%"></div></div>`
      + `<span class="files-quota-lbl">${free}${ofTotal}${vault}</span>`;
  } catch {}
}

const SORTS = [['name', 'name'], ['size', 'size'], ['mtime', 'date']];
function renderSortBar() {
  const bar = $('files-sortbar');
  if (!bar) return;
  bar.innerHTML = SORTS.map(([k, l]) =>
    `<button class="files-sort${k === _sort ? ' on' : ''}" data-k="${k}">${l}${k === _sort ? _si(_isDesc() ? 'chevron-down' : 'chevron-up') : ''}</button>`).join('');
  bar.querySelectorAll('.files-sort').forEach(b => b.addEventListener('click', () => {
    const k = b.dataset.k;
    if (k === _sort) _order = _isDesc() ? 'asc' : 'desc';   // toggle direction
    else { _sort = k; _order = ''; }                        // new column → sensible default
    loadFiles();
  }));
}
function _isDesc() {
  return _order === 'desc' || (_order === '' && (_sort === 'size' || _sort === 'mtime'));
}

const SMART = [
  { kind: 'recent', label: 'recent', icon: 'clock' },
  { kind: 'images', label: 'images', icon: 'image' },
  { kind: 'documents', label: 'documents', icon: 'file' },
  { kind: 'large', label: 'large files', icon: 'archive' },
];

// tiny wrapper so module load order can't bite — window.icon is set by app.js
const _si = n => (window.icon ? window.icon(n) : '');

function _injectSmartFolders() {
  const list = $('files-list');
  if (!list || list.querySelector('.files-smart-bar')) return;
  const bar = document.createElement('div');
  bar.className = 'files-smart-bar';
  bar.innerHTML = SMART.map(s => `<button class="files-smart" data-kind="${s.kind}">${_si(s.icon)} ${s.label}</button>`).join('')
    + `<button class="files-smart" data-kind="__activity">${_si('history')} activity</button>`
    + `<button class="files-smart" data-kind="__duplicates">${_si('copy')} duplicates</button>`
    + `<button class="files-smart" data-kind="__starred">${_si('star')} starred</button>`
    + `<button class="files-smart" data-kind="__trash">${_si('trash')} recently deleted</button>`;
  bar.querySelectorAll('.files-smart').forEach(btn =>
    btn.addEventListener('click', () => {
      if (btn.dataset.kind === '__trash') openTrash();
      else if (btn.dataset.kind === '__starred') openStarred();
      else if (btn.dataset.kind === '__activity') openActivity();
      else if (btn.dataset.kind === '__duplicates') openDuplicates();
      else openSmart(btn.dataset.kind);
    }));
  list.insertBefore(bar, list.firstChild);
}

async function openStarred() {
  _rerender = openStarred;
  let d;
  try { d = await fetch('/api/files/starred').then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  _smartCrumb('starred');
  const items = (d.items || []).map(i => ({
    path: i.path, name: i.path.split('/').pop(), type: 'file',
    is_img: /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(i.path), size: 0,
    tags: i.tags || [], color: i.color || '', starred: true,
  }));
  if (!items.length) { $('files-list').innerHTML = '<div class="files-empty">no starred files</div>'; return; }
  renderList(items);
}

// 4c - browse every file carrying a tag, from anywhere in the tree
async function openByTag(tag) {
  _rerender = () => openByTag(tag);
  let d;
  try { d = await fetch('/api/files/by-tag?tag=' + encodeURIComponent(tag)).then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  _smartCrumb('tagged #' + tag);
  const items = (d.items || []).map(i => ({
    path: i.path, name: i.path.split('/').pop(), type: 'file',
    is_img: /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(i.path), size: 0,
    tags: i.tags || [], color: i.color || '',
  }));
  if (!items.length) { $('files-list').innerHTML = `<div class="files-empty">no files tagged #${esc(tag)}</div>`; return; }
  _setGrid(false);
  renderList(items);
}

async function openTrash() {
  _rerender = openTrash;
  let items;
  try { items = await fetch('/api/files/trash').then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  _smartCrumb('recently deleted');
  const list = $('files-list');
  _setGrid(false);
  if (!items.length) { list.innerHTML = '<div class="files-empty">trash is empty</div>'; return; }
  list.innerHTML = items.map(it => `
    <div class="file-row" data-id="${esc(it.id)}">
      <span class="file-icon">${_si('trash')}</span>
      <span class="file-name">${esc(it.ref)}</span>
      <span class="file-row-actions"><button class="file-act file-act-txt" data-restore title="restore">${_si('undo')} restore</button></span>
    </div>`).join('');
  list.querySelectorAll('.file-row').forEach(row => {
    row.querySelector('[data-restore]').addEventListener('click', async () => {
      try {
        await fetch('/api/files/trash/restore', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id: row.dataset.id }) });
        toast('restored', '');
      } catch { toast('restore failed', 'error'); }
      openTrash();
    });
  });
}

async function openSmart(kind) {
  _rerender = () => openSmart(kind);
  let d;
  try { d = await fetch(`/api/files/smart/${kind}`).then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  const label = (SMART.find(s => s.kind === kind) || {}).label || kind;
  _smartCrumb(label);
  const list = $('files-list');
  _setGrid(false);
  const items = d.items || [];
  if (!items.length) { list.innerHTML = '<div class="files-empty">nothing here</div>'; return; }
  list.innerHTML = items.map(it => `
    <div class="file-row" data-path="${esc(it.path)}" data-img="${it.is_img ? 1 : 0}">
      <span class="file-icon">${_ic(it.is_img ? 'img' : 'file')}</span>
      <span class="file-name">${esc(it.path)}</span>
      <span class="file-meta">${fmtSize(it.size)}</span>
    </div>`).join('');
  list.querySelectorAll('.file-row').forEach(row => {
    const open = () => openPreview(row.dataset.path, row.dataset.img === '1');
    row.querySelector('.file-name').addEventListener('click', open);
    row.querySelector('.file-icon').addEventListener('click', open);
  });
}

function _smartCrumb(label) {
  $('files-breadcrumb').innerHTML =
    `<span class="crumb" id="files-smart-back" data-go="">files</span><span class="crumb-sep">/</span><span style="color:var(--muted)">${esc(label)}</span>`;
  $('files-smart-back')?.addEventListener('click', () => loadFiles(''));
}

const _IMGRE = /\.(png|jpe?g|gif|webp|svg|bmp)$/i;

async function openActivity() {
  _rerender = openActivity;
  let d;
  try { d = await fetch('/api/files/activity').then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  _smartCrumb('activity');
  const list = $('files-list');
  _setGrid(false);
  const items = d.items || [];
  if (!items.length) { list.innerHTML = '<div class="files-empty">no recent changes</div>'; return; }
  list.innerHTML = items.map(it => `
    <div class="file-row" data-path="${esc(it.path)}" data-img="${_IMGRE.test(it.path) ? 1 : 0}">
      <span class="file-icon">${_ic(_IMGRE.test(it.path) ? 'img' : 'file')}</span>
      <span class="file-name">${esc(it.path)}</span>
      <span class="file-meta">${fmtAgo(it.mtime)} · ${fmtSize(it.size)}</span>
    </div>`).join('');
  list.querySelectorAll('.file-row').forEach(row => {
    const open = () => openPreview(row.dataset.path, row.dataset.img === '1');
    row.querySelector('.file-name').addEventListener('click', open);
    row.querySelector('.file-icon').addEventListener('click', open);
  });
}

async function openDuplicates() {
  _rerender = openDuplicates;
  let d;
  try { d = await fetch('/api/files/duplicates').then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  _smartCrumb('duplicates');
  const list = $('files-list');
  _setGrid(false);
  const groups = d.groups || [];
  if (!groups.length) { list.innerHTML = '<div class="files-empty">no duplicate files</div>'; return; }
  list.innerHTML = groups.map((g, gi) => `
    <div class="files-dupgroup" data-g="${gi}">
      <div class="files-dup-head">${g.paths.length} identical copies · ${fmtSize(g.size)} each</div>
      ${g.paths.map(p => `
        <div class="file-row" data-path="${esc(p)}" data-img="${_IMGRE.test(p) ? 1 : 0}">
          <span class="file-icon">${_ic(_IMGRE.test(p) ? 'img' : 'file')}</span>
          <span class="file-name">${esc(p)}</span>
          <span class="file-row-actions"><button class="file-act" data-del title="delete this copy">${_si('trash')}</button></span>
        </div>`).join('')}
    </div>`).join('');
  list.querySelectorAll('.file-row').forEach(row => {
    const path = row.dataset.path;
    const open = () => openPreview(path, row.dataset.img === '1');
    row.querySelector('.file-name').addEventListener('click', open);
    row.querySelector('.file-icon').addEventListener('click', open);
    row.querySelector('[data-del]')?.addEventListener('click', async e => {
      e.stopPropagation();
      const ok = await dlgConfirm(`delete "${path.split('/').pop()}"? the other copies stay.`);
      if (!ok) return;
      const r = await fetch(`/api/files/delete?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
      if (r.ok) openDuplicates(); else toast('delete failed', 'error');
    });
  });
}

function _countDocs(items) {
  let n = 0;
  for (const it of (items || [])) n += it.type === 'dir' ? _countDocs(it.children || it.items) : 1;
  return n;
}

async function _injectDocsShortcut() {
  const list = $('files-list');
  if (!list || list.querySelector('.files-doc-shortcut')) return;
  let n = 0;
  try { n = _countDocs((await fetch('/api/vault-md/tree').then(r => r.json())).items); } catch {}
  const row = document.createElement('div');
  row.className = 'file-row files-doc-shortcut';
  row.style.cursor = 'pointer';
  row.innerHTML = `<span class="file-icon">${_si('file')}</span><span class="file-name">documents</span><span class="file-meta">${n} note${n === 1 ? '' : 's'} · open in docs →</span>`;
  row.addEventListener('click', () => {
    if (window._navigateTo) return window._navigateTo('wiki');   // works on one host or across subdomains
    try { window.location.href = urlForApp('docs'); } catch { location.hash = ''; }
  });
  list.insertBefore(row, list.firstChild);
}

function renderCrumb() {
  const el = $('files-breadcrumb');
  const parts = _cwd ? _cwd.split('/') : [];
  if (!parts.length) { el.innerHTML = ''; return; }   // root: title already says "files", no redundant crumb
  let acc = '';
  let html = `<span class="crumb" data-go="">files</span>`;
  for (const p of parts) {
    acc = acc ? acc + '/' + p : p;
    html += `<span class="crumb-sep">/</span><span class="crumb" data-go="${esc(acc)}">${esc(p)}</span>`;
  }
  el.innerHTML = html;
  el.querySelectorAll('.crumb').forEach(c => c.addEventListener('click', () => loadFiles(c.dataset.go)));
}

function renderList(items) {
  const list = $('files-list');
  _rerender = () => renderList(items);
  _setGrid(_view === 'grid');
  if (!items.length) {
    list.innerHTML = '<div class="files-empty">empty folder</div>';
    return;
  }
  list.innerHTML = items.map(it => `
    <div class="file-row" data-path="${esc(it.path)}" data-type="${it.type}" data-img="${it.is_img ? 1 : 0}">
      ${_view === 'grid' ? _thumb(it) : ''}
      <span class="file-dot ${it.color ? 'on c-' + esc(it.color) : ''}"></span>
      <span class="file-icon">${it.type === 'dir' ? _ic('dir') : _ic(it.is_img ? 'img' : 'file')}</span>
      <span class="file-name">${esc(it.name)}${(it.tags && it.tags.length) ? it.tags.map(t => `<span class="file-tag" data-tag="${esc(t)}" title="show all #${esc(t)}">${esc(t)}</span>`).join('') : ''}</span>
      <span class="file-meta">${it.type === 'file' ? fmtSize(it.size) : ''}</span>
      <span class="file-row-actions">
        <button class="file-act file-star${it.starred ? ' on' : ''}" data-act="star" title="star">${_si(it.starred ? 'star-fill' : 'star')}</button>
        ${it.type === 'file' ? `<a class="file-act" href="/api/files/raw?path=${encodeURIComponent(it.path)}&download=1" download title="download">${_si('download')}</a>` : ''}
        <button class="file-act" data-act="share" title="${it.type === 'dir' ? 'share folder link' : 'copy public link'}">${_si('share')}</button>
        ${it.type === 'file' ? `<button class="file-act file-comment${it.comments ? ' has' : ''}" data-act="comment" title="comments">${_si('comment')}${it.comments ? `<span class="file-cn">${it.comments}</span>` : ''}</button>` : ''}
        ${it.type === 'file' ? `<button class="file-act" data-act="versions" title="version history">${_si('history')}</button>` : ''}
        <button class="file-act" data-act="tag" title="tags & color">${_si('tag')}</button>
        <button class="file-act" data-act="rename" title="rename">${_si('edit')}</button>
        <button class="file-act" data-act="delete" title="delete">${_si('trash')}</button>
      </span>
    </div>`).join('');

  list.querySelectorAll('.file-row').forEach(row => {
    const path = row.dataset.path;
    row.querySelectorAll('.file-tag[data-tag]').forEach(tg => tg.addEventListener('click', e => {
      e.stopPropagation();   // don't open/navigate the row
      openByTag(tg.dataset.tag);
    }));
    row.querySelector('.file-name').addEventListener('click', () => {
      if (row.dataset.type === 'dir') loadFiles(path);
      else openPreview(path, row.dataset.img === '1');
    });
    row.querySelector('.file-icon').addEventListener('click', () => {
      if (row.dataset.type === 'dir') loadFiles(path);
      else openPreview(path, row.dataset.img === '1');
    });
    row.querySelectorAll('.file-act[data-act]').forEach(b => {
      b.addEventListener('click', async e => {
        e.stopPropagation();
        if (b.dataset.act === 'rename') await renameEntry(path);
        else if (b.dataset.act === 'tag') await editTags(path, row);
        else if (b.dataset.act === 'star') await toggleStar(path, b);
        else if (b.dataset.act === 'share') await shareResource(row.dataset.type === 'dir' ? 'folder' : 'file', path);
        else if (b.dataset.act === 'comment') await openComments(path, row);
        else if (b.dataset.act === 'versions') await openVersions(path, row);
        else await deleteEntry(path, row.dataset.type);
      });
    });
  });
}

async function toggleStar(path, btn) {
  const on = !btn.classList.contains('on');
  btn.classList.toggle('on', on); btn.innerHTML = _si(on ? 'star-fill' : 'star');
  try {
    await fetch(`/api/files/star?path=${encodeURIComponent(path)}`, {
      method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ starred: on }),
    });
  } catch { toast('star failed', 'error'); }
}

const COLORS = ['', 'red', 'orange', 'green', 'blue', 'purple', 'gray'];

// one shared dismissal for every file popover: drop any open one, and close on outside-click/Escape
function _closeFilePopovers() { document.querySelectorAll('.file-tagpop').forEach(p => p.remove()); }
function _armPopDismiss(pop) {
  setTimeout(() => {
    const cleanup = () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
    const onDoc = e => { if (!pop.contains(e.target)) { pop.remove(); cleanup(); } };
    const onKey = e => { if (e.key === 'Escape') { pop.remove(); cleanup(); } };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
  }, 0);
}

async function editTags(path, row) {
  _closeFilePopovers();
  let cur = { tags: [], color: '' };
  try { cur = await fetch(`/api/files/tags?path=${encodeURIComponent(path)}`).then(r => r.json()); } catch {}
  const pop = document.createElement('div');
  pop.className = 'file-tagpop';
  pop.innerHTML = `
    <input type="text" class="file-tagin" placeholder="tags, comma separated" value="${esc((cur.tags || []).join(', '))}">
    <div class="file-colors">${COLORS.map(c => `<button class="file-cdot ${c ? 'c-' + c : 'c-none'} ${c === (cur.color || '') ? 'sel' : ''}" data-c="${c}" title="${c || 'none'}"></button>`).join('')}</div>
    <div class="file-tagpop-actions"><button class="btn primary" data-save>save</button><button class="btn" data-cancel>cancel</button></div>`;
  row.appendChild(pop);
  _armPopDismiss(pop);
  let color = cur.color || '';
  pop.querySelectorAll('.file-cdot').forEach(d => d.addEventListener('click', () => {
    color = d.dataset.c;
    pop.querySelectorAll('.file-cdot').forEach(x => x.classList.toggle('sel', x === d));
  }));
  pop.querySelector('.file-tagin').focus();
  pop.querySelector('[data-cancel]').addEventListener('click', () => pop.remove());
  pop.querySelector('[data-save]').addEventListener('click', async () => {
    const tags = pop.querySelector('.file-tagin').value.split(',').map(s => s.trim()).filter(Boolean);
    const r = await fetch(`/api/files/tags?path=${encodeURIComponent(path)}`, {
      method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tags, color }),
    });
    if (r.ok) { pop.remove(); loadFiles(); } else toast('save failed', 'error');
  });
}

async function openVersions(path, row) {
  _closeFilePopovers();
  let vs = [];
  try { vs = await fetch(`/api/files/versions?path=${encodeURIComponent(path)}`).then(r => r.json()); } catch {}
  const pop = document.createElement('div');
  pop.className = 'file-tagpop file-verpop';
  const body = vs.length
    ? vs.map(v => `<div class="file-ver-row" style="display:flex;justify-content:space-between;gap:0.5rem;align-items:center;padding:0.2rem 0">
        <span style="font-size:0.66rem;color:var(--muted)">${esc(new Date(v.created_at).toLocaleString())} · ${fmtSize(v.size)}</span>
        <button class="btn" data-restore="${esc(v.id)}" style="font-size:0.62rem">restore</button></div>`).join('')
    : '<div style="font-size:0.72rem;color:var(--muted)">no earlier versions</div>';
  pop.innerHTML = body + '<div class="file-tagpop-actions"><button class="btn" data-cancel>close</button></div>';
  row.appendChild(pop);
  _armPopDismiss(pop);
  pop.querySelector('[data-cancel]').addEventListener('click', () => pop.remove());
  pop.querySelectorAll('[data-restore]').forEach(btn => btn.addEventListener('click', async () => {
    try {
      const r = await fetch('/api/files/versions/restore', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ path, id: btn.dataset.restore }) });
      if (!r.ok) throw 0;
      toast('restored', ''); pop.remove(); loadFiles();
    } catch { toast('restore failed', 'error'); }
  }));
}

async function openComments(path, row) {
  _closeFilePopovers();
  const pop = document.createElement('div');
  pop.className = 'file-tagpop file-commentpop';
  row.appendChild(pop);
  _armPopDismiss(pop);
  await _renderComments(pop, path, row);
}

function _setCommentBadge(row, n) {
  const btn = row.querySelector('.file-comment');
  if (!btn) return;
  btn.classList.toggle('has', n > 0);
  btn.innerHTML = _si('comment') + (n > 0 ? `<span class="file-cn">${n}</span>` : '');
}

async function _postComment(payload) {
  return fetch('/api/files/comments', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload),
  });
}

async function _renderComments(pop, path, row) {
  let threads = [];
  try { threads = (await fetch(`/api/files/comments?path=${encodeURIComponent(path)}`).then(r => r.json())).threads || []; }
  catch { toast('failed to load comments', 'error'); }
  const body = threads.length ? threads.map(t => `
    <div class="file-cthread${t.resolved ? ' resolved' : ''}" data-id="${esc(t.id)}">
      <div class="file-cmsg"><span class="file-cwho">${esc(t.author)}</span><span class="file-cbody">${esc(t.body)}</span>
        <span class="file-cacts"><button data-resolve title="resolve/unresolve">${_si(t.resolved ? 'check-circle' : 'check')}</button><button data-del title="delete">${_si('trash')}</button></span></div>
      ${(t.replies || []).map(rp => `<div class="file-creply"><span class="file-cwho">${esc(rp.author)}</span> ${esc(rp.body)}</div>`).join('')}
      <div class="file-creplybox"><input class="file-tagin file-creplyin" placeholder="reply…"><button class="btn" data-reply>reply</button></div>
    </div>`).join('') : '<div class="file-cnone">no comments yet</div>';
  pop.innerHTML = body
    + `<div class="file-caddbox"><input class="file-tagin file-caddin" placeholder="add a comment…"><button class="btn primary" data-add>add</button></div>`
    + '<div class="file-tagpop-actions"><button class="btn" data-close>close</button></div>';
  _setCommentBadge(row, threads.reduce((n, t) => n + 1 + (t.replies ? t.replies.length : 0), 0));
  pop.querySelector('[data-close]').addEventListener('click', () => pop.remove());
  pop.querySelector('[data-add]').addEventListener('click', async () => {
    const v = pop.querySelector('.file-caddin').value.trim();
    if (!v) return;
    await _postComment({ path, body: v });
    await _renderComments(pop, path, row);
  });
  pop.querySelectorAll('.file-cthread').forEach(th => {
    const id = th.dataset.id;
    th.querySelector('[data-resolve]')?.addEventListener('click', async () => {
      await fetch(`/api/files/comments/${id}/resolve`, { method: 'POST' });
      await _renderComments(pop, path, row);
    });
    th.querySelector('[data-del]')?.addEventListener('click', async () => {
      await fetch(`/api/files/comments/${id}`, { method: 'DELETE' });
      await _renderComments(pop, path, row);
    });
    th.querySelector('[data-reply]')?.addEventListener('click', async () => {
      const v = th.querySelector('.file-creplyin').value.trim();
      if (!v) return;
      await _postComment({ parent_id: id, body: v });
      await _renderComments(pop, path, row);
    });
  });
}

async function renameEntry(path) {
  const cur = path.split('/').pop();
  const name = await dlgPrompt('rename to:', cur);
  if (!name || name === cur) return;
  const parent = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : '';
  const r = await fetch('/api/files/rename', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ path, to: parent + name }),
  });
  if (r.ok) loadFiles(); else toast('rename failed', 'error');
}

async function deleteEntry(path, type) {
  const ok = await dlgConfirm(`delete ${type === 'dir' ? 'folder' : 'file'} "${path.split('/').pop()}"?`);
  if (!ok) return;
  const r = await fetch(`/api/files/delete?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
  if (r.ok) loadFiles(); else toast('delete failed', 'error');
}

async function openPreview(path, isImg) {
  const name = path.split('/').pop();
  $('files-preview-name').textContent = name;
  $('files-preview-dl').href = `/api/files/raw?path=${encodeURIComponent(path)}&download=1`;
  const body = $('files-preview-body');
  body.innerHTML = '<div class="files-empty">loading…</div>';
  $('files-preview-modal').style.display = 'flex';
  const raw = `/api/files/raw?path=${encodeURIComponent(path)}`;
  const ext = name.split('.').pop().toLowerCase();
  if (isImg) {
    body.innerHTML = `<img class="files-preview-img" src="${raw}" alt="">`;
    return;
  }
  if (ext === 'pdf') {
    body.innerHTML = `<iframe class="files-preview-frame" src="${raw}#view=FitH" title="${esc(name)}"></iframe>`;
    return;
  }
  if (['mp4', 'webm', 'ogv', 'mov', 'm4v'].includes(ext)) {
    body.innerHTML = `<video class="files-preview-media" src="${raw}" controls autoplay playsinline></video>`;
    return;
  }
  if (['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'].includes(ext)) {
    body.innerHTML = `<audio class="files-preview-media" src="${raw}" controls autoplay></audio>`;
    return;
  }
  if (ext === 'docx' || ext === 'xlsx') {   // 6b office preview
    try {
      const d = await fetch(`/api/files/preview?path=${encodeURIComponent(path)}`).then(r => r.json());
      if (d.error) { body.innerHTML = `<div class="files-empty">${esc(d.error)}</div>`; return; }
      if (d.kind === 'docx') {
        // d.html is already server-escaped (only <p>/<br> tags are ours)
        body.innerHTML = `<div class="files-preview-doc">${d.html || ('<pre class="files-preview-pre">' + esc(d.text || '') + '</pre>')}</div>`;
      } else if (d.kind === 'xlsx') {
        const rows = d.rows || [];
        body.innerHTML = rows.length
          ? `<table class="files-preview-table"><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`
          : '<div class="files-empty">empty sheet</div>';
      } else {
        body.innerHTML = '<div class="files-empty">no preview — download to open</div>';
      }
    } catch { body.innerHTML = '<div class="files-empty">failed to read</div>'; }
    return;
  }
  try {
    const d = await fetch(`/api/files/read?path=${encodeURIComponent(path)}`).then(r => r.json());
    if (d.is_text) {
      body.innerHTML = `<pre class="files-preview-pre">${esc(d.content)}</pre>` +
        (d.truncated ? '<div class="files-empty">… truncated</div>' : '');
    } else {
      body.innerHTML = '<div class="files-empty">no text preview — download to open</div>';
    }
  } catch { body.innerHTML = '<div class="files-empty">failed to read</div>'; }
}

function closePreview() { $('files-preview-modal').style.display = 'none'; }

async function searchFiles(q) {
  _rerender = () => searchFiles(q);
  let d;
  try { d = await fetch(`/api/files/search?q=${encodeURIComponent(q)}`).then(r => r.json()); }
  catch { return; }
  $('files-breadcrumb').innerHTML =
    `<span class="crumb" id="files-search-back" data-go="">files</span><span class="crumb-sep">/</span><span style="color:var(--muted)">search: ${esc(q)}</span>`;
  $('files-search-back')?.addEventListener('click', () => { $('files-search').value = ''; loadFiles(''); });
  const list = $('files-list');
  _setGrid(false);
  if (!d.results?.length) { list.innerHTML = '<div class="files-empty">no matches</div>'; return; }
  list.innerHTML = d.results.map(it => `
    <div class="file-row" data-path="${esc(it.path)}" data-img="${it.is_img ? 1 : 0}">
      <span class="file-icon">${_ic(it.is_img ? 'img' : 'file')}</span>
      <span class="file-name">${esc(it.path)}${it.snippet ? `<span class="file-snip">${esc(it.snippet)}</span>` : ''}</span>
      <span class="file-meta">${it.match}</span>
    </div>`).join('');
  list.querySelectorAll('.file-row').forEach(row => {
    const open = () => openPreview(row.dataset.path, row.dataset.img === '1');
    row.querySelector('.file-name').addEventListener('click', open);
    row.querySelector('.file-icon').addEventListener('click', open);
  });
}

async function newFolder() {
  const name = await dlgPrompt('new folder name:');
  if (!name) return;
  const path = _cwd ? _cwd + '/' + name : name;
  const r = await fetch('/api/files/mkdir', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (r.ok) loadFiles(); else toast('mkdir failed', 'error');
}

async function uploadFiles(fileList) {
  let n = 0;
  for (const f of fileList) {
    const fd = new FormData();
    fd.append('path', _cwd);
    fd.append('file', f);
    const r = await fetch('/api/files/upload', { method: 'POST', body: fd });
    if (r.ok) n++; else toast(`upload failed: ${f.name}`, 'error');
  }
  if (n) { toast(`uploaded ${n} file${n > 1 ? 's' : ''}`, 'success'); loadFiles(); }
}

let _inited = false;
export function initFiles() {
  if (_inited) {
    return;
  }
  _inited = true;
  // restore folder + sort from the URL so refresh / deep-link lands in the same place
  _cwd = _pathFromUrl();
  const sp = new URLSearchParams(location.search);
  const us = sp.get('sort');
  if (['name', 'size', 'mtime', 'type'].includes(us)) _sort = us;
  const uo = sp.get('order');
  if (uo === 'asc' || uo === 'desc') _order = uo;   // restore the direction too, not just the column
  try { if (localStorage.getItem('files-view') === 'grid') _view = 'grid'; } catch {}
  _syncViewToggle();
  $('files-view-toggle')?.addEventListener('click', () => {
    _view = _view === 'grid' ? 'list' : 'grid';
    try { localStorage.setItem('files-view', _view); } catch {}
    _syncViewToggle();
    if (_rerender) _rerender(); else loadFiles();
  });
  $('files-up-btn')?.addEventListener('click', () => {
    if (!_cwd) return;
    loadFiles(_cwd.includes('/') ? _cwd.slice(0, _cwd.lastIndexOf('/')) : '');
  });
  $('files-mkdir-btn')?.addEventListener('click', newFolder);
  $('files-upload-btn')?.addEventListener('click', () => $('files-upload-input')?.click());
  $('files-upload-input')?.addEventListener('change', e => { uploadFiles(e.target.files); e.target.value = ''; });
  $('files-preview-close')?.addEventListener('click', closePreview);
  const search = $('files-search');
  let st;
  search?.addEventListener('input', () => {
    clearTimeout(st);
    const q = search.value.trim();
    if (!q) { loadFiles(); return; }
    st = setTimeout(() => searchFiles(q), 300);
  });
}

// minimal monochrome icons
function _ic(kind) {
  const paths = {
    dir: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
    img: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${paths[kind] || paths.file}</svg>`;
}
