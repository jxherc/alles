// journal — one entry per day. mood + tags + prompt + streak + on-this-day + AI reflect.
import { toast, mdToHtml } from './util.js';
import { formatCalendarDate, formatTime } from './i18n.js';

const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe
const MOODS = ['😄', '🙂', '😐', '😕', '😢', '😠', '😴', '🤔', '🥳', '😍'];
function _dayFromUrl() { const d = new URLSearchParams(location.search).get('d'); return (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) ? d : ''; }
let _day = _dayFromUrl() || todayISO();
let _heatYear = null;
let _saveTimer = null;
let _saveInFlight = null;
let _dirty = false;
let _built = false;
let _token = sessionStorage.getItem('journal_token') || '';
let _productNavWired = false;
let _lastHydratedAt = 0;
let _loadGeneration = 0;
let _lockedDraft = null;

export function localISODate(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
function todayISO() { return localISODate(); }
function _setDayUrl() { try { const u = new URL(location.href); u.searchParams.set('d', _day); history.replaceState(null, '', u); } catch {} }
function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function _setToken(t) { _token = t || ''; if (_token) sessionStorage.setItem('journal_token', _token); else sessionStorage.removeItem('journal_token'); }
function _authHeaders(extra = {}) { return _token ? { ...extra, 'X-Journal-Token': _token } : extra; }
export function shiftLocalISO(iso, n) {
  const [year, month, day] = iso.split('-').map(Number);
  const date = new Date(year, month - 1, day + n);
  return localISODate(date);
}
function shift(iso, n) { return shiftLocalISO(iso, n); }
export function formatJournalDay(iso) {
  return formatCalendarDate(iso, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
}

async function jget(url) {
  const r = await fetch(url, { headers: _authHeaders() });
  if (r.status === 403) { _setToken(''); showLock('unlock'); throw new Error('locked'); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}
async function jput(url, body) {
  const r = await fetch(url, { method: 'PUT', headers: _authHeaders({ 'content-type': 'application/json' }), body: JSON.stringify(body) });
  if (r.status === 403) { _setToken(''); showLock('unlock'); throw new Error('locked'); }
  if (!r.ok) throw new Error('save failed');
  return r.json();
}

export async function initJournal() {
  const body = document.getElementById('journal-body');
  if (!body) return;
  wireProductNavigation();
  // Check the server-side lock before trusting hydrated content. Another tab can
  // clear every unlock token while this view is still mounted.
  let status;
  try { status = await jget('/api/journal/lock/status'); }
  catch { _setToken(''); showLock('unavailable'); return; }
  if (status.enabled && !status.unlocked) { _setToken(''); showLock('unlock'); return; }
  if (_built && Date.now() - _lastHydratedAt < 30_000) return;
  return buildJournal();
}

function wireProductNavigation() {
  if (_productNavWired) return;
  _productNavWired = true;
  document.getElementById('journal-migrate')?.addEventListener('click', openMarkdownCopy);
}

async function migrationRequest(url, options = {}) {
  const headers = _authHeaders(options.headers || {});
  const response = await fetch(url, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || 'Journal copy could not continue');
    error.status = response.status;
    error.code = data.code || '';
    throw error;
  }
  return data;
}

async function openMarkdownCopy() {
  while (_dirty || _saveTimer !== null || _saveInFlight !== null) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
    if (!await save(false)) {
      toast('Save the current Journal entry before copying it to Markdown', 'error');
      return;
    }
  }
  let plan;
  try { plan = await migrationRequest('/api/journal-migration/plan'); }
  catch (error) {
    toast(error.status === 403 ? 'Unlock Journal and confirm your owner session first' : error.message, 'error');
    return;
  }
  const layer = document.createElement('div');
  layer.className = 'jrnl-migration-layer';
  layer.setAttribute('role', 'dialog');
  layer.setAttribute('aria-modal', 'true');
  layer.setAttribute('aria-labelledby', 'jrnl-migration-title');
  const conflictCopy = plan.conflicts?.length
    ? `<div class="jrnl-migration-error">${plan.conflicts.length} existing Markdown file${plan.conflicts.length === 1 ? '' : 's'} would conflict. Nothing can be copied until those files are moved or renamed.</div>`
    : '';
  layer.innerHTML = `
    <div class="jrnl-migration-card">
      <div class="jrnl-migration-head">
        <h2 id="jrnl-migration-title">copy Journal to Markdown</h2>
        <button type="button" data-close aria-label="close">close</button>
      </div>
      <p>This makes ${plan.count} daily Markdown file${plan.count === 1 ? '' : 's'} in <b>Journal/</b> so Obsidian and Docs can read them.</p>
      <p class="jrnl-migration-note">Journal stays the source of truth. The database is not deleted, and you can roll back files that Alles created unchanged.</p>
      ${conflictCopy}
      <label class="jrnl-migration-confirm">
        type this exact line to prepare the copy
        <code>${esc(plan.confirmation)}</code>
        <input type="text" autocomplete="off" spellcheck="false" ${plan.conflicts?.length ? 'disabled' : ''}>
      </label>
      <div class="jrnl-migration-status" role="status" aria-live="polite"></div>
      <div class="jrnl-migration-actions">
        <button type="button" data-close>cancel</button>
        <button type="button" data-prepare ${plan.conflicts?.length ? 'disabled' : ''}>prepare private copy</button>
      </div>
    </div>`;
  document.body.appendChild(layer);
  const close = () => layer.remove();
  layer.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', close));
  layer.addEventListener('pointerdown', event => { if (event.target === layer) close(); });
  layer.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  const input = layer.querySelector('input');
  const status = layer.querySelector('.jrnl-migration-status');
  const actions = layer.querySelector('.jrnl-migration-actions');
  layer.querySelector('[data-prepare]')?.addEventListener('click', async buttonEvent => {
    const button = buttonEvent.currentTarget;
    if (input.value !== plan.confirmation) {
      status.textContent = 'The confirmation line does not match.';
      status.classList.add('error');
      input.focus();
      return;
    }
    button.disabled = true;
    status.classList.remove('error');
    status.textContent = 'checking every entry and target…';
    try {
      const prepared = await migrationRequest('/api/journal-migration/prepare', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ confirmation: plan.confirmation }),
      });
      status.textContent = `${prepared.count} file${prepared.count === 1 ? '' : 's'} prepared privately. No Markdown file has changed yet.`;
      actions.innerHTML = '<button type="button" data-close>cancel</button><button type="button" data-apply>copy into vault</button>';
      actions.querySelector('[data-close]').addEventListener('click', close);
      actions.querySelector('[data-apply]').addEventListener('click', async applyEvent => {
        applyEvent.currentTarget.disabled = true;
        status.textContent = 'copying verified Markdown…';
        try {
          const applied = await migrationRequest(`/api/journal-migration/${encodeURIComponent(prepared.operation_id)}/apply`, { method: 'POST' });
          status.textContent = `${applied.installed} Markdown file${applied.installed === 1 ? '' : 's'} copied. Journal is still intact.`;
          actions.innerHTML = '<button type="button" data-close>done</button><button type="button" data-rollback>roll back copied files</button>';
          actions.querySelector('[data-close]').addEventListener('click', close);
          actions.querySelector('[data-rollback]').addEventListener('click', async rollbackEvent => {
            rollbackEvent.currentTarget.disabled = true;
            try {
              const rolledBack = await migrationRequest(`/api/journal-migration/${encodeURIComponent(prepared.operation_id)}/rollback`, { method: 'POST' });
              status.textContent = rolledBack.rollback_conflicts?.length
                ? 'Some copied files changed later, so Alles left them in place.'
                : 'Copied Markdown files rolled back. Journal was never removed.';
              actions.innerHTML = '<button type="button" data-close>done</button>';
              actions.querySelector('[data-close]').addEventListener('click', close);
            } catch (error) { status.textContent = error.message; status.classList.add('error'); }
          });
        } catch (error) { status.textContent = error.message; status.classList.add('error'); applyEvent.currentTarget.disabled = false; }
      });
    } catch (error) {
      status.textContent = error.status === 403 ? 'Unlock Journal and confirm your owner session first.' : error.message;
      status.classList.add('error');
      button.disabled = false;
    }
  });
  requestAnimationFrame(() => input?.focus());
}

