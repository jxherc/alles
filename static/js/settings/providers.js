import { createSettingsPane } from './pane.js';
import { toast } from '../util.js';
import { confirm as _dlgConfirm } from '../dialog.js';
import { loadModels, addEndpoint, renderModelList } from '../models.js?v=213';
import { initCustomDropdowns, getDropdownValue, populateDropdown } from '../dropdown.js?v=212';
import { _esc, _escAttr, _fetchWithRecentOwner } from './shared.js';
import { API_TYPES, authFor, mountProviderPicker } from '../model_providers.js';
import { wireChoiceGroup } from '../kokuen.js?v=2';

let _providersActive = false;
let _providersCurrent = () => false;
let _endpointLoadGeneration = 0;
let _localLoadGeneration = 0;
let _modelRolesDirty = false;
let _modelRolesRevision = 0;
let _oauthStartGeneration = 0;
const _oauthPolls = new Set();
const _endpointPending = new Set();
const _endpointConfirmations = new Set();
let _endpointAddPending = false;
let _endpointAddRevision = 0;
let _endpointAddConfigRevision = 0;
let _endpointPartialCreate = null;
const _localPresetPending = new Map();
const _localPresetConfirmations = new Set();
let _customPullPending = null;

function _syncLocalPresetPending(model) {
  document.querySelectorAll(`#s-local-presets [data-local-model="${CSS.escape(model)}"]`).forEach(row => {
    const pending = _localPresetPending.get(model);
    row.querySelector('[data-local-state]').textContent = pending?.label || 'installed';
    row.querySelectorAll('[data-local-serve], [data-local-remove]').forEach(button => {
      const action = button.hasAttribute('data-local-remove') ? 'remove' : 'serve';
      button.disabled = !!pending || (action === 'remove' && _localPresetConfirmations.has(model));
      button.textContent = pending?.action === action ? pending.label : action;
    });
  });
}

function _claimLocalPreset(model, action, label) {
  const pending = { action, label };
  _localPresetPending.set(model, pending);
  _localLoadGeneration += 1;
  _syncLocalPresetPending(model);
  return pending;
}

function _releaseLocalPreset(model, pending) {
  if (_localPresetPending.get(model) !== pending) return;
  _localPresetPending.delete(model);
  _localLoadGeneration += 1;
  _syncLocalPresetPending(model);
}

function _setEndpointPending(id, pending) {
  if (pending) { _endpointPending.add(id); _endpointLoadGeneration += 1; }
  else _endpointPending.delete(id);
  document.querySelector(`#s-ep-list [data-id="${CSS.escape(id)}"]`)
    ?.querySelectorAll('[data-save-list], [data-probe], [data-test-ep], [data-auth-refresh], [data-auth-revoke], [data-del]')
    .forEach(button => { button.disabled = pending; });
  _showManualEndpointFields();
}

async function _confirmEndpointAction(id, message) {
  if (_endpointConfirmations.has(id)) return false;
  _endpointConfirmations.add(id);
  _endpointLoadGeneration += 1;
  try { return await _dlgConfirm(message); }
  finally {
    _endpointConfirmations.delete(id);
    _endpointLoadGeneration += 1;
  }
}

function _hasEndpointDrafts() {
  // A delayed read must keep the field the owner is about to edit, too.
  return !!document.querySelector('#s-ep-list [data-editor][data-dirty]')
    || !!document.activeElement?.matches('#s-ep-list [data-edit-models], #s-ep-list [data-edit-adapter]');
}

// ── models pane ───────────────────────────────────────────────────────────────
async function loadLocalModels() {
  const ollamaEl = document.getElementById('s-local-ollama');
  const hwEl = document.getElementById('s-local-hw');
  const listEl = document.getElementById('s-local-presets');
  if (!ollamaEl || !hwEl || !listEl || !_providersActive) return;
  const generation = ++_localLoadGeneration;
  ollamaEl.textContent = 'checking Ollama...';
  try {
    const data = await _localJson('/api/local-models/status');
    if (!_providersActive || generation !== _localLoadGeneration) return;
    const o = data.ollama || {};
    const hw = data.hardware || {};
    const gpu = (hw.gpus || []).map(g => `${g.name} (${g.vram_gb} GB)`).join(', ') || 'no NVIDIA GPU detected';
    const state = o.running ? 'running' : (o.installed ? 'installed, stopped' : 'not installed');
    ollamaEl.textContent = `Ollama: ${state} - ${o.base_url || 'http://localhost:11434'}`;
    hwEl.textContent = `Hardware: ${hw.ram_gb || '?'} GB RAM - ${gpu}`;
    renderLocalPresets(data.presets || []);
  } catch (e) {
    if (!_providersActive || generation !== _localLoadGeneration) return;
    ollamaEl.textContent = e.message || 'local model status failed';
    hwEl.textContent = '';
    if (!_localPresetPending.size) listEl.innerHTML = '';
  }
}

