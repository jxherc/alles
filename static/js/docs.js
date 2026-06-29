// thin docs reader over the markdown vault. browse + read (rendered) + search/tags +
// backlinks + ask + basic file mgmt + open-in-obsidian. editing happens in Obsidian.
import { mdToHtml, enhanceMarkdown, toast } from './util.js';
import { loadNotes } from './notes.js';

let _section = 'docs';
let _cur = null;        // open doc rel-path, or null
let _tree = null;
let _wired = false;
let _es = null;         // live file-watch stream
let _deepLinked = false;

const $ = id => document.getElementById(id);
// several of these panes default to display:none in css (the old editor toggled classes),
// so show() must set a real display value, not '' (which falls back to none)
const show = (el, on, disp = 'flex') => { if (el) el.style.display = on ? disp : 'none'; };
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const stem = p => (p || '').split('/').pop().replace(/\.(md|markdown)$/i, '');

async function _get(path) { try { return await (await fetch(path)).json(); } catch { return null; } }

export function initDocs() {
  _wire();
  window._reloadDocs = () => { loadTree(); if (_cur) openNote(_cur); };
  loadTree();
  loadTags();
  showSection('docs');
  _watch();
  // the obsidian plugin links here as /?app=wiki#<note name> — open it (once)
  if (!_deepLinked && location.hash.length > 1) {
    _deepLinked = true;
    openByName(decodeURIComponent(location.hash.slice(1)));
  }
}

// live two-way: refresh when files change on disk (e.g. edited in Obsidian)
function _watch() {
  if (_es || typeof EventSource === 'undefined') return;
  try {
    _es = new EventSource('/api/vault-md/stream');
    _es.onmessage = e => {
      let d; try { d = JSON.parse(e.data); } catch { return; }
      const ch = [...(d.changed || []), ...(d.removed || [])];
      if (!ch.length) return;
      if ($('wiki-view')?.style.display === 'none') return;  // not on screen
      if (_section === 'notes') { window._reloadNotes?.(); return; }
      loadTree();
      if (_cur && ch.includes(_cur)) openNote(_cur);  // re-read the open doc
    };
    _es.onerror = () => {};  // EventSource auto-reconnects
  } catch {}
}

function _wire() {
  if (_wired) return;
  _wired = true;

  // docs / notes section toggle
  document.querySelectorAll('#docs-sections .docs-sec-btn').forEach(b =>
    b.addEventListener('click', () => showSection(b.dataset.section)));
  $('docs-home-notes')?.addEventListener('click', () => showSection('notes'));

  // search (debounced) — empty resets to the tree
  let t;
  const onSearch = e => { clearTimeout(t); t = setTimeout(() => doSearch(e.target.value.trim()), 200); };
  $('wiki-search')?.addEventListener('input', onSearch);
  $('docs-home-search')?.addEventListener('input', onSearch);

  // file mgmt
  $('wiki-new-btn')?.addEventListener('click', newDoc);
  $('wiki-empty-new')?.addEventListener('click', newDoc);
  $('wiki-folder-btn')?.addEventListener('click', newFolder);
  $('wiki-rename-btn')?.addEventListener('click', renameCurrent);
  $('wiki-delete-btn')?.addEventListener('click', deleteCurrent);
  $('wiki-obsidian-btn')?.addEventListener('click', openInObsidian);
  $('wiki-tree-toggle')?.addEventListener('click', () =>
    document.querySelector('.wiki-tree-panel')?.classList.toggle('hidden'));

  // ask
  $('wiki-ask-btn')?.addEventListener('click', () => {
    const a = $('wiki-ask'); const on = a.style.display === 'none' || !a.style.display;
    show(a, on, 'block'); if (on) $('wiki-ask-input')?.focus();
  });
  $('wiki-ask-go')?.addEventListener('click', runAsk);
  $('wiki-ask-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') runAsk(); });

  // clicking a [[wikilink]] in the rendered doc
  $('wiki-preview')?.addEventListener('click', e => {
    const a = e.target.closest('a[href^="#wiki="]');
    if (a) { e.preventDefault(); openByName(decodeURIComponent(a.getAttribute('href').slice(6))); }
  });
}