async function buildJournal() {
  const body = document.getElementById('journal-body');
  if (!body) return;
  if (!_built || body.querySelector('.jrnl-lock')) {
    _built = false;   // lock screen replaced the shell — rebuild it
  }
  if (!_built) {
    body.innerHTML = `
      <div class="jrnl-wrap">
        <div class="jrnl-top">
          <div class="jrnl-toolbar">
            <input id="jrnl-search" class="jrnl-tags jrnl-search" placeholder="search entries…">
            <button class="btn" id="jrnl-export">export</button>
            <button class="btn jrnl-lock-btn" id="jrnl-lock" title="lock"></button>
          </div>
          <div id="jrnl-results" class="jrnl-results"></div>
          <div class="jrnl-side-title jrnl-heat-head">
            <span class="jrnl-heat-label">activity</span>
            <button class="btn jrnl-heat-nav" id="jrnl-heat-prev" title="previous year">‹</button>
            <span id="jrnl-heat-year"></span>
            <button class="btn jrnl-heat-nav" id="jrnl-heat-next" title="next year">›</button>
          </div>
          <div id="jrnl-heatmap" class="jrnl-heatmap"></div>
        </div>
        <div class="jrnl-main">
          <div class="jrnl-datebar">
            <button class="btn" id="jrnl-prev" title="previous day">‹</button>
            <div class="jrnl-date" id="jrnl-date"></div>
            <button class="btn" id="jrnl-next" title="next day">›</button>
            <button class="btn" id="jrnl-today">today</button>
            <span class="jrnl-words" id="jrnl-words"></span>
          </div>
          <div class="jrnl-prompt" id="jrnl-prompt"></div>
          <div class="jrnl-moods" id="jrnl-moods">${MOODS.map(m => `<button class="jrnl-mood" data-m="${m}">${m}</button>`).join('')}</div>
          <textarea id="jrnl-text" class="jrnl-text" placeholder="how was your day?"></textarea>
          <input id="jrnl-tags" class="jrnl-tags" placeholder="tags (comma separated)">
          <div class="jrnl-actions">
            <button class="btn primary" id="jrnl-save">save</button>
            <button class="btn" id="jrnl-reflect">${_si('sparkles')} reflect</button>
            <span class="jrnl-saved" id="jrnl-saved"></span>
          </div>
          <div class="jrnl-reflection" id="jrnl-reflection" style="display:none"></div>
        </div>
        <div class="jrnl-extras">
          <div class="jrnl-col">
            <div class="jrnl-side-title">mood · last 30 days</div>
            <div id="jrnl-moodtrend" class="jrnl-moodtrend"></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">what moves your mood</div>
            <div id="jrnl-moodcorr" class="jrnl-moodcorr"></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">topics</div>
            <div id="jrnl-topics" class="jrnl-topics"></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">on this day</div>
            <div id="jrnl-otd" class="jrnl-otd"><div class="jrnl-empty">nothing from past years yet</div></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">recent</div>
            <div id="jrnl-recent" class="jrnl-recent"></div>
          </div>
        </div>
      </div>`;

    document.getElementById('jrnl-prev').onclick = () => navigateDay(shift(_day, -1));
    document.getElementById('jrnl-next').onclick = () => navigateDay(shift(_day, 1));
    document.getElementById('jrnl-today').onclick = () => navigateDay(todayISO());
    document.getElementById('jrnl-save').onclick = () => save(true);
    document.getElementById('jrnl-reflect').onclick = reflect;
    const scheduleAutosave = () => {
      _dirty = true;
      updateWords();
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => { _saveTimer = null; save(false); }, 1200);   // gentle autosave
    };
    document.getElementById('jrnl-text').addEventListener('input', scheduleAutosave);
    document.getElementById('jrnl-tags').addEventListener('input', scheduleAutosave);
    document.getElementById('jrnl-moods').addEventListener('click', e => {
      const b = e.target.closest('.jrnl-mood'); if (!b) return;
      const on = b.classList.contains('active');
      document.querySelectorAll('.jrnl-mood').forEach(x => x.classList.remove('active'));
      if (!on) b.classList.add('active');
      _dirty = true;
      save(false);
    });
    let _js;
    document.getElementById('jrnl-search').addEventListener('input', e => {
      clearTimeout(_js);
      const q = e.target.value.trim();
      const box = document.getElementById('jrnl-results');
      if (!q) { box.innerHTML = ''; return; }
      _js = setTimeout(async () => {
        const d = await jget('/api/journal/search?q=' + encodeURIComponent(q));
        box.innerHTML = d.results.map(r =>
          `<div class="jrnl-otd-row" data-d="${r.date}"><b>${r.date}</b> ${r.mood || ''} ${esc(r.snippet)}</div>`).join('')
          || '<div class="jrnl-empty">no matches</div>';
        box.querySelectorAll('.jrnl-otd-row').forEach(x => x.onclick = () => navigateDay(x.dataset.d));
      }, 250);
    });
    document.getElementById('jrnl-export').addEventListener('click', async () => {
      const d = await jget('/api/journal/export');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([d.markdown], { type: 'text/markdown' }));
      a.download = 'journal.md'; a.click();
      URL.revokeObjectURL(a.href);
    });
    document.getElementById('jrnl-lock').onclick = openLockMenu;
    document.getElementById('jrnl-heat-prev').onclick = () => { if (_heatYear) { _heatYear--; loadHeatmap(); } };
    document.getElementById('jrnl-heat-next').onclick = () => { if (_heatYear && _heatYear < new Date().getFullYear()) { _heatYear++; loadHeatmap(); } };
    _built = true;
  }
  try {
    const result = await Promise.all([
      load(), loadPrompt(), loadOnThisDay(), loadMoodTrend(), loadMoodCorr(), loadTopics(), refreshLockBtn(),
    ]);
    _lastHydratedAt = Date.now();
    return result;
  } catch (error) {
    _lastHydratedAt = 0;
    const status = document.getElementById('jrnl-saved');
    if (status) status.textContent = 'Journal could not refresh. Try again.';
    return [];
  }
}