// only models already on this machine; nothing is suggested for download
function renderLocalPresets(presets) {
  const listEl = document.getElementById('s-local-presets');
  if (!listEl) return;
  presets = presets.filter(p => p.installed);
  if (!presets.length) {
    listEl.innerHTML = '<div class="s-card-hint">no local models yet. pull one by name below.</div>';
    return;
  }
  listEl.innerHTML = presets.map(p => {
    const badge = p.fit === 'fits_gpu' ? 'gpu fit' : (p.fit === 'fits_cpu' ? 'cpu fit' : 'large');
    return `<div class="settings-list-row" data-local-model="${_escAttr(p.model)}" data-local-installed="true" style="align-items:flex-start;gap:0.55rem">
      <span class="status-dot" style="margin-top:0.35rem;background:var(--green)"></span>
      <div style="min-width:0;flex:1">
        <div class="row-name">${_esc(p.label)} <span style="color:var(--muted);font-weight:400">${_esc(p.model)}</span></div>
        <div class="row-meta">${badge} - <span data-local-state>installed</span> - ${_esc(p.fit_reason || '')}</div>
      </div>
      <button class="btn" data-local-remove="${_escAttr(p.model)}">remove</button>
      <button type="button" class="btn" data-local-serve="${_escAttr(p.model)}">serve</button>
    </div>`;
  }).join('');

  listEl.querySelectorAll('[data-local-serve]').forEach(btn => {
    btn.addEventListener('click', () => serveLocalModel(btn.dataset.localServe, btn));
  });
  listEl.querySelectorAll('[data-local-remove]').forEach(btn => {
    btn.addEventListener('click', () => deleteLocalModel(btn.dataset.localRemove, btn));
  });
  presets.forEach(p => _syncLocalPresetPending(p.model));
}

async function startLocalOllama() {
  const btn = document.getElementById('s-local-start-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'starting...'; }
  try {
    const data = await _localJson('/api/local-models/start', { method: 'POST' });
    if (data.ok) toast(data.started ? 'Ollama started' : 'Ollama already starting', 'success');
    else toast(data.error || 'Ollama start failed', 'error');
  } catch (e) {
    toast(e.message || 'Ollama start failed', 'error');
  }
  if (btn) { btn.disabled = false; btn.textContent = 'start Ollama'; }
  setTimeout(loadLocalModels, 700);
}

async function pollLocalJob(jobId, btn, model = null, pending = null, onFinish = null) {
  if (!jobId) {
    if (model) _releaseLocalPreset(model, pending);
    btn.disabled = false;
    btn.textContent = 'download';
    toast('download could not be confirmed; try again', 'error');
    onFinish?.(false);
    return;
  }
  try {
    const job = await _localJson(`/api/local-models/jobs/${jobId}`);
    if (job?.id !== jobId || !['queued', 'running', 'done', 'error'].includes(job.status))
      throw new Error('download status could not be confirmed');
    if (job.status === 'done') {
      if (typeof job.model !== 'string' || !job.model) throw new Error('invalid download receipt');
      if (model) _releaseLocalPreset(model, pending);
      btn.textContent = 'downloaded';
      toast(`${job.model} downloaded`, 'success');
      loadLocalModels();
      loadModels();
      onFinish?.(true);
      return;
    }
    if (job.status === 'error') {
      if (model) _releaseLocalPreset(model, pending);
      btn.disabled = false;
      btn.textContent = 'download';
      toast(job.error || 'download failed', 'error');
      onFinish?.(false);
      return;
    }
    btn.textContent = job.status === 'running' ? 'pulling...' : 'queued';
    if (model && _localPresetPending.get(model) === pending) {
      pending.label = btn.textContent;
      _syncLocalPresetPending(model);
    }
    setTimeout(() => pollLocalJob(jobId, btn, model, pending, onFinish), 1800);
  } catch {
    if (model) _releaseLocalPreset(model, pending);
    btn.disabled = false;
    btn.textContent = 'download';
    toast('download status could not be confirmed; try again', 'error');
    onFinish?.(false);
  }
}

async function pullCustomLocalModel() {
  const inp = document.getElementById('s-local-custom');
  const btn = document.getElementById('s-local-pull-btn');
  if (!inp || !btn || _customPullPending || btn.disabled) return;
  const draft = inp?.value || '';
  const model = draft.trim();
  if (!model) { toast('enter a model name', 'error'); return; }
  const pending = {};
  _customPullPending = pending;
  let edited = false;
  const markEdited = () => { edited = true; };
  inp.addEventListener('input', markEdited);
  const finish = succeeded => {
    if (_customPullPending !== pending) return;
    _customPullPending = null;
    inp.removeEventListener('input', markEdited);
    btn.disabled = false;
    btn.textContent = 'pull';
    if (succeeded && !edited && inp.value === draft) inp.value = '';
  };
  btn.disabled = true; btn.textContent = 'queued';
  try {
    const job = await _localJson('/api/local-models/download_model', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    if (typeof job?.id !== 'string' || !job.id.trim()) throw new Error('pull could not be confirmed');
    pollLocalJob(job.id, btn, null, null, finish);
  } catch (e) {
    finish(false);
    toast(e.message || 'pull failed to start', 'error');
  }
}

async function deleteLocalModel(model, btn) {
  if (!model || _localPresetPending.has(model) || _localPresetConfirmations.has(model)) return;
  const restoreFocus = document.activeElement === btn;
  const isCurrent = _providersCurrent;
  _localPresetConfirmations.add(model);
  _syncLocalPresetPending(model);
  let confirmed;
  try { confirmed = await _dlgConfirm(`remove ${model} from disk?`); }
  finally {
    _localPresetConfirmations.delete(model);
    _syncLocalPresetPending(model);
    const currentButton = document.querySelector(`#s-local-presets [data-local-remove="${CSS.escape(model)}"]`);
    if (!confirmed && restoreFocus && isCurrent() && currentButton?.isConnected && !currentButton.disabled &&
        document.activeElement === document.body) currentButton.focus({ preventScroll: true });
  }
  if (!confirmed || _localPresetPending.has(model)) return;
  const pending = _claimLocalPreset(model, 'remove', 'removing...');
  btn.disabled = true; btn.textContent = 'removing...';
  try {
    await _localJson('/api/local-models/delete', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    toast(`${model} removed`, 'success');
  } catch (e) {
    toast(e.message || 'remove failed', 'error');
  } finally { _releaseLocalPreset(model, pending); }
  loadLocalModels();
  loadModels();
}

async function serveLocalModel(model, btn) {
  if (!model || _localPresetPending.has(model)) return;
  const pending = _claimLocalPreset(model, 'serve', 'serving...');
  btn.disabled = true;
  btn.textContent = 'serving...';
  try {
    const data = await _localJson('/api/local-models/serve', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model, autostart: true, set_default: true }),
    });
    toast(`${data.model || model} selected`, 'success');
    loadEpList();
    loadModels();
    renderModelList();
  } catch (e) {
    toast(e.message || 'serve failed', 'error');
  } finally { _releaseLocalPreset(model, pending); }
  btn.disabled = false;
  btn.textContent = 'serve';
  loadLocalModels();
}

