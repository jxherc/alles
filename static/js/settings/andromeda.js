// Settings → andromeda: where search comes from, how answers are made, and the model that writes them.
// The answer model is the andromeda_answer role, the same stored value the models section edits.
import { createSettingsPane } from './pane.js';
import { _patchSettings, _bindSwitch, _esc } from './shared.js';
import { onModelRoles, roleOptions, setModelRole } from './model_roles.js';
import { toast, plainError } from '../util.js';
import { confirm as confirmDialog } from '../dialog.js';
import { getDropdownValue, setDropdownValue, populateDropdown } from '../dropdown.js?v=215';
import { t, tp } from '../i18n.js';

export const ANDROMEDA_SETTINGS_EVENT = 'alles:andromeda-settings';
const ANSWER_ROLE = 'andromeda_answer';

const SEARCH_SECRET_SETTINGS = new Set([
  'tavily_api_key', 'brave_api_key', 'google_pse_api_key', 'serper_api_key', 'exa_api_key',
]);

// plaintext keys never stay in this pane's copy of the settings
export function sanitizeSearchSettings(settings = {}) {
  return Object.fromEntries(
    Object.entries(settings).filter(([key]) => !SEARCH_SECRET_SETTINGS.has(key)),
  );
}

export function configuredFallbackChain(primary, fallback) {
  if (!fallback || fallback === 'none' || fallback === 'disabled' || fallback === primary) return [];
  return [fallback];
}

const CREDENTIALS = {
  's-andromeda-tavily-key': 'tavily_api_key',
  's-andromeda-brave-key': 'brave_api_key',
  's-andromeda-searxng-url': 'searxng_url',
  's-andromeda-google-key': 'google_pse_api_key',
  's-andromeda-google-cx': 'google_pse_cx',
  's-andromeda-serper-key': 'serper_api_key',
  's-andromeda-exa-key': 'exa_api_key',
};

let _engines = [];
let _settings = {};
let _roles = {};
let _models = [];
let _answerChoices = {};
let _bandChoices = new Map();
const _clearPending = new Set();

const $ = id => document.getElementById(id);
const value = (id, fallback = '') => getDropdownValue($(id)) || fallback;
const engineById = id => _engines.find(engine => engine.id === id);
// the server calls its keyless engine "free search" in english
const engineName = engine => engine.id === 'duckduckgo' ? t('andromeda.x_free_search') : engine.label;
const labelOf = id => id === 'disabled' ? t('settings.search_disabled')
  : id === 'none' ? t('common.none') : (engineById(id) ? engineName(engineById(id)) : id);

async function json(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data?.detail === 'string' && data.detail ? data.detail : t('common.request_failed'));
  return data;
}

function setStatus(message = '', error = false) {
  const node = $('s-andromeda-search-status');
  if (!node) return;
  node.textContent = message;
  node.dataset.state = error ? 'error' : '';
}

// the andromeda page listens, so a search right after a change already follows it
async function write(patch) {
  const saved = await _patchSettings(patch);
  if (!saved) return null;
  _settings = { ..._settings, ...sanitizeSearchSettings(patch), ...sanitizeSearchSettings(saved) };
  globalThis.window?.dispatchEvent(new CustomEvent(ANDROMEDA_SETTINGS_EVENT, { detail: _settings }));
  return saved;
}

// ── search sources ──
function engineOptions(withNone) {
  const rows = _engines.map(engine => ({
    value: engine.id,
    label: engine.configured || engine.custom ? engineName(engine) : t('settings.search_needs_key', { engine: engineName(engine) }),
  }));
  return withNone ? [{ value: 'none', label: t('common.none') }, ...rows] : [...rows, { value: 'disabled', label: t('settings.search_disabled') }];
}

function savedFallback(settings, primary) {
  return [settings.search_fallback, ...(settings.search_fallback_chain || [])]
    .find(item => item && item !== 'none' && item !== primary) || 'none';
}

