// journal — one entry per day. mood + tags + prompt + streak + on-this-day + AI reflect.
import { toast, mdToHtml, plainError } from './util.js';
import { formatCalendarDate, formatTime, t, tp } from './i18n.js';
import { createFocusBoundary } from './kokuen.js?v=4';
import { replaceRouteUrl } from './route_history.js';

const _si = n => (window.icon ? window.icon(n) : '');   // central icon set, load-order safe
// labels resolve at render so a language switch shows on the next build
const moods = () => [['😄', t('journal.mood_happy')], ['🙂', t('journal.mood_content')], ['😐', t('journal.mood_neutral')], ['😕', t('journal.mood_uneasy')], ['😢', t('journal.mood_sad')], ['😠', t('journal.mood_angry')], ['😴', t('journal.mood_tired')], ['🤔', t('journal.mood_thoughtful')], ['🥳', t('journal.mood_celebrating')], ['😍', t('journal.mood_in_love')]];
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
let _reflectionGeneration = 0;
let _loadedDay = '';
let _loading = false;
let _failedDay = '';
let _lockedDraft = null;
let _copyDialogOpen = false;

export function localISODate(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
function todayISO() { return localISODate(); }
function _setDayUrl() { try { const u = new URL(location.href); u.searchParams.set('d', _day); replaceRouteUrl(u); } catch {} }
function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function _setToken(token) { _token = token || ''; if (_token) sessionStorage.setItem('journal_token', _token); else sessionStorage.removeItem('journal_token'); }
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
  if (r.status === 403) { _setToken(''); showLock('unlock'); throw new Error(t('journal.locked')); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}
async function jput(url, body) {
  const r = await fetch(url, { method: 'PUT', headers: _authHeaders({ 'content-type': 'application/json' }), body: JSON.stringify(body) });
  if (r.status === 403) { _setToken(''); showLock('unlock'); throw new Error(t('journal.locked')); }
  if (!r.ok) throw new Error(t('journal.save_failed'));
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
  if (_built && (_dirty || _saveTimer !== null || _saveInFlight !== null || Date.now() - _lastHydratedAt < 30_000)) return;
  return buildJournal();
}

function wireProductNavigation() {
  if (_productNavWired) return;
  _productNavWired = true;
  document.getElementById('journal-migrate')?.addEventListener('click', openMarkdownCopy);
  window.addEventListener('beforeunload', event => {
    if (!_dirty && _saveTimer === null && _saveInFlight === null) return;
    event.preventDefault();
    event.returnValue = '';
  });
  // the tab can close inside the 1.2s autosave wait (a phone often skips the prompt above), so the
  // last words go out with a keepalive request that outlives the page
  window.addEventListener('pagehide', () => {
    if (!_dirty || _loading || _loadedDay !== _day) return;
    const draft = snapshotEditor();
    if (!draft) return;
    clearTimeout(_saveTimer); _saveTimer = null;
    fetch('/api/journal/' + _day, {
      method: 'PUT', keepalive: true,
      headers: _authHeaders({ 'content-type': 'application/json' }),
      body: JSON.stringify({ content: draft.content, mood: draft.mood, tags: draft.tags }),
    }).catch(() => {});
  });
}

async function migrationRequest(url, options = {}) {
  const headers = _authHeaders(options.headers || {});
  const response = await fetch(url, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || t('journal.copy_could_not_continue'));
    error.status = response.status;
    error.code = data.code || '';
    throw error;
  }
  return data;
}