async function loadHeatmap() {
  const el = document.getElementById('jrnl-heatmap');
  if (!el) return;
  const year = _heatYear || Number(_day.slice(0, 4)) || new Date().getFullYear();
  try {
    const d = await jget('/api/journal/calendar?year=' + year);
    _heatYear = d.year;
    document.getElementById('jrnl-heat-year').textContent = d.year;
    document.getElementById('jrnl-heat-next').disabled = d.year >= new Date().getFullYear();
    // github-style contribution grid: 7 day-rows × ~53 week-columns, weeks left→right
    // from the Sunday on/before Jan 1. cells are a flat list laid out column-major by
    // the css grid (grid-auto-flow:column), so each 1fr column fills the full width.
    const start = new Date(Date.UTC(d.year, 0, 1));
    start.setUTCDate(start.getUTCDate() - start.getUTCDay());
    const end = new Date(Date.UTC(d.year, 11, 31));
    const today = todayISO();
    let cells = '', weeks = 0;
    for (let c = new Date(start); c <= end; c.setUTCDate(c.getUTCDate() + 7)) {
      for (let r = 0; r < 7; r++) {
        const dt = new Date(c); dt.setUTCDate(dt.getUTCDate() + r);
        const iso = dt.toISOString().slice(0, 10);
        const inYear = dt.getUTCFullYear() === d.year;   // padding days from adjacent years stay blank
        const info = d.days[iso];
        const cls = ['jrnl-hc', 'l' + (info ? info.level : 0)];
        if (!inYear) cls.push('off');
        if (iso === today) cls.push('today');
        if (iso === _day) cls.push('sel');
        const title = info ? `${iso} · ${info.words} words ${info.mood || ''}` : iso;
        const clickable = inYear && iso <= today;
        cells += `<span class="${cls.join(' ')}" data-d="${clickable ? iso : ''}" title="${title}"></span>`;
      }
      weeks++;
    }
    // month labels sit above the column where each month's 1st falls
    const M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    let months = '';
    for (let m = 0; m < 12; m++) {
      const wk = Math.floor((Date.UTC(d.year, m, 1) - start.getTime()) / (7 * 86400000));
      const column = m === 11 ? `${wk + 1} / -1` : wk + 1;
      months += `<span class="jrnl-hm" style="grid-column:${column}">${M[m]}</span>`;
    }
    el.innerHTML =
      `<div class="jrnl-heatmonths" style="grid-template-columns:repeat(${weeks},minmax(0,1fr))">${months}</div>` +
      `<div class="jrnl-heatgrid" style="grid-template-columns:repeat(${weeks},minmax(0,1fr))">${cells}</div>`;
    el.querySelectorAll('.jrnl-hc[data-d]:not([data-d=""])').forEach(c => {
      if (c.dataset.d) c.onclick = () => navigateDay(c.dataset.d);
    });
  } catch { el.innerHTML = ''; }
}

