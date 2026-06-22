import { toast } from './util.js';
import { confirm as _dlgConfirm } from './dialog.js';
import { loadModels, addEndpoint, renderModelList } from './models.js';
import { initCustomDropdowns, getDropdownValue, setDropdownValue, populateDropdown } from './dropdown.js';
import { initMemoryPanel } from './memory.js';
import {
  sensitiveBlurEnabled, textOnlyEmojisEnabled, welcomeEnabled,
  setSensitiveBlur, setTextOnlyEmojis, setWelcomeEnabled,
} from './privacy.js';
import { loadShortcuts, saveShortcuts, eventToShortcut, isReservedShortcut } from './shortcuts.js';

// ── visibility prefs (appearance toggles) ────────────────────────────────────
const VIS_KEY = 'aide-ui-vis';

function loadVis() {
  try { return JSON.parse(localStorage.getItem(VIS_KEY) || '{}'); } catch { return {}; }
}

function saveVis(v) { localStorage.setItem(VIS_KEY, JSON.stringify(v)); }

export function applyVis() {
  const v = loadVis();
  document.querySelectorAll('.s-vis-toggle').forEach(sw => {
    const key = sw.dataset.visKey;
    const on = key in v ? v[key] : true; // default on
    _setSwitch(sw, on);
    const sel = sw.dataset.vis;
    if (sel) document.querySelectorAll(sel).forEach(el => {
      el.style.display = on ? '' : 'none';
    });
  });
  // restore compact + font size at boot
  if (localStorage.getItem('aide-compact')) document.body.classList.add('compact');
  _applyFontSize(localStorage.getItem('aide-font-size') || 'md');
}

function _applyFontSize(sz) {
  document.documentElement.dataset.fontSize = sz || 'md';
}

// ── switch helpers ────────────────────────────────────────────────────────────
function _setSwitch(el, on) {
  el.classList.toggle('on', !!on);
}

function _bindSwitch(el, getter, setter) {
  _setSwitch(el, getter());
  el.addEventListener('click', () => {
    const next = !el.classList.contains('on');
    _setSwitch(el, next);
    setter(next);
  });
}

// ── pane navigation ───────────────────────────────────────────────────────────
let _activePane = 'models';

function _switchPane(name) {
  _activePane = name;
  document.querySelectorAll('.s-nav-item').forEach(n =>
    n.classList.toggle('active', n.dataset.pane === name));
  document.querySelectorAll('.s-pane').forEach(p =>
    p.classList.toggle('active', p.id === `s-pane-${name}`));
  _onPaneOpen(name);
}

function _onPaneOpen(name) {
  if (name === 'models')     { loadEpList(); loadLocalModels(); }
  if (name === 'ai')         loadAiPane();
  if (name === 'memory')     initMemoryPanel();
  if (name === 'search')     loadSearchPane();
  if (name === 'appearance') loadAppearancePane();
  if (name === 'voice')      loadVoicePane();
  if (name === 'personas')   { loadPersonas(); loadCookbook(); }
  if (name === 'tools')      { loadAgentStatus(); loadMcpServers(); loadConnections(); loadPermRules(); loadMacosStatus(); }
  if (name === 'developer')  { loadTokens(); loadWebhooks(); loadShortcutSettings(); }
  if (name === 'rules')      loadRulesPane();
  if (name === 'recall')     loadRecallPane();
  if (name === 'proactive')  loadProactivePane();
}

// ── open / close ──────────────────────────────────────────────────────────────
let _bound = false;

export function openSettings(pane, allesOnly = false) {
  const modal = document.getElementById('settings-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  // hub/home settings = alles-wide only (appearance + backup); aide keeps the full set
  modal.classList.toggle('alles-scope', allesOnly);
  const title = document.querySelector('#settings-modal .s-title');
  if (title) title.textContent = allesOnly ? 'alles settings' : 'settings';
  if (!pane) pane = allesOnly ? 'appearance' : 'models';
  if (!_bound) { _initSettings(); _bound = true; }
  // update compat url labels
  const port = location.port || '8000';
  const base = `${location.protocol}//${location.hostname}:${port}/v1`;
  document.getElementById('s-compat-url')?.setAttribute('data-val', base);
  document.getElementById('s-compat-url')?.replaceChildren(document.createTextNode(base));
  document.getElementById('s-compat-url2')?.replaceChildren(document.createTextNode(base));

  _switchPane(pane);
}

export function closeSettings() {
  const modal = document.getElementById('settings-modal');
  if (modal) modal.style.display = 'none';
}

// expose for playwright tests + external callers
window._openSettings = openSettings;

// ── init (runs once) ──────────────────────────────────────────────────────────
function _initSettings() {
  initCustomDropdowns(document.getElementById('settings-modal') || document);

  // nav clicks
  document.querySelectorAll('.s-nav-item').forEach(n => {
    n.addEventListener('click', () => _switchPane(n.dataset.pane));
  });

  // overlay close
  const modal = document.getElementById('settings-modal');
  modal.addEventListener('click', e => { if (e.target === modal) closeSettings(); });
  document.getElementById('settings-modal-close')?.addEventListener('click', closeSettings);

  // ── models pane ──
  document.querySelectorAll('.s-preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('s-ep-url').value = btn.dataset.url;
      document.getElementById('s-ep-name').value = btn.dataset.name;
      document.getElementById('s-ep-key').focus();
    });
  });
  document.getElementById('s-ep-add-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('s-ep-name').value.trim();
    const url  = document.getElementById('s-ep-url').value.trim();
    const key  = document.getElementById('s-ep-key').value.trim();
    if (!name || !url) { toast('name and url required', 'error'); return; }
    const btn = document.getElementById('s-ep-add-btn');
    btn.textContent = 'probing…'; btn.disabled = true;
    try {
      const ep = await addEndpoint(name, url, key);
      const visionRaw = document.getElementById('s-ep-vision')?.value.trim() || '';
      if (visionRaw && ep?.id) {
        const visionList = visionRaw.split(',').map(s => s.trim()).filter(Boolean);
        await fetch(`/api/models/endpoint/${ep.id}`, {
          method: 'PATCH', headers: {'content-type':'application/json'},
          body: JSON.stringify({ vision_models: JSON.stringify(visionList) }),
        });
      }
      ['s-ep-name','s-ep-url','s-ep-key','s-ep-vision'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
      document.getElementById('s-ep-add-details').open = false;
      toast('endpoint added', 'success');
      loadEpList();
      loadModels();
      renderModelList();
    } catch (e) { toast(`failed: ${e.message}`, 'error'); }
    btn.textContent = 'add + probe models'; btn.disabled = false;
  });

  // ── ai pane ──
  document.getElementById('s-local-refresh-btn')?.addEventListener('click', loadLocalModels);
  document.getElementById('s-local-pull-btn')?.addEventListener('click', pullCustomLocalModel);
  document.getElementById('s-local-start-btn')?.addEventListener('click', startLocalOllama);

  document.getElementById('settings-save-btn')?.addEventListener('click', saveAiDefaults);

  // ── search pane ──
  document.getElementById('s-search-provider')?.addEventListener('change', () => {
    _updateSearchKeyRow();
    saveSearchSettings();
  });
  document.getElementById('s-search-fallback')?.addEventListener('change', saveSearchSettings);
  ['s-tavily-key','s-brave-key','s-searxng-url','s-gpse-key','s-gpse-cx','s-serper-key'].forEach(id =>
    document.getElementById(id)?.addEventListener('blur', saveSearchSettings));
  document.getElementById('s-search-count')?.addEventListener('change', saveSearchSettings);
  document.getElementById('s-search-test-btn')?.addEventListener('click', testSearch);

  // ── voice pane ──
  document.getElementById('s-voice-save-btn')?.addEventListener('click', saveVoiceSettings);
  document.getElementById('tts-select')?.addEventListener('change', _updateTtsVoiceRow);

  // ── appearance: vis toggles ──
  document.querySelectorAll('.s-vis-toggle').forEach(sw => {
    sw.addEventListener('click', () => {
      const key = sw.dataset.visKey;
      const next = !sw.classList.contains('on');
      _setSwitch(sw, next);
      const v = loadVis(); v[key] = next; saveVis(v);
      const sel = sw.dataset.vis;
      if (sel) document.querySelectorAll(sel).forEach(el => {
        el.style.display = next ? '' : 'none';
      });
    });
  });
  document.getElementById('s-vis-reset-btn')?.addEventListener('click', () => {
    localStorage.removeItem(VIS_KEY);
    applyVis();
    loadAppearancePane();
    toast('appearance reset', 'success');
  });

  // ── personas / cookbook ──
  document.getElementById('persona-add-btn')?.addEventListener('click', addPersona);
  document.getElementById('persona-cancel-btn')?.addEventListener('click', _resetPersonaForm);
  const _tempBar = document.getElementById('persona-temp');
  _tempBar?.addEventListener('pointerdown', _onTempPointer);
  _tempBar?.addEventListener('pointermove', _onTempPointer);
  document.getElementById('persona-temp-pin')?.addEventListener('click', _togglePersonaTempPin);
  _renderTempBar();   // paint the empty/auto track on first open
  document.getElementById('persona-default')?.addEventListener('click', e => e.currentTarget.classList.toggle('on'));
  document.getElementById('persona-mode')?.addEventListener('click', e => {
    const opt = e.target.closest('.seg-opt'); if (!opt) return;
    opt.parentElement.querySelectorAll('.seg-opt').forEach(o => o.classList.toggle('active', o === opt));
  });
  document.getElementById('cookbook-add-btn')?.addEventListener('click', addCookbookEntry);

  // ── tools (mcp) ──
  document.getElementById('mcp-add-btn')?.addEventListener('click', addMcpServer);
  document.getElementById('persona-doc-add')?.addEventListener('click', _addPersonaDoc);
  document.getElementById('persona-share-btn')?.addEventListener('click', _sharePersona);
  document.getElementById('agent-status-refresh-btn')?.addEventListener('click', loadAgentStatus);

  // ── developer ──
  document.getElementById('token-add-btn')?.addEventListener('click', generateToken);
  document.getElementById('wh-add-btn')?.addEventListener('click', addWebhook);

  // ── backup ──
  document.getElementById('backup-export-btn')?.addEventListener('click', () => {
    window.location = '/api/backup';
  });
  document.getElementById('backup-restore-input')?.addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch('/api/backup/restore', { method: 'POST', body: fd });
    if (r.ok) { toast('restore complete — reloading…', 'success'); setTimeout(() => location.reload(), 1500); }
    else toast('restore failed', 'error');
    e.target.value = '';
  });

  document.querySelectorAll('.shortcut-input').forEach(inp => {
    inp.addEventListener('keydown', e => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === 'Escape') {              // Esc → no shortcut for this action
        inp.value = '';
        saveShortcuts({ [inp.dataset.shortcut]: '' });
        toast('shortcut cleared', '');
        inp.blur();
        return;
      }
      const combo = eventToShortcut(e);
      if (!combo) return;
      if (isReservedShortcut(combo)) { toast(`${combo} is a system/browser shortcut — pick another`, 'error'); return; }
      inp.value = combo;
      saveShortcuts({ [inp.dataset.shortcut]: combo });
      toast('shortcut saved', 'success');
    });
  });
}

