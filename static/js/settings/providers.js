import { createSettingsPane } from './pane.js';
import { toast } from '../util.js';
import { confirm as _dlgConfirm } from '../dialog.js';
import { loadModels, addEndpoint, renderModelList } from '../models.js?v=212';
import { initCustomDropdowns, getDropdownValue, setDropdownValue, populateDropdown } from '../dropdown.js?v=212';
import { _esc, _escAttr, _fetchWithRecentOwner } from './shared.js';

let _providersActive = false;
let _endpointLoadGeneration = 0;
let _localLoadGeneration = 0;
let _modelRolesDirty = false;
let _modelRolesRevision = 0;
const _oauthPolls = new Set();

function _hasEndpointDrafts() {
  return !!document.querySelector('#s-ep-list [data-editor][data-dirty]');
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
    listEl.innerHTML = '';
  }
}

function renderLocalPresets(presets) {
  const listEl = document.getElementById('s-local-presets');
  if (!listEl) return;
  if (!presets.length) {
    listEl.innerHTML = '<div style="font-size:0.75rem;color:var(--muted)">no local presets available</div>';
    return;
  }
  listEl.innerHTML = presets.map(p => {
    const badge = p.fit === 'fits_gpu' ? 'gpu fit' : (p.fit === 'fits_cpu' ? 'cpu fit' : 'large');
    const installed = p.installed ? 'installed' : 'download first';
    const serveDisabled = p.installed ? '' : 'disabled title="download first"';
    return `<div class="settings-list-row" style="align-items:flex-start;gap:0.55rem">
      <span class="status-dot" style="margin-top:0.35rem;background:${p.installed ? 'var(--green)' : 'var(--faint)'}"></span>
      <div style="min-width:0;flex:1">
        <div class="row-name">${_esc(p.label)} <span style="color:var(--muted);font-weight:400">${_esc(p.model)}</span></div>
        <div class="row-meta">${badge} - ${installed} - ${_esc(p.fit_reason || '')}</div>
      </div>
      ${p.installed
        ? `<button class="btn" data-local-remove="${_escAttr(p.model)}">remove</button>`
        : `<button class="btn" data-local-download="${_escAttr(p.model)}">download</button>`}
      <button class="btn primary" data-local-serve="${_escAttr(p.model)}" ${serveDisabled}>serve</button>
    </div>`;
  }).join('');

  listEl.querySelectorAll('[data-local-download]').forEach(btn => {
    btn.addEventListener('click', () => downloadLocalModel(btn.dataset.localDownload, btn));
  });
  listEl.querySelectorAll('[data-local-serve]').forEach(btn => {
    btn.addEventListener('click', () => serveLocalModel(btn.dataset.localServe, btn));
  });
  listEl.querySelectorAll('[data-local-remove]').forEach(btn => {
    btn.addEventListener('click', () => deleteLocalModel(btn.dataset.localRemove, btn));
  });
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

async function downloadLocalModel(model, btn) {
  if (!model) return;
  btn.disabled = true;
  btn.textContent = 'queued';
  try {
    const job = await _localJson('/api/local-models/download_model', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    pollLocalJob(job.id, btn);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'download';
    toast(e.message || 'download failed to start', 'error');
  }
}

async function pollLocalJob(jobId, btn) {
  if (!jobId) return;
  try {
    const job = await _localJson(`/api/local-models/jobs/${jobId}`);
    if (job.status === 'done') {
      btn.textContent = 'downloaded';
      toast(`${job.model} downloaded`, 'success');
      loadLocalModels();
      loadModels();
      return;
    }
    if (job.status === 'error') {
      btn.disabled = false;
      btn.textContent = 'download';
      toast(job.error || 'download failed', 'error');
      return;
    }
    btn.textContent = job.status === 'running' ? 'pulling...' : 'queued';
    setTimeout(() => pollLocalJob(jobId, btn), 1800);
  } catch {
    btn.disabled = false;
    btn.textContent = 'download';
  }
}

async function pullCustomLocalModel() {
  const inp = document.getElementById('s-local-custom');
  const btn = document.getElementById('s-local-pull-btn');
  const model = (inp?.value || '').trim();
  if (!model) { toast('enter a model name', 'error'); return; }
  btn.disabled = true; btn.textContent = 'queued';
  try {
    const job = await _localJson('/api/local-models/download_model', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    pollLocalJob(job.id, btn);
    inp.value = '';
  } catch (e) {
    btn.disabled = false; btn.textContent = 'pull';
    toast(e.message || 'pull failed to start', 'error');
  }
}

async function deleteLocalModel(model, btn) {
  if (!model) return;
  if (!await _dlgConfirm(`remove ${model} from disk?`)) return;
  btn.disabled = true; btn.textContent = 'removing...';
  try {
    await _localJson('/api/local-models/delete', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    toast(`${model} removed`, 'success');
  } catch (e) {
    toast(e.message || 'remove failed', 'error');
  }
  loadLocalModels();
  loadModels();
}

async function serveLocalModel(model, btn) {
  if (!model) return;
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
  }
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
  jarvis: ['Jarvis', 'deep research and delegated work'],
};
const _ADAPTER_OPTIONS = 'auto|auto detect;openai-compatible|openai-compatible;anthropic|anthropic;gemini|gemini;ollama|ollama;manual|manual list';
let _modelRoleSettings = {};

function _adapterForPreset(name = '') {
  if (name === 'Anthropic') return 'anthropic';
  if (name === 'Ollama') return 'ollama';
  return 'openai-compatible';
}

function _showManualEndpointFields() {
  const row = document.getElementById('s-ep-manual-row');
  if (row) row.hidden = getDropdownValue(document.getElementById('s-ep-adapter')) !== 'manual';
  const btn = document.getElementById('s-ep-add-btn');
  if (btn) btn.textContent = row?.hidden ? 'add + probe models' : 'add manual endpoint';
}

function _showEndpointAuthFields() {
  const authType = getDropdownValue(document.getElementById('s-ep-auth')) || 'api_key';
  const keyRow = document.getElementById('s-ep-key-row');
  if (keyRow) keyRow.hidden = authType === 'none';
  const key = document.getElementById('s-ep-key');
  if (key) key.placeholder = authType === 'external_proxy'
    ? 'proxy bearer token, if required'
    : 'provider API key';
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
  btn.disabled = true;
  btn.textContent = 'preparing…';
  try {
    const result = await _endpointJson(await _fetchWithRecentOwner('/api/models/oauth/gemini/start', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, project_id: projectId }),
    }));
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
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = 'refreshing…';
  try {
    const endpoints = await _endpointJson(await fetch('/api/models'));
    if (!Array.isArray(endpoints) || !endpoints.length) {
      toast('add an endpoint first', 'error');
      return;
    }
    const results = await Promise.allSettled(endpoints.map(async endpoint =>
      _endpointJson(await fetch(`/api/models/endpoint/${encodeURIComponent(endpoint.id)}/probe`, { method: 'POST' })),
    ));
    const failed = results.filter(result => result.status === 'rejected').length;
    await loadEpList();
    await loadModels();
    renderModelList();
    toast(failed ? `${endpoints.length - failed} refreshed · ${failed} unavailable` : `${endpoints.length} endpoints refreshed`, failed ? 'error' : 'success');
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

async function _endpointJson(response) {
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
    if (!_modelRolesDirty) _renderModelRoles(eps, settings, roles);
    if (_hasEndpointDrafts()) return;
    if (!eps.length) {
      el.innerHTML = '<div class="s-role-empty">no endpoints yet. add one below, then choose your defaults.</div>';
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
        const editor = el.querySelector(`[data-editor="${CSS.escape(btn.dataset.saveList)}"]`);
        const adapter = getDropdownValue(editor?.querySelector('[data-edit-adapter]')) || 'auto';
        const models = (editor?.querySelector('[data-edit-models]')?.value || '').split(',').map(value => value.trim()).filter(Boolean);
        if (adapter === 'manual' && !models.length) { toast('add at least one manual model', 'error'); return; }
        const draftRevision = editor.dataset.dirty;
        _endpointLoadGeneration += 1;
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
          loadEpList(); loadModels(); renderModelList();
        } catch (error) { toast(error.message || 'endpoint could not be saved', 'error'); }
        finally { btn.disabled = false; btn.textContent = 'save endpoint'; }
      });
    });
    el.querySelectorAll('[data-probe]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.textContent = 'refreshing…'; btn.disabled = true;
        try {
          const data = await _endpointJson(await fetch(`/api/models/endpoint/${btn.dataset.probe}/probe`, { method: 'POST' }));
          toast(`${data.models?.length || 0} models ready`, 'success');
        } catch (error) { toast(error.message || 'catalog refresh failed', 'error'); }
        finally {
          btn.textContent = 'refresh'; btn.disabled = false;
          await loadEpList(); await loadModels(); renderModelList();
        }
      });
    });
    el.querySelectorAll('[data-test-ep]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.textContent = 'testing…'; btn.disabled = true;
        try {
          await _endpointJson(await fetch(`/api/models/endpoint/${btn.dataset.testEp}/test`, { method: 'POST' }));
          toast('model endpoint is working', 'success');
          loadEpList();
        } catch (error) { toast(error.message || 'model endpoint test failed', 'error'); }
        finally { btn.textContent = 'test'; btn.disabled = false; }
      });
    });
    el.querySelectorAll('[data-auth-refresh]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.disabled = true; btn.textContent = 'refreshing…';
        try {
          await _endpointJson(await _fetchWithRecentOwner(`/api/models/endpoint/${btn.dataset.authRefresh}/auth/refresh`, { method: 'POST' }));
          toast('Gemini grant refreshed', 'success');
        } catch (error) { toast(error.message || 'grant refresh failed', 'error'); }
        finally { await loadEpList(); }
      });
    });
    el.querySelectorAll('[data-auth-revoke]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!await _dlgConfirm('revoke this Gemini grant at Google and disable the endpoint?')) return;
        btn.disabled = true; btn.textContent = 'revoking…';
        try {
          await _endpointJson(await _fetchWithRecentOwner(`/api/models/endpoint/${btn.dataset.authRevoke}/auth/revoke`, { method: 'POST' }));
          toast('Gemini grant revoked', 'success');
        } catch (error) { toast(error.message || 'Google did not confirm revocation', 'error'); }
        finally { await loadEpList(); await loadModels(); renderModelList(); }
      });
    });
    el.querySelectorAll('[data-del]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!await _dlgConfirm('remove this endpoint?')) return;
        try {
          await _endpointJson(await _fetchWithRecentOwner(`/api/models/endpoint/${btn.dataset.del}`, { method: 'DELETE' }));
          toast('endpoint removed', 'success');
          loadEpList(); loadModels(); renderModelList();
        } catch (error) { toast(error.message || 'endpoint could not be removed', 'error'); }
      });
    });
  } catch {
    if (!_providersActive || generation !== _endpointLoadGeneration) return;
    if (!_hasEndpointDrafts()) el.innerHTML = '<div class="s-role-empty error">model settings could not be loaded.</div>';
    const roles = document.getElementById('s-model-roles');
    if (roles && !_modelRolesDirty) roles.innerHTML = '<div class="s-role-empty error">model defaults could not be loaded.</div>';
  }
}


