// skills — manage reusable procedures (SKILL.md on disk) that the agent can
// discover + load. category rail on the left, a card grid in the middle, and the
// editor in a right slide-over drawer. library is just a mode of the same surface.
import { toast } from './util.js';
import { createFocusBoundary } from './kokuen.js';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';

let _built = false;
let _cur = null;            // slug open in the drawer, or null for a new one
let _drawerBoundary = null;
let _drawerSource = null;
let _drawerRead = 0;
let _matchSeq = 0;          // bumps per match call so stale responses don't clobber newer ones
let _listRead = 0;
const _pinning = new Set();

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const $ = id => document.getElementById(id);

async function _api(url, opts, fetcher = fetch) {
  const r = await fetcher(url, opts);
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
const _STARTING_SKILLS = ['plan-my-day', 'break-down-project', 'email-draft', 'explain-simply', 'compare-options', 'proofread-polish'];
function _startingSkills(rows) {
  const personal = rows.filter(s => s.pinned || _catOf(s) === 'custom');
  const chosen = new Set(personal.map(s => s.slug));
  return personal.concat(_STARTING_SKILLS.map(slug => rows.find(s => s.slug === slug))
    .filter(s => s && !chosen.has(s.slug)));
}

// ── view state ────────────────────────────────────────────────────────────────
let _state = { mode: 'installed', cat: 'start', q: '', source: null, libCat: 'all' };
let _data = [];
let _sources = [];

export function initSkills(fetcher = fetch) {
  const body = $('skills-body');
  if (!body) return;
  if (!_built) {
    body.innerHTML = `
      <div class="skills2">
        <div class="skl-head">
          <input id="skl-search" class="settings-input skl-search" placeholder="search skills…">
          <button class="btn" id="skl-match">⌕ what aide picks</button>
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
    $('skl-match').onclick = () => _openMatch();
    // rail clicks (delegated): category select + library/github/upload actions
    $('skl-rail').addEventListener('click', e => {
      const cat = e.target.closest('.skl-rail-cat');
      if (cat) {
        if (cat.dataset.src) { _state.q = ''; if ($('skl-search')) $('skl-search').value = ''; _browseSource(cat.dataset.src); return; }
        if (cat.dataset.libcat) { _state.libCat = cat.dataset.libcat; _render(); return; }   // re-filter only, no re-browse
        _state.cat = cat.dataset.cat; _render(); return;
      }
      const act = e.target.closest('.skl-rail-act')?.dataset.act;
      if (act === 'library') _toggleLibrary();
      else if (act === 'github') _importGithub();
      else if (act === 'upload') $('skl-file')?.click();
    });
    _built = true;
  }
  _state = { mode: 'installed', cat: 'start', q: '', source: null, libCat: 'all' };
  return _refresh(fetcher);
}

async function _refresh(fetcher = fetch, { keepGrid = false } = {}) {
  if (_state.mode === 'library') return _browseSource(_state.source || 'builtin');
  const read = ++_listRead;
  const grid = $('skl-grid');
  if (grid && !keepGrid) grid.innerHTML = '<div class="skl-empty">loading…</div>';
  try {
    const data = await _api('/api/skills', undefined, fetcher);
    if (read !== _listRead) return;
    _data = data;
  }
  catch (error) {
    if (read !== _listRead) return;
    if (grid && !keepGrid) grid.innerHTML = '<div class="skl-empty" style="color:var(--error)">failed to load</div>';
    throw error;
  }
  _render();
}

function _catCounts(rows) {
  const c = { all: rows.length, start: _startingSkills(rows).length, pinned: 0 };
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
    const catOn = _state.source === 'builtin' && _state.libCat !== 'all';
    let rows = _data;
    if (catOn) rows = rows.filter(s => _catOf(s) === _state.libCat);
    if (!ql) return rows;
    return rows.filter(s => (`${s.name || ''} ${s.description || ''} ${s.when_to_use || ''} ${s.path || ''} ${s.dir || ''}`).toLowerCase().includes(ql));
  }
  if (!ql && _state.cat === 'start') return _startingSkills(_data);
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
  const focused = rail.contains(document.activeElement) ? document.activeElement.closest('button') : null;
  const focusKey = focused && ['cat', 'libcat', 'src', 'act'].find(key => key in focused.dataset);
  const focusValue = focusKey ? focused.dataset[focusKey] : null;
  let html = '';
  if (_state.mode === 'library') {
    for (const s of _sources) {
      const active = s.id === _state.source;
      html += `<button class="skl-rail-cat${active ? ' active' : ''}" data-src="${esc(s.id)}">
          <span class="skl-rail-label">${esc(s.name)}</span><span class="skl-rail-count">${s.count || ''}</span>
        </button>`;
    }
    // builtin is a flat wall of skills, give it a category sub-filter
    if (_state.source === 'builtin') {
      const counts = _catCounts(_data);
      const lrow = (key, label) => counts[key]
        ? `<button class="skl-rail-cat${_state.libCat === key ? ' active' : ''}" data-libcat="${key}">
             <span class="skl-rail-label">${esc(label)}</span><span class="skl-rail-count">${counts[key]}</span>
           </button>` : '';
      html += '<div class="skl-rail-sub">filter</div>';
      html += lrow('all', 'all');
      for (const k of _CAT_ORDER) if (k !== 'custom') html += lrow(k, _CAT_LABEL[k]);
      html += lrow('custom', 'custom');
    }
  } else {
    const counts = _catCounts(_data);
    const row = (key, label) => counts[key] || key === 'start'
      ? `<button class="skl-rail-cat${!_state.q && _state.cat === key ? ' active' : ''}" data-cat="${key}" aria-pressed="${!_state.q && _state.cat === key}">
           <span class="skl-rail-label">${esc(label)}</span><span class="skl-rail-count">${counts[key]}</span>
         </button>` : '';
    if (_state.q) html += `<div class="skl-rail-results">results · ${_visible().length}</div>`;
    html += row('start', 'start here');
    if (counts.pinned) html += row('pinned', 'pinned');
    html += row('all', 'all');
    if (!['start', 'pinned', 'custom'].includes(_state.cat)) {
      for (const k of _CAT_ORDER) if (k !== 'custom') html += row(k, _CAT_LABEL[k]);
    }
    html += row('custom', 'custom');
  }
  html += `<div class="skl-rail-foot">
      <button class="skl-rail-act${_state.mode === 'library' ? ' active' : ''}" data-act="library">⊕ library</button>
      <button class="skl-rail-act" data-act="github">↳ github</button>
      <button class="skl-rail-act" data-act="upload">↑ upload</button>
    </div>
    <input type="file" id="skl-file" accept=".md,.markdown,.txt" multiple style="display:none">`;
  rail.innerHTML = html;
  if (focusKey && !focused.isConnected && document.activeElement === document.body) {
    rail.querySelector(`[data-${focusKey}="${CSS.escape(focusValue)}"]`)?.focus();
  }
  const f = $('skl-file'); if (f) f.onchange = _uploadFiles;
}

function _renderGrid(list) {
  const grid = $('skl-grid');
  if (!grid) return;
  const focused = grid.contains(document.activeElement) ? document.activeElement.closest('button') : null;
  const card = focused?.closest('.skl-card');
  const key = card?.dataset.slug ? 'slug' : 'path';
  const value = card?.dataset[key];
  const action = focused?.dataset.act;
  if (!list.length) {
    grid.innerHTML = `<div class="skl-empty">${_state.q ? 'no matches' : _state.mode === 'installed' && _state.cat === 'start' ? 'no starting skills here. choose all, search, or create a skill.' : 'nothing here'}</div>`;
  } else if (_state.mode === 'library') {
    grid.innerHTML = list.map(_state.source === 'builtin' ? _libCard : _srcCard).join('');
  } else {
    const sorted = [...list].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
    // explain the order, but only on the plain installed grid (not while searching)
    const hint = _state.q ? '' : `<div class="skl-rankhint">${_state.cat === 'start' ? 'common tasks, plus your pinned and custom skills. search covers all skills.' : 'ranked by usefulness - pinned first, then most-used, then recent'}</div>`;
    grid.innerHTML = hint + sorted.map(_card).join('');
  }
  _bindCards(grid);
  if (focused && !focused.isConnected && document.activeElement === document.body) {
    const replacement = value && grid.querySelector(`.skl-card[data-${key}="${CSS.escape(value)}"] ${action ? `[data-act="${CSS.escape(action)}"]` : '.skl-card-name'}`);
    (replacement || document.querySelector('.skl-rail-cat.active') || $('skl-search'))?.focus();
  }
}

// short relative time from epoch SECONDS. '' if never used
function _ago(epoch) {
  if (!epoch) return '';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60); if (m < 60) return m + 'm';
  const h = Math.floor(m / 60); if (h < 24) return h + 'h';
  const d = Math.floor(h / 24); if (d < 7) return d + 'd';
  const w = Math.floor(d / 7); if (w < 5) return w + 'w';
  const mo = Math.floor(d / 30); if (mo < 12) return mo + 'mo';
  return Math.floor(d / 365) + 'y';
}

function _card(s) {
  const badges = [
    s.uses ? `<span class="skl-badge" title="loaded ${s.uses}×">${s.uses}×</span>` : '',
    s.last_used ? `<span class="skl-badge muted" title="last used">${_ago(s.last_used)}</span>` : '',
    s.source ? '<span class="skl-badge git" title="git-backed">git</span>' : '',
  ].join('');
  const acts = `<div class="skl-card-acts">
         <button class="skl-pin${s.pinned ? ' on' : ''}" data-act="pin" aria-pressed="${!!s.pinned}" aria-disabled="${_pinning.has(s.slug)}"${_pinning.has(s.slug) ? ' aria-busy="true"' : ''} title="${s.pinned ? 'unpin' : 'pin to top'}">${s.pinned ? '★' : '☆'}</button>
         <button class="skl-del-q" data-act="del" title="delete">🗑</button>
       </div>`;
  return `
    <div class="skl-card${s.slug === _cur ? ' active' : ''}" data-slug="${esc(s.slug)}">
      <div class="skl-card-top">
        <button type="button" class="skl-card-name" aria-label="open ${esc(s.name)}">${esc(s.name)}</button>
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
        _previewLibrary(c, c.querySelector('.skl-card-name'));
        return;
      }
      if (act === 'pin') { e.stopPropagation(); const pin = e.target.closest('[data-act="pin"]'); _togglePin(c.dataset.slug, !pin.classList.contains('on'), pin); }
      else if (act === 'del') { e.stopPropagation(); _deleteCard(c.dataset.slug); }
      else _openDrawer(c.dataset.slug, c.querySelector('.skl-card-name'));
    };
  });
}