// only the keys of the engines in use show
function updateFields() {
  const primary = value('s-andromeda-primary', 'duckduckgo');
  const fallback = value('s-andromeda-fallback', 'none');
  const used = [...new Set([primary, fallback].filter(item => item && !['none', 'disabled'].includes(item)))];
  let shown = 0;
  document.querySelectorAll('[data-andromeda-provider-field]').forEach(row => {
    row.hidden = !used.includes(row.dataset.andromedaProviderField);
    if (!row.hidden) shown += 1;
  });
  const container = $('s-andromeda-provider-fields');
  if (container) container.hidden = shown === 0;
}

function setClearState(inputId, configured) {
  const button = document.querySelector(`[data-andromeda-clear-setting="${inputId}"]`);
  if (button) button.disabled = !configured;
}

function setPlaceholder(id, configured, empty = t('andromeda.x_not_configured')) {
  const input = $(id);
  if (input) input.placeholder = configured ? t('andromeda.x_saved_replace') : empty;
}

// engines added after this section was written get the same key field as the first ones
function ensureEngineFields(engines) {
  const container = $('s-andromeda-provider-fields');
  if (!container) return;
  for (const engine of engines) {
    if (engine.custom || !engine.key_setting || engine.extra?.length) continue;
    const inputId = `s-andromeda-${engine.id}-key`;
    if ($(inputId)) continue;
    const name = t('andromeda.x_api_key_named', { name: engine.label.toLowerCase() });
    const field = document.createElement('div');
    field.className = 's-field';
    field.dataset.andromedaProviderField = engine.id;
    field.innerHTML = `<label for="${inputId}">${_esc(name)}</label><div style="display:flex;gap:0.4rem"><input id="${inputId}" type="password" class="settings-input" style="flex:1" autocomplete="new-password" placeholder="${_esc(t('andromeda.x_not_configured'))}"><button type="button" class="btn" data-andromeda-clear-setting="${inputId}" aria-label="${_esc(t('andromeda.x_clear_named', { name }))}">${_esc(t('common.clear'))}</button></div>`;
    container.append(field);
    CREDENTIALS[inputId] = engine.key_setting;
    SEARCH_SECRET_SETTINGS.add(engine.key_setting);
    wireCredentialInput(field.querySelector('input'));
    wireCredentialClear(field.querySelector('button'));
  }
}

function showEngines() {
  const primary = value('s-andromeda-primary', _settings.search_provider || 'duckduckgo');
  const fallback = value('s-andromeda-fallback', savedFallback(_settings, primary));
  populateDropdown($('s-andromeda-primary'), engineOptions(false), primary);
  populateDropdown($('s-andromeda-fallback'), engineOptions(true), fallback);
  ensureEngineFields(_engines);
  updateFields();
}

function showSources() {
  const primary = _settings.search_provider || 'duckduckgo';
  setDropdownValue($('s-andromeda-primary'), primary);
  setDropdownValue($('s-andromeda-fallback'), savedFallback(_settings, primary));
  setDropdownValue($('s-andromeda-count'), String(_settings.search_result_count || 8));
  for (const [id, setting] of Object.entries(CREDENTIALS)) {
    if (id.endsWith('-key')) {
      const configured = !!_settings[`${setting}_configured`];
      setPlaceholder(id, configured);
      setClearState(id, configured);
    }
  }
  const url = $('s-andromeda-searxng-url');
  if (url) url.placeholder = _settings.searxng_url || 'https://search.example.com';
  setClearState('s-andromeda-searxng-url', !!_settings.searxng_url);
  const cx = $('s-andromeda-google-cx');
  if (cx) cx.value = _settings.google_pse_cx || '';
  setClearState('s-andromeda-google-cx', !!_settings.google_pse_cx);
  updateFields();
}

async function refreshEngines() {
  try {
    _engines = (await json('/api/search/engines')).engines || _engines;
  } catch { return; }
  showEngines();
}