async function openMarkdownCopy() {
  if (_copyDialogOpen) return;
  _copyDialogOpen = true;
  const source = document.activeElement;
  while (_dirty || _saveTimer !== null || _saveInFlight !== null) {
    clearTimeout(_saveTimer);
    _saveTimer = null;
    if (!await save(false)) {
      toast(t('journal.copy_save_first'), 'error');
      _copyDialogOpen = false;
      return;
    }
  }
  let plan, existing;
  try {
    existing = await migrationRequest('/api/journal-migration/operations');
    plan = await migrationRequest('/api/journal-migration/plan');
  }
  catch (error) {
    toast(error.status === 403 ? t('journal.copy_unlock_first') : error.message, 'error');
    _copyDialogOpen = false;
    return;
  }
  const layer = document.createElement('div');
  layer.className = 'jrnl-migration-layer';
  layer.setAttribute('role', 'dialog');
  layer.setAttribute('aria-modal', 'true');
  layer.setAttribute('aria-labelledby', 'jrnl-migration-title');
  const copyDescription = current => current.count
    ? tp('journal.copy_description', current.count)
    : t('journal.copy_nothing');
  function copyControls(current) {
    if (!current.count) return `<div class="jrnl-migration-actions"><button type="button" data-close>${t('common.done')}</button></div>`;
    const conflicts = current.conflicts?.length
      ? `<div class="jrnl-migration-error">${tp('journal.copy_conflicts', current.conflicts.length)}</div>`
      : '';
    const invalid = current.invalid_dates?.length
      ? `<div class="jrnl-migration-error">${tp('journal.copy_invalid_dates', current.invalid_dates.length)}</div>`
      : '';
    const disabled = current.conflicts?.length || current.invalid_dates?.length;
    return `${conflicts}${invalid}
      <label class="jrnl-migration-confirm">
        ${t('journal.copy_confirm_label')}
        <code>${esc(current.confirmation)}</code>
        <input type="text" autocomplete="off" spellcheck="false" ${disabled ? 'disabled' : ''}>
      </label>
      <div class="jrnl-migration-actions">
        <button type="button" data-close>${t('common.cancel')}</button>
        <button type="button" data-prepare ${disabled ? 'disabled' : ''}>${t('journal.copy_prepare')}</button>
      </div>`;
  }
  layer.innerHTML = `
    <div class="jrnl-migration-card">
      <div class="jrnl-migration-head">
        <h2 id="jrnl-migration-title">${t('journal.copy_title')}</h2>
        <button type="button" data-close aria-label="${t('common.close')}">${t('common.close')}</button>
      </div>
      <p data-copy-description>${copyDescription(plan)}</p>
      <p class="jrnl-migration-warning">${esc(plan.privacy_warning)}</p>
      <p class="jrnl-migration-note">${t('journal.copy_note')}</p>
      <div class="jrnl-migration-operations" data-operations hidden></div>
      <div data-new-copy>
        ${copyControls(plan)}
      </div>
      <div class="jrnl-migration-status" role="status" aria-live="polite"></div>
    </div>`;
  const background = [...document.body.children].map(element => [element, element.inert]);
  background.forEach(([element]) => { element.inert = true; });
  document.body.appendChild(layer);
  let boundary;
  const close = () => {
    layer.remove();
    background.forEach(([element, inert]) => { element.inert = inert; });
    boundary.deactivate();
    boundary.destroy();
    _copyDialogOpen = false;
  };
  boundary = createFocusBoundary(layer, { trigger: source, onEscape: close });
  layer.addEventListener('pointerdown', event => { if (event.target === layer) close(); });
  const status = layer.querySelector('.jrnl-migration-status');
  const operations = layer.querySelector('[data-operations]');
  const newCopy = layer.querySelector('[data-new-copy]');
  function report(message, error = false) {
    status.textContent = message;
    status.classList.toggle('error', error);
  }
  function renderOperations(data) {
    const pending = data.operations.length || data.unavailable.length;
    newCopy.hidden = Boolean(data.unavailable.length || data.operations.some(item => item.state !== 'applied'));
    operations.hidden = !pending;
    const rows = data.operations.map(item => {
      const id = esc(item.operation_id);
      const label = item.state === 'prepared'
        ? t('journal.operation_prepared', { id: id.slice(0, 8) })
        : item.state === 'applied' ? t('journal.operation_copied', { id: id.slice(0, 8) }) : t('journal.operation_attention', { id: id.slice(0, 8) });
      const action = item.state === 'prepared'
        ? `<button type="button" data-operation="${id}" data-action="apply" data-apply>${t('journal.copy_apply')}</button><button type="button" data-operation="${id}" data-action="rollback" data-rollback>${t('journal.copy_discard_prepared')}</button>`
        : `<button type="button" data-operation="${id}" data-action="rollback" data-rollback>${item.state === 'applied' ? t('journal.copy_roll_back') : t('journal.copy_retry_rollback')}</button>`;
      return `<div class="jrnl-migration-operation"><p>${label} · ${esc(tp('journal.file_count', item.count))}${item.rollback_conflicts ? ` · ${esc(tp('journal.conflict_count', item.rollback_conflicts))}` : ''}</p><div class="jrnl-migration-actions">${action}</div></div>`;
    });
    const unavailable = data.unavailable.map(id => `<p class="jrnl-migration-error">${t('journal.copy_unavailable', { id: esc(id.slice(0, 8)) })}</p>`);
    operations.innerHTML = pending ? `<h3>${t('journal.copy_existing_work')}</h3>${rows.join('')}${unavailable.join('')}` : '';
  }
  renderOperations(existing);
  layer.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button || !layer.contains(button)) return;
    if (button.hasAttribute('data-close')) { close(); return; }
    const operationId = button.dataset.operation;
    if (operationId) {
      button.disabled = true;
      report(button.dataset.action === 'apply' ? t('journal.copy_applying') : t('journal.copy_checking'));
      try {
        const result = await migrationRequest(`/api/journal-migration/${encodeURIComponent(operationId)}/${button.dataset.action}`, { method: 'POST' });
        const latest = await migrationRequest('/api/journal-migration/operations');
        renderOperations(latest);
        if (!newCopy.hidden) {
          try {
            plan = await migrationRequest('/api/journal-migration/plan');
            newCopy.innerHTML = copyControls(plan);
            layer.querySelector('[data-copy-description]').innerHTML = copyDescription(plan);
            layer.querySelector('.jrnl-migration-warning').textContent = plan.privacy_warning;
          } catch {
            newCopy.hidden = true;
            report(t('journal.copy_plan_reload_failed'), true);
            layer.querySelector('[data-close]')?.focus();
            return;
          }
        }
        report(result.state === 'applied'
          ? tp('journal.files_copied', result.installed)
          : result.rollback_conflicts?.length
            ? t('journal.rollback_left_changed')
            : t('journal.rolled_back'));
        (operations.querySelector('[data-operation]') || newCopy.querySelector('input') || layer.querySelector('[data-close]'))?.focus();
      } catch (error) {
        try { renderOperations(await migrationRequest('/api/journal-migration/operations')); }
        catch { /* preserve the last visible recovery choice until the dialog is reopened */ }
        if (!newCopy.hidden) newCopy.hidden = true;
        report(error.status === 403 ? t('journal.copy_unlock_first_sentence') : t('journal.copy_failed_reopen', { error: error.message }), true);
        if (button.isConnected) button.disabled = false;
      }
      return;
    }
    if (!button.hasAttribute('data-prepare')) return;
    const input = newCopy.querySelector('input');
    if (input.value !== plan.confirmation) {
      report(t('journal.copy_confirmation_mismatch'), true);
      input.focus();
      return;
    }
    button.disabled = true;
    report(t('journal.copy_preparing'));
    try {
      const prepared = await migrationRequest('/api/journal-migration/prepare', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ confirmation: plan.confirmation }),
      });
      renderOperations({ operations: [{ ...prepared, rollback_conflicts: prepared.rollback_conflicts?.length || 0 }], unavailable: [] });
      const latest = await migrationRequest('/api/journal-migration/operations');
      renderOperations(latest);
      report(tp('journal.files_prepared', prepared.count));
      operations.querySelector('[data-apply]')?.focus();
    } catch (error) {
      try { renderOperations(await migrationRequest('/api/journal-migration/operations')); }
      catch { newCopy.hidden = true; }
      const message = error.status === 403 ? t('journal.copy_unlock_first_sentence') : error.message;
      report(t('journal.copy_failed_reopen', { error: message }), true);
    }
  });
  boundary.activate({ focus: newCopy.hidden ? operations.querySelector('button') || layer.querySelector('[data-close]') : newCopy.querySelector('input') });
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
        <div class="jrnl-main">
          <div class="jrnl-datebar">
            <button class="btn" id="jrnl-prev" title="${t('journal.previous_day')}" aria-label="${t('journal.previous_day')}">${_si('chevron-left')}</button>
            <div class="jrnl-date" id="jrnl-date"></div>
            <button class="btn" id="jrnl-next" title="${t('journal.next_day')}" aria-label="${t('journal.next_day')}">${_si('chevron-right')}</button>
            <button class="btn" id="jrnl-today">${t('common.today')}</button>
            <span class="jrnl-words" id="jrnl-words"></span>
          </div>
          <div class="jrnl-load-error" id="jrnl-load-error" hidden>
            <span id="jrnl-load-message" role="alert"></span>
            <button class="btn" id="jrnl-load-retry" type="button">${t('journal.retry_load_day')}</button>
          </div>
          <div class="jrnl-prompt" id="jrnl-prompt"></div>
          <textarea id="jrnl-text" class="jrnl-text" rows="7" aria-label="${t('journal.entry_label')}" aria-describedby="jrnl-prompt" placeholder="${t('journal.entry_placeholder')}"></textarea>
          <div class="jrnl-mood-label" id="jrnl-mood-label">${t('journal.mood')}</div>
          <div class="jrnl-moods" id="jrnl-moods" role="group" aria-labelledby="jrnl-mood-label">${moods().map(([m, label]) => `<button type="button" class="jrnl-mood" data-m="${m}" aria-label="${label}" aria-pressed="false">${label}</button>`).join('')}</div>
          <input id="jrnl-tags" class="jrnl-tags" aria-label="${t('journal.tags_label')}" placeholder="${t('journal.tags_label')}">
          <div class="jrnl-actions">
            <button class="btn primary" id="jrnl-save">${t('common.save')}</button>
            <button class="btn" id="jrnl-reflect">${_si('sparkles')} ${t('journal.reflect')}</button>
            <span class="jrnl-saved" id="jrnl-saved" role="status"></span>
          </div>
          <div class="jrnl-reflection" id="jrnl-reflection" role="status" style="display:none"></div>
        </div>
        <div class="jrnl-top">
          <div class="jrnl-toolbar">
            <input id="jrnl-search" class="jrnl-tags jrnl-search" aria-label="${t('journal.search_label')}" placeholder="${t('journal.search_placeholder')}">
            <button class="btn" id="jrnl-export">${t('journal.export')}</button>
            <button class="btn jrnl-lock-btn" id="jrnl-lock" title="${t('journal.lock')}"></button>
          </div>
          <div id="jrnl-export-status" class="jrnl-empty" role="status" hidden></div>
          <div id="jrnl-results" class="jrnl-results"></div>
          <div class="jrnl-side-title jrnl-heat-head">
            <span class="jrnl-heat-label">${t('journal.activity')}</span>
            <button class="btn jrnl-heat-nav" id="jrnl-heat-prev" title="${t('journal.previous_year')}" aria-label="${t('journal.previous_year')}">${_si('chevron-left')}</button>
            <span id="jrnl-heat-year"></span>
            <button class="btn jrnl-heat-nav" id="jrnl-heat-next" title="${t('journal.next_year')}" aria-label="${t('journal.next_year')}">${_si('chevron-right')}</button>
          </div>
          <div id="jrnl-heatmap" class="jrnl-heatmap"></div>
        </div>
        <div class="jrnl-extras">
          <div class="jrnl-col">
            <div class="jrnl-side-title">${t('journal.mood_last_30')}</div>
            <div id="jrnl-moodtrend" class="jrnl-moodtrend"></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">${t('journal.mood_links')}</div>
            <div id="jrnl-moodcorr" class="jrnl-moodcorr"></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">${t('journal.topics')}</div>
            <div id="jrnl-topics" class="jrnl-topics"></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">${t('journal.on_this_day')}</div>
            <div id="jrnl-otd" class="jrnl-otd"><div class="jrnl-empty">${t('journal.on_this_day_empty')}</div></div>
          </div>
          <div class="jrnl-col">
            <div class="jrnl-side-title">${t('journal.recent')}</div>
            <div id="jrnl-recent" class="jrnl-recent"></div>
          </div>
        </div>
      </div>`;

    document.getElementById('jrnl-prev').onclick = () => navigateDay(shift(_day, -1));
    document.getElementById('jrnl-next').onclick = () => navigateDay(shift(_day, 1));
    document.getElementById('jrnl-today').onclick = () => navigateDay(todayISO());
    document.getElementById('jrnl-save').onclick = () => save(true);
    document.getElementById('jrnl-load-retry').onclick = () => {
      if (_loading || !_failedDay) return;
      if (_failedDay === _day) load();
      else navigateDay(_failedDay);
    };
    document.getElementById('jrnl-reflect').onclick = reflect;
    const scheduleAutosave = () => {
      invalidateReflection(t('journal.reflect_stale'));
      _dirty = true;
      document.getElementById('jrnl-saved').textContent = t('journal.unsaved_changes');
      updateWords();
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => { _saveTimer = null; save(false); }, 1200);   // gentle autosave
    };
    document.getElementById('jrnl-text').addEventListener('input', scheduleAutosave);
    document.getElementById('jrnl-tags').addEventListener('input', scheduleAutosave);
    document.getElementById('jrnl-moods').addEventListener('click', e => {
      const b = e.target.closest('.jrnl-mood'); if (!b) return;
      invalidateReflection(t('journal.reflect_stale'));
      const on = b.classList.contains('active');
      document.querySelectorAll('.jrnl-mood').forEach(x => {
        const selected = x === b && !on;
        x.classList.toggle('active', selected);
        x.setAttribute('aria-pressed', String(selected));
      });
      _dirty = true;
      save(false);
    });
    let searchTimer, searchGeneration = 0;
    const search = document.getElementById('jrnl-search');
    const box = document.getElementById('jrnl-results');
    const runSearch = async (q, generation, retry = null) => {
      if (generation !== searchGeneration || !box.isConnected) return;
      try {
        const d = await jget('/api/journal/search?q=' + encodeURIComponent(q));
        if (generation !== searchGeneration || !box.isConnected) return;
        const restoreFocus = retry && document.activeElement === retry;
        box.innerHTML = d.results.map(r =>
          `<button type="button" class="jrnl-otd-row jrnl-search-result" data-d="${esc(r.date)}"><b>${esc(r.date)}</b> ${esc(r.mood || '')} ${esc(r.snippet)}</button>`).join('')
          || `<div class="jrnl-empty" role="status">${t('journal.no_matches')}</div>`;
        box.querySelectorAll('[data-d]').forEach(button => button.onclick = async () => {
          await navigateDay(button.dataset.d);
          if (_loadedDay === button.dataset.d && !_loading && document.activeElement === button) {
            document.getElementById('jrnl-text')?.focus();
          }
        });
        if (restoreFocus) (box.querySelector('button') || search).focus();
      } catch {
        if (generation !== searchGeneration || !box.isConnected) return;
        const restoreFocus = retry && document.activeElement === retry;
        box.innerHTML = `<div class="jrnl-empty" role="alert">${t('journal.search_failed')}</div><button type="button" class="btn" data-search-retry>${t('journal.retry_search')}</button>`;
        const retryButton = box.querySelector('[data-search-retry]');
        retryButton.onclick = () => {
          if (retryButton.getAttribute('aria-disabled') === 'true') return;
          retryButton.setAttribute('aria-disabled', 'true');
          box.querySelector('[role="alert"]').textContent = t('journal.searching');
          runSearch(q, generation, retryButton);
        };
        if (restoreFocus) retryButton.focus();
      }
    };
    search.addEventListener('input', () => {
      clearTimeout(searchTimer);
      const generation = ++searchGeneration;
      const q = search.value.trim();
      box.innerHTML = q ? `<div class="jrnl-empty" role="status">${t('journal.searching')}</div>` : '';
      if (q) searchTimer = setTimeout(() => runSearch(q, generation), 250);
    });
    const exportButton = document.getElementById('jrnl-export');
    const exportStatus = document.getElementById('jrnl-export-status');
    exportButton.addEventListener('click', async () => {
      if (exportButton.getAttribute('aria-disabled') === 'true') return;
      exportButton.setAttribute('aria-disabled', 'true');
      exportStatus.hidden = false;
      exportStatus.textContent = t('journal.export_preparing');
      try {
        while (_dirty || _saveTimer !== null || _saveInFlight !== null) {
          clearTimeout(_saveTimer);
          _saveTimer = null;
          if (!await save(false)) throw new Error(t('journal.save_failed'));
          if (!exportButton.isConnected) return;
        }
        const d = await jget('/api/journal/export');
        if (!exportButton.isConnected) return;
        if (typeof d.markdown !== 'string') throw new Error('invalid export');
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([d.markdown], { type: 'text/markdown' }));
        try { a.download = 'journal.md'; a.click(); }
        finally { URL.revokeObjectURL(a.href); }
        exportStatus.textContent = t('journal.export_done');
      } catch {
        if (exportButton.isConnected) exportStatus.textContent = t('journal.export_failed');
      } finally {
        exportButton.removeAttribute('aria-disabled');
      }
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
    _lastHydratedAt = result[0] ? Date.now() : 0;
    return result;
  } catch (error) {
    _lastHydratedAt = 0;
    const status = document.getElementById('jrnl-saved');
    if (status) status.textContent = t('journal.refresh_failed');
    return [];
  }
}

// a focused button that turns disabled drops focus to <body>: hand it to its opposite first
function stopAt(id, backId, stop) {
  const button = document.getElementById(id);
  if (stop && document.activeElement === button) document.getElementById(backId)?.focus();
  button.disabled = stop;
}

async function loadHeatmap() {
  const el = document.getElementById('jrnl-heatmap');
  if (!el) return;
  const year = _heatYear || Number(_day.slice(0, 4)) || new Date().getFullYear();
  try {
    const d = await jget('/api/journal/calendar?year=' + year);
    _heatYear = d.year;
    document.getElementById('jrnl-heat-year').textContent = d.year;
    stopAt('jrnl-heat-next', 'jrnl-heat-prev', d.year >= new Date().getFullYear());
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
        // a picture: a pointer still gets the day on hover, nothing here takes a click or a tab stop
        const title = inYear ? ` title="${esc(info ? tp('journal.heat_day', info.words, { date: iso, mood: info.mood || '' }) : iso)}"` : '';
        cells += `<span class="${cls.join(' ')}" data-d="${inYear ? iso : ''}"${title} aria-hidden="true"></span>`;
      }
      weeks++;
    }
    // month labels sit above the column where each month's 1st falls. they're the way in: a month
    // opens on its 1st (the picker can't open on a chosen month)
    const M = Array.from({ length: 12 }, (_, m) => formatCalendarDate(`${d.year}-${String(m + 1).padStart(2, '0')}-01`, { month: 'short' }).toLowerCase());
    const written = Object.keys(d.days).filter(iso => iso.startsWith(`${d.year}-`));
    const perMonth = M.map((_, m) => written.filter(iso => Number(iso.slice(5, 7)) === m + 1).length);
    let months = '';
    for (let m = 0; m < 12; m++) {
      const wk = Math.floor((Date.UTC(d.year, m, 1) - start.getTime()) / (7 * 86400000));
      const column = m === 11 ? `${wk + 1} / -1` : wk + 1;
      const first = `${d.year}-${String(m + 1).padStart(2, '0')}-01`;
      const ahead = first > today;
      months += `<button type="button" class="jrnl-hm jrnl-heat-month" style="grid-column:${column}" data-month="${first}" aria-label="${esc(perMonth[m] ? tp('journal.heat_month_entries', perMonth[m], { month: M[m], year: d.year }) : t('journal.heat_month', { month: M[m], year: d.year }))}"${ahead ? ' aria-disabled="true"' : ''}>${M[m]}</button>`;
    }
    const busiest = perMonth.indexOf(Math.max(...perMonth));
    const summary = written.length
      ? tp('journal.heat_summary', written.length, { year: d.year, month: formatCalendarDate(`${d.year}-${String(busiest + 1).padStart(2, '0')}-01`, { month: 'long' }) })
      : t('journal.heat_summary_empty', { year: d.year });
    // the strip redraws after every day change: a focused month stays focused
    const focused = el.contains(document.activeElement) ? document.activeElement.dataset.month : '';
    el.innerHTML =
      `<div class="jrnl-heatmonths" style="grid-template-columns:repeat(${weeks},minmax(0,1fr))">${months}</div>` +
      `<div class="jrnl-heatgrid" role="img" aria-label="${esc(summary)}" style="grid-template-columns:repeat(${weeks},minmax(0,1fr))">${cells}</div>`;
    el.querySelectorAll('.jrnl-heat-month').forEach(button => button.addEventListener('click', () => {
      if (button.getAttribute('aria-disabled') !== 'true') navigateDay(button.dataset.month);
    }));
    if (focused) el.querySelector(`.jrnl-heat-month[data-month="${focused}"]`)?.focus({ preventScroll: true });
  } catch { el.innerHTML = ''; }
}

async function loadMoodTrend() {
  const el = document.getElementById('jrnl-moodtrend');
  if (!el) return;
  try {
    const d = await jget('/api/journal/moods?days=30');
    if (!d.distribution.length) { el.innerHTML = `<div class="jrnl-empty">${t('journal.no_moods')}</div>`; return; }
    const max = Math.max(...d.distribution.map(x => x.count));
    el.innerHTML = d.distribution.map(x => `
      <div class="jrnl-mt-row">
        <span class="jrnl-mt-emoji">${esc(x.mood)}</span>
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
      const needed = /^need (\d+)\+ days with a mood logged/.exec(d.reason || '');
      const reason = needed ? t('journal.mood_need_days', { min: needed[1], have: d.mood_days ?? 0 }) : d.reason;
      el.innerHTML = `<div class="jrnl-empty">${esc(reason || t('journal.mood_links_empty'))}</div>`;
      return;
    }
    el.innerHTML = d.correlations.slice(0, 6).map(c => `
      <div class="jrnl-corr-row">
        <span class="jrnl-corr-dot ${c.rho >= 0 ? 'pos' : 'neg'}"></span>
        <span class="jrnl-corr-text">${esc(c.explain)}</span>
        <span class="jrnl-corr-n" title="${esc(tp('journal.corr_days', c.n))}">${c.rho >= 0 ? '+' : ''}${c.rho.toFixed(2)}</span>
      </div>`).join('');
  } catch { el.innerHTML = ''; }
}