async function loadMoodTrend() {
  const el = document.getElementById('jrnl-moodtrend');
  if (!el) return;
  try {
    const d = await jget('/api/journal/moods?days=30');
    if (!d.distribution.length) { el.innerHTML = '<div class="jrnl-empty">no moods logged yet</div>'; return; }
    const max = Math.max(...d.distribution.map(x => x.count));
    el.innerHTML = d.distribution.map(x => `
      <div class="jrnl-mt-row">
        <span class="jrnl-mt-emoji">${x.mood}</span>
        <span class="jrnl-mt-bar"><span class="jrnl-mt-fill" style="width:${Math.max(6, x.count / max * 100)}%"></span></span>
        <span class="jrnl-mt-n">${x.count}</span>
      </div>`).join('');
  } catch { el.innerHTML = ''; }
}

// 4b - what behaviors track with mood (explainable Spearman); needs enough logged days
async function loadMoodCorr() {
  const el = document.getElementById('jrnl-moodcorr');
  if (!el) return;
  try {
    const d = await jget('/api/journal/mood-correlations');
    if (!d.ok || !d.correlations.length) {
      el.innerHTML = `<div class="jrnl-empty">${esc(d.reason || 'log mood + habits/health for a couple weeks to see links')}</div>`;
      return;
    }
    el.innerHTML = d.correlations.slice(0, 6).map(c => `
      <div class="jrnl-corr-row">
        <span class="jrnl-corr-dot ${c.rho >= 0 ? 'pos' : 'neg'}"></span>
        <span class="jrnl-corr-text">${esc(c.explain)}</span>
        <span class="jrnl-corr-n" title="${c.n} days with both logged">${c.rho >= 0 ? '+' : ''}${c.rho.toFixed(2)}</span>
      </div>`).join('');
  } catch { el.innerHTML = ''; }
}

