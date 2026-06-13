import { toast } from './util.js';
import { confirm as _dlgConfirm } from './dialog.js';

let _endpoints = [];
let _selected = null;   // { endpointId, model }

const _PROVIDER_COLOR = {
  deepseek:   '#4d9ef5',
  anthropic:  '#d4a574',
  openai:     '#74aa9c',
  openrouter: '#818cf8',
  ollama:     '#6e6e6e',
  groq:       '#f59e0b',
  moonshot:   '#a78bfa',
  xai:        '#60a5fa',
  gemini:     '#34d399',
  mistral:    '#f97316',
  perplexity: '#22d3ee',
  together:   '#fb7185',
  fireworks:  '#fbbf24',
  cohere:     '#a3e635',
};

const PRESETS = [
  { name: 'OpenAI',      url: 'https://api.openai.com',                              key: 'sk-...' },
  { name: 'Anthropic',   url: 'https://api.anthropic.com',                           key: 'sk-ant-...' },
  { name: 'DeepSeek',    url: 'https://api.deepseek.com',                            key: 'sk-...' },
  { name: 'Moonshot',    url: 'https://api.moonshot.cn',                             key: 'sk-...' },
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
    const r = await fetch('/api/models');
    _endpoints = await r.json();
    window._endpoints = _endpoints;
    const saved = JSON.parse(localStorage.getItem('aide-model') || 'null');
    if (saved && _endpoints.find(ep => ep.id === saved.endpointId)) {
      _selected = saved;
    } else if (_endpoints.length > 0 && _endpoints[0].models.length > 0) {
      _selected = { endpointId: _endpoints[0].id, model: _endpoints[0].models[0] };
    }
    updateTopbar();
    renderModelList();
    renderSidebarModelList();
  } catch (e) {
    console.error('loadModels', e);
  }
}

export function getSelected() { return _selected; }

export function getCurrentEndpoint() {
  if (!_selected) return null;
  return _endpoints.find(ep => ep.id === _selected.endpointId) || null;
}

function updateTopbar() {
  const label = document.getElementById('model-label');
  const dot = document.getElementById('live-dot');
  if (_selected) {
    label.textContent = _selected.model.split('/').pop();
    dot.classList.remove('offline');
    const ep = getCurrentEndpoint();
    if (ep) window._currentEndpoint = ep;
  } else {
    label.textContent = 'no model';
    dot.classList.add('offline');
  }
}

export function renderModelList(filter = '') {
  const list = document.getElementById('model-list');
  if (!list) return;
  const fl = filter.toLowerCase();
  let html = '';
  for (const ep of _endpoints) {
    const models = fl ? ep.models.filter(m => m.toLowerCase().includes(fl)) : ep.models;
    if (!models.length && fl) continue;
    const color = _PROVIDER_COLOR[ep.provider] || '#6e6e6e';
    html += `<div class="provider-label" style="color:${color}">${ep.name}</div>`;
    if (!models.length) {
      html += `<div style="padding:0.3rem 1rem;font-size:0.72rem;color:var(--muted)">
        no models — <button style="background:none;border:none;cursor:pointer;color:var(--accent);font:inherit;font-size:0.72rem" onclick="probeEndpoint('${ep.id}')">probe</button>
      </div>`;
      continue;
    }
    const visionSet = new Set(ep.vision_models || []);
    for (const m of models) {
      const isActive = _selected?.endpointId === ep.id && _selected?.model === m;
      const eye = visionSet.has(m) ? '<span class="model-vision-badge" title="vision">👁</span>' : '';
      html += `<div class="model-row${isActive ? ' active' : ''}" data-ep="${ep.id}" data-model="${escAttr(m)}">
        <div class="model-dot"></div>
        <span class="model-name">${escHtml(m)}</span>${eye}
      </div>`;
    }
  }
  if (!html) html = '<div style="padding:1rem;font-size:0.75rem;color:var(--faint)">no endpoints — add one in the endpoints tab</div>';
  list.innerHTML = html;
  list.querySelectorAll('.model-row').forEach(el => {
    el.addEventListener('click', () => selectModel(el.dataset.ep, el.dataset.model));
  });
}