function _wireProvidersPane() {
  let draftRevision = 0;
  for (const type of ['input', 'change']) {
    document.getElementById('s-ep-list')?.addEventListener(type, event => {
      const editor = event.target.closest('[data-editor]');
      if (editor) editor.dataset.dirty = String(++draftRevision);
    });
  }

  // ── models pane ──
  document.querySelectorAll('.s-preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('s-ep-url').value = btn.dataset.url;
      document.getElementById('s-ep-name').value = btn.dataset.name;
      setDropdownValue(document.getElementById('s-ep-provider'), btn.dataset.provider || 'custom');
      setDropdownValue(document.getElementById('s-ep-auth'), btn.dataset.provider === 'ollama' ? 'none' : 'api_key');
      setDropdownValue(document.getElementById('s-ep-adapter'), _adapterForPreset(btn.dataset.name));
      _showManualEndpointFields();
      _showEndpointAuthFields();
      document.getElementById('s-ep-key').focus();
    });
  });
  document.getElementById('s-ep-adapter')?.addEventListener('change', _showManualEndpointFields);
  document.getElementById('s-ep-auth')?.addEventListener('change', _showEndpointAuthFields);
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
    const name = document.getElementById('s-ep-name').value.trim();
    const url  = document.getElementById('s-ep-url').value.trim();
    const key  = document.getElementById('s-ep-key').value.trim();
    const adapter = getDropdownValue(document.getElementById('s-ep-adapter')) || 'auto';
    let providerId = getDropdownValue(document.getElementById('s-ep-provider')) || 'custom';
    const authType = getDropdownValue(document.getElementById('s-ep-auth')) || 'api_key';
    if (authType === 'external_proxy') providerId = 'external_proxy';
    const manualModels = (document.getElementById('s-ep-manual')?.value || '')
      .split(',').map(value => value.trim()).filter(Boolean);
    if (!name || !url) { toast('name and url required', 'error'); return; }
    if (adapter === 'manual' && !manualModels.length) {
      toast('add at least one manual model', 'error'); return;
    }
    const btn = document.getElementById('s-ep-add-btn');
    btn.textContent = 'probing…'; btn.disabled = true;
    try {
      const ep = await addEndpoint(name, url, key, adapter, manualModels, { providerId, authType });
      const visionRaw = document.getElementById('s-ep-vision')?.value.trim() || '';
      if (visionRaw && ep?.id) {
        const visionList = visionRaw.split(',').map(s => s.trim()).filter(Boolean);
        await _fetchWithRecentOwner(`/api/models/endpoint/${ep.id}`, {
          method: 'PATCH', headers: {'content-type':'application/json'},
          body: JSON.stringify({ vision_models: JSON.stringify(visionList) }),
        });
      }
      ['s-ep-name','s-ep-url','s-ep-key','s-ep-vision','s-ep-manual'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
      setDropdownValue(document.getElementById('s-ep-adapter'), 'auto');
      setDropdownValue(document.getElementById('s-ep-provider'), 'custom');
      setDropdownValue(document.getElementById('s-ep-auth'), 'api_key');
      _showManualEndpointFields();
      _showEndpointAuthFields();
      document.getElementById('s-ep-add-details').open = false;
      toast('endpoint added', 'success');
      loadEpList();
      loadModels();
      renderModelList();
    } catch (e) { toast(`failed: ${e.message}`, 'error'); }
    btn.disabled = false;
    _showManualEndpointFields();
  });

  document.getElementById('s-local-refresh-btn')?.addEventListener('click', loadLocalModels);
  document.getElementById('s-local-pull-btn')?.addEventListener('click', pullCustomLocalModel);
  document.getElementById('s-local-start-btn')?.addEventListener('click', startLocalOllama);

}

export const providersPane = createSettingsPane({
  init: _wireProvidersPane,
  load() {
    _providersActive = true;
    return Promise.all([loadEpList(), loadLocalModels()]);
  },
  dispose() {
    _providersActive = false;
    _endpointLoadGeneration += 1;
    _localLoadGeneration += 1;
    for (const poll of _oauthPolls) window.clearInterval(poll);
    _oauthPolls.clear();
  },
});