async function saveSources() {
  const primary = value('s-andromeda-primary', 'duckduckgo');
  const picked = value('s-andromeda-fallback', 'none');
  const fallback = picked === primary ? 'none' : picked;
  if (fallback !== picked) setDropdownValue($('s-andromeda-fallback'), fallback);
  const count = Number.parseInt(value('s-andromeda-count', '8'), 10) || 8;
  const changed = primary !== (_settings.search_provider || 'duckduckgo')
    || fallback !== (_settings.search_fallback || 'none');
  const patch = { search_provider: primary, search_fallback: fallback, search_result_count: count };
  // an untouched provider pair keeps the chain it was loaded with
  if (changed) patch.search_fallback_chain = configuredFallbackChain(primary, fallback);
  updateFields();
  if (!await write(patch)) showSources();
}

async function saveCredential(input) {
  const setting = CREDENTIALS[input.id];
  const text = input.value.trim();
  if (!setting || !text || _clearPending.has(input.id)) return;
  input.disabled = true;
  try {
    if (!await write({ [setting]: text })) return;
    setClearState(input.id, true);
    if (input.type === 'password') {
      input.value = '';
      input.placeholder = t('andromeda.x_saved_replace');
    }
    await refreshEngines();
  } finally {
    input.disabled = false;
  }
}

async function clearCredential(button) {
  const input = $(button.dataset.andromedaClearSetting);
  const setting = CREDENTIALS[input?.id];
  if (!input || !setting) return;
  _clearPending.add(input.id);
  let cleared = false;
  button.disabled = true;
  input.disabled = true;
  try {
    if (!await write({ [setting]: '' })) return;
    input.value = '';
    setPlaceholder(input.id, false, input.id === 's-andromeda-searxng-url'
      ? 'https://search.example.com' : input.id === 's-andromeda-google-cx'
        ? t('andromeda.x_search_engine_id') : t('andromeda.x_not_configured'));
    cleared = true;
    await refreshEngines();
  } finally {
    _clearPending.delete(input.id);
    input.disabled = false;
    button.disabled = cleared;
  }
}

function wireCredentialInput(input) {
  input.addEventListener('blur', event => saveCredential(event.currentTarget));
}

function wireCredentialClear(button) {
  button.addEventListener('pointerdown', () => {
    const input = $(button.dataset.andromedaClearSetting);
    if (!input) return;
    _clearPending.add(input.id);
    // a cancelled pointer gesture has no click to perform the clear
    setTimeout(() => { if (!button.disabled) _clearPending.delete(input.id); }, 0);
  });
  button.addEventListener('click', () => clearCredential(button));
}

async function testSources() {
  const button = $('s-andromeda-test');
  const engine = value('s-andromeda-primary');
  if (engine === 'disabled') { setStatus(t('settings.search_is_disabled')); return; }
  button.disabled = true;
  setStatus(t('settings.search_testing', { engine: labelOf(engine) }));
  try {
    const result = await json('/api/search/test', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ engine }),
    });
    setStatus(result.ok
      ? t('settings.search_works', { engine: labelOf(engine), count: result.count, ms: result.ms })
      : t('settings.search_no_results', { engine: labelOf(engine), reason: result.failure || t('settings.search_empty'), ms: result.ms }), !result.ok);
  } catch (error) {
    setStatus(error.message ? t('settings.search_test_failed_why', { message: error.message }) : t('connections.test_failed'), true);
  } finally {
    button.disabled = false;
  }
}

// ── local searxng ──
function searxngState(service) {
  if (!service.support_verified && !service.installed) return t('andromeda.x_sx_unavailable');
  if (!service.installed) return service.available ? t('andromeda.x_sx_ready') : t('andromeda.x_sx_needs_docker');
  if (!service.owned) return t('andromeda.x_sx_ownership');
  if (service.healthy) return t('andromeda.x_sx_healthy');
  if (service.running) return t('andromeda.x_sx_unhealthy');
  return t('andromeda.x_sx_stopped');
}