// 4b - the topics you write about; click one to thread the related entries via search
async function loadTopics() {
  const el = document.getElementById('jrnl-topics');
  if (!el) return;
  try {
    const d = await jget('/api/journal/tags');
    if (!d.tags || !d.tags.length) { el.innerHTML = `<div class="jrnl-empty">${t('journal.topics_empty')}</div>`; return; }
    el.innerHTML = d.tags.map(tag =>
      `<button class="jrnl-topic" data-tag="${esc(tag.tag)}">#${esc(tag.tag)} <span>${tag.count}</span></button>`).join('');
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
    btn.innerHTML = s.enabled ? `${_si('lock')} ${t('journal.lock_options')}` : `${_si('unlock')} ${t('journal.add_passcode')}`;
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
      <button class="btn" data-a="lock">${t('journal.lock_now')}</button>
      <button class="btn" data-a="change">${t('journal.change_passcode')}</button>
      <button class="btn danger" data-a="disable">${t('journal.disable_lock')}</button>`;
    document.body.appendChild(menu);
    const r = btn.getBoundingClientRect();
    menu.style.top = Math.max(8, Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8)) + 'px';
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
  invalidateReflection();
  const draft = snapshotEditor();
  if ((_dirty || _saveTimer !== null || _saveInFlight !== null) && draft) {
    _lockedDraft = draft;
  }
  clearTimeout(_saveTimer);
  _saveTimer = null;
  _loadGeneration += 1;
  _loadedDay = '';
  _loading = false;
  _failedDay = '';
  _built = false;
  if (mode === 'unavailable') {
    body.innerHTML = `
      <div class="jrnl-lock">
        <div class="jrnl-lock-card" role="status">
          <div class="jrnl-lock-icon">${_si('lock')}</div>
          <div class="jrnl-lock-title">${t('journal.unavailable_title')}</div>
          <p class="jrnl-lock-err">${t('journal.unavailable_body')}</p>
        </div>
      </div>`;
    return;
  }
  const titles = { unlock: t('journal.locked_title'), set: t('journal.set_passcode'), change: t('journal.change_passcode'), disable: t('journal.disable_lock') };
  const needsOld = mode === 'change' || mode === 'disable' || mode === 'unlock';
  const needsNew = mode === 'set' || mode === 'change';
  body.innerHTML = `
    <div class="jrnl-lock">
      <div class="jrnl-lock-card">
        <div class="jrnl-lock-icon">${_si('lock')}</div>
        <div class="jrnl-lock-title">${titles[mode] || t('journal.title')}</div>
        ${needsOld ? `<input type="password" id="jl-old" class="jrnl-tags" placeholder="${mode === 'unlock' ? t('journal.passcode') : t('journal.current_passcode')}" autocomplete="off">` : ''}
        ${needsNew ? `<input type="password" id="jl-new" class="jrnl-tags" placeholder="${t('journal.new_passcode')}" minlength="12" autocomplete="new-password">` : ''}
        ${needsNew ? `<input type="password" id="jl-new2" class="jrnl-tags" placeholder="${t('journal.confirm_passcode')}" minlength="12" autocomplete="new-password">` : ''}
        <div class="jrnl-lock-actions">
          <button class="btn primary" id="jl-go">${mode === 'unlock' ? t('journal.unlock') : mode === 'disable' ? t('journal.disable') : t('common.save')}</button>
          ${mode !== 'unlock' ? `<button class="btn" id="jl-cancel">${t('common.cancel')}</button>` : ''}
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
        if (!r.ok) return err(t('journal.wrong_passcode'));
        _setToken((await r.json()).token); _built = false; buildJournal();
      } else if (mode === 'disable') {
        const r = await fetch('/api/journal/lock/disable', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ passcode: old }) });
        if (!r.ok) return err(t('journal.wrong_passcode')); _setToken(''); _built = false; buildJournal();
      } else { // set | change
        if (nw.length < 12) return err(t('journal.passcode_too_short'));
        if (nw !== nw2) return err(t('journal.passcode_mismatch'));
        const r = await fetch('/api/journal/lock/set', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ passcode: nw, old }) });
        if (!r.ok) return err((await r.json().catch(() => ({}))).detail || t('journal.failed'));
        const u = await fetch('/api/journal/unlock', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ passcode: nw }) });
        _setToken((await u.json()).token); _built = false; buildJournal();
        toast(t('journal.passcode_set'), 'success');
      }
    } catch { err(t('journal.something_wrong')); }
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
      toast(t('journal.save_failed_staying'), 'error');
      return;
    }
  }
  _day = nextDay;
  await load();
}