async function _localJson(url, options = {}) {
  const r = await fetch(url, options);
  let data = {};
  try { data = await r.json(); } catch {}
  if (!r.ok) {
    const detail = data.detail || data;
    if (typeof detail === 'string') throw new Error(detail);
    throw new Error(detail.error || data.error || `request failed (${r.status})`);
  }
  return data;
}

const _MODEL_ROLE_COPY = {
  aide_chat: ['Aide Chat', 'normal chats and agent work'],
  andromeda_answer: ['Andromeda answer', 'fast compact cited answers'],
  andromeda_verifier: ['Andromeda verifier', 'independent current-fact checks'],
  jarvis: ['Aide background', 'deep research and background work'],
  coding: ['Coding', 'pi chats in Aide code'],
};
const _ADAPTER_OPTIONS = 'auto|auto detect;openai-compatible|openai-compatible;anthropic|anthropic;gemini|gemini;ollama|ollama;manual|manual list';
let _modelRoleSettings = {};

// the provider picked in "add connection", and the api type a custom endpoint speaks
let _pickedProvider = null;
let _customApiType = 'openai-compatible';

function _manualModels() {
  return (document.getElementById('s-ep-manual')?.value || '')
    .split(',').map(value => value.trim()).filter(Boolean);
}

function _showManualEndpointFields() {
  const btn = document.getElementById('s-ep-add-btn');
  if (!btn) return;
  // hidden until a provider is picked, so only in-flight work disables it
  btn.disabled = _endpointAddPending
    || !!(_endpointPartialCreate && _endpointPending.has(_endpointPartialCreate.id));
  if (!_endpointAddPending) btn.textContent = _manualModels().length ? 'add with these models' : 'add + read models';
}

function _showEndpointAuthFields() {
  const p = _pickedProvider;
  const keyRow = document.getElementById('s-ep-key-row');
  if (keyRow) keyRow.hidden = !p || !!p.keyless;
  const note = document.getElementById('s-ep-key-note');
  if (note) note.textContent = p?.custom ? 'optional for an address on this machine' : '';
}

function _applyProvider(p) {
  _pickedProvider = p;
  _endpointAddRevision += 1;
  _endpointAddConfigRevision += 1;
  _endpointPartialCreate = null;
  const show = (id, on) => { const el = document.getElementById(id); if (el) el.hidden = !on; };
  show('s-ep-fields', true);
  show('s-ep-pick', false);
  show('s-ep-name-row', !!p.custom);
  show('s-ep-url-row', !!p.custom);
  show('s-ep-url-toggle', !p.custom);
  show('s-ep-type-row', !!p.custom);
  show('s-ep-manual-row', !!p.custom);
  document.getElementById('s-ep-name').value = p.custom ? '' : p.label;
  document.getElementById('s-ep-url').value = p.url;
  _showEndpointAuthFields();
  _showManualEndpointFields();
  const next = p.custom ? 's-ep-name' : (p.keyless ? 's-ep-add-btn' : 's-ep-key');
  document.getElementById(next)?.focus();
}

function _renderApiTypes() {
  const group = document.getElementById('s-ep-type');
  if (!group || group.childElementCount) return;
  group.innerHTML = API_TYPES.map(([value, label], index) => `<button type="button" role="radio" data-value="${value}" aria-checked="${index === 0}" tabindex="${index === 0 ? 0 : -1}">${_esc(label)}</button>`).join('');
  wireChoiceGroup(group);
  group.addEventListener('click', event => {
    const choice = event.target.closest('[role="radio"]');
    if (choice) _customApiType = choice.dataset.value;
  });
}