function addSearxngAction(host, action, label, disabled = false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'btn';
  button.dataset.searxngAction = action;
  button.textContent = label;
  button.disabled = disabled;
  host.appendChild(button);
}

async function loadSearxng(isCurrent = () => true) {
  const status = $('s-andromeda-searxng-status');
  const meta = $('s-andromeda-searxng-meta');
  const actions = $('s-andromeda-searxng-actions');
  if (!status || !meta || !actions) return;
  actions.replaceChildren();
  status.dataset.state = '';
  try {
    const service = await json('/api/system/searxng');
    if (!isCurrent()) return;
    status.textContent = searxngState(service);
    meta.textContent = `${service.bind} · ${service.version} · ${service.license}${service.data_kept ? t('andromeda.x_sx_data_kept') : ''}`;
    if (!service.installed) {
      if (service.support_verified) addSearxngAction(actions, 'install', t('andromeda.x_act_install'), !service.available);
      return;
    }
    if (!service.owned) return;
    addSearxngAction(actions, service.running ? 'stop' : 'start', service.running ? t('common.stop') : t('andromeda.x_act_start'), !service.available);
    addSearxngAction(actions, 'restart', t('andromeda.x_act_restart'), !service.available);
    addSearxngAction(actions, 'test', t('andromeda.x_act_test'), !service.available || !service.running);
    addSearxngAction(actions, 'update', t('andromeda.x_act_update'), !service.available);
    addSearxngAction(actions, 'rollback', t('andromeda.x_act_rollback'), !service.available);
    addSearxngAction(actions, 'uninstall', t('andromeda.x_act_uninstall'));
  } catch (error) {
    if (!isCurrent()) return;
    actions.replaceChildren();
    status.textContent = plainError(error.message || t('andromeda.x_sx_status_unavailable'));
    status.dataset.state = 'error';
    meta.textContent = t('andromeda.x_external_remain');
  }
}

const actionLabel = action => ({
  install: t('andromeda.x_act_install'), start: t('andromeda.x_act_start'), stop: t('common.stop'),
  restart: t('andromeda.x_act_restart'), test: t('andromeda.x_act_test'), update: t('andromeda.x_act_update'),
  rollback: t('andromeda.x_act_rollback'), uninstall: t('andromeda.x_act_uninstall_short'),
}[action] ?? action);

async function manageSearxng(action, button) {
  if (action === 'uninstall' && !await confirmDialog(t('andromeda.x_uninstall_confirm'))) return;
  button.disabled = true;
  const status = $('s-andromeda-searxng-status');
  if (status) status.textContent = t('andromeda.x_in_progress', { action: actionLabel(action) });
  let message = '';
  let state = '';
  try {
    const result = await json(`/api/system/searxng/${action}`, { method: 'POST' });
    if (action === 'test') {
      if (result?.ok !== true || !Number.isInteger(result.results) || result.results < 0) throw new Error(t('andromeda.x_invalid_test'));
      message = t('andromeda.x_search_passed', { count: result.results });
    }
    _settings = sanitizeSearchSettings(await json('/api/settings'));
    showSources();
  } catch (error) {
    message = error.message || t('andromeda.x_action_failed', { action: actionLabel(action) });
    state = 'error';
  } finally {
    await loadSearxng();
    await refreshEngines();
    if (status && message) {
      status.textContent = message;
      status.dataset.state = state;
    }
  }
}

// ── answer ──
function showAnswerModel() {
  const select = $('s-andromeda-answer-model');
  if (!select) return;
  const data = roleOptions(_models, _roles[ANSWER_ROLE]);
  _answerChoices = data.choices;
  populateDropdown(select, data.options, data.selected);
  select.setAttribute('aria-invalid', String(data.selected.startsWith('unavailable-')));
}

async function saveAnswerModel() {
  const choice = _answerChoices[value('s-andromeda-answer-model')] || null;
  try {
    _roles = await setModelRole(ANSWER_ROLE, choice, { source: 'andromeda' });
    toast(t('common.saved'), 'success');
  } catch (error) {
    toast(error.message || t('providers.defaults_not_saved'), 'error');
  }
  showAnswerModel();
}

