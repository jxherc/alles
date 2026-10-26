// skills — manage reusable procedures (SKILL.md on disk) that the agent can
// discover + load. category rail on the left, a card grid in the middle, and the
// editor in a right slide-over drawer. library is just a mode of the same surface.
import { toast } from './util.js';
import { t, tp } from './i18n.js';
import { createFocusBoundary } from './kokuen.js?v=4';
import { confirm as dlgConfirm, prompt as dlgPrompt } from './dialog.js';
const _si = n => (globalThis.window?.icon ? globalThis.window.icon(n) : '');   // the shared svg icon set

let _built = false;
let _cur = null;            // slug open in the drawer, or null for a new one
let _drawerBoundary = null;
let _drawerSource = null;
let _drawerRead = 0;
let _matchSeq = 0;          // bumps per match call so stale responses don't clobber newer ones
let _listRead = 0;
const _pinning = new Set();
const _savingDrawers = new WeakSet();
let _saveRead = 0;

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const $ = id => document.getElementById(id);

async function _api(url, opts, fetcher = fetch) {
  const r = await fetcher(url, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}

// each skill carries its category from the backend (the library file it came from —
// coding.json → 'coding'); custom/imported ones have none → bucketed as 'custom'.
// getters, so the label is translated when it is read, not when the module loads
const _CAT_LABEL = {
  get 'ai-prompting'() { return t('aide.skl_cat_ai_prompting'); },
  get 'coding'() { return t('aide.skl_cat_coding'); },
  get 'devops-git'() { return t('aide.skl_cat_devops_git'); },
  get 'testing-debugging'() { return t('aide.skl_cat_testing_debugging'); },
  get 'data-sql'() { return t('aide.skl_cat_data_sql'); },
  get 'utilities'() { return t('aide.skl_cat_utilities'); },
  get 'research'() { return t('aide.skl_cat_research'); },
  get 'writing'() { return t('aide.skl_cat_writing'); },
  get 'marketing-content'() { return t('aide.skl_cat_marketing_content'); },
  get 'communication'() { return t('aide.skl_cat_communication'); },
  get 'creativity'() { return t('aide.skl_cat_creativity'); },
  get 'design-ux'() { return t('aide.skl_cat_design_ux'); },
  get 'decision'() { return t('aide.skl_cat_decision'); },
  get 'learning'() { return t('aide.skl_cat_learning'); },
  get 'productivity'() { return t('aide.skl_cat_productivity'); },
  get 'life-health'() { return t('aide.skl_cat_life_health'); },
  get 'personal-finance'() { return t('aide.skl_cat_personal_finance'); },
  get 'career-business'() { return t('aide.skl_cat_career_business'); },
  get 'custom'() { return t('aide.skl_cat_custom'); },
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
          <input id="skl-search" aria-label="${esc(t('aide.skl_search'))}" class="settings-input skl-search" placeholder="${esc(t('aide.skl_search_placeholder'))}">
          <button class="btn" id="skl-match">${_si('search')} ${esc(t('aide.skl_what_aide_picks'))}</button>
          <button class="btn primary" id="skl-new">${esc(t('aide.skl_new'))}</button>
        </div>
        <div class="skl-body">
          <nav class="skl-rail" id="skl-rail"></nav>
          <div class="skl-grid" id="skl-grid"></div>
        </div>
        <div id="skl-drawer-host"></div>
      </div>`;
    let searchTimer;
    $('skl-search').oninput = e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { _state.q = e.target.value.trim(); _render(); }, 200); };
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
  if (grid && !keepGrid) grid.innerHTML = `<div class="skl-empty">${esc(t('aide.loading'))}</div>`;
  try {
    const data = await _api('/api/skills', undefined, fetcher);
    if (read !== _listRead) return;
    _data = data;
  }
  catch (error) {
    if (read !== _listRead) return;
    if (grid && !keepGrid) grid.innerHTML = `<div class="skl-empty" style="color:var(--error)">${esc(t('aide.skl_load_failed'))}</div>`;
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
      html += `<div class="skl-rail-sub">${esc(t('aide.skl_filter'))}</div>`;
      html += lrow('all', t('aide.skl_all'));
      for (const k of _CAT_ORDER) if (k !== 'custom') html += lrow(k, _CAT_LABEL[k]);
      html += lrow('custom', _CAT_LABEL.custom);
    }
  } else {
    const counts = _catCounts(_data);
    const row = (key, label) => counts[key] || key === 'start'
      ? `<button class="skl-rail-cat${!_state.q && _state.cat === key ? ' active' : ''}" data-cat="${key}" aria-pressed="${!_state.q && _state.cat === key}">
           <span class="skl-rail-label">${esc(label)}</span><span class="skl-rail-count">${counts[key]}</span>
         </button>` : '';
    if (_state.q) html += `<div class="skl-rail-results">${esc(t('aide.skl_results', { count: _visible().length }))}</div>`;
    html += row('start', t('aide.skl_start_here'));
    if (counts.pinned) html += row('pinned', t('aide.skl_pinned'));
    html += row('all', t('aide.skl_all'));
    if (!['start', 'pinned', 'custom'].includes(_state.cat)) {
      for (const k of _CAT_ORDER) if (k !== 'custom') html += row(k, _CAT_LABEL[k]);
    }
    html += row('custom', _CAT_LABEL.custom);
  }
  html += `<div class="skl-rail-foot">
      <button class="skl-rail-act${_state.mode === 'library' ? ' active' : ''}" data-act="library">${_si('plus')} ${esc(t('aide.skl_library'))}</button>
      <button class="skl-rail-act" data-act="github">${_si('download')} ${esc(t('aide.skl_from_github'))}</button>
      <button class="skl-rail-act" data-act="upload">${_si('upload')} ${esc(t('aide.skl_upload'))}</button>
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
    grid.innerHTML = `<div class="skl-empty">${esc(_state.q ? t('aide.skl_no_matches') : _state.mode === 'installed' && _state.cat === 'start' ? t('aide.skl_no_starting') : t('aide.skl_nothing_here'))}</div>`;
  } else if (_state.mode === 'library') {
    grid.innerHTML = list.map(_state.source === 'builtin' ? _libCard : _srcCard).join('');
  } else {
    const sorted = [...list].sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
    // explain the order, but only on the plain installed grid (not while searching)
    const hint = _state.q ? '' : `<div class="skl-rankhint">${esc(_state.cat === 'start' ? t('aide.skl_hint_start') : t('aide.skl_hint_ranked'))}</div>`;
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
  if (s < 60) return t('aide.run_just_now');
  const m = Math.floor(s / 60); if (m < 60) return t('aide.skl_ago_m', { count: m });
  const h = Math.floor(m / 60); if (h < 24) return t('aide.skl_ago_h', { count: h });
  const d = Math.floor(h / 24); if (d < 7) return t('aide.skl_ago_d', { count: d });
  const w = Math.floor(d / 7); if (w < 5) return t('aide.skl_ago_w', { count: w });
  const mo = Math.floor(d / 30); if (mo < 12) return t('aide.skl_ago_mo', { count: mo });
  return t('aide.skl_ago_y', { count: Math.floor(d / 365) });
}

function _card(s) {
  const badges = [
    s.uses ? `<span class="skl-badge" title="${esc(t('aide.skl_loaded_times', { count: s.uses }))}">${s.uses}×</span>` : '',
    s.last_used ? `<span class="skl-badge muted" title="${esc(t('aide.skl_last_used'))}">${_ago(s.last_used)}</span>` : '',
    s.source ? `<span class="skl-badge git" title="${esc(t('aide.skl_git_backed'))}">git</span>` : '',
  ].join('');
  const acts = `<div class="skl-card-acts">
         <button class="skl-pin${s.pinned ? ' on' : ''}" data-act="pin" aria-label="${esc(t('aide.skl_pin_named', { name: s.name }))}" aria-pressed="${!!s.pinned}" aria-disabled="${_pinning.has(s.slug)}"${_pinning.has(s.slug) ? ' aria-busy="true"' : ''} title="${esc(s.pinned ? t('aide.skl_unpin') : t('aide.skl_pin_to_top'))}">${esc(t('aide.skl_pin'))}</button>
         <button class="skl-del-q" data-act="del" aria-label="${esc(t('aide.skl_delete_named', { name: s.name }))}" title="${esc(t('common.delete'))}">${esc(t('common.delete'))}</button>
       </div>`;
  return `
    <div class="skl-card${s.slug === _cur ? ' active' : ''}" data-slug="${esc(s.slug)}">
      <div class="skl-card-top">
        <button type="button" class="skl-card-name" aria-label="${esc(t('aide.skl_open_named', { name: s.name }))}">${esc(s.name)}</button>
        ${badges}
      </div>
      <div class="skl-card-desc">${esc(s.description) || `<em>${esc(t('aide.skl_no_description'))}</em>`}</div>
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
  } catch { toast(saved ? t('aide.skl_pin_saved_stale') : t('aide.skl_pin_unconfirmed'), 'error'); }
  finally {
    _pinning.delete(slug);
    const current = document.querySelector(`.skl-card[data-slug="${CSS.escape(slug)}"] .skl-pin`);
    current?.setAttribute('aria-disabled', 'false');
    current?.removeAttribute('aria-busy');
  }
}

async function _deleteCard(slug) {
  if (!await dlgConfirm(t('aide.skl_delete_confirm'))) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(slug)}`, { method: 'DELETE' });
    toast(t('aide.skl_deleted'), 'success');
    if (_cur === slug) _closeDrawer(true);
    await _refresh();
  } catch { toast(t('aide.skl_delete_failed'), 'error'); }
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
  catch { _sources = [{ id: 'builtin', name: t('aide.skl_builtin'), kind: 'builtin', count: 0 }]; }
  _browseSource('builtin');
}

