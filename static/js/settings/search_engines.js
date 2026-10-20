// Settings → search: engine pickers, the key for the chosen engine, and custom engines.
// Every list comes from /api/search/engines, so a new engine needs no change here.
import { _patchSettings, _esc } from './shared.js';
import { toast } from '../util.js';
import { confirm as _dlgConfirm } from '../dialog.js';
import { getDropdownValue, setDropdownValue, populateDropdown } from '../dropdown.js?v=212';
import { wireChoiceGroup } from '../kokuen.js?v=1';

let _engines = [];
let _settings = {};
let _editing = null; // custom engine id being edited, '' for a new one

const $ = id => document.getElementById(id);
const engineById = id => _engines.find(engine => engine.id === id);
const labelOf = id => id === 'disabled' ? 'disabled' : id === 'none' ? 'none' : engineById(id)?.label || id;

async function _json(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data?.error?.message || data?.detail || `request failed (${response.status})`);
  return data;
}

function _options(withNone) {
  const rows = _engines.map(engine => ({
    value: engine.id,
    label: engine.configured || engine.custom ? engine.label : `${engine.label} · needs a key`,
  }));
  return withNone ? [{ value: 'none', label: 'none' }, ...rows] : [...rows, { value: 'disabled', label: 'disabled' }];
}

// ── hidden sites ──
function renderHiddenSites() {
  const list = $('s-hidden-sites-list');
  if (!list) return;
  const sites = Array.isArray(_settings.andromeda_blocked_sites) ? _settings.andromeda_blocked_sites : [];
  list.innerHTML = sites.length ? sites.map(site => `
    <div class="settings-list-row">
      <div class="row-name" style="flex:1;min-width:0">${_esc(site)}</div>
      <button type="button" class="btn" data-hidden-site="${_esc(site)}" aria-label="show ${_esc(site)} again">show again</button>
    </div>`).join('') : '<div class="s-card-hint">no hidden sites</div>';
}

async function saveHiddenSites(sites, message) {
  const status = $('s-hidden-sites-status');
  const saved = await _patchSettings({ andromeda_blocked_sites: sites });
  if (!saved) {
    if (status) { status.textContent = 'not saved; use a site name like example.com'; status.dataset.state = 'error'; }
    return false;
  }
  _settings = { ..._settings, andromeda_blocked_sites: saved.andromeda_blocked_sites || [] };
  renderHiddenSites();
  if (status) { status.textContent = message; status.dataset.state = ''; }
  return true;
}

export async function loadSearchEngines(settings) {
  _settings = settings || {};
  _engines = (await _json('/api/search/engines')).engines || [];
  populateDropdown($('s-search-provider'), _options(false), _settings.search_provider || 'duckduckgo');
  setDropdownValue($('s-search-provider'), _settings.search_provider || 'duckduckgo');
  populateDropdown($('s-search-fallback'), _options(true), _settings.search_fallback || 'duckduckgo');
  setDropdownValue($('s-search-fallback'), _settings.search_fallback || 'duckduckgo');
  setDropdownValue($('s-search-count'), String(_settings.search_result_count || 8));
  updateEngineFields();
  updateSearchStatus();
  renderCustomList();
  renderHiddenSites();
}

export function updateEngineFields() {
  const id = getDropdownValue($('s-search-provider'));
  const engine = engineById(id);
  const note = $('s-search-engine-note');
  if (note) note.textContent = engine?.note || '';
  const keyRow = $('s-engine-key-row');
  const keyed = !!engine?.key_setting && !engine.custom && id !== 'google_pse';
  if (keyRow) keyRow.hidden = !keyed;
  if (keyed) {
    $('s-engine-key-label').textContent = `${engine.label} api key`;
    const input = $('s-engine-key');
    input.value = '';
    input.placeholder = engine.configured ? 'configured: enter a replacement' : '';
    const signup = $('s-engine-signup');
    signup.hidden = !engine.signup;
    if (engine.signup) signup.href = engine.signup;
  }
  if ($('s-searxng-row')) $('s-searxng-row').hidden = id !== 'searxng';
  if ($('s-google-pse-rows')) $('s-google-pse-rows').hidden = id !== 'google_pse';
}