function updateEditorAvailability() {
  const blocked = _loading || _loadedDay !== _day;
  for (const control of document.querySelectorAll('#jrnl-text, #jrnl-tags, #jrnl-moods button, #jrnl-save, #jrnl-reflect')) {
    control.disabled = blocked;
  }
  document.getElementById('jrnl-load-retry')?.setAttribute('aria-disabled', String(_loading));
}

function renderDay() {
  _setDayUrl();
  document.getElementById('jrnl-date').textContent = formatJournalDay(_day);
  stopAt('jrnl-next', 'jrnl-prev', _day >= todayISO());
}

async function load() {
  if (_dirty && _loadedDay === _day && snapshotEditor()) return true;
  invalidateReflection();
  const generation = ++_loadGeneration;
  const requestedDay = _day;
  const trigger = document.activeElement;
  _loading = true;
  updateEditorAvailability();
  clearTimeout(_saveTimer);
  _saveTimer = null;
  renderDay();
  document.getElementById('jrnl-saved').textContent = t('journal.loading_entry');
  try {
    const e = await jget('/api/journal/' + requestedDay);
    if (generation !== _loadGeneration || requestedDay !== _day) return;
    _loadedDay = requestedDay;
    _failedDay = '';
    const restoreFocus = trigger?.id === 'jrnl-load-retry' && document.activeElement === trigger;
    document.getElementById('jrnl-load-error').hidden = true;
    const draft = _lockedDraft?.day === requestedDay ? _lockedDraft : null;
    document.getElementById('jrnl-text').value = draft?.content ?? e.content ?? '';
    document.getElementById('jrnl-tags').value = draft?.tags ?? e.tags ?? '';
    document.querySelectorAll('.jrnl-mood').forEach(x => {
      const selected = x.dataset.m === (draft?.mood ?? e.mood);
      x.classList.toggle('active', selected);
      x.setAttribute('aria-pressed', String(selected));
    });
    document.getElementById('jrnl-reflection').style.display = 'none';
    document.getElementById('jrnl-saved').textContent = draft ? t('journal.draft_restored') : '';
    _dirty = Boolean(draft);
    updateWords();
    if (restoreFocus && document.getElementById('journal-body')?.getClientRects().length) {
      _loading = false;
      updateEditorAvailability();
      document.getElementById('jrnl-text').focus();
    }
  } catch {
    if (generation !== _loadGeneration || requestedDay !== _day) return;
    _failedDay = requestedDay;
    if (_loadedDay) { _day = _loadedDay; renderDay(); }
    document.getElementById('jrnl-load-message').textContent = _loadedDay
      ? t('journal.load_failed_previous_open', { day: formatJournalDay(requestedDay) })
      : t('journal.load_failed_retry', { day: formatJournalDay(requestedDay) });
    document.getElementById('jrnl-load-error').hidden = false;
    document.getElementById('jrnl-saved').textContent = '';
    return false;
  } finally {
    if (generation === _loadGeneration) {
      _loading = false;
      updateEditorAvailability();
    }
  }
  if (generation !== _loadGeneration || requestedDay !== _day) return;
  loadStats();
  loadRecent();
  loadHeatmap();
  return true;
}