// ── models pane ───────────────────────────────────────────────────────────────
async function loadLocalModels() {
  const ollamaEl = document.getElementById('s-local-ollama');
  const hwEl = document.getElementById('s-local-hw');
  const listEl = document.getElementById('s-local-presets');
  if (!ollamaEl || !hwEl || !listEl) return;
  ollamaEl.textContent = 'checking Ollama...';
  try {
    const data = await _localJson('/api/local-models/status');
    const o = data.ollama || {};
    const hw = data.hardware || {};
    const gpu = (hw.gpus || []).map(g => `${g.name} (${g.vram_gb} GB)`).join(', ') || 'no NVIDIA GPU detected';
    const state = o.running ? 'running' : (o.installed ? 'installed, stopped' : 'not installed');
    ollamaEl.textContent = `Ollama: ${state} - ${o.base_url || 'http://localhost:11434'}`;
    hwEl.textContent = `Hardware: ${hw.ram_gb || '?'} GB RAM - ${gpu}`;
    renderLocalPresets(data.presets || []);
  } catch (e) {
    ollamaEl.textContent = e.message || 'local model status failed';
    hwEl.textContent = '';
    listEl.innerHTML = '';
  }
}

function renderLocalPresets(presets) {
  const listEl = document.getElementById('s-local-presets');
  if (!listEl) return;
  if (!presets.length) {
    listEl.innerHTML = '<div style="font-size:0.72rem;color:var(--muted)">no local presets available</div>';
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

async function loadEpList() {
  const el = document.getElementById('s-ep-list');
  if (!el) return;
  try {
    const eps = await fetch('/api/models').then(r => r.json());
    if (!eps.length) {
      el.innerHTML = '<div style="font-size:0.75rem;color:var(--muted);padding:0.3rem 0">no endpoints — add one below</div>';
      return;
    }
    el.innerHTML = eps.map(ep => `
      <div class="s-ep-card" data-id="${ep.id}">
        <div class="s-ep-dot ${ep.models?.length ? 'ok' : ''}"></div>
        <div class="s-ep-info">
          <div class="s-ep-name">${_esc(ep.name)}</div>
          <div class="s-ep-meta">${_esc(ep.base_url)} · ${ep.models?.length || 0} models</div>
        </div>
        <div class="s-ep-actions">
          <button class="btn" data-probe="${ep.id}">probe</button>
          <button class="btn danger" data-del="${ep.id}">×</button>
        </div>
      </div>`).join('');

    el.querySelectorAll('[data-probe]').forEach(btn => {
      btn.addEventListener('click', async () => {
        btn.textContent = '…'; btn.disabled = true;
        try {
          const r = await fetch(`/api/models/endpoint/${btn.dataset.probe}/probe`, { method: 'POST' });
          const d = await r.json();
          toast(`${d.models?.length || 0} models found`, 'success');
          loadEpList(); loadModels(); renderModelList();
        } catch { toast('probe failed', 'error'); }
        btn.textContent = 'probe'; btn.disabled = false;
      });
    });

    el.querySelectorAll('[data-del]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!await _dlgConfirm('remove this endpoint?')) return;
        await fetch(`/api/models/endpoint/${btn.dataset.del}`, { method: 'DELETE' });
        toast('endpoint removed', 'success');
        loadEpList(); loadModels(); renderModelList();
      });
    });
  } catch { el.innerHTML = '<div style="font-size:0.75rem;color:var(--error)">failed to load</div>'; }
}

// ── ai pane ───────────────────────────────────────────────────────────────────
async function loadAiPane() {
  try {
    const s = await fetch('/api/settings').then(r => r.json());
    document.getElementById('settings-system-prompt').value = s.system_prompt || '';
    document.getElementById('settings-context-limit').value = s.context_limit ?? 40;
    _bindSwitch(document.getElementById('s-thinking-toggle'),
      () => s.stream_thinking !== false,
      v => _patchSetting('stream_thinking', v));
    _bindSwitch(document.getElementById('s-artifacts-toggle'),
      () => s.artifacts_enabled !== false,
      v => _patchSetting('artifacts_enabled', v));
    _bindSwitch(document.getElementById('s-compact-toggle'),
      () => s.auto_compact !== false,
      v => _patchSetting('auto_compact', v));
  } catch {}
}

async function saveAiDefaults() {
  const patch = {
    system_prompt: document.getElementById('settings-system-prompt').value,
    context_limit: parseInt(document.getElementById('settings-context-limit').value) || 40,
  };
  await _patchSettings(patch);
  toast('saved', 'success');
}

// ── search pane ───────────────────────────────────────────────────────────────
const _SEARCH_KEY_FIELDS = {
  tavily:     ['s-tavily-row'],
  brave:      ['s-brave-row'],
  searxng:    ['s-searxng-row'],
  google_pse: ['s-google-pse-rows'],
  serper:     ['s-serper-row'],
};

async function loadSearchPane() {
  try {
    const s = await fetch('/api/settings').then(r => r.json());
    const prov = s.search_provider || 'duckduckgo';
    setDropdownValue(document.getElementById('s-search-provider'), prov);
    setDropdownValue(document.getElementById('s-search-fallback'), s.search_fallback || 'duckduckgo');
    if (s.tavily_api_key)  document.getElementById('s-tavily-key').value  = s.tavily_api_key;
    if (s.brave_api_key)   document.getElementById('s-brave-key').value   = s.brave_api_key;
    if (s.searxng_url)     document.getElementById('s-searxng-url').value  = s.searxng_url;
    if (s.google_pse_api_key) document.getElementById('s-gpse-key').value = s.google_pse_api_key;
    if (s.google_pse_cx)   document.getElementById('s-gpse-cx').value     = s.google_pse_cx;
    if (s.serper_api_key)  document.getElementById('s-serper-key').value  = s.serper_api_key;
    const sel = document.getElementById('s-search-count');
    if (sel) setDropdownValue(sel, String(s.search_result_count || 5));
    _updateSearchKeyRow();
    _updateSearchStatus(s);
  } catch {}
}

function _updateSearchKeyRow() {
  const prov = getDropdownValue(document.getElementById('s-search-provider'));
  // hide all key rows, then show the right one
  const allRows = ['s-tavily-row','s-brave-row','s-searxng-row','s-google-pse-rows','s-serper-row'];
  allRows.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  const rows = _SEARCH_KEY_FIELDS[prov] || [];
  rows.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'flex';
  });
}

function _updateSearchStatus(s) {
  const el = document.getElementById('s-search-status');
  if (!el) return;
  const prov  = s.search_provider || 'duckduckgo';
  const count = s.search_result_count || 5;
  const labels = { duckduckgo:'DuckDuckGo', tavily:'Tavily', brave:'Brave', searxng:'SearXNG', google_pse:'Google PSE', serper:'Serper', disabled:'disabled' };
  const needsKey = { tavily:'tavily_api_key', brave:'brave_api_key', google_pse:'google_pse_api_key', serper:'serper_api_key' };
  const needsUrl = { searxng:'searxng_url' };
  const keyField = needsKey[prov]; const urlField = needsUrl[prov];
  const missing  = (keyField && !s[keyField]) || (urlField && !s[urlField]);
  el.textContent = `active: ${labels[prov]||prov} · ${count} results${missing?' · missing credentials':''}`;
  el.style.color  = missing ? 'var(--error)' : 'var(--muted)';
}