// ── sections ────────────────────────────────────────────────────────────────
function showSection(sec) {
  _section = sec;
  document.querySelectorAll('#docs-sections .docs-sec-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.section === sec));
  const docs = sec === 'docs';
  show(document.querySelector('.wiki-tree-panel'), docs);
  show($('wiki-notes'), !docs, 'block');
  show(document.querySelector('.docs-editor-head'), docs);
  if (docs) {
    show($('wiki-empty-state'), !_cur);
    show($('wiki-preview'), !!_cur, 'block');
    show($('wiki-backlinks'), !!_cur, 'block');
  } else {
    show($('wiki-empty-state'), false);
    show($('wiki-preview'), false);
    show($('wiki-backlinks'), false);
    show($('wiki-ask'), false);
    loadNotes();
  }
}

// ── tree ─────────────────────────────────────────────────────────────────────
export async function loadTree() {
  _tree = await _get('/api/vault-md/tree');
  renderTree(_tree?.items || []);
  paintRecent(_tree?.items || []);
}

function renderTree(items) {
  const box = $('wiki-tree');
  if (!box) return;
  box.innerHTML = items.length ? items.map(rowHtml).join('') : '<div class="muted" style="padding:8px">no docs yet</div>';
  box.querySelectorAll('[data-file]').forEach(el =>
    el.addEventListener('click', () => openNote(el.dataset.file)));
  box.querySelectorAll('[data-dir]').forEach(el =>
    el.addEventListener('click', () => el.parentElement.classList.toggle('open')));
}

function rowHtml(it) {
  if (it.type === 'dir') {
    return `<div class="wiki-dir"><div class="wiki-dir-head" data-dir="${esc(it.path)}">▸ ${esc(it.name)}</div>` +
      `<div class="wiki-dir-kids">${(it.children || []).map(rowHtml).join('')}</div></div>`;
  }
  return `<div class="wiki-file${_cur === it.path ? ' active' : ''}" data-file="${esc(it.path)}">${esc(it.name)}</div>`;
}

function _flat(items, out = []) {
  for (const it of items) {
    if (it.type === 'dir') _flat(it.children || [], out);
    else out.push(it);
  }
  return out;
}

function paintRecent(items) {
  const grid = $('wiki-empty-recent');
  if (!grid) return;
  const recent = _flat(items).sort((a, b) => (b.mtime || 0) - (a.mtime || 0)).slice(0, 12);
  grid.innerHTML = recent.map(f =>
    `<div class="docs-home-card" data-file="${esc(f.path)}"><div class="dhc-title">${esc(f.name)}</div></div>`).join('');
  grid.querySelectorAll('[data-file]').forEach(el =>
    el.addEventListener('click', () => openNote(el.dataset.file)));
}

// ── read ──────────────────────────────────────────────────────────────────────
function _prep(md) {
  // obsidian embeds + wikilinks (mdToHtml doesn't know them) → things it does know
  md = md.replace(/!\[\[([^\]]+)\]\]/g, (m, a) => {
    const name = a.split('|')[0].trim();
    return `![${name}](/api/vault-md/raw?path=${encodeURIComponent(name)})`;
  });
  md = md.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (m, name, alias) =>
    `[${(alias || name).trim()}](#wiki=${encodeURIComponent(name.trim())})`);
  return md;
}

export async function openNote(path) {
  if (!path) return;
  if (_section !== 'docs') showSection('docs');
  const doc = await _get('/api/vault-md/file?path=' + encodeURIComponent(path));
  if (!doc || !doc.exists) { toast('couldn\'t open that doc', 'error'); return; }
  _cur = doc.path || path;
  const pv = $('wiki-preview');
  pv.innerHTML = mdToHtml(_prep(doc.content || ''));
  enhanceMarkdown(pv);
  if ($('wiki-current')) $('wiki-current').textContent = stem(_cur);
  show($('wiki-empty-state'), false);
  show(pv, true, 'block');
  loadBacklinks();
  // mark the active row
  document.querySelectorAll('#wiki-tree .wiki-file').forEach(el =>
    el.classList.toggle('active', el.dataset.file === _cur));
}

async function openByName(name) {
  const r = await _get('/api/vault-md/search?q=' + encodeURIComponent(name));
  const hits = r?.results || [];
  const hit = hits.find(h => (h.name || '').toLowerCase() === name.toLowerCase()) || hits[0];
  if (hit) openNote(hit.path);
  else toast(`"${name}" not found`, '');
}

