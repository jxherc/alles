// obsidian-style vault: file tree + editor + live preview with [[wikilinks]] + backlinks
import { mdToHtml, toast } from './util.js';
import { prompt as dlgPrompt, confirm as dlgConfirm } from './dialog.js';

let _cur = null;          // current note path
let _saveT = 0;
let _inited = false;

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export function initVault() {
  if (_inited) { loadTree(); return; }
  _inited = true;
  $('wiki-new-btn')?.addEventListener('click', newNote);
  $('wiki-delete-btn')?.addEventListener('click', deleteCurrent);
  $('wiki-export-btn')?.addEventListener('click', exportDocx);
  $('wiki-folder-btn')?.addEventListener('click', newFolder);
  $('wiki-graph-btn')?.addEventListener('click', openGraph);
  $('wiki-graph-close')?.addEventListener('click', () => { $('wiki-graph').style.display = 'none'; });
  let _searchT = 0;
  $('wiki-search')?.addEventListener('input', e => {
    clearTimeout(_searchT);
    _searchT = setTimeout(() => doSearch(e.target.value.trim()), 160);
  });
  $('wiki-preview')?.addEventListener('click', e => {
    const tag = e.target.closest('.md-tag');
    if (tag) { filterByTag(tag.dataset.tag); }
  });
  $('wiki-preview-toggle')?.addEventListener('click', () => {
    $('wiki-view').classList.toggle('preview-only');
  });
  const src = $('wiki-source');
  src?.addEventListener('input', () => {
    renderPreview();
    queueSave();
    autocomplete();
  });
  src?.addEventListener('keydown', acKeydown);
  $('wiki-preview')?.addEventListener('click', e => {
    const a = e.target.closest('.wikilink');
    if (a) { e.preventDefault(); openByName(a.dataset.note); }
  });
  $('wiki-ai-send')?.addEventListener('click', aiEdit);
  $('wiki-ai-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') aiEdit(); });
  loadTree();
}

async function aiEdit() {
  if (!_cur) { toast('open a note first', 'error'); return; }
  const inp = $('wiki-ai-input');
  const instruction = inp.value.trim();
  if (!instruction) return;
  inp.value = '';
  const src = $('wiki-source');
  src.value = '';
  $('wiki-save-status').textContent = 'ai editing…';
  try {
    const r = await fetch('/api/vault-md/ai-edit', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ path: _cur, instruction }),
    });
    if (!r.ok) { toast('ai edit failed', 'error'); $('wiki-save-status').textContent = ''; return; }
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const raw = line.slice(5).trim();
        if (raw === '[DONE]') continue;
        try { const c = JSON.parse(raw); if (c.delta) { src.value += c.delta; renderPreview(); } } catch {}
      }
    }
    $('wiki-save-status').textContent = 'saved';   // backend persisted it
    loadBacklinks();
  } catch { toast('ai edit failed', 'error'); $('wiki-save-status').textContent = ''; }
}

let _activeTag = null;

async function loadTree() {
  _activeTag = null;
  const search = $('wiki-search');
  if (search) search.value = '';
  loadTags();
  const el = $('wiki-tree');
  if (!el) return;
  try {
    const t = await fetch('/api/vault-md/tree').then(r => r.json());
    el.innerHTML = t.items.length ? renderItems(t.items, 0) : '<div class="wiki-empty">empty vault — create a note</div>';
    el.querySelectorAll('.wiki-file').forEach(f =>
      f.addEventListener('click', () => openFile(f.dataset.path)));
  } catch { el.innerHTML = '<div class="wiki-empty">failed to load</div>'; }
}

async function loadTags() {
  const el = $('wiki-tags');
  if (!el) return;
  try {
    const d = await fetch('/api/vault-md/tags').then(r => r.json());
    el.innerHTML = (d.tags || []).map(t =>
      `<span class="wiki-tag${t.tag === _activeTag ? ' active' : ''}" data-tag="${esc(t.tag)}">#${esc(t.tag)} <em>${t.count}</em></span>`).join('');
    el.querySelectorAll('.wiki-tag').forEach(t =>
      t.addEventListener('click', () => filterByTag(t.dataset.tag)));
  } catch {}
}

