// journal — one entry per day. mood + tags + prompt + streak + on-this-day + AI reflect.
import { toast, mdToHtml } from './util.js';

const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe
const MOODS = ['😄', '🙂', '😐', '😕', '😢', '😠', '😴', '🤔', '🥳', '😍'];
function _dayFromUrl() { const d = new URLSearchParams(location.search).get('d'); return (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) ? d : ''; }
let _day = _dayFromUrl() || todayISO();
let _heatYear = null;
let _saveTimer = null;
let _built = false;
let _token = sessionStorage.getItem('journal_token') || '';

function todayISO() { return new Date().toISOString().slice(0, 10); }
function _setDayUrl() { try { const u = new URL(location.href); u.searchParams.set('d', _day); history.replaceState(null, '', u); } catch {} }
function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function _setToken(t) { _token = t || ''; if (_token) sessionStorage.setItem('journal_token', _token); else sessionStorage.removeItem('journal_token'); }
function _authHeaders(extra = {}) { return _token ? { ...extra, 'X-Journal-Token': _token } : extra; }
function shift(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
function pretty(iso) {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
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
  // gate: if a passcode is set and we don't hold a valid token, show the lock screen
  let status = { enabled: false };
  try { status = await jget('/api/journal/lock/status'); } catch {}
  if (status.enabled && !_token) { showLock('unlock'); return; }
  buildJournal();
}

function buildJournal() {
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
            <div class="jrnl-side-title">on this day</div>
            <div id="jrnl-otd" class="jrnl-otd"><div class="jrnl-empty">nothing from past years yet</div></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">recent</div>
            <div id="jrnl-recent" class="jrnl-recent"></div>
          </div>
        </div>
      </div>`;

    document.getElementById('jrnl-prev').onclick = () => { _day = shift(_day, -1); load(); };
    document.getElementById('jrnl-next').onclick = () => { _day = shift(_day, 1); load(); };
    document.getElementById('jrnl-today').onclick = () => { _day = todayISO(); load(); };
    document.getElementById('jrnl-save').onclick = () => save(true);
    document.getElementById('jrnl-reflect').onclick = reflect;
    document.getElementById('jrnl-text').addEventListener('input', () => {
      updateWords();
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => save(false), 1200);   // gentle autosave
    });
    document.getElementById('jrnl-moods').addEventListener('click', e => {
      const b = e.target.closest('.jrnl-mood'); if (!b) return;
      const on = b.classList.contains('active');
      document.querySelectorAll('.jrnl-mood').forEach(x => x.classList.remove('active'));
      if (!on) b.classList.add('active');
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
        box.querySelectorAll('.jrnl-otd-row').forEach(x => x.onclick = () => { _day = x.dataset.d; load(); });
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
  load();
  loadPrompt();
  loadOnThisDay();
  loadMoodTrend();
  refreshLockBtn();
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
      months += `<span class="jrnl-hm" style="grid-column:${wk + 1}">${M[m]}</span>`;
    }
    el.innerHTML =
      `<div class="jrnl-heatmonths" style="grid-template-columns:repeat(${weeks},1fr)">${months}</div>` +
      `<div class="jrnl-heatgrid">${cells}</div>`;
    el.querySelectorAll('.jrnl-hc[data-d]:not([data-d=""])').forEach(c => {
      if (c.dataset.d) c.onclick = () => { _day = c.dataset.d; load(); };
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
  _built = false;
  const titles = { unlock: 'journal is locked', set: 'set a passcode', change: 'change passcode', disable: 'disable lock' };
  const needsOld = mode === 'change' || mode === 'disable' || mode === 'unlock';
  const needsNew = mode === 'set' || mode === 'change';
  body.innerHTML = `
    <div class="jrnl-lock">
      <div class="jrnl-lock-card">
        <div class="jrnl-lock-icon">${_si('lock')}</div>
        <div class="jrnl-lock-title">${titles[mode] || 'journal'}</div>
        ${needsOld ? `<input type="password" id="jl-old" class="jrnl-tags" placeholder="${mode === 'unlock' ? 'passcode' : 'current passcode'}" autocomplete="off">` : ''}
        ${needsNew ? `<input type="password" id="jl-new" class="jrnl-tags" placeholder="new passcode" autocomplete="off">` : ''}
        ${needsNew ? `<input type="password" id="jl-new2" class="jrnl-tags" placeholder="confirm passcode" autocomplete="off">` : ''}
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
        if (nw.length < 4) return err('use at least 4 characters');
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

async function load() {
  _setDayUrl();
  document.getElementById('jrnl-date').textContent = pretty(_day) + (_day === todayISO() ? '' : '');
  document.getElementById('jrnl-next').disabled = _day >= todayISO();
  try {
    const e = await jget('/api/journal/' + _day);
    document.getElementById('jrnl-text').value = e.content || '';
    document.getElementById('jrnl-tags').value = e.tags || '';
    document.querySelectorAll('.jrnl-mood').forEach(x => x.classList.toggle('active', x.dataset.m === e.mood));
    document.getElementById('jrnl-reflection').style.display = 'none';
    document.getElementById('jrnl-saved').textContent = '';
    updateWords();
  } catch { /* fresh shell is fine */ }
  loadStats();
  loadRecent();
  loadHeatmap();
}

function updateWords() {
  const n = (document.getElementById('jrnl-text').value.trim().match(/\S+/g) || []).length;
  document.getElementById('jrnl-words').textContent = n ? `${n} word${n === 1 ? '' : 's'}` : '';
}

async function save(explicit) {
  const content = document.getElementById('jrnl-text').value;
  const tags = document.getElementById('jrnl-tags').value;
  try {
    await jput('/api/journal/' + _day, { content, mood: curMood(), tags });
    document.getElementById('jrnl-saved').textContent = 'saved ' + new Date().toLocaleTimeString();
    if (explicit) toast('entry saved', 'success');
    loadStats(); loadRecent(); loadMoodTrend();
  } catch (e) {
    if (explicit) toast(e.message || 'save failed', 'error');
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
    el.innerHTML = d.entries.map(e =>
      `<div class="jrnl-otd-row" data-d="${e.date}"><b>${e.date.slice(0, 4)}</b> ${e.mood || ''} ${esc((e.content || '').slice(0, 90))}…</div>`
    ).join('');
    el.querySelectorAll('.jrnl-otd-row').forEach(r => r.onclick = () => { _day = r.dataset.d; load(); });
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
    el.querySelectorAll('.jrnl-recent-row').forEach(r => r.onclick = () => { _day = r.dataset.d; load(); });
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