async function _togglePin(slug, pinned, trigger) {
  if (_pinning.has(slug)) return;
  _pinning.add(slug);
  trigger.setAttribute('aria-disabled', 'true');
  trigger.setAttribute('aria-busy', 'true');
  let saved = false;
  try {
    await _api(`/api/skills/${encodeURIComponent(slug)}/pin`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ pinned }),
    });
    saved = true;
    if (_state.mode === 'installed') await _refresh(fetch, { keepGrid: true });
  } catch { toast(saved ? 'pin saved, but the list could not refresh. reopen skills.' : 'pin not confirmed. try again.', 'error'); }
  finally {
    _pinning.delete(slug);
    const current = document.querySelector(`.skl-card[data-slug="${CSS.escape(slug)}"] .skl-pin`);
    current?.setAttribute('aria-disabled', 'false');
    current?.removeAttribute('aria-busy');
  }
}

async function _deleteCard(slug) {
  if (!await dlgConfirm('delete this skill?')) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(slug)}`, { method: 'DELETE' });
    toast('skill deleted', 'success');
    if (_cur === slug) _closeDrawer(true);
    await _refresh();
  } catch { toast('delete failed', 'error'); }
}

// ── library mode ────────────────────────────────────────────────────────────
async function _toggleLibrary() {
  if (_state.mode === 'library') {
    _state.mode = 'installed'; _state.cat = 'all'; _state.q = ''; _state.source = null; _state.libCat = 'all';
    if ($('skl-search')) $('skl-search').value = '';
    _refresh(); return;
  }
  ++_listRead;
  _state.mode = 'library'; _state.q = '';
  if ($('skl-search')) $('skl-search').value = '';
  try { _sources = await _api('/api/skills/sources'); }
  catch { _sources = [{ id: 'builtin', name: 'built-in', kind: 'builtin', count: 0 }]; }
  _browseSource('builtin');
}

async function _browseSource(id) {
  const read = ++_listRead;
  _state.source = id;
  _state.libCat = 'all';   // switching sources / re-entering library clears the sub-filter
  _renderRail();
  const grid = $('skl-grid');
  if (grid) grid.innerHTML = '<div class="skl-empty">loading…</div>';
  let data;
  try { data = await _api(`/api/skills/sources/${encodeURIComponent(id)}/browse`); }
  catch { if (read === _listRead && grid) grid.innerHTML = '<div class="skl-empty" style="color:var(--error)">couldn\'t reach this source</div>'; return; }
  if (read !== _listRead) return;
  _data = data.skills || [];
  _render();
}

const _libCard = s => `
  <div class="skl-card" data-slug="${esc(s.slug)}" data-kind="builtin">
    <div class="skl-card-top"><button type="button" class="skl-card-name" aria-label="open ${esc(s.name)}">${esc(s.name)}</button></div>
    <div class="skl-card-desc">${esc(s.description) || ''}</div>
    ${s.installed ? '<span class="skl-added">✓ added</span>' : '<button class="skl-add" data-act="add">+ add</button>'}
  </div>`;

const _srcCard = s => `
  <div class="skl-card" data-path="${esc(s.path)}" data-url="${esc(s.import_url)}" data-kind="github">
    <div class="skl-card-top"><button type="button" class="skl-card-name" aria-label="open ${esc(s.name)}">${esc(s.name)}</button></div>
    ${s.dir ? `<div class="skl-card-desc skl-card-dir">${esc(s.dir)}</div>` : ''}
    ${s.installed ? '<span class="skl-added">✓ added</span>' : '<button class="skl-add" data-act="add">+ add</button>'}
  </div>`;

async function _addFromLibrary(c) {
  if (c.dataset.kind === 'builtin') { await _install([c.dataset.slug]); return; }
  try {
    await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: c.dataset.url }) });
    toast('added', 'success');
    _browseSource(_state.source);
  } catch { toast('add failed', 'error'); }
}

function _previewLibrary(c, source) {
  const read = ++_drawerRead;
  source?.focus();
  if (c.dataset.kind === 'builtin') {
    const s = _data.find(x => x.slug === c.dataset.slug);
    if (s) _openPreview(s, { builtin: true, slug: s.slug, installed: !!s.installed }, source);
    return;
  }
  _api(`/api/skills/sources/${encodeURIComponent(_state.source)}/preview?path=${encodeURIComponent(c.dataset.path)}`)
    .then(s => {
      if (read === _drawerRead && source?.isConnected && document.activeElement === source) {
        _openPreview(s, { builtin: false, url: c.dataset.url }, source);
      }
    })
    .catch(() => toast("couldn't fetch skill", 'error'));
}

function _openPreview(s, opts, source) {
  _drawerRead++;
  const host = $('skl-drawer-host');
  if (!host) return;
  const addCtl = opts.installed
    ? '<span class="skl-added">✓ added</span>'
    : '<button class="btn primary" id="skl-pv-add">+ add</button>';
  const srcLink = (s.source_url && /^https?:\/\//i.test(s.source_url)) ? `<a class="skl-pv-src" href="${esc(s.source_url)}" target="_blank" rel="noopener">view source</a>` : '';
  host.innerHTML = `
    <div class="skl-drawer-backdrop open" id="skl-drawer-bd"></div>
    <aside class="skl-drawer open" id="skl-drawer" role="dialog" aria-labelledby="skl-d-heading">
      <div class="skl-drawer-head"><span id="skl-d-heading">${esc(s.name)}</span><button class="skl-drawer-x" id="skl-d-close" aria-label="close">✕</button></div>
      <div class="skl-drawer-body">
        ${s.when_to_use ? `<div class="skl-pv-when"><b>when:</b> ${esc(s.when_to_use)}</div>` : ''}
        ${s.description ? `<div class="skl-pv-desc">${esc(s.description)}</div>` : ''}
        <pre class="skl-pv-body">${esc(s.body || '')}</pre>
        <div class="skl-drawer-acts">${addCtl}${srcLink}</div>
      </div>
    </aside>`;
  $('skl-d-close').onclick = _closeDrawer;
  $('skl-drawer-bd').onclick = _closeDrawer;

  _activateDrawer(source);
  const add = $('skl-pv-add');
  if (add) add.onclick = async () => {
    add.disabled = true;
    if (opts.builtin) { await _install([opts.slug]); }
    else {
      try { await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: opts.url }) }); toast('added', 'success'); }
      catch { toast('add failed', 'error'); add.disabled = false; return; }
    }
    _closeDrawer();
    _browseSource(_state.source);
  };
}

// "what aide picks" - read-only preview of the agent's auto-pick for a task.
// reuses the same drawer shell/close pattern as _openPreview.
function _openMatch() {
  const source = document.activeElement;
  _drawerRead++;
  const host = $('skl-drawer-host');
  if (!host) return;
  _matchSeq++;  // ignore any late response from a previously-open drawer
  host.innerHTML = `
    <div class="skl-drawer-backdrop open" id="skl-drawer-bd"></div>
    <aside class="skl-drawer open" id="skl-drawer" role="dialog" aria-labelledby="skl-d-heading">
      <div class="skl-drawer-head"><span id="skl-d-heading">what would aide load?</span><button class="skl-drawer-x" id="skl-d-close" aria-label="close">✕</button></div>
      <div class="skl-drawer-body">
        <input id="skl-match-q" class="settings-input" placeholder="describe a task…">
        <div id="skl-match-results" class="skl-match-results"><div class="skl-match-hint">type a task to see which skills rank</div></div>
      </div>
    </aside>`;
  $('skl-d-close').onclick = _closeDrawer;
  $('skl-drawer-bd').onclick = _closeDrawer;

  const inp = $('skl-match-q');
  let t;
  const go = () => _runMatch(inp.value.trim());
  inp.oninput = () => { clearTimeout(t); t = setTimeout(go, 250); };
  inp.onkeydown = e => { if (e.key === 'Enter') { clearTimeout(t); go(); } };
  _activateDrawer(source, inp);
}

async function _runMatch(q) {
  const seq = ++_matchSeq;  // claim this generation; bail later if a newer call superseded us
  const box = $('skl-match-results');
  if (!box) return;
  if (!q) { box.innerHTML = '<div class="skl-match-hint">type a task to see which skills rank</div>'; return; }
  let data;
  try { data = await _api(`/api/skills/match?q=${encodeURIComponent(q)}&k=8`); }
  catch { if (seq === _matchSeq) box.innerHTML = '<div class="skl-match-hint" style="color:var(--error)">match failed</div>'; return; }
  if (seq !== _matchSeq) return;  // a newer query landed while we were waiting, drop this
  const matches = data.matches || [];
  if (!matches.length) { box.innerHTML = '<div class="skl-match-hint">no skill matches that yet</div>'; return; }
  const top = matches[0].score || 1;
  box.innerHTML = matches.map((m, i) => {
    const w = Math.max(2, Math.round((m.score / top) * 100));
    const tag = i === 0 ? '<span class="skl-match-auto">auto-loaded</span>' : '';
    return `
      <div class="skl-match-row${i === 0 ? ' top' : ''}">
        <div class="skl-match-top">
          <span class="skl-match-name">${esc(m.name)}</span>${tag}
          <span class="skl-match-score">${m.score.toFixed(2)}</span>
        </div>
        ${m.description ? `<div class="skl-match-desc">${esc(m.description)}</div>` : ''}
        <div class="skl-match-bar"><span style="width:${w}%"></span></div>
      </div>`;
  }).join('');
}

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
    <aside class="skl-drawer" id="skl-drawer" role="dialog" aria-labelledby="skl-d-heading" hidden inert>
      <div class="skl-drawer-head">
        <span id="skl-d-heading">new skill</span>
        <button class="skl-drawer-x" id="skl-d-close" title="close">✕</button>
      </div>
      <div class="skl-drawer-body">
        <div class="s-field"><label for="skl-d-name">name</label><input id="skl-d-name" class="settings-input" placeholder="e.g. PDF form filler"></div>
        <div class="s-field"><label for="skl-d-desc">description</label><input id="skl-d-desc" class="settings-input" placeholder="one line: what it does"></div>
        <div class="s-field"><label for="skl-d-when">when to use</label><input id="skl-d-when" class="settings-input" placeholder="the trigger"></div>
        <div class="s-field"><label for="skl-d-body">procedure (markdown)</label><textarea id="skl-d-body" class="settings-textarea" rows="14"></textarea></div>
        <div class="skl-drawer-acts">
          <button class="btn primary" id="skl-d-save">save</button>
          <button class="btn" id="skl-d-export" hidden>export</button>
          <button class="btn" id="skl-d-update" hidden>update</button>
          <button class="btn danger" id="skl-d-del" hidden>delete</button>
          <span id="skl-d-status" class="skl-status"></span>
        </div>
        <div id="skl-d-source" class="skl-source" hidden></div>
      </div>
    </aside>`;
}