async function _browseSource(id) {
  const read = ++_listRead;
  _state.source = id;
  _state.libCat = 'all';   // switching sources / re-entering library clears the sub-filter
  _renderRail();
  const grid = $('skl-grid');
  if (grid) grid.innerHTML = `<div class="skl-empty">${esc(t('aide.loading'))}</div>`;
  let data;
  try { data = await _api(`/api/skills/sources/${encodeURIComponent(id)}/browse`); }
  catch { if (read === _listRead && grid) grid.innerHTML = `<div class="skl-empty" style="color:var(--error)">${esc(t('aide.skl_source_unreachable'))}</div>`; return; }
  if (read !== _listRead) return;
  _data = data.skills || [];
  _render();
}

const _libCard = s => `
  <div class="skl-card" data-slug="${esc(s.slug)}" data-kind="builtin">
    <div class="skl-card-top"><button type="button" class="skl-card-name" aria-label="${esc(t('aide.skl_open_named', { name: s.name }))}">${esc(s.name)}</button></div>
    <div class="skl-card-desc">${esc(s.description) || ''}</div>
    ${s.installed ? `<span class="skl-added">${_si('check')} ${esc(t('aide.skl_added'))}</span>` : `<button class="skl-add" data-act="add">${_si('plus')} ${esc(t('aide.skl_add'))}</button>`}
  </div>`;

