import { toast } from './util.js';

let _endpoints = [];
let _selected = null;   // { endpointId, model }

// provider logos — simple colored dots or text icons
const _PROVIDER_COLOR = {
  deepseek:  '#4d9ef5',
  anthropic: '#d4a574',
  openai:    '#74aa9c',
  openrouter:'#818cf8',
  ollama:    '#6e6e6e',
  groq:      '#f59e0b',
};

export async function loadModels() {
  try {
    const r = await fetch('/api/models');
    _endpoints = await r.json();
    window._endpoints = _endpoints;

    // restore last selection or default to first model
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
    const short = _selected.model.split('/').pop();
    label.textContent = short;
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
    const models = fl
      ? ep.models.filter(m => m.toLowerCase().includes(fl))
      : ep.models;

    if (!models.length && fl) continue;

    const color = _PROVIDER_COLOR[ep.provider] || '#6e6e6e';
    html += `<div class="provider-label" style="color:${color}">${ep.name}</div>`;

    if (!models.length) {
      html += `<div style="padding:0.3rem 1rem;font-size:0.72rem;color:var(--muted)">
        no models — <button style="background:none;border:none;cursor:pointer;color:var(--accent);font:inherit;font-size:0.72rem" onclick="probeEndpoint('${ep.id}')">probe</button>
      </div>`;
      continue;
    }

    for (const m of models) {
      const isActive = _selected?.endpointId === ep.id && _selected?.model === m;
      html += `<div class="model-row${isActive ? ' active' : ''}" data-ep="${ep.id}" data-model="${m}">
        <div class="model-dot"></div>
        <span class="model-name">${m}</span>
      </div>`;
    }
  }

  if (!html) {
    html = '<div style="padding:1rem;font-size:0.75rem;color:var(--faint)">no endpoints yet — add one below</div>';
  }

  list.innerHTML = html;

  list.querySelectorAll('.model-row').forEach(el => {
    el.addEventListener('click', () => {
      selectModel(el.dataset.ep, el.dataset.model);
    });
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

  // update current session if one is open
  const session = window._currentSession;
  if (session) {
    fetch(`/api/sessions/${session.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model, endpoint_id: endpointId }),
    }).catch(() => {});
  }
}


// expose for inline onclick in model list
window.probeEndpoint = async function(epId) {
  try {
    const r = await fetch(`/api/models/endpoint/${epId}/probe`, { method: 'POST' });
    const data = await r.json();
    toast(`found ${data.models.length} models`, 'success');
    await loadModels();
  } catch (e) {
    toast('probe failed', 'error');
  }
};

function escHtml(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escAttr(s = '') {
  return escHtml(s).replace(/"/g, '&quot;');
}


export async function addEndpoint(name, url, key) {
  const r = await fetch('/api/models/endpoint', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name, base_url: url, api_key: key }),
  });
  if (!r.ok) throw new Error(await r.text());
  const ep = await r.json();
  // auto-probe
  await fetch(`/api/models/endpoint/${ep.id}/probe`, { method: 'POST' }).catch(() => {});
  await loadModels();
  return ep;
}
