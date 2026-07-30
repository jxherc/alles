import { toast } from './util.js';
import { confirm as _dlgConfirm } from './dialog.js';
import { providerLogo, providerKey, brandColor } from './brandlogo.js';
import { sortModels, filterNewest } from './modelfilter.js';

let _endpoints = [];
let _selected = null;   // { endpointId, model }
let _selectionSource = 'none'; // role | persona | explicit | session | broken
let _aideDefault = null;
const _modelSelectionQueues = new Map();
const _modelSelectionGenerations = new Map();

// safe ls read — corrupt json here used to throw at module load and kill app boot
function _ls(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } }

function _ownerFetch(input, init) {
  return window._fetchWithRecentOwner?.(input, init) || fetch(input, init);
}

const PRESETS = [
  { name: 'OpenAI',      url: 'https://api.openai.com',                              key: 'sk-...' },
  { name: 'Anthropic',   url: 'https://api.anthropic.com',                           key: 'sk-ant-...' },
  { name: 'DeepSeek',    url: 'https://api.deepseek.com',                            key: 'sk-...' },
  { name: 'Kimi',        url: 'https://api.moonshot.ai/v1',                          key: 'sk-...' },
  { name: 'Groq',        url: 'https://api.groq.com/openai',                         key: 'gsk_...' },
  { name: 'Gemini',      url: 'https://generativelanguage.googleapis.com/v1beta/openai', key: 'AIza...' },
  { name: 'xAI (Grok)', url: 'https://api.x.ai',                                    key: 'xai-...' },
  { name: 'Mistral',     url: 'https://api.mistral.ai',                              key: '' },
  { name: 'Perplexity',  url: 'https://api.perplexity.ai',                           key: 'pplx-...' },
  { name: 'OpenRouter',  url: 'https://openrouter.ai/api',                           key: 'sk-or-...' },
  { name: 'Together',    url: 'https://api.together.xyz',                            key: '' },
  { name: 'Fireworks',   url: 'https://api.fireworks.ai/inference',                  key: 'fw-...' },
  { name: 'Cohere',      url: 'https://api.cohere.ai',                               key: '' },
  { name: 'Ollama',      url: 'http://localhost:11434',                              key: '' },
];

export async function loadModels() {
  try {
    const [modelsResponse, rolesResponse] = await Promise.all([
      fetch('/api/models'),
      fetch('/api/models/roles'),
    ]);
    if (!modelsResponse.ok || !rolesResponse.ok) throw new Error('model state unavailable');
    _endpoints = await modelsResponse.json();
    const roles = await rolesResponse.json();
    window._endpoints = _endpoints;
    const savedRaw = localStorage.getItem('aide-model');
    const saved = _ls('aide-model');
    if (savedRaw && (!saved || !_catalogSelection(saved))) localStorage.removeItem('aide-model');

    const roleState = roles?.aide_chat;
    _aideDefault = roleState?.status === 'ready'
      ? _catalogSelection(roleState.effective, false)
      : null;

    // An explicit conversation choice survives catalog refreshes while it is still
    // available. Defaults are re-read from the server instead of trusting the old
    // browser-wide picker value.
    if (window._currentSession) {
      if (window._currentSession.model) restoreSessionModel(window._currentSession);
      else if (window._activePersonaModel) selectPersonaModel(window._activePersonaModel);
      else selectAideDefault();
    } else if (_selectionSource === 'explicit' || _selectionSource === 'session') {
      const current = _catalogSelection(_selected);
      if (current) _setSelection(current, _selectionSource);
      else _setSelection(null, 'broken');
    } else {
      selectAideDefault();
    }
  } catch (e) {
    if (globalThis.navigator?.onLine !== false) console.error('loadModels', e);
  }
}

export function getSelected() { return _selected; }

export function getSelectionSource() { return _selectionSource; }

export function getCurrentEndpoint() {
  if (!_selected) return null;
  return _endpoints.find(ep => ep.id === _selected.endpointId) || null;
}