const _srcCard = s => `
  <div class="skl-card" data-path="${esc(s.path)}" data-url="${esc(s.import_url)}" data-kind="github">
    <div class="skl-card-top"><button type="button" class="skl-card-name" aria-label="${esc(t('aide.skl_open_named', { name: s.name }))}">${esc(s.name)}</button></div>
    ${s.dir ? `<div class="skl-card-desc skl-card-dir">${esc(s.dir)}</div>` : ''}
    ${s.installed ? `<span class="skl-added">${_si('check')} ${esc(t('aide.skl_added'))}</span>` : `<button class="skl-add" data-act="add">${_si('plus')} ${esc(t('aide.skl_add'))}</button>`}
  </div>`;

async function _addFromLibrary(c) {
  if (c.dataset.kind === 'builtin') { await _install([c.dataset.slug]); return; }
  try {
    await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: c.dataset.url }) });
    toast(t('aide.skl_added'), 'success');
    _browseSource(_state.source);
  } catch { toast(t('aide.skl_add_failed'), 'error'); }
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
    .catch(() => toast(t('aide.skl_fetch_failed'), 'error'));
}

function _openPreview(s, opts, source) {
  _drawerRead++;
  const host = $('skl-drawer-host');
  if (!host) return;
  const addCtl = opts.installed
    ? `<span class="skl-added">${_si('check')} ${esc(t('aide.skl_added'))}</span>`
    : `<button class="btn primary" id="skl-pv-add">${esc(t('aide.skl_plus_add'))}</button>`;
  const srcLink = (s.source_url && /^https?:\/\//i.test(s.source_url)) ? `<a class="skl-pv-src" href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(t('aide.skl_view_source'))}</a>` : '';
  host.innerHTML = `
    <div class="skl-drawer-backdrop open" id="skl-drawer-bd"></div>
    <aside class="skl-drawer open" id="skl-drawer" role="dialog" aria-labelledby="skl-d-heading">
      <div class="skl-drawer-head"><span id="skl-d-heading">${esc(s.name)}</span><button type="button" class="skl-drawer-x" id="skl-d-close" aria-label="${esc(t('common.close'))}" data-kokuen-icon="close">✕</button></div>
      <div class="skl-drawer-body">
        ${s.when_to_use ? `<div class="skl-pv-when"><b>${esc(t('aide.skl_when'))}</b> ${esc(s.when_to_use)}</div>` : ''}
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
      try { await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: opts.url }) }); toast(t('aide.skl_added'), 'success'); }
      catch { toast(t('aide.skl_add_failed'), 'error'); add.disabled = false; return; }
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
      <div class="skl-drawer-head"><span id="skl-d-heading">${esc(t('aide.skl_what_load'))}</span><button type="button" class="skl-drawer-x" id="skl-d-close" aria-label="${esc(t('common.close'))}" data-kokuen-icon="close">✕</button></div>
      <div class="skl-drawer-body">
        <input id="skl-match-q" aria-label="${esc(t('aide.skl_describe_task'))}" class="settings-input" placeholder="${esc(t('aide.skl_describe_task_placeholder'))}">
        <div id="skl-match-results" class="skl-match-results"><div class="skl-match-hint">${esc(t('aide.skl_type_task'))}</div></div>
      </div>
    </aside>`;
  $('skl-d-close').onclick = _closeDrawer;
  $('skl-drawer-bd').onclick = _closeDrawer;

  const inp = $('skl-match-q');
  let matchTimer;
  const go = () => _runMatch(inp.value.trim());
  inp.oninput = () => { clearTimeout(matchTimer); matchTimer = setTimeout(go, 250); };
  inp.onkeydown = e => { if (e.key === 'Enter') { clearTimeout(matchTimer); go(); } };
  _activateDrawer(source, inp);
}

async function _runMatch(q) {
  const seq = ++_matchSeq;  // claim this generation; bail later if a newer call superseded us
  const box = $('skl-match-results');
  if (!box) return;
  if (!q) { box.innerHTML = `<div class="skl-match-hint">${esc(t('aide.skl_type_task'))}</div>`; return; }
  let data;
  try { data = await _api(`/api/skills/match?q=${encodeURIComponent(q)}&k=8`); }
  catch { if (seq === _matchSeq) box.innerHTML = `<div class="skl-match-hint" style="color:var(--error)">${esc(t('aide.skl_match_failed'))}</div>`; return; }
  if (seq !== _matchSeq) return;  // a newer query landed while we were waiting, drop this
  const matches = data.matches || [];
  if (!matches.length) { box.innerHTML = `<div class="skl-match-hint">${esc(t('aide.skl_no_match_yet'))}</div>`; return; }
  const top = matches[0].score || 1;
  box.innerHTML = matches.map((m, i) => {
    const w = Math.max(2, Math.round((m.score / top) * 100));
    const tag = i === 0 ? `<span class="skl-match-auto">${esc(t('aide.skl_auto_loaded'))}</span>` : '';
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
    toast(tp('aide.skl_added_count', r.installed), 'success');
    await _refresh();
  } catch { toast(t('aide.skl_install_failed'), 'error'); }
}

async function _importGithub() {
  const url = await dlgPrompt('', '', { title: t('aide.skl_add_title'), label: t('aide.skl_github_label'), confirmLabel: t('aide.skl_add') });
  if (!url || !url.trim()) return;
  toast(t('aide.skl_fetching'));
  try {
    const r = await _api('/api/skills/import-github', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ url: url.trim() }) });
    const n = r.imported.length;
    toast(`${tp('aide.skl_imported', n)}${r.failed ? t('aide.skl_failed_suffix', { count: r.failed }) : ''}`, n ? 'success' : 'error');
    _refresh();
  } catch (e) { toast(t('aide.skl_github_failed', { message: e.message }), 'error'); }
}