async function loadBacklinks() {
  const box = $('wiki-backlinks');
  if (!box || !_cur) return;
  const r = await _get('/api/vault-md/backlinks?name=' + encodeURIComponent(stem(_cur)));
  const bl = r?.backlinks || [];
  if (!bl.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="wiki-bl-head">linked from</div>` + bl.map(b =>
    `<div class="wiki-bl" data-file="${esc(b.path)}">${esc(b.name)}</div>`).join('');
  box.querySelectorAll('[data-file]').forEach(el =>
    el.addEventListener('click', () => openNote(el.dataset.file)));
}

// ── search + tags ─────────────────────────────────────────────────────────────
async function doSearch(q) {
  if (!q) { renderTree(_tree?.items || []); return; }
  const r = await _get('/api/vault-md/grep?q=' + encodeURIComponent(q));
  const hits = r?.results || [];
  const box = $('wiki-tree');
  box.innerHTML = hits.length
    ? hits.map(h => `<div class="wiki-file" data-file="${esc(h.path)}">${esc(h.name)}` +
        (h.context ? `<div class="wiki-file-ctx">${esc(h.context)}</div>` : '') + `</div>`).join('')
    : '<div class="muted" style="padding:8px">no matches</div>';
  box.querySelectorAll('[data-file]').forEach(el =>
    el.addEventListener('click', () => openNote(el.dataset.file)));
}

async function loadTags() {
  const box = $('wiki-tags');
  if (!box) return;
  const r = await _get('/api/vault-md/tags');
  const tags = r?.tags || [];
  box.innerHTML = tags.slice(0, 40).map(t =>
    `<button class="wiki-tag" data-tag="${esc(t.tag)}">#${esc(t.tag)} ${t.count}</button>`).join('');
  box.querySelectorAll('[data-tag]').forEach(el =>
    el.addEventListener('click', () => filterByTag(el.dataset.tag)));
}

async function filterByTag(tag) {
  const r = await _get('/api/vault-md/tag?tag=' + encodeURIComponent(tag));
  const notes = r?.notes || [];
  const box = $('wiki-tree');
  box.innerHTML = `<div class="wiki-tag-hdr">#${esc(tag)} · <a href="#" id="wiki-tag-clear">clear</a></div>` +
    notes.map(n => `<div class="wiki-file" data-file="${esc(n.path)}">${esc(n.name)}</div>`).join('');
  box.querySelector('#wiki-tag-clear')?.addEventListener('click', e => { e.preventDefault(); renderTree(_tree?.items || []); });
  box.querySelectorAll('[data-file]').forEach(el =>
    el.addEventListener('click', () => openNote(el.dataset.file)));
}

// ── ask ───────────────────────────────────────────────────────────────────────
async function runAsk() {
  const q = $('wiki-ask-input')?.value.trim();
  const out = $('wiki-ask-results');
  if (!q || !out) return;
  out.innerHTML = '<div class="muted">thinking…</div>';
  const r = await _get('/api/vault-md/ask?q=' + encodeURIComponent(q));
  const hits = r?.sources || [];
  out.innerHTML = hits.length
    ? hits.map(h => `<div class="wiki-ask-hit" data-file="${esc(h.ref)}"><div class="waih-ref">${esc(stem(h.ref))}</div>` +
        `<div class="waih-snip">${esc((h.chunk || '').slice(0, 200))}</div></div>`).join('')
    : '<div class="muted">nothing found</div>';
  out.querySelectorAll('[data-file]').forEach(el =>
    el.addEventListener('click', () => openNote(el.dataset.file)));
}

// ── file management (content edited in Obsidian) ──────────────────────────────
async function _post(path, body) {
  try {
    const r = await fetch(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    return await r.json();
  } catch { return null; }
}

async function newDoc() {
  const name = prompt('new doc name (no extension):');
  if (!name) return;
  const out = await _post('/api/vault-md/file', { path: name });
  await loadTree();
  if (out?.path) openNote(out.path);
}

async function newFolder() {
  const name = prompt('new folder name:');
  if (!name) return;
  await _post('/api/vault-md/folder', { path: name });
  loadTree();
}

async function renameCurrent() {
  if (!_cur) return;
  const next = prompt('rename to:', stem(_cur));
  if (!next) return;
  const dir = _cur.includes('/') ? _cur.slice(0, _cur.lastIndexOf('/') + 1) : '';
  const out = await _post('/api/vault-md/rename', { path: _cur, new_path: dir + next });
  await loadTree();
  if (out?.path) openNote(out.path);
}

async function deleteCurrent() {
  if (!_cur || !confirm(`delete "${stem(_cur)}"? (edit/restore in Obsidian)`)) return;
  await fetch('/api/vault-md/file?path=' + encodeURIComponent(_cur), { method: 'DELETE' });
  _cur = null;
  $('wiki-preview').innerHTML = '';
  $('wiki-backlinks').innerHTML = '';
  if ($('wiki-current')) $('wiki-current').textContent = 'no doc open';
  show($('wiki-preview'), false);
  show($('wiki-empty-state'), true);
  loadTree();
}

async function openInObsidian() {
  const r = await _get('/api/vault-location' + (_cur ? '?path=' + encodeURIComponent(_cur) : ''));
  if (r?.obsidian) location.href = r.obsidian;
}