function showBandModels() {
  const saved = _settings.andromeda_model_bands || {};
  _bandChoices = new Map();
  let index = 0;
  document.querySelectorAll('.s-andromeda-model').forEach(select => {
    const options = [{ value: '', label: select.dataset.band === 'standard' ? t('settings.andromeda_use_answer_role') : t('settings.not_configured') }];
    let selected = '';
    for (const endpoint of _models) {
      for (const model of endpoint.models || []) {
        const key = String(++index);
        _bandChoices.set(`${select.dataset.band}:${key}`, { endpoint_id: endpoint.id, model });
        options.push({ value: key, label: `${model} · ${endpoint.name}` });
        const current = saved[select.dataset.band] || {};
        if (current.endpoint_id === endpoint.id && current.model === model) selected = key;
      }
    }
    populateDropdown(select, options, selected);
  });
}

async function saveBandModels() {
  const choices = {};
  document.querySelectorAll('.s-andromeda-model').forEach(select => {
    const choice = _bandChoices.get(`${select.dataset.band}:${getDropdownValue(select)}`);
    if (choice) choices[select.dataset.band] = choice;
  });
  const status = $('s-andromeda-model-status');
  const saved = await write({ andromeda_model_bands: choices });
  if (status) status.textContent = saved ? t('settings.andromeda_choices_saved') : '';
  if (!saved) showBandModels();
}

async function qualifyAutoModel() {
  const choice = _bandChoices.get(`auto:${value('s-andromeda-model-auto')}`);
  const status = $('s-andromeda-model-status');
  if (!choice) { if (status) status.textContent = t('settings.andromeda_choose_auto'); return; }
  const button = $('s-andromeda-qualify');
  if (button) button.disabled = true;
  if (status) status.textContent = t('settings.andromeda_qualifying');
  try {
    const result = await json('/api/andromeda/models/qualify', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(choice),
    });
    if (status) {
      status.textContent = result.passed
        ? tp('settings.andromeda_qualified', result.required_claims, { supported: result.supported_claims })
        : tp('settings.andromeda_not_qualified', result.required_claims, { supported: result.supported_claims });
    }
  } catch (error) {
    if (status) status.textContent = plainError(error.message || t('settings.andromeda_fixture_failed'));
  }
  if (button) button.disabled = false;
}

function showAnswerSettings() {
  for (const [id, key] of [['s-andromeda-results', 'andromeda_normal_results'],
    ['s-andromeda-overview', 'andromeda_overview'], ['s-andromeda-verification', 'andromeda_verification_enabled']]) {
    _bindSwitch($(id), () => _settings[key] !== false, next => write({ [key]: next }));
  }
  // off unless the owner turns it on
  _bindSwitch($('s-andromeda-confirm-remote'), () => _settings.andromeda_confirm_remote === true,
    next => write({ andromeda_confirm_remote: next }));
  setDropdownValue($('s-andromeda-verifier-mode'), _settings.andromeda_verifier_mode || 'freshness-sensitive');
  setDropdownValue($('s-andromeda-band'), _settings.andromeda_model_band || 'standard');
}

async function saveDropdown(id, key, fallback) {
  if (!await write({ [key]: value(id, fallback) })) setDropdownValue($(id), _settings[key] || fallback);
}

// ── hidden sites ──
function renderHiddenSites() {
  const list = $('s-hidden-sites-list');
  if (!list) return;
  const sites = Array.isArray(_settings.andromeda_blocked_sites) ? _settings.andromeda_blocked_sites : [];
  list.innerHTML = sites.length ? sites.map(site => `
    <div class="settings-list-row">
      <div class="row-name" style="flex:1;min-width:0">${_esc(site)}</div>
      <button type="button" class="btn" data-hidden-site="${_esc(site)}" aria-label="${_esc(t('settings.search_show_site_again', { site }))}">${_esc(t('settings.search_show_again'))}</button>
    </div>`).join('') : `<div class="s-card-hint">${_esc(t('settings.search_no_hidden'))}</div>`;
}