async function _uploadFiles(e) {
  const files = [...(e.target.files || [])];
  e.target.value = '';   // let the same file be re-picked later
  if (!files.length) return;
  const items = await Promise.all(files.map(async f => ({ filename: f.name, text: await f.text() })));
  try {
    const r = await _api('/api/skills/upload', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ items }) });
    const n = r.imported.length;
    toast(`${tp('aide.skl_uploaded', n)}${r.failed ? t('aide.skl_skipped_suffix', { count: r.failed }) : ''}`, n ? 'success' : 'error');
    _refresh();
  } catch (e) { toast(t('aide.skl_upload_failed', { message: e.message }), 'error'); }
}

// ── editor drawer ───────────────────────────────────────────────────────────
function _drawerHtml() {
  return `
    <div class="skl-drawer-backdrop" id="skl-drawer-bd"></div>
    <aside class="skl-drawer" id="skl-drawer" role="dialog" aria-labelledby="skl-d-heading" hidden inert>
      <div class="skl-drawer-head">
        <span id="skl-d-heading">${esc(t('aide.skl_new_skill'))}</span>
        <button type="button" class="skl-drawer-x" id="skl-d-close" aria-label="${esc(t('common.close'))}" data-kokuen-icon="close">✕</button>
      </div>
      <div class="skl-drawer-body">
        <div class="s-field"><label for="skl-d-name">${esc(t('aide.skl_f_name'))}</label><input id="skl-d-name" class="settings-input" placeholder="${esc(t('aide.skl_f_name_ph'))}"></div>
        <div class="s-field"><label for="skl-d-desc">${esc(t('aide.skl_f_desc'))}</label><input id="skl-d-desc" class="settings-input" placeholder="${esc(t('aide.skl_f_desc_ph'))}"></div>
        <div class="s-field"><label for="skl-d-when">${esc(t('aide.skl_f_when'))}</label><input id="skl-d-when" class="settings-input" placeholder="${esc(t('aide.skl_f_when_ph'))}"></div>
        <div class="s-field"><label for="skl-d-body">${esc(t('aide.skl_f_body'))}</label><textarea id="skl-d-body" class="settings-textarea" rows="14"></textarea></div>
        <div class="skl-drawer-acts">
          <button class="btn primary" id="skl-d-save">${esc(t('common.save'))}</button>
          <button class="btn" id="skl-d-export" hidden>${esc(t('aide.skl_export'))}</button>
          <button class="btn" id="skl-d-update" hidden>${esc(t('aide.skl_update'))}</button>
          <button class="btn danger" id="skl-d-del" hidden>${esc(t('common.delete'))}</button>
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
    catch { toast(t('aide.skl_open_failed'), 'error'); return; }
  }
  if (read !== _drawerRead || !source?.isConnected || document.activeElement !== source) return;
  _cur = slug || null;
  $('skl-d-heading').textContent = slug ? t('aide.skl_edit_skill') : t('aide.skl_new_skill');
  $('skl-d-name').value = s.name || '';
  $('skl-d-desc').value = s.description || '';
  $('skl-d-when').value = s.when_to_use || '';
  $('skl-d-body').value = s.body || '';
  $('skl-d-status').textContent = '';
  $('skl-d-del').hidden = !slug;
  $('skl-d-export').hidden = !slug;
  if (s.source) {
    $('skl-d-update').hidden = false; $('skl-d-source').hidden = false;
    // a source from a shared SKILL.md is only a link when it is a web address
    $('skl-d-source').innerHTML = /^https?:\/\//i.test(String(s.source || ''))
      ? `${esc(t('aide.skl_git_backed'))} · <a href="${esc(s.source)}" target="_blank" rel="noopener">${esc(s.source)}</a>`
      : `${esc(t('aide.skl_git_backed'))} · ${esc(s.source)}`;
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
  const drawer = $('skl-drawer');
  if (!drawer || _savingDrawers.has(drawer)) return;
  const read = _drawerRead;
  const slug = _cur;
  const name = $('skl-d-name').value.trim();
  if (!name) { toast(t('aide.skl_needs_name'), 'error'); return; }
  const payload = { name, description: $('skl-d-desc').value.trim(), when_to_use: $('skl-d-when').value.trim(), body: $('skl-d-body').value };
  const button = $('skl-d-save');
  const saveRead = ++_saveRead;
  _savingDrawers.add(drawer);
  button.setAttribute('aria-disabled', 'true');
  button.setAttribute('aria-busy', 'true');
  let saved = false;
  try {
    const res = slug
      ? await _api(`/api/skills/${encodeURIComponent(slug)}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) })
      : await _api('/api/skills', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    if (!res?.slug) throw new Error(t('aide.skl_save_unconfirmed'));
    saved = true;
    const current = read === _drawerRead && drawer === $('skl-drawer');
    if (current) {
      _cur = res.slug;
      $('skl-d-del').hidden = false; $('skl-d-export').hidden = false;
      $('skl-d-heading').textContent = t('aide.skl_edit_skill');
      const unchanged = name === $('skl-d-name').value.trim() && payload.description === $('skl-d-desc').value.trim()
        && payload.when_to_use === $('skl-d-when').value.trim() && payload.body === $('skl-d-body').value;
      const status = $('skl-d-status');
      status.textContent = unchanged ? t('models.saved') : t('aide.skl_newer_edits');
      if (unchanged) setTimeout(() => {
        if (read === _drawerRead && saveRead === _saveRead && drawer === $('skl-drawer')) status.textContent = '';
      }, 1500);
    }
    toast(current ? t('aide.skl_saved') : t('aide.skl_named_saved', { name }), 'success');
    await _refresh();
  } catch (e) { toast(saved ? t('aide.skl_saved_stale') : t('aide.skl_save_failed', { message: e.message }), 'error'); }
  finally {
    _savingDrawers.delete(drawer);
    button.removeAttribute('aria-disabled');
    button.removeAttribute('aria-busy');
  }
}

async function _delete() {
  if (!_cur) return;
  if (!await dlgConfirm(t('aide.skl_delete_confirm'))) return;
  try {
    await _api(`/api/skills/${encodeURIComponent(_cur)}`, { method: 'DELETE' });
    toast(t('aide.skl_deleted'), 'success');
    _closeDrawer(true);
    await _refresh();
  } catch { toast(t('aide.skl_delete_failed'), 'error'); }
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
  toast(t('aide.skl_updating'));
  try {
    const r = await _api(`/api/skills/${encodeURIComponent(_cur)}/update`, { method: 'POST' });
    toast(r.updated ? t('aide.skl_updated') : t('aide.skl_no_source'), r.updated ? 'success' : '');
    if (r.updated) { _openDrawer(_cur); await _refresh(); }
  } catch (e) { toast(t('aide.skl_update_failed', { message: e.message }), 'error'); }
}
