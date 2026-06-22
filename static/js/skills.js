// skills — manage reusable procedures (SKILL.md on disk) that the agent can
// discover + load. category rail on the left, a card grid in the middle, and the
// editor in a right slide-over drawer. library is just a mode of the same surface.
import { toast } from './util.js';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';

let _built = false;
let _cur = null;            // slug open in the drawer, or null for a new one

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const $ = id => document.getElementById(id);

async function _api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}

// each skill carries its category from the backend (the library file it came from —
// coding.json → 'coding'); custom/imported ones have none → bucketed as 'custom'.
const _CAT_LABEL = {
  'ai-prompting': 'ai & prompting', coding: 'coding', 'devops-git': 'devops & git',
  'testing-debugging': 'testing & debugging', 'data-sql': 'data & sql', utilities: 'utilities',
  research: 'research', writing: 'writing', 'marketing-content': 'marketing & content',
  communication: 'communication', creativity: 'creativity', 'design-ux': 'design & ux',
  decision: 'decisions', learning: 'learning', productivity: 'productivity',
  'life-health': 'life & health', 'personal-finance': 'personal finance',
  'career-business': 'career & business', custom: 'custom',
};
const _CAT_ORDER = [
  'ai-prompting', 'coding', 'devops-git', 'testing-debugging', 'data-sql', 'utilities',
  'research', 'writing', 'marketing-content', 'communication', 'creativity', 'design-ux',
  'decision', 'learning', 'productivity', 'life-health', 'personal-finance', 'career-business',
  'custom',
];
const _catOf = s => (s.category && _CAT_LABEL[s.category]) ? s.category : 'custom';

// ── view state ────────────────────────────────────────────────────────────────
let _state = { mode: 'installed', cat: 'all', q: '', source: null };
let _data = [];
let _sources = [];

export function initSkills() {
  const body = $('skills-body');
  if (!body) return;
  if (!_built) {
    body.innerHTML = `
      <div class="skills2">
        <div class="skl-head">
          <input id="skl-search" class="settings-input skl-search" placeholder="search skills…">
          <button class="btn primary" id="skl-new">+ new</button>
        </div>
        <div class="skl-body">
          <nav class="skl-rail" id="skl-rail"></nav>
          <div class="skl-grid" id="skl-grid"></div>
        </div>
        <div id="skl-drawer-host"></div>
      </div>`;
    let t;
    $('skl-search').oninput = e => { clearTimeout(t); t = setTimeout(() => { _state.q = e.target.value.trim(); _render(); }, 200); };
    $('skl-new').onclick = () => _openDrawer(null);
    // rail clicks (delegated): category select + library/github/upload actions
    $('skl-rail').addEventListener('click', e => {
      const cat = e.target.closest('.skl-rail-cat');
      if (cat) {
        if (cat.dataset.src) { _state.q = ''; if ($('skl-search')) $('skl-search').value = ''; _browseSource(cat.dataset.src); return; }
        _state.cat = cat.dataset.cat; _render(); return;
      }
      const act = e.target.closest('.skl-rail-act')?.dataset.act;
      if (act === 'library') _toggleLibrary();
      else if (act === 'github') _importGithub();
      else if (act === 'upload') $('skl-file')?.click();
    });
    _built = true;
  }
  _state = { mode: 'installed', cat: 'all', q: '', source: null };
  _refresh();
}

async function _refresh() {
  if (_state.mode === 'library') return _browseSource(_state.source || 'builtin');
  const grid = $('skl-grid');
  if (grid) grid.innerHTML = '<div class="skl-empty">loading…</div>';
  try { _data = await _api('/api/skills' + (_state.q ? `?q=${encodeURIComponent(_state.q)}` : '')); }
  catch { if (grid) grid.innerHTML = '<div class="skl-empty" style="color:var(--error)">failed to load</div>'; return; }
  _render();
}

function _catCounts(rows) {
  const c = { all: rows.length, pinned: 0 };
  for (const s of rows) {
    if (s.pinned) c.pinned++;
    const k = _catOf(s);
    c[k] = (c[k] || 0) + 1;
  }
  return c;
}

function _visible() {
  const ql = _state.q.toLowerCase();
  if (_state.mode === 'library') {
    if (!ql) return _data;
    return _data.filter(s => (`${s.name || ''} ${s.description || ''} ${s.when_to_use || ''}`).toLowerCase().includes(ql));
  }
  return _data.filter(s => {
    if (ql) return (`${s.name} ${s.description} ${s.when_to_use || ''}`).toLowerCase().includes(ql);
    if (_state.cat === 'pinned') return !!s.pinned;
    if (_state.cat !== 'all') return _catOf(s) === _state.cat;
    return true;
  });
}