async function _openDrawer(slug, source = document.activeElement) {
  const read = ++_drawerRead;
  source?.focus();
  const host = $('skl-drawer-host');
  if (!host) return;
  host.innerHTML = _drawerHtml();
  $('skl-d-close').onclick = _closeDrawer;
  $('skl-drawer-bd').onclick = _closeDrawer;
  $('skl-d-save').onclick = _save;
  $('skl-d-export').onclick = _export;
  $('skl-d-update').onclick = _update;
  $('skl-d-del').onclick = _delete;

  let s = { name: '', description: '', when_to_use: '', body: '', source: '' };
  if (slug) {
    try { s = await _api(`/api/skills/${encodeURIComponent(slug)}`); }
    catch { toast('failed to open skill', 'error'); return; }
  }
  if (read !== _drawerRead || !source?.isConnected || document.activeElement !== source) return;
  _cur = slug || null;
  $('skl-d-heading').textContent = slug ? 'edit skill' : 'new skill';
  $('skl-d-name').value = s.name || '';
  $('skl-d-desc').value = s.description || '';
  $('skl-d-when').value = s.when_to_use || '';
  $('skl-d-body').value = s.body || '';
  $('skl-d-status').textContent = '';
  $('skl-d-del').hidden = !slug;
  $('skl-d-export').hidden = !slug;
  if (s.source) {
    $('skl-d-update').hidden = false; $('skl-d-source').hidden = false;
    $('skl-d-source').innerHTML = `git-backed · <a href="${esc(s.source)}" target="_blank" rel="noopener">${esc(s.source)}</a>`;
  } else { $('skl-d-update').hidden = true; $('skl-d-source').hidden = true; }
  $('skl-drawer').classList.add('open');
  $('skl-drawer-bd').classList.add('open');
  document.querySelectorAll('.skl-card').forEach(c => c.classList.toggle('active', c.dataset.slug === slug));
  _activateDrawer(source, $('skl-d-name'));
}