async function saveSearchSettings() {
  const prov  = getDropdownValue(document.getElementById('s-search-provider'));
  const count = parseInt(getDropdownValue(document.getElementById('s-search-count'))) || 5;
  const fall  = getDropdownValue(document.getElementById('s-search-fallback')) || 'duckduckgo';
  const patch = { search_provider: prov, search_result_count: count, search_fallback: fall };
  const fields = {
    s_tavily_key: 'tavily_api_key', s_brave_key: 'brave_api_key',
    s_searxng_url: 'searxng_url', s_gpse_key: 'google_pse_api_key',
    s_gpse_cx: 'google_pse_cx', s_serper_key: 'serper_api_key',
  };
  for (const [htmlId, settingKey] of Object.entries(fields)) {
    const val = document.getElementById(htmlId.replace(/_/g, '-'))?.value.trim();
    if (val) patch[settingKey] = val;
  }
  await _patchSettings(patch);
  _updateSearchStatus({ search_provider: prov, search_result_count: count, ...patch });
}

async function testSearch() {
  const btn = document.getElementById('s-search-test-btn');
  const status = document.getElementById('s-search-status');
  btn.textContent = 'testing...'; btn.disabled = true;
  try {
    const prov = getDropdownValue(document.getElementById('s-search-provider'));
    if (prov === 'disabled') { status.textContent = 'search is disabled'; btn.textContent = 'test'; btn.disabled = false; return; }
    const r = await fetch('/api/research', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: 'test', session_id: 'settings-test', max_rounds: 1 }),
    });
    status.textContent = r.ok ? 'connection ok' : `error: ${r.status}`;
    status.style.color = r.ok ? 'var(--green)' : 'var(--error)';
  } catch (e) {
    status.textContent = `error: ${e.message}`; status.style.color = 'var(--error)';
  }
  btn.textContent = 'test'; btn.disabled = false;
}

// ── appearance pane ───────────────────────────────────────────────────────────
function loadAppearancePane() {
  const v = loadVis();
  document.querySelectorAll('.s-vis-toggle').forEach(sw => {
    const key = sw.dataset.visKey;
    _setSwitch(sw, key in v ? v[key] : true);
  });
  _bindSwitchOnce(document.getElementById('s-sensitive-blur-toggle'), sensitiveBlurEnabled, setSensitiveBlur);
  _bindSwitchOnce(document.getElementById('s-text-emoji-toggle'), textOnlyEmojisEnabled, setTextOnlyEmojis);
  _bindSwitchOnce(document.getElementById('s-welcome-toggle'), welcomeEnabled, setWelcomeEnabled);
  // memory inject loaded async — fetch setting first
  fetch('/api/settings').then(r => r.json()).then(s => {
    _bindSwitchOnce(document.getElementById('s-memory-inject-toggle'),
      () => s.memory_auto_inject !== false,
      on => _patchSettings({ memory_auto_inject: on })
    );
  }).catch(() => {});
  _bindSwitchOnce(document.getElementById('s-ui-compact-toggle'),
    () => document.body.classList.contains('compact'),
    on => {
      document.body.classList.toggle('compact', on);
      localStorage.setItem('aide-compact', on ? '1' : '');
    }
  );
  const fsEl = document.getElementById('s-ui-font-size');
  if (fsEl) {
    const cur = localStorage.getItem('aide-font-size') || 'md';
    setDropdownValue(fsEl, cur);
    if (!fsEl.dataset.fsBound) {
      fsEl.dataset.fsBound = '1';
      fsEl.addEventListener('change', () => {
        const sz = getDropdownValue(fsEl) || 'md';
        localStorage.setItem('aide-font-size', sz);
        _applyFontSize(sz);
      });
    }
  }
  _loadThemeColorControls();
  const teBtn = document.getElementById('s-open-theme-editor');
  if (teBtn && !teBtn.dataset.bound) {
    teBtn.dataset.bound = '1';
    teBtn.addEventListener('click', async () => { (await import('./theme.js')).openThemeEditor(); });
  }
}

// ── theme mode + accent color ─────────────────────────────────────────────────
const ACCENT_PRESETS = [
  ['#818cf8', 'indigo'], ['#a78bfa', 'purple'], ['#60a5fa', 'blue'], ['#22d3ee', 'cyan'],
  ['#34d399', 'emerald'], ['#4ade80', 'green'], ['#facc15', 'yellow'], ['#fb923c', 'orange'],
  ['#f87171', 'red'], ['#f472b6', 'pink'], ['#e879f9', 'fuchsia'], ['#e8e6e3', 'mono'],
];
const DEFAULT_ACCENT = '#818cf8';
const _curAccent = () => (localStorage.getItem('aide-accent') || DEFAULT_ACCENT).toLowerCase();

function applyAccent(hex) {
  if (hex) {
    document.documentElement.style.setProperty('--accent', hex);
    localStorage.setItem('aide-accent', hex);
  } else {
    document.documentElement.style.removeProperty('--accent');
    localStorage.removeItem('aide-accent');
  }
  _markAccent();
  window._updateFavicon?.();
  _patchSettings({ accent: hex || '' });   // persist server-side → same accent on every subdomain
}
function applyThemeMode(mode) {
  if (mode === 'light') { document.documentElement.dataset.theme = 'light'; localStorage.setItem('aide-theme', 'light'); }
  else { delete document.documentElement.dataset.theme; localStorage.removeItem('aide-theme'); }
  document.querySelectorAll('.theme-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.themeMode === (mode === 'light' ? 'light' : 'dark')));
  window._updateFavicon?.();
  _patchSettings({ theme: mode === 'light' ? 'light' : '' });   // persist server-side → synced
}
function _markAccent() {
  const cur = _curAccent();
  document.querySelectorAll('#s-accent-swatches .accent-swatch').forEach(s =>
    s.classList.toggle('active', s.dataset.hex.toLowerCase() === cur));
  const hexInp = document.getElementById('s-accent-hex'); if (hexInp) hexInp.value = cur;
}
function _loadThemeColorControls() {
  // theme mode buttons
  const curMode = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  document.querySelectorAll('.theme-mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.themeMode === curMode);
    if (!b.dataset.bound) { b.dataset.bound = '1'; b.addEventListener('click', () => applyThemeMode(b.dataset.themeMode)); }
  });
  // accent swatches
  const box = document.getElementById('s-accent-swatches');
  if (box && !box.dataset.built) {
    box.dataset.built = '1';
    box.innerHTML = ACCENT_PRESETS.map(([hex, name]) =>
      `<button class="accent-swatch" data-hex="${hex}" title="${name}" style="background:${hex}"></button>`).join('');
    box.querySelectorAll('.accent-swatch').forEach(s => s.addEventListener('click', () => applyAccent(s.dataset.hex)));
  }
  const hexInp = document.getElementById('s-accent-hex');
  if (hexInp && !hexInp.dataset.bound) {
    hexInp.dataset.bound = '1';
    hexInp.addEventListener('keydown', e => {
      if (e.key !== 'Enter') return;
      let v = hexInp.value.trim(); if (v && v[0] !== '#') v = '#' + v;
      if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v)) applyAccent(v); else toast('not a valid hex color', 'error');
    });
  }
  const reset = document.getElementById('s-accent-reset');
  if (reset && !reset.dataset.bound) { reset.dataset.bound = '1'; reset.addEventListener('click', () => applyAccent(null)); }
  _markAccent();

  // username (server-synced) — bind once
  const uname = document.getElementById('s-username');
  if (uname && !uname.dataset.bound) {
    uname.dataset.bound = '1';
    fetch('/api/auth/me').then(r => r.json()).then(m => { uname.value = m.username || ''; }).catch(() => {});
    let t; uname.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => _patchSettings({ username: uname.value.trim() }), 400); });
  }
  // change password — bind once
  const pwBtn = document.getElementById('s-pw-save');
  if (pwBtn && !pwBtn.dataset.bound) {
    pwBtn.dataset.bound = '1';
    pwBtn.addEventListener('click', async () => {
      const oldp = document.getElementById('s-pw-old').value;
      const newp = document.getElementById('s-pw-new').value;
      const conf = document.getElementById('s-pw-new2')?.value ?? '';
      if (newp.length < 4) { toast('new password must be at least 4 characters', 'error'); return; }
      if (newp !== conf) { toast("passwords don't match", 'error'); return; }
      try {
        const r = await fetch('/api/auth/change-password', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ old_password: oldp, new_password: newp }) });
        if (!r.ok) { toast((await r.json().catch(() => ({}))).detail || 'change failed', 'error'); return; }
        toast('password changed', 'success');
        document.getElementById('s-pw-old').value = '';
        document.getElementById('s-pw-new').value = '';
        const c = document.getElementById('s-pw-new2'); if (c) c.value = '';
      } catch { toast('failed to change password', 'error'); }
    });
  }

  // password-lock toggle (enable/disable auth from the UI, no file editing) — bind once
  const authSw = document.getElementById('s-auth-enable');
  if (authSw && !authSw.dataset.bound) {
    authSw.dataset.bound = '1';
    fetch('/api/auth/me').then(r => r.json()).then(m => _setSwitch(authSw, !!m.enabled)).catch(() => {});
    authSw.addEventListener('click', async () => {
      const turnOn = !authSw.classList.contains('on');
      // enabling uses the new-password field (to set one if none); disabling uses current
      const password = document.getElementById(turnOn ? 's-pw-new' : 's-pw-old')?.value || '';
      try {
        const r = await fetch('/api/auth/config', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled: turnOn, password }) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { toast(d.detail || 'could not change the lock', 'error'); return; }
        _setSwitch(authSw, d.enabled);
        toast(d.enabled ? 'password lock on' : 'password lock off', 'success');
      } catch { toast('could not change the lock', 'error'); }
    });
  }
}