// 4b - the topics you write about; click one to thread the related entries via search
async function loadTopics() {
  const el = document.getElementById('jrnl-topics');
  if (!el) return;
  try {
    const d = await jget('/api/journal/tags');
    if (!d.tags || !d.tags.length) { el.innerHTML = '<div class="jrnl-empty">tag entries to see your topics</div>'; return; }
    el.innerHTML = d.tags.map(t =>
      `<button class="jrnl-topic" data-tag="${esc(t.tag)}">#${esc(t.tag)} <span>${t.count}</span></button>`).join('');
    el.querySelectorAll('.jrnl-topic').forEach(b => b.onclick = () => {
      const inp = document.getElementById('jrnl-search');
      if (!inp) return;
      inp.value = b.dataset.tag;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.scrollIntoView({ block: 'nearest' });
    });
  } catch { el.innerHTML = ''; }
}

async function refreshLockBtn() {
  const btn = document.getElementById('jrnl-lock');
  if (!btn) return;
  try {
    const s = await jget('/api/journal/lock/status');
    btn.innerHTML = s.enabled ? `${_si('lock')} lock options` : `${_si('unlock')} add passcode`;
    btn.dataset.enabled = s.enabled ? '1' : '';
  } catch {}
}

async function openLockMenu() {
  const btn = document.getElementById('jrnl-lock');
  if (btn?.dataset.enabled) {
    // enabled + unlocked → offer lock-now / change / disable
    const choice = await pickLockAction();
    if (choice === 'lock') { await fetch('/api/journal/lock', { method: 'POST' }); _setToken(''); showLock('unlock'); }
    else if (choice === 'change') showLock('change');
    else if (choice === 'disable') showLock('disable');
  } else {
    showLock('set');
  }
}