function _catalogSelection(value, allowImages = true) {
  if (!value || typeof value !== 'object') return null;
  const endpointId = value.endpointId || value.endpoint_id || '';
  let model = typeof value.model === 'string' ? value.model : '';
  let endpoint = endpointId ? _endpoints.find(ep => ep.id === endpointId) : null;
  if (endpointId && !endpoint) return null;
  if (!endpoint && model) {
    endpoint = _endpoints.find(ep => (ep.models || []).includes(model) ||
      (allowImages && (ep.image_models || []).includes(model)));
  }
  if (!endpoint) return null;
  if (!model) model = (endpoint.models || [])[0] || '';
  const offered = (endpoint.models || []).includes(model) ||
    (allowImages && (endpoint.image_models || []).includes(model));
  const unavailable = (endpoint.unavailable_models || []).includes(model);
  if (!model || !offered || unavailable) return null;
  return { endpointId: endpoint.id, model };
}

function _renderSelection() {
  updateTopbar();
  window._refreshEffortLabel?.();
  renderModelList(document.getElementById('model-search-input')?.value || '');
  renderSidebarModelList(document.getElementById('sidebar-model-search')?.value || '');
}

function _setSelection(selection, source, persist = false) {
  _selected = selection;
  _selectionSource = source;
  if (persist && selection) localStorage.setItem('aide-model', JSON.stringify(selection));
  _renderSelection();
  return _selected;
}

// The server resolver is the source of truth for a fresh Aide chat. A broken
// configured default stays visibly broken instead of quietly picking another provider.
export function selectAideDefault() {
  return _setSelection(_aideDefault, _aideDefault ? 'role' : 'broken');
}

// Restore the model that the saved conversation will actually use. Session choices
// win over the role default; an unavailable saved choice is not hidden by a fallback.
export function restoreSessionModel(session = {}) {
  const hasOverride = !!(session.model || session.endpoint_id);
  if (!hasOverride) return selectAideDefault();
  const selection = _catalogSelection({
    endpointId: session.endpoint_id || '',
    model: session.model || '',
  }, false);
  return _setSelection(selection, selection ? 'session' : 'broken');
}

export function selectPersonaModel(model = '') {
  const selection = _catalogSelection({ model }, false);
  return _setSelection(selection, selection ? 'persona' : 'broken');
}

// Role defaults should remain defaults, not become session overrides. This keeps a
// persona model free to win on the server. A model picked in the chat stays explicit.
export function modelOverrideForNewSession(model = '', endpointId = '') {
  const requested = _catalogSelection({ endpointId, model }, false);
  const inherited = (_selectionSource === 'role' || _selectionSource === 'persona') && requested &&
    _selected && requested.endpointId === _selected.endpointId && requested.model === _selected.model;
  return inherited ? { model: '', endpointId: '' } : { model, endpointId };
}

export async function refreshAideModelDefault() {
  await loadModels();
  await window._refreshPersonaBtn?.();
  return _selected;
}

// clean display label instead of the raw id — drop the vendor prefix + dash soup.
// "claude-opus-4-8" → "opus 4.8", "deepseek-v4-flash" → "deepseek v4 flash"
export function prettyModel(id = '') {
  let s = String(id).split('/').pop();                          // drop "vendor/" prefix
  // deepseek branding: drop the word "deepseek", map the two tiers to v4 pro / v4 flash
  const ds = s.toLowerCase();
  if (ds.includes('deepseek') || ds.includes('reasoner')) {
    if (ds.includes('reasoner')) return 'v4 pro';
    if (ds.includes('chat')) return 'v4 flash';
    s = s.replace(/deepseek[-_]?/i, '');
  }
  s = s.replace(/^claude-/, '');                                // redundant w/ opus/sonnet/haiku
  s = s.replace(/^kimi[-_]?/i, '');                             // moonshot/kimi → just the model (e.g. "k2.7 code")
  s = s.replace(/[-_ ]?20\d{2}[-_]?\d{2}[-_]?\d{2}$/, '');      // drop trailing release date
  s = s.replace(/(\d)[-_](\d)/g, '$1.$2');                      // version dashes → dots (4-8 → 4.8)
  s = s.replace(/[-_]/g, ' ').trim();                           // the rest → spaces
  return s || id;
}

