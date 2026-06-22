// skills — manage reusable procedures (SKILL.md on disk) that the agent can
// discover + load. master/detail: pick from the list, edit on the right.
import { toast } from './util.js';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';

let _built = false;
let _cur = null;            // slug being edited, or null for a new one

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const $ = id => document.getElementById(id);

async function _api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}

export function initSkills() {
  const body = $('skills-body');
  if (!body) return;
  if (!_built) {
    body.innerHTML = `
      <div class="skills-wrap">
        <div class="skills-side">
          <input id="skl-search" class="settings-input" placeholder="search skills…">
          <button class="btn" id="skl-new" style="width:100%;margin:0.5rem 0 0.35rem">+ new skill</button>
          <button class="btn" id="skl-library" style="width:100%;margin:0 0 0.35rem">⊕ browse library</button>
          <div class="skl-import-row">
            <button class="btn" id="skl-github" title="import SKILL.md from a github repo, folder, or file">↳ github</button>
            <button class="btn" id="skl-upload" title="upload SKILL.md file(s)">↑ upload</button>
          </div>
          <input type="file" id="skl-file" accept=".md,.markdown,.txt" multiple style="display:none">
          <div id="skl-list" class="skl-list"></div>
        </div>
        <div class="skills-main">
          <div class="s-field"><label>name</label><input id="skl-name" class="settings-input" placeholder="e.g. PDF form filler"></div>
          <div class="s-field"><label>description</label><input id="skl-desc" class="settings-input" placeholder="one line — what it does"></div>
          <div class="s-field"><label>when to use</label><input id="skl-when" class="settings-input" placeholder="the trigger — when the agent should reach for this"></div>
          <div class="s-field"><label>procedure (markdown)</label><textarea id="skl-bodytext" class="settings-textarea" rows="14" placeholder="the steps, in plain markdown…"></textarea></div>
          <div class="skl-actions">
            <button class="btn primary" id="skl-save">save</button>
            <button class="btn" id="skl-export" style="display:none" title="download this skill's SKILL.md to share">export</button>
            <button class="btn" id="skl-update" style="display:none" title="re-pull this skill from its git source">update</button>
            <button class="btn danger" id="skl-del" style="display:none">delete</button>
            <span id="skl-status" class="skl-status"></span>
          </div>
          <div id="skl-source" class="skl-source" style="display:none"></div>
        </div>
      </div>`;
    $('skl-new').onclick = () => _editNew();
    $('skl-library').onclick = _showLibrary;
    $('skl-github').onclick = _importGithub;
    $('skl-upload').onclick = () => $('skl-file').click();
    $('skl-file').onchange = _uploadFiles;
    $('skl-save').onclick = _save;
    $('skl-export').onclick = _export;
    $('skl-update').onclick = _update;
    $('skl-del').onclick = _delete;
    let t;
    $('skl-search').oninput = e => { clearTimeout(t); t = setTimeout(() => _loadList(e.target.value), 200); };
    _built = true;
  }
  _editNew();
  _loadList('');
}

// browse-by-category: each skill carries its real category from the backend (the
// library file it came from — coding.json → 'coding'); custom/imported ones have none.
// label + display order for the known library categories; anything else → 'custom'.
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

const _collapsed = () => { try { return JSON.parse(localStorage.getItem('skl-collapsed') || '{}'); } catch { return {}; } };
const _setCollapsed = m => localStorage.setItem('skl-collapsed', JSON.stringify(m));

// pinned skills get pulled into their own group on top, the rest bucket by category
function _groupRows(skills) {
  const buckets = {};
  for (const s of skills) { if (s.pinned) continue; (buckets[_catOf(s)] ||= []).push(s); }
  const groups = [];
  const pinned = skills.filter(s => s.pinned);
  if (pinned.length) groups.push({ key: 'pinned', label: 'pinned', items: pinned });
  for (const k of _CAT_ORDER) if (buckets[k]?.length) groups.push({ key: k, label: _CAT_LABEL[k], items: buckets[k] });
  return groups;
}