// after adding: one click makes a model Aide's chat default; other roles keep theirs
async function _offerAideModel(endpointId) {
  const box = document.getElementById('s-ep-pick');
  const list = document.getElementById('s-ep-pick-list');
  if (!box || !list) return;
  const endpoints = await fetch('/api/models').then(r => r.ok ? r.json() : []).catch(() => []);
  const models = endpoints.find(ep => ep.id === endpointId)?.models || [];
  box.hidden = !models.length;
  if (!models.length) return;
  list.innerHTML = models.map((model, index) => `<button type="button" class="model-provider-option" role="option" aria-selected="false" tabindex="${index ? -1 : 0}" data-model="${_escAttr(model)}"><span class="model-provider-name">${_esc(model)}</span></button>`).join('');
  list.onclick = async event => {
    const option = event.target.closest('[role="option"]');
    if (!option || list.getAttribute('aria-busy') === 'true') return;
    list.setAttribute('aria-busy', 'true');
    const roles = { ..._modelRoleSettings, aide_chat: { endpoint_id: endpointId, model: option.dataset.model, cost_class: '', fallbacks: [] } };
    try {
      const response = await fetch('/api/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ model_roles: roles }),
      });
      if (!response.ok) throw new Error('the default could not be saved');
      list.querySelectorAll('[role="option"]').forEach(o => o.setAttribute('aria-selected', String(o === option)));
      await window._refreshAideModelDefault?.();
      toast(`Aide chat now uses ${option.dataset.model}`, 'success');
      await loadEpList();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      list.removeAttribute('aria-busy');
    }
  };
  list.onkeydown = event => {
    const items = [...list.querySelectorAll('[role="option"]')];
    const at = items.indexOf(document.activeElement);
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = items[Math.max(0, Math.min(items.length - 1, at + step))];
    items.forEach(o => { o.tabIndex = -1; });
    if (next) { next.tabIndex = 0; next.focus(); }
  };
}

async function startGeminiOAuth() {
  const btn = document.getElementById('s-gemini-oauth-start');
  const clientId = document.getElementById('s-gemini-client-id')?.value.trim() || '';
  const clientSecret = document.getElementById('s-gemini-client-secret')?.value.trim() || '';
  const projectId = document.getElementById('s-gemini-project-id')?.value.trim() || '';
  if (!clientId || !clientSecret || !projectId) {
    toast('client ID, client secret, and project ID are required', 'error');
    return;
  }
  const generation = ++_oauthStartGeneration;
  btn.disabled = true;
  btn.textContent = 'preparing…';
  try {
    const result = await _endpointJson(await _fetchWithRecentOwner('/api/models/oauth/gemini/start', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, project_id: projectId }),
    }));
    if (!_providersActive || generation !== _oauthStartGeneration) return;
    const popup = window.open(result.authorization_url, 'alles-gemini-oauth', 'popup,width=620,height=760');
    if (!popup) throw new Error('allow the authorization popup and try again');
    toast('finish authorization in the Google window', 'success');
    let checks = 0;
    const poll = window.setInterval(async () => {
      checks += 1;
      await loadEpList();
      if (popup.closed || checks >= 60) {
        window.clearInterval(poll);
        _oauthPolls.delete(poll);
      }
    }, 2000);
    _oauthPolls.add(poll);
  } catch (error) {
    toast(error.message || 'Gemini OAuth could not start', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'open Google authorization';
  }
}

function _safeDropdownLabel(value = '') {
  return String(value).replace(/[;|]/g, ' ');
}

function _roleOptionData(eps, configured) {
  const options = [{ value: '', label: 'automatic' }];
  const choices = { '': null };
  let index = 0;
  for (const ep of eps) {
    for (const model of (ep.models || [])) {
      const token = `choice-${index++}`;
      options.push({ value: token, label: `${_safeDropdownLabel(ep.name)} · ${_safeDropdownLabel(model)}` });
      choices[token] = { endpoint_id: ep.id, model };
    }
  }
  let selected = '';
  if (configured?.endpoint_id && configured?.model) {
    selected = Object.keys(choices).find(token => {
      const choice = choices[token];
      return choice?.endpoint_id === configured.endpoint_id && choice?.model === configured.model;
    }) || '';
    if (!selected) {
      selected = `unavailable-${index}`;
      options.push({ value: selected, label: `${_safeDropdownLabel(configured.model)} · unavailable` });
      choices[selected] = { endpoint_id: configured.endpoint_id, model: configured.model };
    }
  }
  return { options, choices, selected };
}