function updateSearchStatus(message = '', error = false) {
  const el = $('s-search-status');
  if (!el) return;
  if (message) {
    el.textContent = message;
    el.dataset.state = error ? 'error' : '';
    return;
  }
  const id = getDropdownValue($('s-search-provider'));
  const engine = engineById(id);
  const count = getDropdownValue($('s-search-count')) || _settings.search_result_count || 8;
  const missing = engine && !engine.configured;
  el.textContent = `active: ${labelOf(id)} · ${count} results${missing ? ' · needs a key first' : ''}`;
  el.dataset.state = missing ? 'error' : '';
}

export async function saveSearchSettings() {
  const provider = getDropdownValue($('s-search-provider'));
  const fallback = getDropdownValue($('s-search-fallback')) || 'duckduckgo';
  const count = parseInt(getDropdownValue($('s-search-count')), 10) || 8;
  const patch = {
    search_provider: provider,
    search_result_count: count,
    search_fallback: fallback,
    search_fallback_chain: fallback === 'none' ? [] : [fallback],
  };
  const engine = engineById(provider);
  const key = $('s-engine-key')?.value.trim();
  if (key && engine?.key_setting && !$('s-engine-key-row').hidden) patch.search_keys = { [provider]: key };
  for (const [id, setting] of [['s-searxng-url', 'searxng_url'], ['s-gpse-key', 'google_pse_api_key'], ['s-gpse-cx', 'google_pse_cx']]) {
    const value = $(id)?.value.trim();
    if (value) patch[setting] = value;
  }
  const saved = await _patchSettings(patch);
  if (!saved) return;
  _settings = { ..._settings, ...patch };
  if (patch.search_keys || patch.google_pse_api_key || patch.searxng_url) {
    _engines = (await _json('/api/search/engines').catch(() => ({ engines: _engines }))).engines || _engines;
    updateEngineFields();
  }
  updateSearchStatus();
}

async function testSearch() {
  const button = $('s-search-test-btn');
  const engine = getDropdownValue($('s-search-provider'));
  if (engine === 'disabled') { updateSearchStatus('search is disabled'); return; }
  button.disabled = true;
  updateSearchStatus(`testing ${labelOf(engine)}…`);
  try {
    const result = await _json('/api/search/test', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ engine }),
    });
    updateSearchStatus(result.ok
      ? `${labelOf(engine)} works · ${result.count} results in ${result.ms} ms`
      : `${labelOf(engine)} gave no results (${result.failure || 'empty'}) after ${result.ms} ms`, !result.ok);
  } catch (error) {
    // say it failed, then why; the bare server detail read like a status, not an error
    updateSearchStatus(error.message ? `test failed: ${error.message}` : 'test failed', true);
  } finally {
    button.disabled = false;
  }
}

// ── custom engines ──
function renderCustomList() {
  const list = $('s-custom-search-list');
  if (!list) return;
  const rows = _engines.filter(engine => engine.custom);
  list.innerHTML = rows.length ? rows.map(engine => `
    <div class="settings-list-row" data-custom-engine="${_esc(engine.id)}">
      <div style="min-width:0;flex:1">
        <div class="row-name">${_esc(engine.label)}</div>
        <div class="row-meta">${_esc(engine.url)}${engine.key_configured ? ' · key saved' : ''}</div>
      </div>
      <button type="button" class="btn" data-custom-edit="${_esc(engine.id)}">edit</button>
      <button type="button" class="btn" data-custom-remove="${_esc(engine.id)}">remove</button>
    </div>`).join('') : '<div class="s-card-hint">no custom engines yet</div>';
}

const FORM_FIELDS = {
  name: 's-cse-name', url: 's-cse-url', body: 's-cse-body', key_header: 's-cse-key-header',
  key_prefix: 's-cse-key-prefix', results: 's-cse-results', url_field: 's-cse-url-field',
  title_field: 's-cse-title-field', snippet_field: 's-cse-snippet-field',
};

function setMethod(value) {
  $('s-cse-method').querySelectorAll('[role="radio"]').forEach(choice => {
    const on = choice.dataset.value === value;
    choice.setAttribute('aria-checked', String(on));
    choice.tabIndex = on ? 0 : -1;
  });
  $('s-cse-body-row').hidden = value !== 'POST';
}

const currentMethod = () => $('s-cse-method').querySelector('[aria-checked="true"]')?.dataset.value || 'GET';