function _render() {
  _renderRail();
  _renderGrid(_visible());
}

function _renderRail() {
  const rail = $('skl-rail');
  if (!rail) return;
  let html = '';
  if (_state.mode === 'library') {
    for (const s of _sources) {
      const active = s.id === _state.source;
      html += `<button class="skl-rail-cat${active ? ' active' : ''}" data-src="${esc(s.id)}">
          <span class="skl-rail-label">${esc(s.name)}</span><span class="skl-rail-count">${s.count || ''}</span>
        </button>`;
    }
  } else {
    const counts = _catCounts(_data);
    const row = (key, label) => counts[key]
      ? `<button class="skl-rail-cat${_state.cat === key ? ' active' : ''}" data-cat="${key}">
           <span class="skl-rail-label">${esc(label)}</span><span class="skl-rail-count">${counts[key]}</span>
         </button>` : '';
    if (_state.q) html += `<div class="skl-rail-results">results · ${_visible().length}</div>`;
    if (counts.pinned) html += row('pinned', 'pinned');
    html += row('all', 'all');
    for (const k of _CAT_ORDER) if (k !== 'custom') html += row(k, _CAT_LABEL[k]);
    html += row('custom', 'custom');
  }
  html += `<div class="skl-rail-foot">
      <button class="skl-rail-act${_state.mode === 'library' ? ' active' : ''}" data-act="library">⊕ library</button>
      <button class="skl-rail-act" data-act="github">↳ github</button>
      <button class="skl-rail-act" data-act="upload">↑ upload</button>
    </div>
    <input type="file" id="skl-file" accept=".md,.markdown,.txt" multiple style="display:none">`;
  rail.innerHTML = html;
  const f = $('skl-file'); if (f) f.onchange = _uploadFiles;
}

function _renderGrid(list) {
  const grid = $('skl-grid');
  if (!grid) return;
  if (!list.length) { grid.innerHTML = `<div class="skl-empty">${_state.q ? 'no matches' : 'nothing here'}</div>`; return; }
  if (_state.mode === 'library') {
    grid.innerHTML = list.map(_state.source === 'builtin' ? _libCard : _srcCard).join('');
  } else {
    const sorted = [...list].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
    grid.innerHTML = sorted.map(_card).join('');
  }
  _bindCards(grid);
}

function _card(s) {
  const badges = [
    s.uses ? `<span class="skl-badge" title="loaded ${s.uses}×">${s.uses}×</span>` : '',
    s.source ? '<span class="skl-badge git" title="git-backed">git</span>' : '',
  ].join('');
  const acts = _state.mode === 'library'
    ? (s.installed
        ? '<span class="skl-added" title="installed">✓ added</span>'
        : `<button class="skl-add" data-act="add" data-slug="${esc(s.slug)}">+ add</button>`)
    : `<div class="skl-card-acts">
         <button class="skl-pin${s.pinned ? ' on' : ''}" data-act="pin" title="${s.pinned ? 'unpin' : 'pin to top'}">${s.pinned ? '★' : '☆'}</button>
         <button class="skl-del-q" data-act="del" title="delete">🗑</button>
       </div>`;
  return `
    <div class="skl-card${s.slug === _cur ? ' active' : ''}" data-slug="${esc(s.slug)}">
      <div class="skl-card-top">
        <span class="skl-card-name">${esc(s.name)}</span>
        ${badges}
      </div>
      <div class="skl-card-desc">${esc(s.description) || '<em>no description</em>'}</div>
      ${acts}
    </div>`;
}

function _bindCards(root) {
  root.querySelectorAll('.skl-card').forEach(c => {
    c.onclick = e => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (_state.mode === 'library') {
        if (act === 'add') { e.stopPropagation(); _addFromLibrary(c); return; }
        _previewLibrary(c);
        return;
      }
      if (act === 'pin') { e.stopPropagation(); _togglePin(c.dataset.slug, !e.target.classList.contains('on')); }
      else if (act === 'del') { e.stopPropagation(); _deleteCard(c.dataset.slug); }
      else _openDrawer(c.dataset.slug);
    };
  });
}

async function _togglePin(slug, pinned) {
  try {
    await _api(`/api/skills/${encodeURIComponent(slug)}/pin`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ pinned }),
    });
    await _refresh();
  } catch { toast('pin failed', 'error'); }
}