function updateWords() {
  const text = document.getElementById('jrnl-text').value.trim();
  const n = (text.match(/\S+/g) || []).length;
  const main = document.querySelector('.jrnl-main');
  const using = document.activeElement?.matches?.('.jrnl-tags, .jrnl-mood');
  if (main && !using) main.dataset.blank = String(!text && !document.getElementById('jrnl-tags')?.value.trim() && !document.querySelector('.jrnl-mood.active'));
  document.getElementById('jrnl-words').textContent = n ? tp('journal.word_count', n) : '';
}

async function save(explicit) {
  if (_loading || _loadedDay !== _day) return false;
  if (_saveInFlight !== null) {
    const previousSaved = await _saveInFlight;
    if (!_dirty) return previousSaved;
  }
  const savedDay = _day;
  const draft = snapshotEditor();
  if (!draft) return false;
  const { content, tags, mood } = draft;
  document.getElementById('jrnl-saved').textContent = t('common.saving');
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
      if (saved) saved.textContent = unchanged ? t('journal.saved_at', { time: formatTime(new Date()) }) : t('journal.unsaved_changes');
      if (explicit && unchanged) toast(t('journal.entry_saved'), 'success');
      loadStats(); loadRecent(); loadMoodTrend(); loadMoodCorr(); loadTopics();
      return true;
    } catch (e) {
      const status = document.getElementById('jrnl-saved');
      if (status && savedDay === _day) status.textContent = t('journal.save_failed_kept');
      if (explicit) toast(e.message || t('journal.save_failed'), 'error');
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
    if (el) el.innerHTML = `${_si('fire')} ${tp('journal.streak_days', s.streak || 0)} · ${tp('journal.entry_total', s.total || 0)} · ${tp('journal.this_month_count', s.this_month || 0)}`;
  } catch {}
}