async function filterByTag(tag) {
  if (_activeTag === tag) { loadTree(); return; }   // toggle off
  _activeTag = tag;
  loadTags();
  const el = $('wiki-tree');
  try {
    const d = await fetch(`/api/vault-md/tag?tag=${encodeURIComponent(tag)}`).then(r => r.json());
    el.innerHTML = `<div class="wiki-filter-note">#${esc(tag)} · ${d.notes.length}</div>`
      + d.notes.map(n => `<div class="wiki-file" data-path="${esc(n.path)}">${esc(n.name)}</div>`).join('');
    el.querySelectorAll('.wiki-file').forEach(f => f.addEventListener('click', () => openFile(f.dataset.path)));
  } catch {}
}

async function doSearch(q) {
  if (!q) { loadTree(); return; }
  const el = $('wiki-tree');
  try {
    const d = await fetch(`/api/vault-md/grep?q=${encodeURIComponent(q)}`).then(r => r.json());
    if (!d.results.length) { el.innerHTML = '<div class="wiki-empty">no matches</div>'; return; }
    el.innerHTML = d.results.map(r =>
      `<div class="wiki-file wiki-search-hit" data-path="${esc(r.path)}"><div>${esc(r.name)}</div>${r.context ? `<span>${esc(r.context)}</span>` : ''}</div>`).join('');
    el.querySelectorAll('.wiki-file').forEach(f => f.addEventListener('click', () => openFile(f.dataset.path)));
  } catch { el.innerHTML = '<div class="wiki-empty">search failed</div>'; }
}

async function newFolder() {
  const name = await dlgPrompt('folder name:');
  if (!name?.trim()) return;
  await fetch('/api/vault-md/folder', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ path: name.trim() }),
  });
  loadTree();
}

// ── graph view ────────────────────────────────────────────────────────────
async function openGraph() {
  const box = $('wiki-graph');
  box.style.display = 'flex';
  try {
    const data = await fetch('/api/vault-md/graph').then(r => r.json());
    renderGraph(data);
  } catch { toast('graph failed', 'error'); }
}