function _renderModelRoles(eps, settings, states) {
  const root = document.getElementById('s-model-roles');
  if (!root) return;
  const saveState = document.getElementById('s-role-save-state');
  if (saveState) saveState.textContent = '';
  _modelRoleSettings = settings.model_roles || {};
  const defaults = document.getElementById('s-model-defaults-card');
  // Keep saved defaults visible even when their connection is no longer available.
  if (defaults) defaults.hidden = !eps.length && !Object.values(_modelRoleSettings)
    .some(role => role?.endpoint_id || role?.model);
  root.innerHTML = Object.entries(_MODEL_ROLE_COPY).map(([role, copy]) => {
    const state = states?.[role];
    const effective = state?.effective;
    const configured = _modelRoleSettings[role] || {};
    const hasConfigured = !!(configured.endpoint_id || configured.model);
    const broken = state?.status === 'broken' && hasConfigured;
    const automatic = !configured.endpoint_id && !configured.model;
    const status = broken
      ? 'needs a replacement'
      : effective
        ? `${automatic ? 'automatic · ' : ''}${effective.privacy_class} · ${_safeDropdownLabel(effective.model)}`
        : 'add an endpoint first';
    return `<div class="s-role-row${broken ? ' broken' : ''}" data-role="${role}">
      <div class="s-role-copy">
        <div class="s-role-name">${copy[0]}</div>
        <div class="s-role-desc">${copy[1]}</div>
      </div>
      <div class="s-role-control">
        <div class="custom-select settings-input s-role-select" data-role-select="${role}" aria-label="${copy[0]} default model"></div>
        <div class="s-role-status">${_esc(status)}</div>
      </div>
    </div>`;
  }).join('');
  initCustomDropdowns(root);
  root.querySelectorAll('[data-role-select]').forEach(select => {
    const role = select.dataset.roleSelect;
    const data = _roleOptionData(eps, _modelRoleSettings[role] || {});
    select._modelChoices = data.choices;
    populateDropdown(select, data.options, data.selected);
    select.setAttribute('aria-invalid', String(data.selected.startsWith('unavailable-')));
    select.addEventListener('change', () => {
      _modelRolesDirty = true;
      _modelRolesRevision += 1;
      select.setAttribute('aria-invalid', String(getDropdownValue(select).startsWith('unavailable-')));
      const row = select.closest('.s-role-row');
      row?.classList.remove('broken');
      const status = row?.querySelector('.s-role-status');
      if (status) status.textContent = 'not saved';
      const saveState = document.getElementById('s-role-save-state');
      if (saveState) saveState.textContent = 'changes not saved';
    });
  });
}

async function saveModelRoles() {
  const btn = document.getElementById('s-role-save-btn');
  if (!btn) return;
  const unavailable = [...document.querySelectorAll('[data-role-select]')]
    .find(select => getDropdownValue(select).startsWith('unavailable-'));
  if (unavailable) {
    unavailable.focus();
    toast('replace the unavailable model before saving', 'error');
    return;
  }
  const revision = _modelRolesRevision;
  const focusTarget = document.activeElement;
  _endpointLoadGeneration += 1;
  btn.disabled = true;
  btn.textContent = 'saving…';
  const modelRoles = {};
  document.querySelectorAll('[data-role-select]').forEach(select => {
    const role = select.dataset.roleSelect;
    const choice = select._modelChoices?.[getDropdownValue(select)];
    if (!choice) { modelRoles[role] = {}; return; }
    const old = _modelRoleSettings[role] || {};
    modelRoles[role] = {
      endpoint_id: choice.endpoint_id,
      model: choice.model,
      cost_class: old.cost_class || '',
      fallbacks: old.fallbacks || [],
    };
  });
  try {
    const response = await fetch('/api/settings', {
      method: 'PATCH', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model_roles: modelRoles }),
    });
    if (!response.ok) throw new Error('defaults could not be saved');
    if (revision === _modelRolesRevision) _modelRolesDirty = false;
    await window._refreshAideModelDefault?.();
    toast('model defaults saved', 'success');
    await loadEpList();
  } catch (error) {
    toast(error.message || 'defaults could not be saved', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'save defaults';
    if (_providersActive && focusTarget?.isConnected && document.activeElement === document.body) {
      focusTarget.focus({ preventScroll: true });
    }
  }
}

async function refreshAllModelEndpoints() {
  const btn = document.getElementById('s-ep-refresh-all');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  btn.textContent = 'refreshing…';
  try {
    const endpoints = await _endpointJson(await fetch('/api/models'));
    if (!Array.isArray(endpoints) || !endpoints.length) {
      toast('add an endpoint first', 'error');
      return;
    }
    const available = endpoints.filter(endpoint => !_endpointPending.has(endpoint.id));
    const results = await Promise.allSettled(available.map(async endpoint => {
      _setEndpointPending(endpoint.id, true);
      try {
        return await _endpointJson(await fetch(`/api/models/endpoint/${encodeURIComponent(endpoint.id)}/probe`, { method: 'POST' }));
      } finally { _setEndpointPending(endpoint.id, false); }
    }));
    const failed = results.filter(result => result.status === 'rejected').length;
    await loadEpList();
    await loadModels();
    renderModelList();
    toast(failed ? `${available.length - failed} refreshed · ${failed} unavailable` : `${available.length} endpoints refreshed`, failed ? 'error' : 'success');
  } catch (error) {
    toast(error.message || 'endpoints could not be refreshed', 'error');
    await loadEpList();
  } finally {
    btn.disabled = false;
    btn.textContent = 'refresh all';
  }
}

function _catalogLabel(ep) {
  const status = ep.catalog_status || 'unverified';
  if (status === 'stale' && ep.catalog_error) return `stale · ${ep.catalog_error.replaceAll('_', ' ')}`;
  return status;
}

export async function _endpointJson(response) {
  let data = {};
  try { data = await response.json(); } catch {}
  if (!response.ok) throw new Error(data.detail || 'request failed');
  return data;
}