async function loadPrompt() {
  try {
    const d = await jget('/api/journal/prompt');
    const el = document.getElementById('jrnl-prompt');
    if (el) el.textContent = t('journal.prompt_quote', { prompt: d.prompt });
  } catch {}
}

async function loadOnThisDay() {
  try {
    const d = await jget('/api/journal/on-this-day');
    const el = document.getElementById('jrnl-otd');
    if (!el) return;
    if (!d.entries.length) { el.innerHTML = `<div class="jrnl-empty">${t('journal.on_this_day_empty')}</div>`; return; }
    el.innerHTML = d.entries.map(e => {
      const c = e.content || '';
      return `<div class="jrnl-otd-row" data-d="${e.date}"><b>${esc(e.date.slice(0, 4))}</b> ${esc(e.mood || '')} ${esc(c.slice(0, 90))}${c.length > 90 ? '…' : ''}</div>`;
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
        <span class="jrnl-recent-mood">${esc(e.mood || '·')}</span>
        <span class="jrnl-recent-date">${e.date}</span>
        <span class="jrnl-recent-snip">${esc((e.content || '').slice(0, 60))}</span>
      </div>`
    ).join('') || `<div class="jrnl-empty">${t('journal.recent_empty')}</div>`;
    el.querySelectorAll('.jrnl-recent-row').forEach(r => r.onclick = () => navigateDay(r.dataset.d));
  } catch {}
}

function invalidateReflection(message = '') {
  _reflectionGeneration += 1;
  const btn = document.getElementById('jrnl-reflect');
  const box = document.getElementById('jrnl-reflection');
  if (btn) {
    btn.removeAttribute('aria-disabled');
    btn.innerHTML = `${_si('sparkles')} ${t('journal.reflect')}`;
  }
  if (box) {
    const visible = box.style.display !== 'none';
    box.textContent = visible ? message : '';
    box.style.display = visible && message ? 'block' : 'none';
  }
}

async function reflect() {
  const btn = document.getElementById('jrnl-reflect');
  const box = document.getElementById('jrnl-reflection');
  if (_loading || _loadedDay !== _day || btn.getAttribute('aria-disabled') === 'true') return;
  if (!document.getElementById('jrnl-text').value.trim()) { toast(t('journal.write_first'), 'error'); return; }
  const generation = ++_reflectionGeneration;
  const day = _day;
  const current = () => generation === _reflectionGeneration && day === _day && btn.isConnected;
  btn.setAttribute('aria-disabled', 'true');
  btn.textContent = t('journal.reflecting');
  box.textContent = t('journal.reflection_preparing');
  box.style.display = 'block';
  try {
    while (_dirty || _saveTimer !== null || _saveInFlight !== null) {
      clearTimeout(_saveTimer);
      _saveTimer = null;
      if (!await save(false)) throw new Error(t('journal.save_failed'));
      if (!current()) return;
    }
    const r = await fetch('/api/journal/' + day + '/reflect', { method: 'POST', headers: _authHeaders() });
    if (!current()) return;
    if (r.status === 403) { _setToken(''); showLock('unlock'); throw new Error(t('journal.locked')); }
    const d = await r.json();
    if (!current()) return;
    if (!r.ok) throw new Error(d.detail || t('journal.reflect_failed'));
    if (typeof d.reflection !== 'string' || !d.reflection.trim()) throw new Error(t('journal.no_reflection'));
    box.innerHTML = mdToHtml(d.reflection);
  } catch (e) {
    if (current()) box.textContent = t('journal.reflect_error', { error: plainError(e.message || t('common.request_failed')) });
  } finally {
    if (current()) {
      btn.removeAttribute('aria-disabled');
      btn.innerHTML = `${_si('sparkles')} ${t('journal.reflect')}`;
    }
  }
}