function _activateDrawer(source, focus = $('skl-d-close')) {
  _drawerBoundary?.destroy();
  _drawerSource = source;
  const drawer = $('skl-drawer');
  drawer.hidden = false;
  drawer.inert = false;
  _drawerBoundary = createFocusBoundary(drawer, { onEscape: _closeDrawer });
  _drawerBoundary.activate({ source, focus });
}

function _closeDrawer(returnToNew = false) {
  _drawerRead++;
  _matchSeq++;
  const drawer = $('skl-drawer');
  const ownedFocus = drawer?.contains(document.activeElement);
  _drawerBoundary?.deactivate({ restoreFocus: false });
  _drawerBoundary?.destroy();
  _drawerBoundary = null;
  if (drawer) { drawer.classList.remove('open'); drawer.hidden = true; drawer.inert = true; }
  $('skl-drawer-bd')?.classList.remove('open');
  const originalCard = _drawerSource?.closest('.skl-card');
  const replacement = [...document.querySelectorAll('.skl-card')].find(card =>
    (_cur && card.dataset.slug === _cur) || (originalCard &&
      (originalCard.dataset.slug ? card.dataset.slug === originalCard.dataset.slug : card.dataset.path === originalCard.dataset.path)));
  const target = returnToNew === true ? $('skl-new')
    : _drawerSource?.isConnected ? _drawerSource : replacement?.querySelector('.skl-card-name') || $('skl-new');
  if (ownedFocus && target?.getClientRects().length) target.focus();
  _drawerSource = null;
  _cur = null;
  document.querySelectorAll('.skl-card.active').forEach(c => c.classList.remove('active'));
}

async function _save() {
  const name = $('skl-d-name').value.trim();
  if (!name) { toast('give the skill a name', 'error'); return; }
  const payload = { name, description: $('skl-d-desc').value.trim(), when_to_use: $('skl-d-when').value.trim(), body: $('skl-d-body').value };
  try {
    const res = _cur
      ? await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) })
      : await _api('/api/skills', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    _cur = res.slug;
    $('skl-d-del').hidden = false; $('skl-d-export').hidden = false;
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
    _closeDrawer(true);
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