// (end loadAppearancePane helper)

function _bindSwitchOnce(el, getter, setter) {
  if (!el) return;
  _setSwitch(el, getter());
  if (el.dataset.bound === '1') return;
  el.dataset.bound = '1';
  el.addEventListener('click', () => {
    const next = !el.classList.contains('on');
    _setSwitch(el, next);
    setter(next);
  });
}

function loadShortcutSettings() {
  const shortcuts = loadShortcuts();
  document.querySelectorAll('.shortcut-input').forEach(inp => {
    inp.value = shortcuts[inp.dataset.shortcut] || '';
    inp.placeholder = 'press keys · Esc = none';
    inp.readOnly = true;   // it's a key-capture field, not free text
  });
}

// ── voice pane ────────────────────────────────────────────────────────────────
async function loadVoicePane() {
  try {
    const s = await fetch('/api/settings').then(r => r.json());
    const ttsEl = document.getElementById('tts-select');
    const sttEl = document.getElementById('stt-select');
    if (ttsEl) setDropdownValue(ttsEl, s.tts_provider || 'browser');
    if (sttEl) setDropdownValue(sttEl, s.stt_provider || 'browser');
    const voiceSel = document.getElementById('s-tts-voice');
    if (voiceSel) setDropdownValue(voiceSel, s.tts_voice || 'alloy');
    if (s.openai_api_key) document.getElementById('settings-openai-key').value = s.openai_api_key;
    const langEl = document.getElementById('s-stt-language');
    if (langEl && s.stt_language) langEl.value = s.stt_language;
    setDropdownValue(document.getElementById('s-tts-speed'), String(s.tts_speed ?? 1));
    _bindSwitchOnce(document.getElementById('s-tts-enabled-toggle'),
      () => !!(s.tts_auto_play),
      async on => { await _patchSettings({ tts_auto_play: on }); }
    );
    _updateTtsVoiceRow();
  } catch {}
  _loadMicDevices();
}

// populate the microphone picker. device labels are hidden until mic permission is
// granted, so if they're blank we ask once (then drop the stream) to reveal them.
async function _loadMicDevices() {
  const el = document.getElementById('s-mic-select');
  if (!el || !navigator.mediaDevices?.enumerateDevices) return;
  let mics = (await navigator.mediaDevices.enumerateDevices().catch(() => []))
    .filter(d => d.kind === 'audioinput');
  if (mics.length && !mics.some(m => m.label)) {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      s.getTracks().forEach(t => t.stop());
      mics = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput');
    } catch {}
  }
  const opts = [{ value: '', label: 'default microphone' },
    ...mics.map((m, i) => ({ value: m.deviceId, label: m.label || `microphone ${i + 1}` }))];
  const saved = localStorage.getItem('alles-mic-id') || '';
  populateDropdown(el, opts, opts.some(o => o.value === saved) ? saved : '');
  if (!el.dataset.micBound) {
    el.dataset.micBound = '1';
    el.addEventListener('change', () => localStorage.setItem('alles-mic-id', getDropdownValue(el) || ''));
  }
}

function _updateTtsVoiceRow() {
  const tts = getDropdownValue(document.getElementById('tts-select'));
  const row = document.getElementById('s-tts-voice-row');
  if (row) row.style.display = tts === 'openai' ? 'flex' : 'none';
}

async function saveVoiceSettings() {
  const patch = {
    tts_provider: getDropdownValue(document.getElementById('tts-select')) || 'browser',
    stt_provider: getDropdownValue(document.getElementById('stt-select')) || 'browser',
    tts_voice:    getDropdownValue(document.getElementById('s-tts-voice')) || 'alloy',
    tts_speed:    parseFloat(document.getElementById('s-tts-speed')?.value || '1.0'),
    stt_language: document.getElementById('s-stt-language')?.value.trim() || '',
  };
  const key = document.getElementById('settings-openai-key')?.value.trim();
  if (key) patch.openai_api_key = key;
  await _patchSettings(patch);
  toast('voice settings saved', 'success');
}

// ── personas ──────────────────────────────────────────────────────────────────
let _personaCache = [];
let _editingPersona = null;

// ── temperature: btop-style block meter (null = auto/provider default) ──
// 0..2 in hard 0.1 steps. each lit cell is coloured by its POSITION on the scale,
// in discrete bands (cold blue → hot red) — no smooth blend, snaps to a cell.
const TEMP_CELLS = 20;
const TEMP_STEP  = 0.1;
const TEMP_RAMP  = ['#3b82f6','#6366f1','#8b5cf6','#a855f7','#d946ef','#f43f5e','#ef4444'];
let _tempVal = 0.7, _tempOn = false;

// snap to nearest 0.1, rounded clean so we don't store float cruft like 0.70000001
const _tempSnap = v => Math.max(0, Math.min(2, Math.round(v * 10) / 10));
// colour by cell index — floor into the ramp so neighbouring cells share a band
const _tempCellColor = i => TEMP_RAMP[Math.min(TEMP_RAMP.length - 1, Math.floor(i / TEMP_CELLS * TEMP_RAMP.length))];

function _renderTempBar() {
  const bar = document.getElementById('persona-temp');
  const lbl = document.getElementById('persona-temp-val');
  if (!bar) return;
  bar.classList.toggle('is-auto', !_tempOn);
  bar.setAttribute('aria-valuenow', _tempOn ? _tempVal.toFixed(1) : '');
  const lit = Math.round(_tempVal / TEMP_STEP);   // cells filled, 0..20
  let html = '';
  for (let i = 0; i < TEMP_CELLS; i++) {
    if (i < lit) {
      const c = _tempCellColor(i);
      html += `<span class="tc f${i === lit - 1 ? ' edge' : ''}" style="background:${c}"></span>`;
    } else {
      html += '<span class="tc"></span>';
    }
  }
  bar.innerHTML = html;
  if (lbl) {
    lbl.textContent = _tempOn ? _tempVal.toFixed(1) : 'auto';
    lbl.classList.toggle('muted', !_tempOn);
    lbl.style.color = _tempOn ? _tempCellColor(Math.max(0, lit - 1)) : '';
  }
}

function _setPersonaTemp(val) {
  _tempOn = val != null;
  if (_tempOn) _tempVal = _tempSnap(val);
  document.getElementById('persona-temp-pin')?.classList.toggle('on', _tempOn);
  _renderTempBar();
}

// pointer x along the bar → snapped temperature
function _tempFromEvent(e) {
  const r = document.getElementById('persona-temp').getBoundingClientRect();
  const f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  return _tempSnap(f * 2);
}
// click or drag a cell → pins and sets. pointermove only counts while held down.
function _onTempPointer(e) {
  if (e.type === 'pointermove' && e.buttons !== 1) return;
  e.preventDefault();
  if (e.type === 'pointerdown') e.currentTarget.setPointerCapture?.(e.pointerId);
  _tempOn = true;
  _tempVal = _tempFromEvent(e);
  document.getElementById('persona-temp-pin')?.classList.add('on');
  _renderTempBar();
}

function _setPersonaMode(val) {
  document.querySelectorAll('#persona-mode .seg-opt').forEach(o =>
    o.classList.toggle('active', (o.dataset.val || '') === (val || '')));
}
function _getPersonaMode() {
  return document.querySelector('#persona-mode .seg-opt.active')?.dataset.val || '';
}

// curated persona accent palette. deliberately NO green / red — those carry "right vs
// wrong" (success/error) meaning across the app, so a green/red accent would read as a
// state signal, not a persona's identity. anything added here later should hold that line.
const PERSONA_ACCENTS = [
  ['#818cf8','indigo'], ['#a78bfa','violet'], ['#c084fc','purple'], ['#60a5fa','blue'],
  ['#38bdf8','sky'],    ['#22d3ee','cyan'],   ['#fbbf24','amber'],  ['#fb923c','orange'],
  ['#f472b6','pink'],   ['#e879f9','fuchsia'],['#94a3b8','slate'],
];
let _personaAccent = '';

function _buildPersonaAccents() {
  const box = document.getElementById('persona-accent');
  if (!box || box.dataset.built) return;
  box.dataset.built = '1';
  box.innerHTML =
    '<button type="button" class="pa-swatch pa-none" data-hex="" title="no override — use your theme accent">default</button>' +
    PERSONA_ACCENTS.map(([hex, name]) =>
      `<button type="button" class="pa-swatch" data-hex="${hex}" title="${name}" style="background:${hex}"></button>`).join('');
  box.querySelectorAll('.pa-swatch').forEach(s => s.addEventListener('click', () => {
    _setPersonaAccent(s.dataset.hex);
    // live preview the re-theme as you pick (reset/save restores the real active accent)
    document.documentElement.style.setProperty('--accent', s.dataset.hex || (localStorage.getItem('aide-accent') || '#818cf8'));
  }));
}