// themed action dropdown anchored under the lock button (was buried in the reflection panel)
function pickLockAction() {
  return new Promise(resolve => {
    document.querySelector('.jrnl-lockmenu')?.remove();
    const btn = document.getElementById('jrnl-lock');
    const menu = document.createElement('div');
    menu.className = 'jrnl-lockmenu';
    menu.innerHTML = `
      <button class="btn" data-a="lock">lock now</button>
      <button class="btn" data-a="change">change passcode</button>
      <button class="btn danger" data-a="disable">disable lock</button>`;
    document.body.appendChild(menu);
    const r = btn.getBoundingClientRect();
    menu.style.top = (r.bottom + 4) + 'px';
    menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)) + 'px';
    const done = v => { menu.remove(); document.removeEventListener('mousedown', out); resolve(v); };
    const out = e => { if (!menu.contains(e.target) && e.target !== btn) done(''); };
    menu.querySelectorAll('[data-a]').forEach(b => b.onclick = () => done(b.dataset.a));
    setTimeout(() => document.addEventListener('mousedown', out), 0);
  });
}

// the lock screen — modes: unlock | set | change | disable
function showLock(mode) {
  const body = document.getElementById('journal-body');
  if (!body) return;
  const draft = snapshotEditor();
  if ((_dirty || _saveTimer !== null || _saveInFlight !== null) && draft) {
    _lockedDraft = draft;
  }
  clearTimeout(_saveTimer);
  _saveTimer = null;
  _loadGeneration += 1;
  _built = false;
  if (mode === 'unavailable') {
    body.innerHTML = `
      <div class="jrnl-lock">
        <div class="jrnl-lock-card" role="status">
          <div class="jrnl-lock-icon">${_si('lock')}</div>
          <div class="jrnl-lock-title">journal unavailable</div>
          <p class="jrnl-lock-err">Alles could not verify the journal lock. Reload when the server is reachable.</p>
        </div>
      </div>`;
    return;
  }
  const titles = { unlock: 'journal is locked', set: 'set a passcode', change: 'change passcode', disable: 'disable lock' };
  const needsOld = mode === 'change' || mode === 'disable' || mode === 'unlock';
  const needsNew = mode === 'set' || mode === 'change';
  body.innerHTML = `
    <div class="jrnl-lock">
      <div class="jrnl-lock-card">
        <div class="jrnl-lock-icon">${_si('lock')}</div>
        <div class="jrnl-lock-title">${titles[mode] || 'journal'}</div>
        ${needsOld ? `<input type="password" id="jl-old" class="jrnl-tags" placeholder="${mode === 'unlock' ? 'passcode' : 'current passcode'}" autocomplete="off">` : ''}
        ${needsNew ? `<input type="password" id="jl-new" class="jrnl-tags" placeholder="new passcode (12+ characters)" minlength="12" autocomplete="new-password">` : ''}
        ${needsNew ? `<input type="password" id="jl-new2" class="jrnl-tags" placeholder="confirm passcode" minlength="12" autocomplete="new-password">` : ''}
        <div class="jrnl-lock-actions">
          <button class="btn primary" id="jl-go">${mode === 'unlock' ? 'unlock' : mode === 'disable' ? 'disable' : 'save'}</button>
          ${mode !== 'unlock' ? '<button class="btn" id="jl-cancel">cancel</button>' : ''}
        </div>
        <div class="jrnl-lock-err" id="jl-err"></div>
      </div>
    </div>`;
  const err = m => { document.getElementById('jl-err').textContent = m; };
  const first = body.querySelector('input'); first?.focus();
  body.querySelector('#jl-cancel')?.addEventListener('click', () => { _built = false; buildJournal(); });
  const submit = async () => {
    const old = document.getElementById('jl-old')?.value || '';
    const nw = document.getElementById('jl-new')?.value || '';
    const nw2 = document.getElementById('jl-new2')?.value || '';
    try {
      if (mode === 'unlock') {
        const r = await fetch('/api/journal/unlock', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ passcode: old }) });
        if (!r.ok) return err('wrong passcode');
        _setToken((await r.json()).token); _built = false; buildJournal();
      } else if (mode === 'disable') {
        const r = await fetch('/api/journal/lock/disable', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ passcode: old }) });
        if (!r.ok) return err('wrong passcode'); _setToken(''); _built = false; buildJournal();
      } else { // set | change
        if (nw.length < 12) return err('use at least 12 characters');
        if (nw !== nw2) return err('passcodes don\'t match');
        const r = await fetch('/api/journal/lock/set', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ passcode: nw, old }) });
        if (!r.ok) return err((await r.json().catch(() => ({}))).detail || 'failed');
        const u = await fetch('/api/journal/unlock', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ passcode: nw }) });
        _setToken((await u.json()).token); _built = false; buildJournal();
        toast('passcode set', 'success');
      }
    } catch { err('something went wrong'); }
  };
  document.getElementById('jl-go').addEventListener('click', submit);
  body.querySelectorAll('input').forEach(i => i.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); }));
}