// is the currently-picked model an image-generation model? (chat branches on this)
export function isImageSelected() {
  if (!_selected) return false;
  const ep = _endpoints.find(e => e.id === _selected.endpointId);
  return !!ep && (ep.image_models || []).includes(_selected.model);
}

function _isImageModel(endpointId, model) {
  const ep = _endpoints.find(e => e.id === endpointId);
  return !!ep && (ep.image_models || []).includes(model);
}

// optional companion image-gen model — the "image slot" — kept separate from the primary chat
// model so you can run e.g. sonnet (chat) + gpt-image-2 (images) at once. chat auto-routes
// image requests here. selecting an image model in the picker fills this instead of swapping
// out the chat model.
let _imageSlot = _ls('aide-image-model');
export function getImageSlot() {
  if (!_imageSlot) return null;
  // drop it if a refresh pruned the model (no longer offered by the endpoint)
  if (!_isImageModel(_imageSlot.endpointId, _imageSlot.model)) {
    _imageSlot = null;
    localStorage.removeItem('aide-image-model');
    return null;
  }
  return _imageSlot;
}
export function setImageSlot(endpointId, model) {
  _imageSlot = (endpointId && model) ? { endpointId, model } : null;
  if (_imageSlot) localStorage.setItem('aide-image-model', JSON.stringify(_imageSlot));
  else localStorage.removeItem('aide-image-model');
  updateTopbar();
  renderModelList(document.getElementById('model-search-input')?.value || '');
  renderSidebarModelList(document.getElementById('sidebar-model-search')?.value || '');
}

// ordering + "newest only" collapsing live in modelfilter.js (pure, unit-tested). this module
// just owns the toggle state and passes it in.
let _newestOnly = localStorage.getItem('aide-newest-only') === '1';
export function setNewestOnly(on) {
  _newestOnly = !!on;
  localStorage.setItem('aide-newest-only', _newestOnly ? '1' : '0');
  // keep every newest-only switch in the ui in sync (top picker modal + models page)
  document.querySelectorAll('.newest-only-switch, #newest-only-switch').forEach(sw => {
    sw.classList.toggle('on', _newestOnly);
    sw.setAttribute('aria-checked', String(_newestOnly));
  });
  renderModelList(document.getElementById('model-search-input')?.value || '');
  renderSidebarModelList(document.getElementById('sidebar-model-search')?.value || '');
}
const _filterNewest = m => filterNewest(m, _newestOnly);

function updateTopbar() {
  const label = document.getElementById('model-label');
  const aideLabel = document.getElementById('aide-model-choice-label');
  const aideLogo = document.getElementById('aide-model-choice-logo');
  const provider = document.getElementById('model-provider');
  const button = document.getElementById('model-btn');
  const aideButton = document.getElementById('aide-model-choice');
  const dot = document.getElementById('live-dot');
  if (_selected) {
    const displayModel = prettyModel(_selected.model);
    if (label) label.textContent = displayModel;
    if (aideLabel) aideLabel.textContent = displayModel;
    const ep = getCurrentEndpoint();
    const selectedProvider = providerKey([
      ep && ep.provider,
      ep && ep.name,
      ep && ep.base_url,
      _selected.model,
    ].filter(Boolean).join(' '));
    if (aideLogo) aideLogo.innerHTML = providerLogo(selectedProvider, { size: 14 });
    if (provider) provider.textContent = ep?.name || '';
    if (button) {
      button.title = `${_selected.model} · ${ep?.name || 'unknown provider'}`;
      button.setAttribute('aria-label', `model ${_selected.model}, provider ${ep?.name || 'unknown'}`);
    }
    if (aideButton) {
      aideButton.title = `${_selected.model} · ${ep?.name || 'unknown provider'}`;
      aideButton.setAttribute('aria-label', `model ${_selected.model}, provider ${ep?.name || 'unknown'}`);
    }
    // the "glowing thing" becomes the provider's glowing brand logo
    dot?.classList.remove('offline');
    dot?.classList.add('has-logo');
    if (dot) dot.innerHTML = providerLogo(providerKey([ep && ep.provider, ep && ep.name, ep && ep.base_url, _selected.model].filter(Boolean).join(' ')), { size: 13 });
    if (ep) window._currentEndpoint = ep;
  } else {
    if (label) label.textContent = 'no model';
    if (aideLabel) aideLabel.textContent = 'no model';
    if (aideLogo) aideLogo.innerHTML = '';
    if (provider) provider.textContent = '';
    if (button) button.setAttribute('aria-label', 'select model and provider');
    if (aideButton) {
      aideButton.title = 'choose model';
      aideButton.setAttribute('aria-label', 'select model and provider');
    }
    dot?.classList.remove('has-logo');
    if (dot) dot.innerHTML = '';
    dot?.classList.add('offline');
    window._currentEndpoint = null;
  }
  // companion image-slot chip
  const slotBtn = document.getElementById('image-slot-btn');
  if (slotBtn) {
    const slot = getImageSlot();
    // hide it when the primary IS the image model (legacy single-pick) — no point showing twice
    if (slot && !(isImageSelected() && _selected.model === slot.model)) {
      const ep = _endpoints.find(e => e.id === slot.endpointId);
      document.getElementById('image-slot-label').textContent = prettyModel(slot.model);
      document.getElementById('image-slot-ic').innerHTML = providerLogo(providerKey([ep && ep.provider, ep && ep.name, ep && ep.base_url, slot.model].filter(Boolean).join(' ')), { size: 12 });
      slotBtn.style.display = '';
    } else {
      slotBtn.style.display = 'none';
    }
  }
}