function _setPersonaAccent(hex) {
  _personaAccent = hex || '';
  document.querySelectorAll('#persona-accent .pa-swatch').forEach(s =>
    s.classList.toggle('active', (s.dataset.hex || '') === _personaAccent));
}
function _getPersonaAccent() { return _personaAccent; }

function _togglePersonaTempPin() {
  const on = !document.getElementById('persona-temp-pin').classList.contains('on');
  _setPersonaTemp(on ? (_tempVal || 0.7) : null);
}

function _fillPersonaModels(selected = '') {
  const sel = document.getElementById('persona-model');
  if (!sel) return;
  const eps = window._endpoints || [];
  const opts = [{ value: '', label: "— use chat's model" }];
  for (const ep of eps) {
    for (const m of (ep.models || [])) opts.push({ value: m, label: m });
  }
  // keep a pinned model that isn't in any endpoint's list (e.g. a renamed/removed one)
  if (selected && !eps.some(ep => (ep.models || []).includes(selected)))
    opts.push({ value: selected, label: `${selected} (not in any endpoint)` });
  populateDropdown(sel, opts, selected || '');   // custom dropdown — no native <select>
}

export async function loadPersonas() {
  const el = document.getElementById('persona-list');
  if (!el) return;
  _fillPersonaModels(document.getElementById('persona-model')?.value || '');
  _buildPersonaAccents();
  _personaCache = await fetch('/api/personas').then(r => r.json()).catch(() => []);
  if (!_personaCache.length) { el.innerHTML = '<div class="settings-row-empty">no personas yet</div>'; return; }
  el.innerHTML = _personaCache.map(p => {
    const prev = (p.system_prompt || '').replace(/\s+/g, ' ').trim();
    return `
    <div class="settings-list-row persona-row${_editingPersona === p.id ? ' editing' : ''}" data-id="${p.id}" onclick="window._editPersona('${p.id}')">
      <span class="row-name">${_esc(p.name)}${p.is_default ? ' <span class="row-tag">default</span>' : ''}</span>
      <span class="row-meta">${_esc(prev.slice(0, 60))}${prev.length > 60 ? '…' : ''}</span>
      <button class="act-btn" data-id="${p.id}" onclick="event.stopPropagation();window._dupPersona('${p.id}')">duplicate</button>
      <button class="act-btn" data-id="${p.id}" onclick="event.stopPropagation();window._rmPersona(this)">remove</button>
    </div>`;
  }).join('');
}

window._editPersona = id => {
  const p = _personaCache.find(x => x.id === id);
  if (!p) return;
  _editingPersona = id;
  document.getElementById('persona-name').value   = p.name || '';
  document.getElementById('persona-prompt').value = p.system_prompt || '';
  const initEl = document.getElementById('persona-initial'); if (initEl) initEl.value = p.initial_message || '';
  _fillPersonaModels(p.model || '');
  _setPersonaTemp(p.temperature == null ? null : p.temperature);
  _setPersonaMode(p.default_mode || '');
  _buildPersonaAccents(); _setPersonaAccent(p.accent || '');
  document.getElementById('persona-default')?.classList.toggle('on', !!p.is_default);
  const title = document.getElementById('persona-form-title');
  if (title) { title.textContent = `editing "${p.name}"`; title.hidden = false; }
  document.getElementById('persona-add-btn').textContent = 'save changes';
  document.getElementById('persona-cancel-btn').hidden = false;
  const extra = document.getElementById('persona-extra');
  if (extra) extra.hidden = false;   // 10d — knowledge files + share for a saved persona
  _loadPersonaDocs(id);
  loadPersonas();   // re-render so the active row highlights
  document.getElementById('persona-prompt').focus();
};

// 10d — persona knowledge files + share
async function _loadPersonaDocs(pid) {
  const box = document.getElementById('persona-docs');
  if (!box) return;
  let docs;
  try { docs = await fetch(`/api/personas/${pid}/docs`).then(r => r.json()); }
  catch { box.innerHTML = ''; return; }
  box.innerHTML = docs.length
    ? docs.map(d => `<div class="persona-doc-row"><span>📄 ${_esc(d.title)}</span>` +
        `<button class="act-btn" data-id="${_escAttr(d.id)}">remove</button></div>`).join('')
    : '<div class="settings-row-empty">no knowledge files yet</div>';
  box.querySelectorAll('.act-btn').forEach(b => b.onclick = async () => {
    await fetch(`/api/personas/${pid}/docs/${b.dataset.id}`, { method: 'DELETE' });
    _loadPersonaDocs(pid);
  });
}

async function _addPersonaDoc() {
  if (!_editingPersona) return;
  const title = document.getElementById('persona-doc-title').value.trim();
  const content = document.getElementById('persona-doc-content').value.trim();
  if (!content) { toast('paste some text first', 'error'); return; }
  await fetch(`/api/personas/${_editingPersona}/docs`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ title: title || 'untitled', content }),
  });
  document.getElementById('persona-doc-title').value = '';
  document.getElementById('persona-doc-content').value = '';
  toast('knowledge file added', 'success');
  _loadPersonaDocs(_editingPersona);
}

async function _sharePersona() {
  if (!_editingPersona) return;
  try {
    const r = await fetch(`/api/personas/${_editingPersona}/share`, { method: 'POST' }).then(x => x.json());
    const url = location.origin + r.url;
    try { await navigator.clipboard.writeText(url); toast('share link copied', 'success'); }
    catch { toast(url, ''); }
  } catch { toast('share failed', 'error'); }
}

function _resetPersonaForm() {
  _editingPersona = null;
  ['persona-name','persona-prompt','persona-initial'].forEach(id => { const e = document.getElementById(id); if (e) e.value = ''; });
  _fillPersonaModels('');
  _setPersonaTemp(null);
  _setPersonaMode('');
  _setPersonaAccent('');
  document.getElementById('persona-default')?.classList.remove('on');
  window._refreshPersonaBtn?.();   // restore the live accent to the active session's persona
  const title = document.getElementById('persona-form-title'); if (title) title.hidden = true;
  document.getElementById('persona-add-btn').textContent = 'add persona';
  document.getElementById('persona-cancel-btn').hidden = true;
  const extra = document.getElementById('persona-extra'); if (extra) extra.hidden = true;
  loadPersonas();
}

window._rmPersona = async btn => {
  await fetch(`/api/personas/${btn.dataset.id}`, { method: 'DELETE' });
  if (_editingPersona === btn.dataset.id) _resetPersonaForm();
  else loadPersonas();
  window._refreshPersonaBtn?.();
};

window._dupPersona = async id => {
  const r = await fetch(`/api/personas/${id}/duplicate`, { method: 'POST' });
  if (r.ok) { toast('duplicated', 'success'); loadPersonas(); window._refreshPersonaBtn?.(); }
};

async function addPersona() {
  const name   = document.getElementById('persona-name').value.trim();
  const prompt = document.getElementById('persona-prompt').value.trim();
  const initial_message = document.getElementById('persona-initial')?.value.trim() || '';
  const model  = document.getElementById('persona-model')?.value || '';
  const temperature = _tempOn ? _tempVal : null;
  const is_default = !!document.getElementById('persona-default')?.classList.contains('on');
  const default_mode = _getPersonaMode();
  const accent = _getPersonaAccent();
  if (!name) { toast('name required', 'error'); return; }
  const payload = { name, system_prompt: prompt, initial_message, model, temperature, default_mode, accent, is_default };
  if (_editingPersona) {
    await fetch(`/api/personas/${_editingPersona}`, { method: 'PATCH', headers: {'content-type':'application/json'},
      body: JSON.stringify(payload) });
    toast('persona updated', 'success');
  } else {
    await fetch('/api/personas', { method: 'POST', headers: {'content-type':'application/json'},
      body: JSON.stringify(payload) });
    toast('persona added', 'success');
  }
  _resetPersonaForm();
  window._refreshPersonaBtn?.();
}

// ── cookbook ──────────────────────────────────────────────────────────────────
export async function loadCookbook() {
  const el = document.getElementById('cookbook-list');
  if (!el) return;
  const entries = await fetch('/api/cookbook').then(r => r.json()).catch(() => []);
  if (!entries.length) { el.innerHTML = '<div class="settings-row-empty">no commands — type / in chat to use</div>'; return; }
  el.innerHTML = entries.map(e => `
    <div class="settings-list-row">
      <span class="row-name" style="color:var(--accent)">/${_esc(e.name)}</span>
      <span class="row-meta">${_esc(e.description || e.prompt.slice(0,40))}</span>
      <button class="act-btn" data-id="${e.id}" onclick="window._rmCookbook(this)">remove</button>
    </div>`).join('');
}

window._rmCookbook = async btn => {
  await fetch(`/api/cookbook/${btn.dataset.id}`, { method: 'DELETE' });
  loadCookbook();
};

async function addCookbookEntry() {
  const name   = document.getElementById('cookbook-name').value.trim();
  const desc   = document.getElementById('cookbook-desc').value.trim();
  const prompt = document.getElementById('cookbook-prompt').value.trim();
  if (!name || !prompt) { toast('name + prompt required', 'error'); return; }
  await fetch('/api/cookbook', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, description: desc, prompt }) });
  ['cookbook-name','cookbook-desc','cookbook-prompt'].forEach(id => document.getElementById(id).value = '');
  toast('added', 'success');
  loadCookbook();
}