function curMood() { return document.querySelector('.jrnl-mood.active')?.dataset.m || ''; }

function snapshotEditor() {
  const text = document.getElementById('jrnl-text');
  const tags = document.getElementById('jrnl-tags');
  if (!text || !tags) return null;
  return { day: _day, content: text.value, tags: tags.value, mood: curMood() };
}

async function navigateDay(nextDay) {
  if (nextDay === _day) return;
  while (_dirty || _saveTimer !== null || _saveInFlight !== null) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
    if (!await save(false)) {
      toast('save failed; staying on this day', 'error');
      return;
    }
  }
  _day = nextDay;
  await load();
}

async function load() {
  const generation = ++_loadGeneration;
  const requestedDay = _day;
  clearTimeout(_saveTimer);
  _saveTimer = null;
  _setDayUrl();
  document.getElementById('jrnl-date').textContent = formatJournalDay(requestedDay);
  document.getElementById('jrnl-next').disabled = requestedDay >= todayISO();
  try {
    const e = await jget('/api/journal/' + requestedDay);
    if (generation !== _loadGeneration || requestedDay !== _day) return;
    const draft = _lockedDraft?.day === requestedDay ? _lockedDraft : null;
    document.getElementById('jrnl-text').value = draft?.content ?? e.content ?? '';
    document.getElementById('jrnl-tags').value = draft?.tags ?? e.tags ?? '';
    document.querySelectorAll('.jrnl-mood').forEach(x => x.classList.toggle('active', x.dataset.m === (draft?.mood ?? e.mood)));
    document.getElementById('jrnl-reflection').style.display = 'none';
    document.getElementById('jrnl-saved').textContent = draft ? 'unsaved draft restored' : '';
    _dirty = Boolean(draft);
    updateWords();
  } catch {
    if (generation !== _loadGeneration || requestedDay !== _day) return;
    /* fresh shell is fine */
  }
  if (generation !== _loadGeneration || requestedDay !== _day) return;
  loadStats();
  loadRecent();
  loadHeatmap();
}

function updateWords() {
  const n = (document.getElementById('jrnl-text').value.trim().match(/\S+/g) || []).length;
  document.getElementById('jrnl-words').textContent = n ? `${n} word${n === 1 ? '' : 's'}` : '';
}