export function renderModelList(filter = '') {
  const list = document.getElementById('model-list');
  if (!list) return;
  const fl = filter.toLowerCase();
  let html = '';
  for (const ep of _endpoints) {
    const keep = m => !fl || m.toLowerCase().includes(fl);
    const models = _filterNewest(sortModels(ep.models.filter(keep)));
    const imgs = _filterNewest(sortModels((ep.image_models || []).filter(keep)));
    if (!models.length && !imgs.length && fl) continue;
    // detect from provider + name + url so openai-compatible endpoints (moonshot, groq,
    // openrouter…) get their real brand colour + logo, not the generic openai one. raw
    // ep.provider would paint moonshot/groq the same teal as gpt (they report 'openai').
    const epCtx = [ep.provider, ep.name, ep.base_url].filter(Boolean).join(' ');
    const color = brandColor(providerKey(epCtx));
    const logoFor = m => providerLogo(providerKey(epCtx + ' ' + m), { size: 14 });
    html += `<div class="provider-label" style="color:${color}">${ep.name}</div>`;
    if (!models.length && !imgs.length) {
      html += `<div style="padding:0.3rem 1rem;font-size:0.75rem;color:var(--muted)">
        no models — <button style="background:none;border:none;cursor:pointer;color:var(--accent);font:inherit;font-size:0.75rem" onclick="probeEndpoint('${ep.id}')">probe</button>
      </div>`;
      continue;
    }
    const visionSet = new Set(ep.vision_models || []);
    for (const m of models) {
      const isActive = _selected?.endpointId === ep.id && _selected?.model === m;
      const eye = visionSet.has(m) ? '<span class="model-vision-badge" title="vision">👁</span>' : '';
      html += `<button type="button" role="option" aria-selected="${isActive}" tabindex="${isActive ? '0' : '-1'}" class="model-row${isActive ? ' active' : ''}" data-ep="${ep.id}" data-model="${escAttr(m)}">
        ${logoFor(m)}
        <span class="model-name" title="${escAttr(m)}">${escHtml(prettyModel(m))}</span>${eye}
      </button>`;
    }
    for (const m of imgs) {
      const isActive = (_imageSlot?.endpointId === ep.id && _imageSlot?.model === m) ||
        (_selected?.endpointId === ep.id && _selected?.model === m);
      html += `<button type="button" role="option" aria-selected="${isActive}" tabindex="${isActive ? '0' : '-1'}" class="model-row model-row-img${isActive ? ' active' : ''}" data-ep="${ep.id}" data-model="${escAttr(m)}">
        ${logoFor(m)}
        <span class="model-name" title="${escAttr(m)}">${escHtml(prettyModel(m))}</span><span class="model-img-badge" title="image generation">🎨</span>
      </button>`;
    }
  }
  if (!html) html = '<div style="padding:1rem;font-size:0.75rem;color:var(--faint)">no endpoints — add one in the endpoints tab</div>';
  list.innerHTML = html;
  const rows = [...list.querySelectorAll('.model-row')];
  if (rows.length && !rows.some(row => row.tabIndex === 0)) rows[0].tabIndex = 0;
  rows.forEach(el => {
    el.addEventListener('click', () => selectModel(el.dataset.ep, el.dataset.model));
  });
  list.onkeydown = event => {
    const index = rows.indexOf(document.activeElement);
    let next = -1;
    if (event.key === 'ArrowDown') next = (index + 1 + rows.length) % rows.length;
    else if (event.key === 'ArrowUp') next = (index - 1 + rows.length) % rows.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = rows.length - 1;
    if (next < 0 || !rows.length) return;
    event.preventDefault();
    rows.forEach((row, rowIndex) => { row.tabIndex = rowIndex === next ? 0 : -1; });
    rows[next].focus();
  };
}

