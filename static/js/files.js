import { toast } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';
import { urlForApp } from './subdomain.js';

let _cwd = '';   // current relative dir

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function fmtSize(n) {
  if (!n) return '';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  return (n / 1024 / 1024 / 1024).toFixed(1) + ' GB';
}

export async function loadFiles(path = _cwd) {
  let data;
  try {
    data = await fetch(`/api/files/list?path=${encodeURIComponent(path)}`).then(r => r.json());
  } catch { toast('failed to load files', 'error'); return; }
  if (data.detail) {  // server rejected the path — bounce to root
    _cwd = '';
    data = await fetch('/api/files/list?path=').then(r => r.json());
  } else {
    _cwd = data.path || '';
  }
  renderCrumb();
  renderList(data.items || []);
  if (!_cwd) { _injectSmartFolders(); _injectDocsShortcut(); }   // at root, surface smart views + the docs vault
}

const SMART = [
  { kind: 'recent', label: 'recent', icon: '🕘' },
  { kind: 'images', label: 'images', icon: '🖼' },
  { kind: 'documents', label: 'documents', icon: '📄' },
  { kind: 'large', label: 'large files', icon: '📦' },
];

function _injectSmartFolders() {
  const list = $('files-list');
  if (!list || list.querySelector('.files-smart-bar')) return;
  const bar = document.createElement('div');
  bar.className = 'files-smart-bar';
  bar.innerHTML = SMART.map(s => `<button class="files-smart" data-kind="${s.kind}">${s.icon} ${s.label}</button>`).join('');
  bar.querySelectorAll('.files-smart').forEach(btn =>
    btn.addEventListener('click', () => openSmart(btn.dataset.kind)));
  list.insertBefore(bar, list.firstChild);
}

async function openSmart(kind) {
  let d;
  try { d = await fetch(`/api/files/smart/${kind}`).then(r => r.json()); }
  catch { toast('failed to load', 'error'); return; }
  const label = (SMART.find(s => s.kind === kind) || {}).label || kind;
  $('files-breadcrumb').innerHTML =
    `<span class="crumb" id="files-smart-back" data-go="">files</span><span class="crumb-sep">/</span><span style="color:var(--muted)">${esc(label)}</span>`;
  $('files-smart-back')?.addEventListener('click', () => loadFiles(''));
  const list = $('files-list');
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
  row.innerHTML = `<span class="file-icon">📄</span><span class="file-name">documents</span><span class="file-meta">${n} note${n === 1 ? '' : 's'} · open in docs →</span>`;
  row.addEventListener('click', () => { try { window.location.href = urlForApp('docs'); } catch { location.hash = ''; } });
  list.insertBefore(row, list.firstChild);
}

function renderCrumb() {
  const el = $('files-breadcrumb');
  const parts = _cwd ? _cwd.split('/') : [];
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
  if (!items.length) {
    list.innerHTML = '<div class="files-empty">empty folder</div>';
    return;
  }
  list.innerHTML = items.map(it => `
    <div class="file-row" data-path="${esc(it.path)}" data-type="${it.type}" data-img="${it.is_img ? 1 : 0}">
      <span class="file-icon">${it.type === 'dir' ? _ic('dir') : _ic(it.is_img ? 'img' : 'file')}</span>
      <span class="file-name">${esc(it.name)}</span>
      <span class="file-meta">${it.type === 'file' ? fmtSize(it.size) : ''}</span>
      <span class="file-row-actions">
        ${it.type === 'file' ? `<a class="file-act" href="/api/files/raw?path=${encodeURIComponent(it.path)}&download=1" download title="download">↓</a>` : ''}
        <button class="file-act" data-act="rename" title="rename">✎</button>
        <button class="file-act" data-act="delete" title="delete">✕</button>
      </span>
    </div>`).join('');

  list.querySelectorAll('.file-row').forEach(row => {
    const path = row.dataset.path;
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
        else await deleteEntry(path, row.dataset.type);
      });
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
  let d;
  try { d = await fetch(`/api/files/search?q=${encodeURIComponent(q)}`).then(r => r.json()); }
  catch { return; }
  $('files-breadcrumb').innerHTML =
    `<span class="crumb" id="files-search-back" data-go="">files</span><span class="crumb-sep">/</span><span style="color:var(--muted)">search: ${esc(q)}</span>`;
  $('files-search-back')?.addEventListener('click', () => { $('files-search').value = ''; loadFiles(''); });
  const list = $('files-list');
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
  if (_inited) return;
  _inited = true;
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