async function save(explicit) {
  if (_saveInFlight !== null) {
    const previousSaved = await _saveInFlight;
    if (!_dirty) return previousSaved;
  }
  const savedDay = _day;
  const draft = snapshotEditor();
  if (!draft) return false;
  const { content, tags, mood } = draft;
  const request = (async () => {
    try {
      await jput('/api/journal/' + savedDay, { content, mood, tags });
      if (savedDay !== _day) return true;
      const current = snapshotEditor();
      const locked = _lockedDraft?.day === savedDay ? _lockedDraft : null;
      const unchanged = current
        ? current.day === savedDay && current.content === content && current.tags === tags && current.mood === mood
        : locked?.content === content && locked?.tags === tags && locked?.mood === mood;
      if (unchanged) {
        _dirty = false;
        if (locked) _lockedDraft = null;
      }
      const saved = document.getElementById('jrnl-saved');
      if (saved) saved.textContent = 'saved ' + formatTime(new Date());
      if (explicit) toast('entry saved', 'success');
      loadStats(); loadRecent(); loadMoodTrend(); loadMoodCorr(); loadTopics();
      return true;
    } catch (e) {
      if (explicit) toast(e.message || 'save failed', 'error');
      return false;
    }
  })();
  _saveInFlight = request;
  try {
    return await request;
  } finally {
    if (_saveInFlight === request) _saveInFlight = null;
  }
}

async function loadStats() {
  try {
    const d = await jget('/api/journal');
    const s = d.stats || {};
    const el = document.getElementById('journal-stats');
    if (el) el.innerHTML = `${_si('fire')} ${s.streak || 0} day streak · ${s.total || 0} entries · ${s.this_month || 0} this month`;
  } catch {}
}

async function loadPrompt() {
  try {
    const d = await jget('/api/journal/prompt');
    const el = document.getElementById('jrnl-prompt');
    if (el) el.textContent = '“' + d.prompt + '”';
  } catch {}
}

async function loadOnThisDay() {
  try {
    const d = await jget('/api/journal/on-this-day');
    const el = document.getElementById('jrnl-otd');
    if (!el) return;
    if (!d.entries.length) { el.innerHTML = '<div class="jrnl-empty">nothing from past years yet</div>'; return; }
    el.innerHTML = d.entries.map(e => {
      const c = e.content || '';
      return `<div class="jrnl-otd-row" data-d="${e.date}"><b>${e.date.slice(0, 4)}</b> ${e.mood || ''} ${esc(c.slice(0, 90))}${c.length > 90 ? '…' : ''}</div>`;
    }).join('');
    el.querySelectorAll('.jrnl-otd-row').forEach(r => r.onclick = () => navigateDay(r.dataset.d));
  } catch {}
}

async function loadRecent() {
  try {
    const d = await jget('/api/journal?limit=30');
    const el = document.getElementById('jrnl-recent');
    if (!el) return;
    el.innerHTML = (d.entries || []).map(e =>
      `<div class="jrnl-recent-row ${e.date === _day ? 'active' : ''}" data-d="${e.date}">
        <span class="jrnl-recent-mood">${e.mood || '·'}</span>
        <span class="jrnl-recent-date">${e.date}</span>
        <span class="jrnl-recent-snip">${esc((e.content || '').slice(0, 60))}</span>
      </div>`
    ).join('') || '<div class="jrnl-empty">no entries yet — write one</div>';
    el.querySelectorAll('.jrnl-recent-row').forEach(r => r.onclick = () => navigateDay(r.dataset.d));
  } catch {}
}

async function reflect() {
  const btn = document.getElementById('jrnl-reflect');
  const box = document.getElementById('jrnl-reflection');
  if (!document.getElementById('jrnl-text').value.trim()) { toast('write something first', 'error'); return; }
  await save(false);
  btn.disabled = true; btn.textContent = 'reflecting…';
  try {
    const r = await fetch('/api/journal/' + _day + '/reflect', { method: 'POST', headers: _authHeaders() });
    if (r.status === 403) { _setToken(''); showLock('unlock'); throw new Error('locked'); }
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'reflect failed');
    box.innerHTML = mdToHtml(d.reflection || '');
    box.style.display = 'block';
  } catch (e) {
    toast(e.message || 'reflect failed', 'error');
  }
  btn.disabled = false; btn.innerHTML = `${_si('sparkles')} reflect`;
}