export function renderSidebarModelList(filter = '') {
  const list = document.getElementById('sidebar-model-list');
  if (!list) return;
  const fl = filter.toLowerCase();
  let html = '';
  for (const ep of _endpoints) {
    const keep = m => !fl || m.toLowerCase().includes(fl) || ep.name.toLowerCase().includes(fl);
    const models = _filterNewest(sortModels(ep.models.filter(keep)));
    const imgs = _filterNewest(sortModels((ep.image_models || []).filter(keep)));
    if (!models.length && !imgs.length && fl) continue;
    const epCtx = [ep.provider, ep.name, ep.base_url].filter(Boolean).join(' ');
    html += `<div class="sidebar-model-provider">
      ${providerLogo(providerKey(epCtx), { size: 13 })}
      <span style="color:${brandColor(providerKey(epCtx))}">${escHtml(ep.name)}</span>
    </div>`;
    if (!models.length && !imgs.length) {
      html += `<div class="sidebar-model-empty">no cached models</div>`;
      continue;
    }
    const row = (m, img) => {
      const isActive = (_selected?.endpointId === ep.id && _selected?.model === m) ||
        (img && _imageSlot?.endpointId === ep.id && _imageSlot?.model === m);
      return `<button type="button" class="sidebar-model-row${isActive ? ' active' : ''}${img ? ' sidebar-model-img' : ''}" data-ep="${ep.id}" data-model="${escAttr(m)}" title="${escAttr(m)}">
        <span>${escHtml(prettyModel(m))}</span>${img ? '<span class="model-img-badge" title="image generation">🎨</span>' : ''}
      </button>`;
    };
    html += models.map(m => row(m, false)).join('');
    html += imgs.map(m => row(m, true)).join('');
  }
  if (!html) html = '<div class="sidebar-model-empty">no models found</div>';
  list.innerHTML = html;
  list.querySelectorAll('.sidebar-model-row').forEach(btn => {
    btn.addEventListener('click', () => selectModel(btn.dataset.ep, btn.dataset.model));
  });
}