function openForm(engine = null) {
  _editing = engine?.id || '';
  const form = $('s-custom-search-form');
  for (const [field, id] of Object.entries(FORM_FIELDS)) {
    const saved = field === 'name' ? engine?.label : engine?.[field];
    $(id).value = engine ? saved || '' : { url_field: 'url', title_field: 'title', snippet_field: 'snippet' }[field] || '';
  }
  $('s-cse-key').value = '';
  $('s-cse-key').placeholder = engine?.key_configured ? 'saved: enter a replacement' : '';
  setMethod(engine?.method || 'GET');
  $('s-cse-status').textContent = '';
  $('s-cse-save').textContent = engine ? 'save changes' : 'save engine';
  form.hidden = false;
  $('s-custom-search-add').hidden = true;
  $('s-cse-name').focus();
}

function closeForm() {
  _editing = null;
  $('s-custom-search-form').hidden = true;
  $('s-custom-search-add').hidden = false;
  $('s-custom-search-add').focus();
}

async function saveCustom(event) {
  event.preventDefault();
  const button = $('s-cse-save');
  const status = $('s-cse-status');
  const body = { method: currentMethod() };
  for (const [field, id] of Object.entries(FORM_FIELDS)) body[field] = $(id).value.trim();
  const key = $('s-cse-key').value.trim();
  body.key = key || (_editing ? null : '');
  button.disabled = true;
  status.dataset.state = '';
  status.textContent = 'saving…';
  try {
    const url = _editing ? `/api/search/custom/${encodeURIComponent(_editing)}` : '/api/search/custom';
    const saved = await _json(url, {
      method: _editing ? 'PUT' : 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    });
    await loadSearchEngines(_settings);
    toast(`${saved.label} saved`, 'success');
    closeForm();
  } catch (error) {
    status.textContent = error.message || 'could not save this engine';
    status.dataset.state = 'error';
  } finally {
    button.disabled = false;
  }
}

async function removeCustom(id) {
  const engine = engineById(id);
  if (!engine || !await _dlgConfirm(`remove ${engine.label}? its saved key goes too.`, { confirmLabel: 'remove engine' })) return;
  try {
    await _json(`/api/search/custom/${encodeURIComponent(id)}`, { method: 'DELETE' });
    const settings = await _json('/api/settings').catch(() => _settings);
    await loadSearchEngines(settings);
    toast(`${engine.label} removed`, 'success');
  } catch (error) {
    toast(error.message || 'could not remove this engine', 'error');
  }
}

export function wireSearchEngines() {
  $('s-search-provider')?.addEventListener('change', () => { updateEngineFields(); saveSearchSettings(); });
  $('s-search-fallback')?.addEventListener('change', saveSearchSettings);
  $('s-search-count')?.addEventListener('change', saveSearchSettings);
  ['s-engine-key', 's-searxng-url', 's-gpse-key', 's-gpse-cx'].forEach(id => $(id)?.addEventListener('blur', saveSearchSettings));
  $('s-search-test-btn')?.addEventListener('click', testSearch);
  $('s-custom-search-add')?.addEventListener('click', () => openForm());
  $('s-cse-cancel')?.addEventListener('click', closeForm);
  $('s-custom-search-form')?.addEventListener('submit', saveCustom);
  $('s-custom-search-form')?.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); closeForm(); }
  });
  const method = $('s-cse-method');
  if (method) {
    method.addEventListener('click', event => {
      const choice = event.target.closest('[role="radio"]');
      if (choice) setMethod(choice.dataset.value);
    });
    wireChoiceGroup(method);
  }
  $('s-hidden-sites-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const input = $('s-hidden-site');
    const site = input.value.trim();
    if (!site) { input.focus(); return; }
    const current = _settings.andromeda_blocked_sites || [];
    if (await saveHiddenSites([...current, site], `${site} is hidden`)) input.value = '';
  });
  $('s-hidden-sites-list')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-hidden-site]');
    if (!button) return;
    const site = button.dataset.hiddenSite;
    const sites = (_settings.andromeda_blocked_sites || []).filter(value => value !== site);
    if (await saveHiddenSites(sites, `${site} shows in results again`)) $('s-hidden-site')?.focus();
  });
  $('s-custom-search-list')?.addEventListener('click', event => {
    const edit = event.target.closest('[data-custom-edit]');
    const remove = event.target.closest('[data-custom-remove]');
    if (edit) openForm(engineById(edit.dataset.customEdit));
    if (remove) removeCustom(remove.dataset.customRemove);
  });
}