// prefix namespaces the collapse state so the installed list and the library don't share it
function _renderGrouped(el, skills, rowHtml, forceOpen, prefix = '') {
  const col = _collapsed();
  el.innerHTML = _groupRows(skills).map(g => {
    const ck = prefix + g.key;
    const open = forceOpen || !col[ck];
    return `<div class="skl-group${open ? '' : ' collapsed'}" data-grp="${ck}">
      <div class="skl-group-head">
        <span class="skl-group-chev">${open ? '▾' : '▸'}</span>
        <span class="skl-group-label">${esc(g.label)}</span>
        <span class="skl-group-count">${g.items.length}</span>
      </div>
      <div class="skl-group-body">${g.items.map(rowHtml).join('')}</div>
    </div>`;
  }).join('');
  el.querySelectorAll('.skl-group-head').forEach(h => h.addEventListener('click', () => {
    const g = h.parentElement;
    const nowCollapsed = g.classList.toggle('collapsed');
    h.querySelector('.skl-group-chev').textContent = nowCollapsed ? '▸' : '▾';
    const m = _collapsed();
    if (nowCollapsed) m[g.dataset.grp] = true; else delete m[g.dataset.grp];
    _setCollapsed(m);
  }));
}

const _skillRow = s => `
  <div class="skl-row${s.slug === _cur ? ' active' : ''}" data-slug="${esc(s.slug)}">
    <div class="skl-row-name">
      <button class="skl-pin${s.pinned ? ' on' : ''}" data-pin="${esc(s.slug)}" title="${s.pinned ? 'unpin' : 'pin to top'}">${s.pinned ? '★' : '☆'}</button>
      <span class="skl-row-title">${esc(s.name)}</span>
      ${s.source ? '<span class="skl-git" title="git-backed — can be updated from source">git</span>' : ''}
      ${s.uses ? `<span class="skl-uses" title="loaded ${s.uses} time${s.uses === 1 ? '' : 's'}">${s.uses}×</span>` : ''}
    </div>
    <div class="skl-row-desc">${esc(s.description) || '<em>no description</em>'}</div>
  </div>`;

async function _loadList(q) {
  const el = $('skl-list');
  if (!el) return;
  let skills;
  try { skills = await _api('/api/skills' + (q ? `?q=${encodeURIComponent(q)}` : '')); }
  catch { el.innerHTML = '<div class="skl-empty" style="color:var(--error)">failed to load</div>'; return; }
  if (!skills.length) {
    el.innerHTML = `<div class="skl-empty">${q ? 'no matches' : 'no skills yet — make one the agent can reuse'}</div>`;
    return;
  }
  _renderGrouped(el, skills, _skillRow, !!q, 'list:');   // a search keeps every group open
  el.querySelectorAll('.skl-row').forEach(r => r.onclick = () => _open(r.dataset.slug));
  el.querySelectorAll('.skl-pin').forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    _togglePin(b.dataset.pin, !b.classList.contains('on'));
  }));
}

async function _togglePin(slug, pinned) {
  try {
    await _api(`/api/skills/${encodeURIComponent(slug)}/pin`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ pinned }),
    });
    _loadList($('skl-search').value || '');   // re-sort, pinned jumps to top
  } catch { toast('pin failed', 'error'); }
}

// the built-in library — browse + one-click install ready-made skills
async function _showLibrary() {
  const el = $('skl-list');
  if (!el) return;
  el.innerHTML = '<div class="skl-empty">loading…</div>';
  let cat;
  try { cat = await _api('/api/skills/catalog'); }
  catch { el.innerHTML = '<div class="skl-empty" style="color:var(--error)">failed to load</div>'; return; }
  const remaining = cat.filter(c => !c.installed).length;
  const libRow = c => `
    <div class="skl-row skl-lib-row">
      <div style="flex:1;min-width:0">
        <div class="skl-row-name"><span class="skl-row-title">${esc(c.name)}</span></div>
        <div class="skl-row-desc">${esc(c.description)}</div>
      </div>
      ${c.installed ? '<span class="skl-installed">✓ added</span>' : `<button class="btn skl-add" data-slug="${esc(c.slug)}">add</button>`}
    </div>`;
  el.innerHTML =
    `<div class="skl-lib-head"><span>library · ${cat.length}</span>${remaining ? `<button class="btn skl-addall">add all (${remaining})</button>` : '<span class="skl-installed">all added ✓</span>'}</div>` +
    '<div id="skl-grp-host"></div>';
  _renderGrouped($('skl-grp-host'), cat, libRow, false, 'lib:');
  el.querySelector('.skl-addall')?.addEventListener('click', () => _install(cat.filter(c => !c.installed).map(c => c.slug)));
  el.querySelectorAll('.skl-add').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); _install([b.dataset.slug]); }));
}