function renderGraph(data) {
  const svg = $('wiki-graph-svg');
  const W = svg.clientWidth || 700, H = svg.clientHeight || 520;
  const nodes = data.nodes.map(n => ({ ...n, x: W / 2 + (Math.random() - 0.5) * 200, y: H / 2 + (Math.random() - 0.5) * 200, vx: 0, vy: 0 }));
  const idx = {}; nodes.forEach(n => idx[n.id] = n);
  const edges = data.edges.filter(e => idx[e.source] && idx[e.target]);
  // tiny force sim
  for (let it = 0; it < 140; it++) {
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y; const d = Math.hypot(dx, dy) || 1;
      const f = 2600 / (d * d); dx /= d; dy /= d; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
    for (const e of edges) {
      const a = idx[e.source], b = idx[e.target]; let dx = b.x - a.x, dy = b.y - a.y; const d = Math.hypot(dx, dy) || 1;
      const f = (d - 90) * 0.012; dx /= d; dy /= d; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
    for (const n of nodes) {
      n.vx += (W / 2 - n.x) * 0.003; n.vy += (H / 2 - n.y) * 0.003;
      n.x += n.vx * 0.82; n.y += n.vy * 0.82; n.vx *= 0.82; n.vy *= 0.82;
      n.x = Math.max(24, Math.min(W - 24, n.x)); n.y = Math.max(24, Math.min(H - 24, n.y));
    }
  }
  let html = '';
  for (const e of edges) html += `<line x1="${idx[e.source].x.toFixed(1)}" y1="${idx[e.source].y.toFixed(1)}" x2="${idx[e.target].x.toFixed(1)}" y2="${idx[e.target].y.toFixed(1)}" class="wg-edge"/>`;
  for (const n of nodes) {
    const r = 4 + Math.min(11, n.degree * 1.6);
    html += `<g class="wg-node" data-path="${esc(n.path)}"><circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${r}"/><text x="${n.x.toFixed(1)}" y="${(n.y - r - 4).toFixed(1)}">${esc(n.id)}</text></g>`;
  }
  svg.innerHTML = html;
  svg.querySelectorAll('.wg-node').forEach(g =>
    g.addEventListener('click', () => { $('wiki-graph').style.display = 'none'; openFile(g.dataset.path); }));
}

function renderItems(items, depth) {
  return items.map(it => {
    const pad = `style="padding-left:${0.4 + depth * 0.7}rem"`;
    if (it.type === 'dir') {
      return `<div class="wiki-dir" ${pad}>▸ ${esc(it.name)}</div>` + renderItems(it.children || [], depth + 1);
    }
    const active = it.path === _cur ? ' active' : '';
    return `<div class="wiki-file${active}" data-path="${esc(it.path)}" ${pad}>${esc(it.name)}</div>`;
  }).join('');
}

async function openFile(path) {
  try {
    const d = await fetch(`/api/vault-md/file?path=${encodeURIComponent(path)}`).then(r => r.json());
    _cur = d.path || path;
    $('wiki-source').value = d.content || '';
    $('wiki-current').textContent = _cur.replace(/\.md$/, '');
    renderPreview();
    loadBacklinks();
    document.querySelectorAll('.wiki-file').forEach(f => f.classList.toggle('active', f.dataset.path === _cur));
  } catch { toast('failed to open note', 'error'); }
}

async function openByName(name) {
  // find an existing note by stem, else create it
  const res = await fetch(`/api/vault-md/search?q=${encodeURIComponent(name)}`).then(r => r.json()).catch(() => ({ results: [] }));
  const hit = (res.results || []).find(r => r.name.toLowerCase() === name.toLowerCase());
  if (hit) return openFile(hit.path);
  await fetch('/api/vault-md/file', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ path: name }),
  });
  await loadTree();
  openFile(name.endsWith('.md') ? name : name + '.md');
}

function renderPreview() {
  const src = $('wiki-source').value;
  let html = mdToHtml(src);
  // [[note]] and [[note|alias]] -> clickable links
  html = html.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g,
    (_, name, alias) => `<a class="wikilink" data-note="${esc(name.trim())}">${esc((alias || name).trim())}</a>`);
  // #tags -> clickable (not markdown headings, which have a space after #)
  html = html.replace(/(^|[\s(])#([A-Za-z0-9][A-Za-z0-9_/\-]*)/g,
    (_, pre, tag) => `${pre}<span class="md-tag" data-tag="${esc(tag)}">#${esc(tag)}</span>`);
  $('wiki-preview').innerHTML = html;
}

function queueSave() {
  if (!_cur) return;
  $('wiki-save-status').textContent = 'saving…';
  clearTimeout(_saveT);
  _saveT = setTimeout(async () => {
    try {
      await fetch('/api/vault-md/file', {
        method: 'PUT', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ path: _cur, content: $('wiki-source').value }),
      });
      $('wiki-save-status').textContent = 'saved';
      loadBacklinks();
    } catch { $('wiki-save-status').textContent = 'save failed'; }
  }, 600);
}