// (session templates were merged into personas — a persona's "starter message" now
//  does what a template's initial message did; see openPersonaPicker in app.js)

// ── agent + mcp servers ───────────────────────────────────────────────────────
async function loadAgentStatus() {
  const grid = document.getElementById('agent-status-grid');
  const list = document.getElementById('agent-tool-list');
  const runsEl = document.getElementById('agent-run-list');
  if (!grid || !list) return;
  try {
    const [s, runs] = await Promise.all([
      fetch('/api/agent/status').then(r => r.json()),
      fetch('/api/agent/runs?limit=5').then(r => r.json()).catch(() => []),
    ]);
    const opencode = s.opencode?.installed
      ? 'installed'
      : (s.opencode?.npx_fallback ? 'npx fallback' : 'missing');
    grid.innerHTML = `
      <div><span>tools</span><strong>${s.tool_count || 0}</strong></div>
      <div><span>opencode</span><strong>${_esc(opencode)}</strong></div>
      <div><span>mcp</span><strong>${s.mcp?.connected_tool_count || 0}</strong></div>
      <div><span>skills</span><strong>${s.skills?.count || 0}</strong></div>
      <div><span>docker</span><strong>${s.sandbox?.docker ? 'yes' : 'no'}</strong></div>
      <div><span>pyautogui</span><strong>${s.computer_use?.pyautogui ? 'yes' : 'no'}</strong></div>
      <div><span>connections</span><strong>${(s.connections || []).join(', ') || 'none'}</strong></div>
    `;
    list.innerHTML = (s.tools || []).map(t => `<span>${_esc(t)}</span>`).join('');

    // capability toggles (backend settings)
    const cfg = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
    _bindSwitchOnce(document.getElementById('s-agent-ctx-toggle'),
      () => cfg.agent_context_files !== false, v => _patchSetting('agent_context_files', v));
    _bindSwitchOnce(document.getElementById('s-agent-sandbox-toggle'),
      () => !!cfg.agent_sandbox, v => _patchSetting('agent_sandbox', v));
    _bindSwitchOnce(document.getElementById('s-agent-computer-toggle'),
      () => !!cfg.agent_computer_use, v => _patchSetting('agent_computer_use', v));
    _bindSwitchOnce(document.getElementById('s-agent-subagents-toggle'),
      () => cfg.agent_subagents !== false, v => _patchSetting('agent_subagents', v));

    if (runsEl) {
      runsEl.innerHTML = Array.isArray(runs) && runs.length
        ? runs.map(r => `
          <div class="agent-run-row">
            <span>${_esc(r.status || 'unknown')}</span>
            <strong>${_esc((r.model || '').split('/').pop() || 'agent')}</strong>
            <em>${_esc((r.updated_at || '').replace('T', ' ').slice(0, 19))}</em>
          </div>
        `).join('')
        : '<div class="settings-row-empty">no agent runs yet</div>';
    }
  } catch {
    grid.innerHTML = '<div class="settings-row-empty">agent status unavailable</div>';
    list.innerHTML = '';
    if (runsEl) runsEl.innerHTML = '';
  }
}

export async function loadMcpServers() {
  const el = document.getElementById('mcp-server-list');
  if (!el) return;
  _loadMcpPresets();  // 10d — render presets regardless of how many servers exist
  try {
    const servers = await fetch('/api/mcp/servers').then(r => r.json());
    if (!servers.length) { el.innerHTML = '<div class="settings-row-empty">no servers</div>'; return; }
    el.innerHTML = servers.map(s => `
      <div class="settings-list-row">
        <span class="status-dot" style="background:${s.connected ? 'var(--green)' : 'var(--faint)'}"></span>
        <span class="row-name">${_esc(s.name)}</span>
        <span class="row-meta">${s.tools.length} tools</span>
        <button class="act-btn" data-id="${s.id}" onclick="window._rmMcp(this)">remove</button>
      </div>`).join('');
  } catch { el.innerHTML = '<div class="settings-row-empty">failed to load</div>'; }
}

// 11a — macOS native integration status (available only on the Mac mini)
async function loadMacosStatus() {
  const box = document.getElementById('macos-status');
  if (!box) return;
  let cap;
  try { cap = await fetch('/api/macos/status').then(r => r.json()); }
  catch { box.innerHTML = '<div class="settings-row-empty">status unavailable</div>'; return; }
  const dot = ok => `<span class="status-dot" style="background:${ok ? 'var(--green)' : 'var(--faint)'}"></span>`;
  const row = (label, ok) => `<div class="macos-row">${dot(ok)}<span>${label}</span></div>`;
  if (!cap.available) {
    box.innerHTML = `<div class="settings-row-empty">unavailable on ${_esc(cap.platform)} — `
      + 'macOS native integration runs on the Mac mini.</div>';
    return;
  }
  box.innerHTML = '<div class="macos-avail">✓ available</div>'
    + row('Keychain', cap.keychain)
    + row('Calendar / Reminders (EventKit)', cap.eventkit)
    + row('Photos (PhotoKit)', cap.photokit)
    + row('iCloud Drive', cap.icloud);
}

// 10d — one-click connector presets
async function _loadMcpPresets() {
  const box = document.getElementById('mcp-presets');
  if (!box) return;
  let presets;
  try { presets = await fetch('/api/mcp/presets').then(r => r.json()); }
  catch { box.innerHTML = ''; return; }
  box.innerHTML = presets.map(p =>
    `<button class="btn mcp-preset" data-id="${_escAttr(p.id)}" title="${_escAttr(p.description)}">+ ${_esc(p.name)}</button>`
  ).join('');
  box.querySelectorAll('.mcp-preset').forEach(b => b.onclick = () => _addMcpPreset(b.dataset.id));
}

async function _addMcpPreset(id) {
  toast('adding connector…');
  try {
    const r = await fetch(`/api/mcp/presets/${encodeURIComponent(id)}`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ params: {} }),
    });
    if (!r.ok) throw new Error(r.status);
    toast('connector added — edit its args if it needs a path/key', 'success');
    loadMcpServers();
  } catch { toast('could not add connector', 'error'); }
}

window._rmMcp = async btn => {
  await fetch(`/api/mcp/servers/${btn.dataset.id}`, { method: 'DELETE' });
  loadMcpServers();
};

// ── connections (github etc) ────────────────────────────────────────────────
export async function loadConnections() {
  const el = document.getElementById('conn-list');
  if (!el) return;
  // custom-service field toggle (bind once)
  const sel = document.getElementById('conn-service');
  if (sel && !sel.dataset.bound) {
    sel.dataset.bound = '1';
    sel.addEventListener('change', () => {
      document.getElementById('conn-custom-row').style.display = sel.value === 'custom' ? '' : 'none';
    });
    document.getElementById('conn-add-btn')?.addEventListener('click', addConnection);
  }
  try {
    const conns = await fetch('/api/connections').then(r => r.json());
    if (!conns.length) { el.innerHTML = '<div class="settings-row-empty">nothing connected</div>'; return; }
    el.innerHTML = conns.map(c => `
      <div class="settings-list-row">
        <span class="status-dot" style="background:${c.connected ? 'var(--green)' : 'var(--faint)'}"></span>
        <span class="row-name">${_esc(c.service)}</span>
        <span class="row-meta">${_esc(c.token_masked || '')}</span>
        <button class="act-btn" data-svc="${_esc(c.service)}" onclick="window._testConn(this)">test</button>
        <button class="act-btn" data-id="${c.id}" onclick="window._rmConn(this)">remove</button>
      </div>`).join('');
  } catch { el.innerHTML = '<div class="settings-row-empty">failed to load</div>'; }
}

async function addConnection() {
  const sel = document.getElementById('conn-service');
  let service = sel.value;
  if (service === 'custom') service = document.getElementById('conn-custom').value.trim();
  const token = document.getElementById('conn-token').value.trim();
  if (!service) { toast('pick a service', 'error'); return; }
  if (!token) { toast('token required', 'error'); return; }
  const r = await fetch('/api/connections', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ service, token }),
  });
  if (r.ok) { toast(`${service} connected`, 'success'); document.getElementById('conn-token').value = ''; loadConnections(); }
  else toast('connect failed', 'error');
}

window._rmConn = async btn => {
  await fetch(`/api/connections/${btn.dataset.id}`, { method: 'DELETE' });
  loadConnections();
};

window._testConn = async btn => {
  btn.textContent = '…';
  try {
    const r = await fetch(`/api/connections/${btn.dataset.svc}/test`).then(x => x.json());
    if (r.ok) toast(`${btn.dataset.svc} ok${r.user ? ' — ' + r.user : ''}`, 'success');
    else toast(r.error || 'test failed', 'error');
  } catch { toast('test failed', 'error'); }
  btn.textContent = 'test';
};