async function loadEpList() {
  const el = document.getElementById('s-ep-list');
  if (!el || !_providersActive) return;
  const generation = ++_endpointLoadGeneration;
  try {
    const [epsResponse, settingsResponse, rolesResponse] = await Promise.all([
      fetch('/api/models'), fetch('/api/settings'), fetch('/api/models/roles'),
    ]);
    const eps = await _endpointJson(epsResponse);
    const settings = await _endpointJson(settingsResponse);
    const roles = await _endpointJson(rolesResponse);
    if (!_providersActive || generation !== _endpointLoadGeneration) return;
    if (!_modelRolesDirty && !document.activeElement?.matches('#s-model-roles [data-role-select]')) _renderModelRoles(eps, settings, roles);
    if (_hasEndpointDrafts() || _endpointPending.size || _endpointConfirmations.size) return;
    if (!eps.length) {
      el.innerHTML = '<div class="s-role-empty">connect a local model server or a provider below. then choose your defaults.</div>';
      return;
    }
    el.innerHTML = eps.map(ep => {
      const status = ep.catalog_status || 'unverified';
      const unavailable = ep.unavailable_models?.length || 0;
      return `<div class="s-ep-card" data-id="${_escAttr(ep.id)}">
        <div class="s-ep-main">
          <div class="s-ep-dot ${ep.health_status === 'healthy' ? 'ok' : status === 'stale' || ep.health_status === 'unavailable' ? 'stale' : ''}"></div>
          <div class="s-ep-info">
            <div class="s-ep-title-line"><span class="s-ep-name">${_esc(ep.name)}</span><span class="s-state-tag ${_escAttr(status)}">${_esc(_catalogLabel(ep))}</span></div>
            <div class="s-ep-meta">${_esc(ep.provider_label || ep.provider || 'custom')} · ${_esc((ep.auth_type || 'api_key').replaceAll('_', ' '))} · ${_esc(ep.auth_status || 'incomplete')}</div>
            <div class="s-ep-meta">${_esc(ep.base_url)} · ${ep.models?.length || 0} ready · ${_esc(ep.health_status || 'unverified')}${unavailable ? ` · ${unavailable} unavailable` : ''}</div>
          </div>
          <div class="s-ep-actions">
            <button class="btn" data-probe="${_escAttr(ep.id)}">refresh</button>
            <button class="btn" data-test-ep="${_escAttr(ep.id)}">test</button>
            ${ep.auth_type === 'oauth' ? `<button class="btn" data-auth-refresh="${_escAttr(ep.id)}">refresh grant</button><button class="btn danger" data-auth-revoke="${_escAttr(ep.id)}">revoke</button>` : ''}
            <button class="btn" data-edit-list="${_escAttr(ep.id)}" aria-expanded="false">models</button>
            <button class="btn danger" data-del="${_escAttr(ep.id)}" aria-label="disconnect ${_escAttr(ep.name)}">disconnect</button>
          </div>
        </div>
        <div class="s-ep-editor" data-editor="${_escAttr(ep.id)}" hidden>
          <div class="s-ep-editor-note">${_esc(ep.quota_warning || '')}${ep.account_identity ? ` Connected project/account: ${_esc(ep.account_identity)}.` : ''} ${_esc(ep.revocation || '')}${ep.billing_url ? ` <a href="${_escAttr(ep.billing_url)}" target="_blank" rel="noopener noreferrer">provider usage</a>` : ''}</div>
          <div class="s-ep-editor-note">use discovery when the provider supports it. saving a manual list turns discovery off for this endpoint.</div>
          <div class="s-ep-editor-grid">
            <div class="s-field"><label>adapter</label><div class="custom-select settings-input" data-edit-adapter data-value="${_escAttr(ep.provider_adapter || 'auto')}" data-options="${_ADAPTER_OPTIONS}" aria-label="provider adapter"></div></div>
            <div class="s-field"><label>models <span class="s-field-note">comma-separated</span></label><input class="settings-input" data-edit-models value="${_escAttr((ep.models || []).join(', '))}"></div>
          </div>
          <div class="s-ep-editor-actions"><button class="btn primary" data-save-list="${_escAttr(ep.id)}">save endpoint</button></div>
        </div>
      </div>`;
    }).join('');
    initCustomDropdowns(el);

    el.querySelectorAll('[data-edit-list]').forEach(btn => {
      btn.addEventListener('click', () => {
        const editor = el.querySelector(`[data-editor="${CSS.escape(btn.dataset.editList)}"]`);
        if (!editor) return;
        editor.hidden = !editor.hidden;
        btn.setAttribute('aria-expanded', String(!editor.hidden));
      });
    });
    el.querySelectorAll('[data-save-list]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (_endpointPending.has(btn.dataset.saveList)) return;
        const editor = el.querySelector(`[data-editor="${CSS.escape(btn.dataset.saveList)}"]`);
        const adapter = getDropdownValue(editor?.querySelector('[data-edit-adapter]')) || 'auto';
        const models = (editor?.querySelector('[data-edit-models]')?.value || '').split(',').map(value => value.trim()).filter(Boolean);
        if (adapter === 'manual' && !models.length) { toast('add at least one manual model', 'error'); return; }
        const draftRevision = editor.dataset.dirty;
        _setEndpointPending(btn.dataset.saveList, true);
        btn.disabled = true; btn.textContent = 'saving…';
        try {
          const patch = { provider_adapter: adapter };
          if (adapter === 'manual') patch.models = models;
          await _endpointJson(await _fetchWithRecentOwner(`/api/models/endpoint/${btn.dataset.saveList}`, {
            method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(patch),
          }));
          if (adapter !== 'manual') {
            await _endpointJson(await fetch(`/api/models/endpoint/${btn.dataset.saveList}/probe`, { method: 'POST' }));
          }
          if (editor.dataset.dirty === draftRevision) delete editor.dataset.dirty;
          toast('endpoint saved', 'success');
          loadModels(); renderModelList();
        } catch (error) { toast(error.message || 'endpoint could not be saved', 'error'); }
        finally {
          _setEndpointPending(btn.dataset.saveList, false);
          btn.textContent = 'save endpoint';
          await loadEpList();
        }
      });
    });
    el.querySelectorAll('[data-probe]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (_endpointPending.has(btn.dataset.probe)) return;
        _setEndpointPending(btn.dataset.probe, true);
        btn.textContent = 'refreshing…'; btn.disabled = true;
        try {
          const data = await _endpointJson(await fetch(`/api/models/endpoint/${btn.dataset.probe}/probe`, { method: 'POST' }));
          toast(`${data.models?.length || 0} models ready`, 'success');
        } catch (error) { toast(error.message || 'catalog refresh failed', 'error'); }
        finally {
          _setEndpointPending(btn.dataset.probe, false);
          btn.textContent = 'refresh';
          await loadEpList(); await loadModels(); renderModelList();
        }
      });
    });
    el.querySelectorAll('[data-test-ep]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (_endpointPending.has(btn.dataset.testEp)) return;
        _setEndpointPending(btn.dataset.testEp, true);
        btn.textContent = 'testing…'; btn.disabled = true;
        try {
          await _endpointJson(await fetch(`/api/models/endpoint/${btn.dataset.testEp}/test`, { method: 'POST' }));
          toast('model endpoint is working', 'success');
        } catch (error) { toast(error.message || 'model endpoint test failed', 'error'); }
        finally {
          _setEndpointPending(btn.dataset.testEp, false);
          btn.textContent = 'test';
          await loadEpList();
        }
      });
    });
    el.querySelectorAll('[data-auth-refresh]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (_endpointPending.has(btn.dataset.authRefresh)) return;
        _setEndpointPending(btn.dataset.authRefresh, true);
        btn.disabled = true; btn.textContent = 'refreshing…';
        try {
          await _endpointJson(await _fetchWithRecentOwner(`/api/models/endpoint/${btn.dataset.authRefresh}/auth/refresh`, { method: 'POST' }));
          toast('Gemini grant refreshed', 'success');
        } catch (error) { toast(error.message || 'grant refresh failed', 'error'); }
        finally {
          _setEndpointPending(btn.dataset.authRefresh, false);
          btn.textContent = 'refresh grant';
          await loadEpList();
        }
      });
    });
    el.querySelectorAll('[data-auth-revoke]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (_endpointPending.has(btn.dataset.authRevoke)) return;
        if (!await _confirmEndpointAction(btn.dataset.authRevoke, 'revoke this Gemini grant at Google and disable the endpoint?')) return;
        if (_endpointPending.has(btn.dataset.authRevoke)) return;
        _setEndpointPending(btn.dataset.authRevoke, true);
        btn.disabled = true; btn.textContent = 'revoking…';
        try {
          await _endpointJson(await _fetchWithRecentOwner(`/api/models/endpoint/${btn.dataset.authRevoke}/auth/revoke`, { method: 'POST' }));
          toast('Gemini grant revoked', 'success');
        } catch (error) { toast(error.message || 'Google did not confirm revocation', 'error'); }
        finally {
          _setEndpointPending(btn.dataset.authRevoke, false);
          btn.textContent = 'revoke';
          await loadEpList(); await loadModels(); renderModelList();
        }
      });
    });
    el.querySelectorAll('[data-del]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (_endpointPending.has(btn.dataset.del)) return;
        if (!await _confirmEndpointAction(btn.dataset.del, 'remove this endpoint?')) return;
        if (_endpointPending.has(btn.dataset.del)) return;
        _setEndpointPending(btn.dataset.del, true);
        btn.textContent = 'removing…';
        try {
          await _endpointJson(await _fetchWithRecentOwner(`/api/models/endpoint/${btn.dataset.del}`, { method: 'DELETE' }));
          if (_endpointPartialCreate?.id === btn.dataset.del) _endpointPartialCreate = null;
          toast('endpoint removed', 'success');
          loadModels(); renderModelList();
        } catch (error) { toast(error.message || 'endpoint could not be removed', 'error'); }
        finally {
          _setEndpointPending(btn.dataset.del, false);
          btn.textContent = 'disconnect';
          await loadEpList();
        }
      });
    });
  } catch {
    if (!_providersActive || generation !== _endpointLoadGeneration) return;
    if (!_hasEndpointDrafts() && !_endpointPending.size && !_endpointConfirmations.size) el.innerHTML = '<div class="s-role-empty error">model settings could not be loaded.</div>';
    const roles = document.getElementById('s-model-roles');
    if (roles && !_modelRolesDirty && !roles.contains(document.activeElement)) roles.innerHTML = '<div class="s-role-empty error">model defaults could not be loaded.</div>';
  }
}