export function renderSidebarModelList(filter = '') {
  const list = document.getElementById('sidebar-model-list');
  if (!list) return;
  const fl = filter.toLowerCase();
  let html = '';
  for (const ep of _endpoints) {
    const models = fl
      ? ep.models.filter(m => m.toLowerCase().includes(fl) || ep.name.toLowerCase().includes(fl))
      : ep.models;
    if (!models.length && fl) continue;
    const color = _PROVIDER_COLOR[ep.provider] || '#6e6e6e';
    html += `<div class="sidebar-model-provider">
      <span class="provider-dot" style="background:${color}"></span>
      <span>${escHtml(ep.name)}</span>
    </div>`;
    if (!models.length) {
      html += `<div class="sidebar-model-empty">no cached models</div>`;
      continue;
    }
    html += models.map(m => {
      const isActive = _selected?.endpointId === ep.id && _selected?.model === m;
      return `<button class="sidebar-model-row${isActive ? ' active' : ''}" data-ep="${ep.id}" data-model="${escAttr(m)}">
        <span>${escHtml(m)}</span>
      </button>`;
    }).join('');
  }
  if (!html) html = '<div class="sidebar-model-empty">no models found</div>';
  list.innerHTML = html;
  list.querySelectorAll('.sidebar-model-row').forEach(btn => {
    btn.addEventListener('click', () => selectModel(btn.dataset.ep, btn.dataset.model));
  });
}

export function selectModel(endpointId, model) {
  _selected = { endpointId, model };
  localStorage.setItem('aide-model', JSON.stringify(_selected));
  updateTopbar();
  renderModelList();
  renderSidebarModelList(document.getElementById('sidebar-model-search')?.value || '');
  const session = window._currentSession;
  if (session) {
    fetch(`/api/sessions/${session.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model, endpoint_id: endpointId }),
    }).catch(() => {});
  }
  // close modal + go back to models tab
  document.getElementById('model-modal').style.display = 'none';
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
    const color = _PROVIDER_COLOR[ep.provider] || '#6e6e6e';
    return `
    <div class="mm-ep-card" data-id="${ep.id}">
      <div class="mm-ep-card-head">
        <span class="provider-dot" style="background:${color}"></span>
        <span class="mm-ep-name" style="font-weight:500">${escHtml(ep.name)}</span>
        <span style="font-size:0.68rem;color:var(--muted)">${ep.models.length} models</span>
        <div class="mm-ep-actions" style="margin-left:auto;display:flex;gap:0.25rem">
          <button class="btn mm-probe-btn" data-id="${ep.id}" title="probe models">probe</button>
          <button class="act-btn mm-del-btn" data-id="${ep.id}">×</button>
        </div>
      </div>
      <div class="mm-ep-edit" id="mm-ep-edit-${ep.id}" style="display:none">
        <input class="settings-input mm-edit-name" placeholder="name" value="${escAttr(ep.name)}" style="width:120px">
        <input class="settings-input mm-edit-url" placeholder="base url" value="${escAttr(ep.base_url || '')}" style="flex:1">
        <input class="settings-input mm-edit-key" type="password" placeholder="api key" value="" style="width:140px">
        <button class="btn primary mm-save-btn" data-id="${ep.id}">save</button>
        <button class="btn mm-cancel-btn" data-id="${ep.id}">cancel</button>
      </div>
      <div class="mm-ep-info">
        <span style="font-size:0.68rem;color:var(--muted)">${escHtml(ep.base_url || '')}</span>
        <button class="mm-edit-toggle" data-id="${ep.id}" style="font-size:0.68rem;color:var(--accent);background:none;border:none;cursor:pointer;padding:0 0.25rem">edit</button>
      </div>
    </div>`;
  }).join('');

  el.querySelectorAll('.mm-edit-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.mm-ep-card');
      const editRow = card.querySelector('.mm-ep-edit');
      const isOpen = editRow.style.display !== 'none';
      editRow.style.display = isOpen ? 'none' : 'flex';
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
      await fetch(`/api/models/endpoint/${btn.dataset.id}`, {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify(patch),
      });
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

  el.querySelectorAll('.mm-del-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!await _dlgConfirm('remove this endpoint?')) return;
      await fetch(`/api/models/endpoint/${btn.dataset.id}`, { method: 'DELETE' });
      toast('removed', 'success');
      await loadModels();
      renderEndpointList();
    });
  });
}

function _renderPresets() {
  const el = document.getElementById('mm-presets');
  if (!el) return;
  el.innerHTML = '<span style="font-size:0.68rem;color:var(--muted);flex-shrink:0">quick add:</span>';
  for (const p of PRESETS) {
    const btn = document.createElement('button');
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
  document.querySelectorAll('.mm-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.mm-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const name = tab.dataset.tab;
      document.getElementById('mm-panel-models').style.display = name === 'models' ? '' : 'none';
      document.getElementById('mm-panel-endpoints').style.display = name === 'endpoints' ? '' : 'none';
      if (name === 'endpoints') {
        renderEndpointList();
        _renderPresets();
      }
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

export async function addEndpoint(name, url, key) {
  const r = await fetch('/api/models/endpoint', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, base_url: url, api_key: key }),
  });
  if (!r.ok) throw new Error(await r.text());
  const ep = await r.json();
  await fetch(`/api/models/endpoint/${ep.id}/probe`, { method: 'POST' }).catch(() => {});
  await loadModels();
  return ep;
}

function escHtml(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function escAttr(s = '') {
  return escHtml(s).replace(/"/g,'&quot;');
}