async function addMcpServer() {
  const name    = document.getElementById('mcp-name').value.trim();
  const command = document.getElementById('mcp-command').value.trim();
  if (!name || !command) { toast('name + command required', 'error'); return; }
  const parts = command.match(/(?:[^\s"]+|"[^"]*")+/g) || [];
  const cmd = parts[0], args = parts.slice(1).map(a => a.replace(/^"|"$/g,''));
  await fetch('/api/mcp/servers', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, transport: 'stdio', command: cmd, args }) });
  document.getElementById('mcp-name').value = '';
  document.getElementById('mcp-command').value = '';
  toast('mcp server added', 'success');
  loadMcpServers();
}

// ── api tokens ────────────────────────────────────────────────────────────────
async function loadTokens() {
  const el = document.getElementById('token-list');
  if (!el) return;
  const tokens = await fetch('/api/tokens').then(r => r.json()).catch(() => []);
  if (!tokens.length) { el.innerHTML = '<div class="settings-row-empty">no tokens</div>'; return; }
  el.innerHTML = tokens.map(t => `
    <div class="settings-list-row">
      <span class="row-name" style="font-family:monospace;font-size:0.72rem">${t.prefix}…</span>
      <span class="row-meta">${_esc(t.name)}</span>
      <span class="row-meta">${t.last_used_at ? 'used ' + new Date(t.last_used_at).toLocaleDateString() : 'never used'}</span>
      <button class="act-btn" data-id="${t.id}" onclick="window._rmToken(this)">revoke</button>
    </div>`).join('');
}

window._rmToken = async btn => {
  await fetch(`/api/tokens/${btn.dataset.id}`, { method: 'DELETE' });
  loadTokens();
};

async function generateToken() {
  const name = document.getElementById('token-name').value.trim();
  if (!name) { toast('name required', 'error'); return; }
  const r = await fetch('/api/tokens', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name }) });
  const data = await r.json();
  document.getElementById('token-name').value = '';
  const reveal = document.getElementById('token-reveal');
  reveal.style.display = 'block';
  reveal.textContent = data.token;
  reveal.title = 'click to copy';
  reveal.onclick = () => {
    navigator.clipboard.writeText(data.token).then(() => toast('token copied', 'success'));
  };
  toast('token generated — copy it now, shown once', 'success');
  loadTokens();
}

// ── webhooks ──────────────────────────────────────────────────────────────────
async function loadWebhooks() {
  const el = document.getElementById('webhook-list');
  if (!el) return;
  const hooks = await fetch('/api/webhooks').then(r => r.json()).catch(() => []);
  if (!hooks.length) { el.innerHTML = '<div class="settings-row-empty">no webhooks</div>'; return; }
  el.innerHTML = hooks.map(h => {
    const st = h.last_status === 'ok' ? ' · ✓ ok'
      : h.last_status ? ` · ✕ ${_esc(h.last_error || h.last_status)}` : '';
    return `
    <div class="settings-list-row">
      <span class="status-dot" style="background:${h.enabled ? 'var(--green)' : 'var(--faint)'}"></span>
      <span class="row-name">${_esc(h.name)}</span>
      <span class="row-meta">${h.events.join(', ')}${st}</span>
      ${h.secret ? `<code class="wh-secret" title="HMAC-SHA256 signing key — verify the X-Alles-Signature header with this" onclick="navigator.clipboard.writeText('${_esc(h.secret)}');window._toastCopied&&window._toastCopied()" style="font-size:0.6rem;color:var(--muted);max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer">${_esc(h.secret)}</code>` : ''}
      <button class="act-btn" data-id="${h.id}" onclick="window._testWebhook(this)">test</button>
      <button class="act-btn" data-id="${h.id}" onclick="window._rmWebhook(this)">remove</button>
    </div>`;
  }).join('');
}

window._testWebhook = async btn => {
  btn.disabled = true; const old = btn.textContent; btn.textContent = '…';
  try {
    const r = await fetch(`/api/webhooks/${btn.dataset.id}/test`, { method: 'POST' }).then(r => r.json());
    toast(r.status === 'ok' ? 'webhook delivered ✓' : `failed: ${r.error || r.status}`, r.status === 'ok' ? 'success' : 'error');
  } catch { toast('test failed', 'error'); }
  btn.disabled = false; btn.textContent = old;
  loadWebhooks();
};

window._rmWebhook = async btn => {
  await fetch(`/api/webhooks/${btn.dataset.id}`, { method: 'DELETE' });
  loadWebhooks();
};

async function addWebhook() {
  const name = document.getElementById('wh-name').value.trim();
  const url  = document.getElementById('wh-url').value.trim();
  if (!name || !url) { toast('name + url required', 'error'); return; }
  await fetch('/api/webhooks', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, url, events: ['message'] }) });
  ['wh-name','wh-url'].forEach(id => document.getElementById(id).value = '');
  toast('webhook added', 'success');
  loadWebhooks();
}

// ── recall pane ───────────────────────────────────────────────────────────────
async function loadRecallPane() {
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const keys = ['enabled', 'mail', 'note', 'journal', 'contact', 'read', 'book'];
  for (const k of keys) {
    const el = document.getElementById('s-pidx-' + k);
    if (el) _bindSwitch(el, () => s['pidx_' + k] !== false, v => _patchSetting('pidx_' + k, v));
  }
  const stats = await fetch('/api/recall/stats').then(r => r.json()).catch(() => null);
  const el = document.getElementById('s-pidx-stats');
  if (el && stats) {
    const total = Object.values(stats.by_kind || {}).reduce((a, b) => a + b, 0);
    el.textContent = `${total} chunks indexed · ${stats.mail_pending || 0} mail bodies pending`;
  }
  const rb = document.getElementById('s-pidx-reindex');
  if (rb && !rb.dataset.bound) { rb.dataset.bound = '1'; rb.addEventListener('click', async () => { rb.disabled = true; await fetch('/api/recall/reindex', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }); rb.disabled = false; loadRecallPane(); }); }
  const cb = document.getElementById('s-pidx-clear');
  if (cb && !cb.dataset.bound) { cb.dataset.bound = '1'; cb.addEventListener('click', async () => { if (!await _dlgConfirm('clear the recall index?')) return; await fetch('/api/recall/clear', { method: 'POST' }); loadRecallPane(); }); }
}

async function loadProactivePane() {
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  // bind a switch once (visual state refreshed every open), guard against listener leak
  const sw = (id, key, defOn) => {
    const el = document.getElementById(id);
    if (!el) return;
    _setSwitch(el, s[key] === undefined ? defOn : !!s[key]);
    if (el.dataset.bound) return;
    el.dataset.bound = '1';
    el.addEventListener('click', () => {
      const next = !el.classList.contains('on');
      _setSwitch(el, next);
      _patchSetting(key, next);
    });
  };
  sw('s-prox-enabled', 'pidx_proactive_enabled', false);
  sw('s-prox-cat-task', 'pidx_proactive_cat_task', true);
  sw('s-prox-cat-sub', 'pidx_proactive_cat_sub', true);
  sw('s-prox-cat-event', 'pidx_proactive_cat_event', true);
  sw('s-prox-cat-habit', 'pidx_proactive_cat_habit', true);
  sw('s-prox-cat-read', 'pidx_proactive_cat_read', true);
  sw('s-prox-cat-health', 'pidx_proactive_cat_health', true);
  sw('s-prox-cat-money', 'pidx_proactive_cat_money', true);
  sw('s-prox-cat-mail', 'pidx_proactive_cat_mail', true);
  sw('s-prox-cat-journal', 'pidx_proactive_cat_journal', false);

  const num = (id, key) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (s[key] !== undefined) el.value = s[key];
    if (el.dataset.bound) return;
    el.dataset.bound = '1';
    el.addEventListener('change', () => {
      const v = parseInt(el.value, 10);
      if (!isNaN(v)) _patchSetting(key, v);
    });
  };
  num('s-prox-hours', 'pidx_proactive_every_hours');
  num('s-prox-qstart', 'pidx_proactive_quiet_start');
  num('s-prox-qend', 'pidx_proactive_quiet_end');

  // channel is a string ("push" | "inapp"), drive it from one switch
  const pushEl = document.getElementById('s-prox-push');
  if (pushEl) {
    _setSwitch(pushEl, s.pidx_proactive_channel === 'push');
    if (!pushEl.dataset.bound) {
      pushEl.dataset.bound = '1';
      pushEl.addEventListener('click', () => {
        const next = !pushEl.classList.contains('on');
        _setSwitch(pushEl, next);
        _patchSetting('pidx_proactive_channel', next ? 'push' : 'inapp');
      });
    }
  }

  const run = document.getElementById('s-prox-run');
  const status = document.getElementById('s-prox-status');
  if (run && !run.dataset.bound) {
    run.dataset.bound = '1';
    run.addEventListener('click', async () => {
      run.disabled = true;
      if (status) status.textContent = 'thinking...';
      try {
        const r = await fetch('/api/proactive/run', { method: 'POST' }).then(r => r.json());
        if (status) status.textContent = r.ran
          ? `done - ${r.written} new card${r.written === 1 ? '' : 's'} from ${r.signals} signal${r.signals === 1 ? '' : 's'}`
          : `nothing to show (${r.reason})`;
      } catch { if (status) status.textContent = 'run failed'; }
      run.disabled = false;
    });
  }
}