export async function selectModel(endpointId, model) {
  // an image model fills the companion image slot and leaves the chat model alone. only when
  // there's no chat model yet do we also seed the primary, so image-only use still works.
  if (_isImageModel(endpointId, model)) {
    setImageSlot(endpointId, model);
    if (!_selected) {
      _setSelection({ endpointId, model }, 'explicit', true);
    }
    if (typeof window._closeModelModal === 'function') window._closeModelModal();
    else {
      const modal = document.getElementById('model-modal');
      if (modal) modal.style.display = 'none';
    }
    return;
  }
  const selection = _catalogSelection({ endpointId, model }, false);
  if (!selection) return;
  const session = window._currentSession;
  const selectionKey = session ? String(session.id) : '__global__';
  const selectionGeneration = (_modelSelectionGenerations.get(selectionKey) || 0) + 1;
  _modelSelectionGenerations.set(selectionKey, selectionGeneration);
  if (session) {
    const save = async () => {
      const response = await fetch(`/api/sessions/${session.id}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ model, endpoint_id: endpointId }),
      });
      if (!response.ok) throw new Error('model save failed');
      session.model = model;
      session.endpoint_id = endpointId;
      if (window._currentSession?.id !== session.id) return;
    };
    try {
      const sessionId = String(session.id);
      const pending = (_modelSelectionQueues.get(sessionId) || Promise.resolve())
        .catch(() => {})
        .then(save);
      _modelSelectionQueues.set(sessionId, pending);
      try {
        await pending;
      } finally {
        if (_modelSelectionQueues.get(sessionId) === pending) _modelSelectionQueues.delete(sessionId);
      }
    } catch {
      if (selectionGeneration !== _modelSelectionGenerations.get(selectionKey)) return;
      if (window._currentSession?.id !== session?.id) return;
      toast('model change could not be saved', 'error');
      restoreSessionModel(session);
      return;
    }
  }
  if (selectionGeneration !== _modelSelectionGenerations.get(selectionKey)) return;
  if (session && window._currentSession?.id !== session.id) return;
  _setSelection(selection, 'explicit', true);
  // close modal + go back to models tab
  if (typeof window._closeModelModal === 'function') window._closeModelModal();
  else {
    const modal = document.getElementById('model-modal');
    if (modal) modal.style.display = 'none';
  }
}

// ── endpoints tab ─────────────────────────────────────────────────────────────
export function renderEndpointList() {
  const el = document.getElementById('mm-ep-list');
  if (!el) return;
  if (!_endpoints.length) {
    el.innerHTML = '<div style="padding:0.65rem 0.75rem;font-size:0.75rem;color:var(--muted)">no endpoints yet — use presets below</div>';
    return;
  }
  el.innerHTML = _endpoints.map(ep => {
    const color = brandColor(providerKey([ep.provider, ep.name, ep.base_url].filter(Boolean).join(' ')));
    return `
    <div class="mm-ep-card" data-id="${ep.id}">
      <div class="mm-ep-card-head">
        <span class="provider-dot" style="background:${color}"></span>
        <span class="mm-ep-name" style="font-weight:500">${escHtml(ep.name)}</span>
        <span style="font-size:0.75rem;color:var(--muted)">${ep.models.length} models</span>
        <div class="mm-ep-actions" style="margin-left:auto;display:flex;gap:0.25rem">
          <button class="btn mm-test-btn" type="button" data-id="${ep.id}" title="test completion" ${!ep.models.length ? 'disabled' : ''}>test</button>
          <button class="btn mm-probe-btn" type="button" data-id="${ep.id}" title="probe models">probe</button>
          <button class="act-btn mm-del-btn" type="button" data-id="${ep.id}" aria-label="remove ${escAttr(ep.name)} endpoint">×</button>
        </div>
      </div>
      <div class="mm-ep-edit" id="mm-ep-edit-${ep.id}" style="display:none">
        <input class="settings-input mm-edit-name" placeholder="name" value="${escAttr(ep.name)}" style="width:120px">
        <input class="settings-input mm-edit-url" placeholder="base url" value="${escAttr(ep.base_url || '')}" style="flex:1">
        <input class="settings-input mm-edit-key" type="password" placeholder="api key" value="" style="width:140px">
        <button class="btn primary mm-save-btn" type="button" data-id="${ep.id}">save</button>
        <button class="btn mm-cancel-btn" type="button" data-id="${ep.id}">cancel</button>
      </div>
      <div class="mm-ep-info">
        <span style="font-size:0.75rem;color:var(--muted)">${escHtml(ep.base_url || '')}</span>
        <button class="mm-edit-toggle" type="button" data-id="${ep.id}" aria-expanded="false" aria-controls="mm-ep-edit-${ep.id}" style="font-size:0.75rem;color:var(--accent);background:none;border:none;cursor:pointer;padding:0 0.25rem">edit</button>
      </div>
    </div>`;
  }).join('');

  el.querySelectorAll('.mm-edit-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.mm-ep-card');
      const editRow = card.querySelector('.mm-ep-edit');
      const isOpen = editRow.style.display !== 'none';
      editRow.style.display = isOpen ? 'none' : 'flex';
      btn.setAttribute('aria-expanded', String(!isOpen));
    });
  });

  el.querySelectorAll('.mm-save-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const card = btn.closest('.mm-ep-card');
      const patch = {
        name: card.querySelector('.mm-edit-name').value.trim(),
        base_url: card.querySelector('.mm-edit-url').value.trim(),
      };
      const keyVal = card.querySelector('.mm-edit-key').value.trim();
      if (keyVal) patch.api_key = keyVal;
      const response = await _ownerFetch(`/api/models/endpoint/${btn.dataset.id}`, {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify(patch),
      });
      if (!response.ok) { toast('endpoint could not be saved', 'error'); return; }
      toast('saved', 'success');
      await loadModels();
      renderEndpointList();
    });
  });

  el.querySelectorAll('.mm-cancel-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.closest('.mm-ep-card').querySelector('.mm-ep-edit').style.display = 'none';
    });
  });

  el.querySelectorAll('.mm-probe-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.textContent = '…'; btn.disabled = true;
      try {
        const r = await fetch(`/api/models/endpoint/${btn.dataset.id}/probe`, { method: 'POST' });
        const d = await r.json();
        toast(`${d.models?.length || 0} models`, 'success');
        await loadModels();
        renderEndpointList();
      } catch { toast('probe failed', 'error'); }
      btn.textContent = 'probe'; btn.disabled = false;
    });
  });

  el.querySelectorAll('.mm-test-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.textContent = '…'; btn.disabled = true;
      try {
        const r = await fetch(`/api/models/endpoint/${btn.dataset.id}/test`, { method: 'POST' });
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        toast(`success! model responded: ${d.response}`, 'success', 4000);
      } catch (e) { toast('test failed', 'error'); }
      btn.textContent = 'test'; btn.disabled = false;
    });
  });

  el.querySelectorAll('.mm-del-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await _dlgConfirm('remove this endpoint?')) return;
      const response = await _ownerFetch(`/api/models/endpoint/${btn.dataset.id}`, { method: 'DELETE' });
      if (!response.ok) { toast('endpoint could not be disconnected', 'error'); return; }
      toast('removed', 'success');
      await loadModels();
      renderEndpointList();
    });
  });
}

function _renderPresets() {
  const el = document.getElementById('mm-presets');
  if (!el) return;
  el.innerHTML = '<span style="font-size:0.75rem;color:var(--muted);flex-shrink:0">quick add:</span>';
  for (const p of PRESETS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'mm-preset-btn';
    btn.textContent = p.name;
    btn.addEventListener('click', () => {
      document.getElementById('ep-name').value = p.name;
      document.getElementById('ep-url').value = p.url;
      document.getElementById('ep-key').value = '';
      document.getElementById('ep-key').placeholder = p.key || 'leave blank';
      document.getElementById('ep-key').focus();
    });
    el.appendChild(btn);
  }
}

export function initModelModal() {
  // newest-only toggle — both the models page (#newest-only-switch) and the top picker modal
  // (.newest-only-switch) share the same state; setNewestOnly() re-syncs every switch.
  document.querySelectorAll('.newest-only-switch, #newest-only-switch').forEach(sw => {
    sw.classList.toggle('on', _newestOnly);
    sw.setAttribute('aria-checked', String(_newestOnly));
    sw.addEventListener('click', () => setNewestOnly(!sw.classList.contains('on')));
  });
  // clicking the image-slot chip drops the companion image model
  document.getElementById('image-slot-btn')?.addEventListener('click', () => {
    setImageSlot(null, null);
    toast('image model cleared', '');
  });
  // refresh model lists when the picker opens (debounced) + manual button
  document.getElementById('model-btn')?.addEventListener('click', maybeAutoRefresh);
  document.getElementById('mm-refresh-all')?.addEventListener('click', async () => {
    const b = document.getElementById('mm-refresh-all');
    b.textContent = '…'; b.disabled = true;
    await refreshModels(true);
    renderEndpointList();
    b.textContent = 'refresh'; b.disabled = false;
  });
  // tab switching
  const tabs = [...document.querySelectorAll('.mm-tab')];
  const activateTab = tab => {
    tabs.forEach(candidate => {
      const active = candidate === tab;
      candidate.classList.toggle('active', active);
      candidate.setAttribute('aria-selected', String(active));
      candidate.tabIndex = active ? 0 : -1;
    });
    const name = tab.dataset.tab;
    const modelsPanel = document.getElementById('mm-panel-models');
    const endpointsPanel = document.getElementById('mm-panel-endpoints');
    modelsPanel.style.display = name === 'models' ? '' : 'none';
    endpointsPanel.style.display = name === 'endpoints' ? '' : 'none';
    modelsPanel.hidden = name !== 'models';
    endpointsPanel.hidden = name !== 'endpoints';
    if (name === 'endpoints') {
      renderEndpointList();
      _renderPresets();
    }
  };
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      activateTab(tab);
    });
    tab.addEventListener('keydown', event => {
      const index = tabs.indexOf(tab);
      let next = -1;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      if (next < 0) return;
      event.preventDefault();
      activateTab(tabs[next]);
      tabs[next].focus();
    });
  });

  // add endpoint from modal
  document.getElementById('ep-add-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('ep-name').value.trim();
    const url  = document.getElementById('ep-url').value.trim();
    const key  = document.getElementById('ep-key').value.trim();
    if (!name || !url) { toast('name + url required', 'error'); return; }
    const btn = document.getElementById('ep-add-btn');
    btn.textContent = 'probing…'; btn.disabled = true;
    try {
      await addEndpoint(name, url, key);
      ['ep-name','ep-url','ep-key'].forEach(id => document.getElementById(id).value = '');
      toast('endpoint added', 'success');
      renderEndpointList();
    } catch (e) { toast(`failed: ${e.message}`, 'error'); }
    btn.textContent = 'add + probe'; btn.disabled = false;
  });
}

window.probeEndpoint = async function(epId) {
  try {
    const r = await fetch(`/api/models/endpoint/${epId}/probe`, { method: 'POST' });
    const data = await r.json();
    toast(`found ${data.models.length} models`, 'success');
    await loadModels();
  } catch { toast('probe failed', 'error'); }
};

// ── auto-refresh: re-probe enabled endpoints so new provider models show up ──
let _lastAutoRefresh = 0;
export async function refreshModels(force = false) {
  try {
    const r = await fetch('/api/models/refresh' + (force ? '?force=1' : ''), { method: 'POST' });
    const d = await r.json();
    if (d.added?.length) {
      await loadModels();
      toast('new models: ' + d.added.slice(0, 6).join(', '), 'success');
    } else if (force) {
      await loadModels();
      toast('models up to date', '');
    }
    return d;
  } catch { if (force) toast('refresh failed', 'error'); }
}
// called when the picker opens — client-debounced so opening it repeatedly is cheap
function maybeAutoRefresh() {
  if (Date.now() - _lastAutoRefresh < 120000) return;
  _lastAutoRefresh = Date.now();
  refreshModels(false);
}

export async function addEndpoint(name, url, key, adapter = 'auto', manualModels = [], auth = {}) {
  const r = await _ownerFetch('/api/models/endpoint', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      name,
      base_url: url,
      api_key: key,
      provider_adapter: adapter,
      provider_id: auth.providerId || '',
      auth_type: auth.authType || 'api_key',
    }),
  });
  if (!r.ok) throw new Error(await r.text());
  const ep = await r.json();
  if (adapter === 'manual') {
    const updated = await _ownerFetch(`/api/models/endpoint/${ep.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ models: manualModels }),
    });
    if (!updated.ok) throw new Error(await updated.text());
  } else {
    const probe = await fetch(`/api/models/endpoint/${ep.id}/probe`, { method: 'POST' });
    if (!probe.ok) toast(`${ep.name} saved, but its catalog is not available`, 'error');
  }
  await loadModels();
  return ep;
}

function escHtml(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function escAttr(s = '') {
  return escHtml(s).replace(/"/g,'&quot;');
}

// Settings can call this after saving role defaults without importing app internals.
window._refreshAideModelDefault = refreshAideModelDefault;