async function loadBacklinks() {
  if (!_cur) return;
  const name = _cur.split('/').pop().replace(/\.md$/, '');
  try {
    const d = await fetch(`/api/vault-md/backlinks?name=${encodeURIComponent(name)}`).then(r => r.json());
    const el = $('wiki-backlinks');
    if (!d.backlinks.length) { el.innerHTML = '<span class="wiki-bl-empty">no backlinks</span>'; return; }
    el.innerHTML = `<div class="wiki-bl-head">${d.backlinks.length} backlink${d.backlinks.length > 1 ? 's' : ''}</div>` +
      d.backlinks.map(b => `<div class="wiki-bl" data-path="${esc(b.path)}"><b>${esc(b.name)}</b> <span>${esc(b.context)}</span></div>`).join('');
    el.querySelectorAll('.wiki-bl').forEach(b => b.addEventListener('click', () => openFile(b.dataset.path)));
  } catch {}
}

async function exportDocx() {
  if (!_cur) { toast('open a note first', 'error'); return; }
  try {
    const r = await fetch(`/api/vault-md/export-docx?path=${encodeURIComponent(_cur)}`);
    if (!r.ok) throw new Error();
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = _cur.split('/').pop().replace(/\.md$/, '') + '.docx';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast('exported .docx', 'success');
  } catch { toast('export failed', 'error'); }
}

async function newNote() {
  const name = await dlgPrompt('note name (folders ok, e.g. ideas/new):');
  if (!name?.trim()) return;
  await fetch('/api/vault-md/file', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ path: name.trim() }),
  });
  await loadTree();
  openFile(name.trim().endsWith('.md') ? name.trim() : name.trim() + '.md');
}

async function deleteCurrent() {
  if (!_cur) return;
  if (!await dlgConfirm(`delete ${_cur}?`)) return;
  await fetch(`/api/vault-md/file?path=${encodeURIComponent(_cur)}`, { method: 'DELETE' });
  _cur = null;
  $('wiki-source').value = '';
  $('wiki-preview').innerHTML = '';
  $('wiki-current').textContent = 'no note open';
  $('wiki-backlinks').innerHTML = '';
  loadTree();
}

// ── [[ autocomplete ───────────────────────────────────────────────────────
let _acItems = [], _acSel = 0, _acStart = -1;

async function autocomplete() {
  const src = $('wiki-source');
  const v = src.value, pos = src.selectionStart;
  const open = v.lastIndexOf('[[', pos - 1);
  if (open < 0 || v.slice(open, pos).includes(']]')) return hideAc();
  const q = v.slice(open + 2, pos);
  if (q.includes('\n')) return hideAc();
  _acStart = open;
  const res = await fetch(`/api/vault-md/search?q=${encodeURIComponent(q)}`).then(r => r.json()).catch(() => ({ results: [] }));
  _acItems = res.results || [];
  if (!_acItems.length) return hideAc();
  _acSel = 0;
  renderAc();
}

function renderAc() {
  const box = $('wiki-autocomplete');
  box.innerHTML = _acItems.map((it, i) =>
    `<div class="wiki-ac-item${i === _acSel ? ' active' : ''}" data-i="${i}">${esc(it.name)}</div>`).join('');
  box.style.display = 'block';
  box.querySelectorAll('.wiki-ac-item').forEach(el =>
    el.addEventListener('mousedown', e => { e.preventDefault(); pickAc(+el.dataset.i); }));
}

function hideAc() { $('wiki-autocomplete').style.display = 'none'; _acItems = []; }

function acKeydown(e) {
  if ($('wiki-autocomplete').style.display !== 'block' || !_acItems.length) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); _acSel = (_acSel + 1) % _acItems.length; renderAc(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); _acSel = (_acSel - 1 + _acItems.length) % _acItems.length; renderAc(); }
  else if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickAc(_acSel); }
  else if (e.key === 'Escape') hideAc();
}

function pickAc(i) {
  const src = $('wiki-source');
  const name = _acItems[i].name;
  const v = src.value, pos = src.selectionStart;
  src.value = v.slice(0, _acStart) + `[[${name}]]` + v.slice(pos);
  const caret = _acStart + name.length + 4;
  src.setSelectionRange(caret, caret);
  hideAc();
  renderPreview();
  queueSave();
  src.focus();
}