function _wireProvidersPane() {
  for (const id of ['s-ep-name', 's-ep-url', 's-ep-key', 's-ep-vision', 's-ep-manual']) {
    for (const type of ['input', 'change']) {
      document.getElementById(id)?.addEventListener(type, () => {
        _endpointAddRevision += 1;
        if (id !== 's-ep-vision') {
          _endpointAddConfigRevision += 1;
          _endpointPartialCreate = null;
        }
        _showManualEndpointFields();
      });
    }
  }
  let draftRevision = 0;
  for (const type of ['input', 'change']) {
    document.getElementById('s-ep-list')?.addEventListener(type, event => {
      const editor = event.target.closest('[data-editor]');
      if (editor) editor.dataset.dirty = String(++draftRevision);
    });
  }

  // ── models pane ──
  mountProviderPicker(document.getElementById('s-ep-provider-list'), {
    filter: document.getElementById('s-ep-provider-filter'),
    onPick: _applyProvider,
  });
  _renderApiTypes();
  _showManualEndpointFields();
  document.getElementById('s-ep-url-toggle')?.addEventListener('click', event => {
    const row = document.getElementById('s-ep-url-row');
    if (!row) return;
    row.hidden = false;
    event.currentTarget.hidden = true;
    document.getElementById('s-ep-url')?.focus();
  });
  document.getElementById('s-gemini-oauth-toggle')?.addEventListener('click', event => {
    const panel = document.getElementById('s-gemini-oauth-panel');
    if (!panel) return;
    panel.hidden = !panel.hidden;
    event.currentTarget.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden) document.getElementById('s-gemini-client-id')?.focus();
  });
  document.getElementById('s-gemini-oauth-start')?.addEventListener('click', startGeminiOAuth);
  document.getElementById('s-role-save-btn')?.addEventListener('click', saveModelRoles);
  document.getElementById('s-ep-refresh-all')?.addEventListener('click', refreshAllModelEndpoints);
  document.getElementById('s-ep-add-btn')?.addEventListener('click', async () => {
    if (_endpointAddPending) return;
    const p = _pickedProvider;
    if (!p) return;
    const name = document.getElementById('s-ep-name').value.trim() || p.label;
    const url  = document.getElementById('s-ep-url').value.trim();
    const key  = p.keyless ? '' : document.getElementById('s-ep-key').value.trim();
    const manualModels = p.custom ? _manualModels() : [];
    // a listed model set skips reading the endpoint's catalog; otherwise it is read now
    const adapter = manualModels.length ? 'manual' : (p.custom ? _customApiType : p.adapter);
    const providerId = p.provider;
    const authType = authFor(p, key);
    if (!url) { toast('add the endpoint address', 'error'); document.getElementById('s-ep-url')?.focus(); return; }
    const btn = document.getElementById('s-ep-add-btn');
    const revision = _endpointAddRevision;
    const configRevision = _endpointAddConfigRevision;
    const visionRaw = document.getElementById('s-ep-vision')?.value.trim() || '';
    const partial = _endpointPartialCreate?.configRevision === configRevision ? _endpointPartialCreate : null;
    if (partial && _endpointPending.has(partial.id)) return;
    let pendingId = null;
    _endpointAddPending = true;
    btn.textContent = 'probing…'; btn.disabled = true;
    try {
      const ep = partial || await addEndpoint(name, url, key, adapter, manualModels, { providerId, authType });
      if (ep?.id && configRevision === _endpointAddConfigRevision) {
        _endpointPartialCreate = { id: ep.id, configRevision };
      }
      if ((visionRaw || partial) && ep?.id) {
        if (_endpointPending.has(ep.id)) throw new Error('endpoint is busy; try again');
        pendingId = ep.id;
        _setEndpointPending(pendingId, true);
        const visionList = visionRaw.split(',').map(s => s.trim()).filter(Boolean);
        const response = await _fetchWithRecentOwner(`/api/models/endpoint/${ep.id}`, {
          method: 'PATCH', headers: {'content-type':'application/json'},
          body: JSON.stringify({ vision_models: JSON.stringify(visionList) }),
        });
        if (response.status === 404 && _endpointPartialCreate?.id === ep.id) _endpointPartialCreate = null;
        await _endpointJson(response);
      }
      if (revision === _endpointAddRevision) {
        _endpointPartialCreate = null;
        ['s-ep-name','s-ep-url','s-ep-key','s-ep-vision','s-ep-manual'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        document.getElementById('s-ep-fields').hidden = true;
        _pickedProvider = null;
        document.querySelectorAll('#s-ep-provider-list [role="option"]').forEach(o => o.setAttribute('aria-selected', 'false'));
        _showManualEndpointFields();
      }
      toast('connection added', 'success');
      loadEpList();
      loadModels();
      renderModelList();
      if (ep?.id) await _offerAideModel(ep.id);
    } catch (e) { toast(`failed: ${e.message}`, 'error'); }
    finally {
      if (pendingId) _setEndpointPending(pendingId, false);
      _endpointAddPending = false;
      _showManualEndpointFields();
    }
  });

  document.getElementById('s-local-refresh-btn')?.addEventListener('click', loadLocalModels);
  document.getElementById('s-local-pull-btn')?.addEventListener('click', pullCustomLocalModel);
  document.getElementById('s-local-start-btn')?.addEventListener('click', startLocalOllama);

}

export const providersPane = createSettingsPane({
  init: _wireProvidersPane,
  load(isCurrent) {
    _providersCurrent = isCurrent;
    _providersActive = true;
    return Promise.all([loadEpList(), loadLocalModels()]);
  },
  dispose() {
    _providersActive = false;
    _endpointLoadGeneration += 1;
    _localLoadGeneration += 1;
    _oauthStartGeneration += 1;
    for (const poll of _oauthPolls) window.clearInterval(poll);
    _oauthPolls.clear();
  },
});