async function _install(slugs) {
  if (!slugs.length) return;
  try {
    const r = await _api('/api/skills/install', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ slugs }) });
    toast(`added ${r.installed} skill${r.installed === 1 ? '' : 's'}`, 'success');
    _showLibrary();
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
    _loadList('');
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
    _loadList('');
  } catch (e) { toast('upload failed: ' + e.message, 'error'); }
}

function _editNew() {
  _cur = null;
  $('skl-name').value = '';
  $('skl-desc').value = '';
  $('skl-when').value = '';
  $('skl-bodytext').value = '';
  $('skl-del').style.display = 'none';
  $('skl-export').style.display = 'none';
  $('skl-update').style.display = 'none';
  $('skl-source').style.display = 'none';
  $('skl-status').textContent = '';
  document.querySelectorAll('.skl-row.active').forEach(r => r.classList.remove('active'));
}

async function _open(slug) {
  let s;
  try { s = await _api(`/api/skills/${encodeURIComponent(slug)}`); }
  catch { toast('failed to open skill', 'error'); return; }
  _cur = s.slug;
  $('skl-name').value = s.name || '';
  $('skl-desc').value = s.description || '';
  $('skl-when').value = s.when_to_use || '';
  $('skl-bodytext').value = s.body || '';
  $('skl-del').style.display = '';
  $('skl-export').style.display = '';
  $('skl-status').textContent = '';
  if (s.source) {
    $('skl-update').style.display = '';
    $('skl-source').style.display = '';
    $('skl-source').innerHTML = `git-backed · <a href="${esc(s.source)}" target="_blank" rel="noopener">${esc(s.source)}</a>`;
  } else {
    $('skl-update').style.display = 'none';
    $('skl-source').style.display = 'none';
  }
  document.querySelectorAll('.skl-row').forEach(r => r.classList.toggle('active', r.dataset.slug === slug));
}

function _export() {
  if (!_cur) return;
  const a = document.createElement('a');
  a.href = `/api/skills/${encodeURIComponent(_cur)}/export`;
  a.download = `${_cur}.SKILL.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function _update() {
  if (!_cur) return;
  toast('updating from source…');
  try {
    const r = await _api(`/api/skills/${encodeURIComponent(_cur)}/update`, { method: 'POST' });
    toast(r.updated ? 'updated from source' : 'no source to update from', r.updated ? 'success' : '');
    if (r.updated) { _open(_cur); _loadList($('skl-search').value); }
  } catch (e) { toast('update failed: ' + e.message, 'error'); }
}

async function _save() {
  const name = $('skl-name').value.trim();
  if (!name) { toast('give the skill a name', 'error'); return; }
  const payload = {
    name,
    description: $('skl-desc').value.trim(),
    when_to_use: $('skl-when').value.trim(),
    body: $('skl-bodytext').value,
  };
  try {
    const res = _cur
      ? await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) })
      : await _api('/api/skills', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    _cur = res.slug;
    $('skl-del').style.display = '';
    $('skl-status').textContent = 'saved';
    setTimeout(() => { if ($('skl-status')) $('skl-status').textContent = ''; }, 1500);
    toast('skill saved', 'success');
    _loadList($('skl-search').value);
  } catch (e) { toast('save failed: ' + e.message, 'error'); }
}

async function _delete() {
  if (!_cur) return;
  if (!await dlgConfirm('delete this skill?')) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'DELETE' });
    toast('skill deleted', 'success');
    _editNew();
    _loadList($('skl-search').value);
  } catch { toast('delete failed', 'error'); }
}