async function saveHiddenSites(sites, message) {
  const status = $('s-hidden-sites-status');
  const saved = await write({ andromeda_blocked_sites: sites });
  if (!saved) {
    if (status) { status.textContent = t('settings.search_site_not_saved'); status.dataset.state = 'error'; }
    return false;
  }
  _settings = { ..._settings, andromeda_blocked_sites: saved.andromeda_blocked_sites || [] };
  renderHiddenSites();
  if (status) { status.textContent = message; status.dataset.state = ''; }
  return true;
}

function wire() {
  for (const id of ['s-andromeda-primary', 's-andromeda-fallback', 's-andromeda-count']) {
    $(id)?.addEventListener('change', saveSources);
  }
  $('s-andromeda-test')?.addEventListener('click', testSources);
  for (const id of Object.keys(CREDENTIALS)) {
    const input = $(id);
    if (input) wireCredentialInput(input);
  }
  document.querySelectorAll('[data-andromeda-clear-setting]').forEach(wireCredentialClear);
  $('s-andromeda-searxng-refresh')?.addEventListener('click', () => loadSearxng());
  $('s-andromeda-searxng-actions')?.addEventListener('click', event => {
    const button = event.target.closest('[data-searxng-action]');
    if (button) manageSearxng(button.dataset.searxngAction, button);
  });
  $('s-andromeda-answer-model')?.addEventListener('change', saveAnswerModel);
  $('s-andromeda-verifier-mode')?.addEventListener('change', () => saveDropdown('s-andromeda-verifier-mode', 'andromeda_verifier_mode', 'freshness-sensitive'));
  $('s-andromeda-band')?.addEventListener('change', () => saveDropdown('s-andromeda-band', 'andromeda_model_band', 'standard'));
  document.querySelectorAll('.s-andromeda-model').forEach(select => select.addEventListener('change', saveBandModels));
  $('s-andromeda-qualify')?.addEventListener('click', qualifyAutoModel);
  $('s-hidden-sites-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const input = $('s-hidden-site');
    const site = input.value.trim();
    if (!site) { input.focus(); return; }
    const current = _settings.andromeda_blocked_sites || [];
    if (await saveHiddenSites([...current, site], t('settings.search_site_hidden', { site }))) input.value = '';
  });
  $('s-hidden-sites-list')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-hidden-site]');
    if (!button) return;
    const site = button.dataset.hiddenSite;
    const sites = (_settings.andromeda_blocked_sites || []).filter(item => item !== site);
    if (await saveHiddenSites(sites, t('settings.search_site_shown', { site }))) $('s-hidden-site')?.focus();
  });
  // the models section can change the answer model while this one is closed
  onModelRoles(({ roles, source }) => {
    if (source === 'andromeda' || !roles) return;
    _roles = roles;
    showAnswerModel();
  });
}

export const andromedaPane = createSettingsPane({
  init: wire,
  async load(isCurrent) {
    let settings;
    let engines;
    let models;
    try {
      [settings, engines, models] = await Promise.all([
        json('/api/settings'),
        json('/api/search/engines').catch(() => ({ engines: _engines })),
        json('/api/models').catch(() => _models),
      ]);
    } catch {
      if (isCurrent()) toast(t('settings.search_load_failed'), 'error');
      return;
    }
    if (!isCurrent()) return;
    _settings = sanitizeSearchSettings(settings);
    _roles = settings.model_roles || {};
    _engines = engines.engines || [];
    _models = Array.isArray(models) ? models : [];
    showEngines();
    showSources();
    showAnswerSettings();
    showBandModels();
    showAnswerModel();
    renderHiddenSites();
    setStatus('');
    void loadSearxng(isCurrent);
  },
});