// ── helpers ───────────────────────────────────────────────────────────────────
async function _patchSettings(patch) {
  await fetch('/api/settings', {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

async function _patchSetting(key, val) {
  await _patchSettings({ [key]: val });
}

function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _escAttr(s = '') {
  return _esc(s).replace(/"/g,'&quot;');
}

// ── permission rules: per-tool/path allow|ask|deny, layered over the agent mode ──
let _permRules = [];
let _permWired = false;
async function loadPermRules() {
  try { _permRules = (await fetch('/api/settings').then(r => r.json())).permission_rules || []; }
  catch { _permRules = []; }
  const el = document.getElementById('perm-rules-list');
  if (el) {
    el.innerHTML = _permRules.length
      ? _permRules.map((r, i) => `
        <div class="perm-rule-row">
          <span class="perm-rule-act perm-${_esc(r.action)}">${_esc(r.action)}</span>
          <span class="perm-rule-tool">${_esc(r.tool || '*')}</span>
          ${r.path ? `<span class="perm-rule-path">${_esc(r.path)}</span>` : ''}
          <button class="perm-rule-del" data-i="${i}" title="remove">✕</button>
        </div>`).join('')
      : '<div style="font-size:0.72rem;color:var(--muted)">no rules — the agent follows the mode for everything</div>';
    el.querySelectorAll('.perm-rule-del').forEach(b => b.onclick = () => _delPermRule(+b.dataset.i));
  }
  if (!_permWired) {
    _permWired = true;
    document.getElementById('perm-rule-add-btn')?.addEventListener('click', _addPermRule);
  }
}
async function _addPermRule() {
  const tool = document.getElementById('perm-rule-tool').value.trim();
  const path = document.getElementById('perm-rule-path').value.trim();
  const action = getDropdownValue(document.getElementById('perm-rule-action')) || 'ask';
  if (!tool) { toast('tool pattern required (use * for any)', 'error'); return; }
  _permRules.push({ tool, path, action });
  await _patchSettings({ permission_rules: _permRules });
  document.getElementById('perm-rule-tool').value = '';
  document.getElementById('perm-rule-path').value = '';
  toast('rule added', 'success');
  loadPermRules();
}
async function _delPermRule(i) {
  _permRules.splice(i, 1);
  await _patchSettings({ permission_rules: _permRules });
  loadPermRules();
}

// ── rules pane: personal automations ──────────────────────────────────────────
let _ruleOpts = null;
let _rulesWired = false;
let _editingRule = null;   // rule id being edited (null = adding a new one)

// one-click starting points — prefill the form with a sensible rule to tweak
const _RULE_PRESETS = [
  { label: '☀ morning digest', trigger: 'daily_at', trigger_arg: '08:00', action: 'push_digest', action_arg: '', name: 'morning digest' },
  { label: '📥 important email → task', trigger: 'mail_from', trigger_arg: '', action: 'create_task', action_arg: '{subject} — from {from}', name: '' },
  { label: '💳 renewal heads-up', trigger: 'sub_renewing', trigger_arg: '3', action: 'push', action_arg: '{name} renews in 3 days', name: 'renewal reminder' },
  { label: '📅 upcoming day', trigger: 'day_event_near', trigger_arg: '7', action: 'push', action_arg: '{name} is in a week', name: '' },
];

async function loadRulesPane() {
  if (!_ruleOpts) {
    try { _ruleOpts = await fetch('/api/automations/options').then(r => r.json()); }
    catch { _ruleOpts = { triggers: [], actions: [] }; }
  }
  const trigEl = document.getElementById('rule-trigger');
  const actEl = document.getElementById('rule-action');
  if (trigEl && !trigEl.dataset.populated) {
    populateDropdown(trigEl, _ruleOpts.triggers.map(t => ({ value: t.value, label: t.label })));
    populateDropdown(actEl, _ruleOpts.actions.map(a => ({ value: a.value, label: a.label })));
    trigEl.dataset.populated = '1';
    const syncPh = () => {
      const t = _ruleOpts.triggers.find(x => x.value === trigEl.dataset.value);
      const a = _ruleOpts.actions.find(x => x.value === actEl.dataset.value);
      document.getElementById('rule-trigger-arg').placeholder = t?.arg || '…';
      const actArg = document.getElementById('rule-action-arg');
      actArg.placeholder = a?.arg || '…';
      actArg.style.display = actEl.dataset.value === 'push_digest' ? 'none' : '';
    };
    trigEl.addEventListener('change', syncPh);
    actEl.addEventListener('change', syncPh);
    syncPh();
  }
  if (!_rulesWired) {
    _rulesWired = true;
    document.getElementById('rule-add-btn')?.addEventListener('click', _addRule);
    document.getElementById('rule-cancel-btn')?.addEventListener('click', _resetRuleForm);
    _renderRulePresets();
  }
  _renderRules();
}

function _renderRulePresets() {
  const box = document.getElementById('rule-presets');
  if (!box) return;
  box.innerHTML = '<span class="rule-presets-label">quick start:</span>' +
    _RULE_PRESETS.map((p, i) => `<button class="rule-preset" data-i="${i}">${p.label}</button>`).join('');
  box.querySelectorAll('.rule-preset').forEach(b =>
    b.addEventListener('click', () => _fillRuleForm(_RULE_PRESETS[+b.dataset.i], null)));
}

// load a rule (or preset) into the form. id=null → adding/preset; id set → editing
function _fillRuleForm(r, id) {
  _editingRule = id;
  setDropdownValue(document.getElementById('rule-trigger'), r.trigger);
  setDropdownValue(document.getElementById('rule-action'), r.action);
  document.getElementById('rule-trigger-arg').value = r.trigger_arg || '';
  document.getElementById('rule-action-arg').value = r.action_arg || '';
  document.getElementById('rule-name').value = r.name || '';
  document.getElementById('rule-trigger')?.dispatchEvent(new Event('change'));   // sync placeholders
  document.getElementById('rule-action')?.dispatchEvent(new Event('change'));
  document.getElementById('rule-add-btn').textContent = id ? 'save changes' : 'add rule';
  document.getElementById('rule-cancel-btn').style.display = id ? '' : 'none';
}

function _resetRuleForm() {
  _editingRule = null;
  ['rule-trigger-arg', 'rule-action-arg', 'rule-name'].forEach(id => { const e = document.getElementById(id); if (e) e.value = ''; });
  document.getElementById('rule-add-btn').textContent = 'add rule';
  document.getElementById('rule-cancel-btn').style.display = 'none';
}

async function _renderRules() {
  const el = document.getElementById('rules-list');
  if (!el) return;
  let rules = [];
  try { rules = await fetch('/api/automations').then(r => r.json()); } catch {}
  if (!rules.length) {
    el.innerHTML = '<div class="settings-row-empty">no rules yet — your first automation is one form away</div>';
    return;
  }
  const label = (list, v) => list.find(x => x.value === v)?.label || v;
  el.innerHTML = rules.map(r => `
    <div class="rule-row${r.enabled ? '' : ' off'}" data-id="${r.id}">
      <div class="rule-row-main">
        <span class="rule-row-name">${_esc(r.name)}</span>
        <span class="rule-row-desc">${_esc(label(_ruleOpts.triggers, r.trigger))} <b>${_esc(r.trigger_arg)}</b> → ${_esc(label(_ruleOpts.actions, r.action))}${r.action_arg ? `: <i>${_esc(r.action_arg.slice(0, 60))}</i>` : ''}</span>
      </div>
      <button class="btn" data-act="test" title="run once with sample data">test</button>
      <button class="btn" data-act="toggle">${r.enabled ? 'pause' : 'resume'}</button>
      <button class="btn danger" data-act="del">×</button>
    </div>`).join('');
  el.querySelectorAll('.rule-row').forEach(row => {
    const id = row.dataset.id;
    row.querySelector('.rule-row-main')?.addEventListener('click', () => {
      const r = rules.find(x => x.id === id);
      if (r) _fillRuleForm(r, id);
    });
    row.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', async () => {
      if (b.dataset.act === 'del') {
        await fetch(`/api/automations/${id}`, { method: 'DELETE' });
        _renderRules(); return;
      }
      if (b.dataset.act === 'toggle') {
        const off = row.classList.contains('off');
        await fetch(`/api/automations/${id}`, {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ enabled: off }),
        });
        _renderRules(); return;
      }
      if (b.dataset.act === 'test') {
        b.disabled = true;
        const r = await fetch(`/api/automations/${id}/test`, { method: 'POST' });
        toast(r.ok ? 'rule fired with sample data — check the result' : 'test failed', r.ok ? 'success' : 'error');
        b.disabled = false;
      }
    }));
  });
}

async function _addRule() {
  const body = {
    name: document.getElementById('rule-name')?.value.trim() || '',
    trigger: document.getElementById('rule-trigger')?.dataset.value,
    trigger_arg: document.getElementById('rule-trigger-arg')?.value.trim() || '',
    action: document.getElementById('rule-action')?.dataset.value,
    action_arg: document.getElementById('rule-action-arg')?.value.trim() || '',
  };
  const editing = _editingRule;
  const r = await fetch(editing ? `/api/automations/${editing}` : '/api/automations', {
    method: editing ? 'PATCH' : 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) { toast((await r.json().catch(() => ({}))).detail || 'failed to save rule', 'error'); return; }
  _resetRuleForm();
  toast(editing ? 'rule updated' : 'rule added — it runs automatically from now on', 'success');
  _renderRules();
}