async function _deleteCard(slug) {
  if (!await dlgConfirm('delete this skill?')) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(slug)}`, { method: 'DELETE' });
    toast('skill deleted', 'success');
    if (_cur === slug) _closeDrawer();
    await _refresh();
  } catch { toast('delete failed', 'error'); }
}

// ── library mode ────────────────────────────────────────────────────────────
async function _toggleLibrary() {
  if (_state.mode === 'library') {
    _state.mode = 'installed'; _state.cat = 'all'; _state.q = ''; _state.source = null;
    if ($('skl-search')) $('skl-search').value = '';
    _refresh(); return;
  }
  _state.mode = 'library'; _state.q = '';
  if ($('skl-search')) $('skl-search').value = '';
  try { _sources = await _api('/api/skills/sources'); }
  catch { _sources = [{ id: 'builtin', name: 'built-in', kind: 'builtin', count: 0 }]; }
  _browseSource('builtin');
}

async function _browseSource(id) {
  _state.source = id;
  _renderRail();
  const grid = $('skl-grid');
  if (grid) grid.innerHTML = '<div class="skl-empty">loading…</div>';
  let data;
  try { data = await _api(`/api/skills/sources/${encodeURIComponent(id)}/browse`); }
  catch { if (grid) grid.innerHTML = '<div class="skl-empty" style="color:var(--error)">couldn\'t reach this source</div>'; return; }
  _data = data.skills || [];
  _render();
}

const _libCard = s => `
  <div class="skl-card" data-slug="${esc(s.slug)}" data-kind="builtin">
    <div class="skl-card-top"><span class="skl-card-name">${esc(s.name)}</span></div>
    <div class="skl-card-desc">${esc(s.description) || ''}</div>
    ${s.installed ? '<span class="skl-added">✓ added</span>' : '<button class="skl-add" data-act="add">+ add</button>'}
  </div>`;

const _srcCard = s => `
  <div class="skl-card" data-path="${esc(s.path)}" data-url="${esc(s.import_url)}" data-kind="github">
    <div class="skl-card-top"><span class="skl-card-name">${esc(s.name)}</span></div>
    <div class="skl-card-desc skl-card-path">${esc(s.path)}</div>
    <button class="skl-add" data-act="add">+ add</button>
  </div>`;

async function _addFromLibrary(c) {
  if (c.dataset.kind === 'builtin') { await _install([c.dataset.slug]); return; }
  try {
    await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: c.dataset.url }) });
    toast('added', 'success');
    _browseSource(_state.source);
  } catch { toast('add failed', 'error'); }
}

function _previewLibrary(c) { /* Task 3 */ }

async function _install(slugs) {
  if (!slugs.length) return;
  try {
    const r = await _api('/api/skills/install', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ slugs }) });
    toast(`added ${r.installed} skill${r.installed === 1 ? '' : 's'}`, 'success');
    await _refresh();
  } catch { toast('install failed', 'error'); }
}

async function _importGithub() {
  const url = await dlgPrompt('paste a github repo, folder, or SKILL.md url', '');
  if (!url || !url.trim()) return;
  toast('fetching from github…');
  try {
    const r = await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: url.trim() }) });
    const n = r.imported.length;
    toast(`imported ${n} skill${n === 1 ? '' : 's'}${r.failed ? `, ${r.failed} failed` : ''}`, n ? 'success' : 'error');
    _refresh();
  } catch (e) { toast('github import failed: ' + e.message, 'error'); }
}

async function _uploadFiles(e) {
  const files = [...(e.target.files || [])];
  e.target.value = '';   // let the same file be re-picked later
  if (!files.length) return;
  const items = await Promise.all(files.map(async f => ({ filename: f.name, text: await f.text() })));
  try {
    const r = await _api('/api/skills/upload', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ items }) });
    const n = r.imported.length;
    toast(`uploaded ${n} skill${n === 1 ? '' : 's'}${r.failed ? `, ${r.failed} skipped` : ''}`, n ? 'success' : 'error');
    _refresh();
  } catch (e) { toast('upload failed: ' + e.message, 'error'); }
}

// ── editor drawer ───────────────────────────────────────────────────────────
function _drawerHtml() {
  return `
    <div class="skl-drawer-backdrop" id="skl-drawer-bd"></div>
    <aside class="skl-drawer" id="skl-drawer">
      <div class="skl-drawer-head">
        <span id="skl-d-heading">new skill</span>
        <button class="skl-drawer-x" id="skl-d-close" title="close">✕</button>
      </div>
      <div class="skl-drawer-body">
        <div class="s-field"><label>name</label><input id="skl-d-name" class="settings-input" placeholder="e.g. PDF form filler"></div>
        <div class="s-field"><label>description</label><input id="skl-d-desc" class="settings-input" placeholder="one line — what it does"></div>
        <div class="s-field"><label>when to use</label><input id="skl-d-when" class="settings-input" placeholder="the trigger"></div>
        <div class="s-field"><label>procedure (markdown)</label><textarea id="skl-d-body" class="settings-textarea" rows="14"></textarea></div>
        <div class="skl-drawer-acts">
          <button class="btn primary" id="skl-d-save">save</button>
          <button class="btn" id="skl-d-export" style="display:none">export</button>
          <button class="btn" id="skl-d-update" style="display:none">update</button>
          <button class="btn danger" id="skl-d-del" style="display:none">delete</button>
          <span id="skl-d-status" class="skl-status"></span>
        </div>
        <div id="skl-d-source" class="skl-source" style="display:none"></div>
      </div>
    </aside>`;
}

async function _openDrawer(slug) {
  const host = $('skl-drawer-host');
  if (!host) return;
  if (!$('skl-drawer')) {
    host.innerHTML = _drawerHtml();
    $('skl-d-close').onclick = _closeDrawer;
    $('skl-drawer-bd').onclick = _closeDrawer;
    $('skl-d-save').onclick = _save;
    $('skl-d-export').onclick = _export;
    $('skl-d-update').onclick = _update;
    $('skl-d-del').onclick = _delete;
    document.addEventListener('keydown', _drawerEsc);
  }
  let s = { name: '', description: '', when_to_use: '', body: '', source: '' };
  if (slug) {
    try { s = await _api(`/api/skills/${encodeURIComponent(slug)}`); }
    catch { toast('failed to open skill', 'error'); return; }
  }
  _cur = slug || null;
  $('skl-d-heading').textContent = slug ? 'edit skill' : 'new skill';
  $('skl-d-name').value = s.name || '';
  $('skl-d-desc').value = s.description || '';
  $('skl-d-when').value = s.when_to_use || '';
  $('skl-d-body').value = s.body || '';
  $('skl-d-status').textContent = '';
  $('skl-d-del').style.display = slug ? '' : 'none';
  $('skl-d-export').style.display = slug ? '' : 'none';
  if (s.source) {
    $('skl-d-update').style.display = ''; $('skl-d-source').style.display = '';
    $('skl-d-source').innerHTML = `git-backed · <a href="${esc(s.source)}" target="_blank" rel="noopener">${esc(s.source)}</a>`;
  } else { $('skl-d-update').style.display = 'none'; $('skl-d-source').style.display = 'none'; }
  $('skl-drawer').classList.add('open');
  $('skl-drawer-bd').classList.add('open');
  document.querySelectorAll('.skl-card').forEach(c => c.classList.toggle('active', c.dataset.slug === slug));
  $('skl-d-name').focus();
}

function _closeDrawer() {
  $('skl-drawer')?.classList.remove('open');
  $('skl-drawer-bd')?.classList.remove('open');
  _cur = null;
  document.querySelectorAll('.skl-card.active').forEach(c => c.classList.remove('active'));
}
function _drawerEsc(e) { if (e.key === 'Escape' && $('skl-drawer')?.classList.contains('open')) _closeDrawer(); }

async function _save() {
  const name = $('skl-d-name').value.trim();
  if (!name) { toast('give the skill a name', 'error'); return; }
  const payload = { name, description: $('skl-d-desc').value.trim(), when_to_use: $('skl-d-when').value.trim(), body: $('skl-d-body').value };
  try {
    const res = _cur
      ? await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) })
      : await _api('/api/skills', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    _cur = res.slug;
    $('skl-d-del').style.display = ''; $('skl-d-export').style.display = '';
    $('skl-d-heading').textContent = 'edit skill';
    $('skl-d-status').textContent = 'saved';
    setTimeout(() => { if ($('skl-d-status')) $('skl-d-status').textContent = ''; }, 1500);
    toast('skill saved', 'success');
    await _refresh();
  } catch (e) { toast('save failed: ' + e.message, 'error'); }
}

async function _delete() {
  if (!_cur) return;
  if (!await dlgConfirm('delete this skill?')) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'DELETE' });
    toast('skill deleted', 'success');
    _closeDrawer();
    await _refresh();
  } catch { toast('delete failed', 'error'); }
}

function _export() {
  if (!_cur) return;
  const a = document.createElement('a');
  a.href = `/api/skills/${encodeURIComponent(_cur)}/export`;
  a.download = `${_cur}.SKILL.md`;
  document.body.appendChild(a); a.click(); a.remove();
}

async function _update() {
  if (!_cur) return;
  toast('updating from source…');
  try {
    const r = await _api(`/api/skills/${encodeURIComponent(_cur)}/update`, { method: 'POST' });
    toast(r.updated ? 'updated from source' : 'no source to update from', r.updated ? 'success' : '');
    if (r.updated) { _openDrawer(_cur); await _refresh(); }
  } catch (e) { toast('update failed: ' + e.message, 'error'); }
}
