import { toast } from './util.js';
import { loadModels, addEndpoint, renderModelList } from './models.js';
import { initCustomDropdowns, getDropdownValue, setDropdownValue } from './dropdown.js';

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
  if (name === 'models')     loadEpList();
  if (name === 'ai')         loadAiPane();
  if (name === 'search')     loadSearchPane();
  if (name === 'appearance') loadAppearancePane();
  if (name === 'voice')      loadVoicePane();
  if (name === 'personas')   { loadPersonas(); loadCookbook(); }
  if (name === 'tools')      loadMcpServers();
  if (name === 'developer')  { loadTokens(); loadWebhooks(); }
}

// ── open / close ──────────────────────────────────────────────────────────────
let _bound = false;

export function openSettings(pane = 'models') {
  const modal = document.getElementById('settings-modal');
  if (!modal) return;
  modal.style.display = 'flex';
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
      await addEndpoint(name, url, key);
      ['s-ep-name','s-ep-url','s-ep-key'].forEach(id => document.getElementById(id).value = '');
      document.getElementById('s-ep-add-details').open = false;
      toast('endpoint added', 'success');
      loadEpList();
      loadModels();
      renderModelList();
    } catch (e) { toast(`failed: ${e.message}`, 'error'); }
    btn.textContent = 'add + probe models'; btn.disabled = false;
  });

  // ── ai pane ──
  document.getElementById('settings-save-btn')?.addEventListener('click', saveAiDefaults);

  // ── search pane ──
  document.getElementById('s-search-provider')?.addEventListener('change', () => {
    _updateSearchKeyRow();
    saveSearchSettings();
  });
  document.getElementById('s-tavily-key')?.addEventListener('blur', saveSearchSettings);
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
  document.getElementById('cookbook-add-btn')?.addEventListener('click', addCookbookEntry);

  // ── tools (mcp) ──
  document.getElementById('mcp-add-btn')?.addEventListener('click', addMcpServer);

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
}

// ── models pane ───────────────────────────────────────────────────────────────
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
        if (!confirm('remove this endpoint?')) return;
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
async function loadSearchPane() {
  try {
    const s = await fetch('/api/settings').then(r => r.json());
    const prov = s.search_provider || 'duckduckgo';
    setDropdownValue(document.getElementById('s-search-provider'), prov);
    if (s.tavily_api_key) document.getElementById('s-tavily-key').value = s.tavily_api_key;
    const count = s.search_result_count || 5;
    const sel = document.getElementById('s-search-count');
    if (sel) setDropdownValue(sel, String(count));
    _updateSearchKeyRow();
    _updateSearchStatus(s);
  } catch {}
}

function _updateSearchKeyRow() {
  const prov = getDropdownValue(document.getElementById('s-search-provider'));
  const row = document.getElementById('s-tavily-row');
  if (row) row.style.display = prov === 'tavily' ? 'flex' : 'none';
}

function _updateSearchStatus(s) {
  const el = document.getElementById('s-search-status');
  if (!el) return;
  const prov = s.search_provider || 'duckduckgo';
  const labels = { duckduckgo: 'DuckDuckGo · free', tavily: 'Tavily', disabled: 'disabled' };
  const count = s.search_result_count || 5;
  const hasKey = prov === 'tavily' ? !!(s.tavily_api_key || '').trim() : true;
  el.textContent = `active: ${labels[prov] || prov} · ${count} results${prov === 'tavily' && !hasKey ? ' · ⚠ no api key' : ''}`;
  el.style.color = (prov === 'tavily' && !hasKey) ? 'var(--error)' : 'var(--muted)';
}

async function saveSearchSettings() {
  const prov  = getDropdownValue(document.getElementById('s-search-provider'));
  const count = parseInt(getDropdownValue(document.getElementById('s-search-count'))) || 5;
  const key   = document.getElementById('s-tavily-key')?.value.trim() || '';
  const patch = { search_provider: prov, search_result_count: count };
  if (key) patch.tavily_api_key = key;
  await _patchSettings(patch);
  _updateSearchStatus({ search_provider: prov, search_result_count: count, tavily_api_key: key });
}

async function testSearch() {
  const btn = document.getElementById('s-search-test-btn');
  const status = document.getElementById('s-search-status');
  btn.textContent = 'testing…'; btn.disabled = true;
  try {
    const prov = getDropdownValue(document.getElementById('s-search-provider'));
    if (prov === 'disabled') { status.textContent = 'search is disabled'; btn.textContent = 'test'; btn.disabled = false; return; }
    const r = await fetch('/api/research', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: 'test', session_id: 'settings-test', max_rounds: 1 }),
    });
    status.textContent = r.ok ? '✓ connection ok' : `error: ${r.status}`;
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
    _updateTtsVoiceRow();
  } catch {}
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
  };
  const key = document.getElementById('settings-openai-key')?.value.trim();
  if (key) patch.openai_api_key = key;
  await _patchSettings(patch);
  toast('voice settings saved', 'success');
}

// ── personas ──────────────────────────────────────────────────────────────────
export async function loadPersonas() {
  const el = document.getElementById('persona-list');
  if (!el) return;
  const personas = await fetch('/api/personas').then(r => r.json()).catch(() => []);
  if (!personas.length) { el.innerHTML = '<div class="settings-row-empty">no personas yet</div>'; return; }
  el.innerHTML = personas.map(p => `
    <div class="settings-list-row">
      <span>${p.emoji}</span>
      <span class="row-name">${_esc(p.name)}</span>
      <span class="row-meta">${_esc((p.system_prompt||'').slice(0,40))}${p.system_prompt?.length>40?'…':''}</span>
      <button class="act-btn" data-id="${p.id}" onclick="window._rmPersona(this)">remove</button>
    </div>`).join('');
}

window._rmPersona = async btn => {
  await fetch(`/api/personas/${btn.dataset.id}`, { method: 'DELETE' });
  loadPersonas();
};

async function addPersona() {
  const name   = document.getElementById('persona-name').value.trim();
  const emoji  = document.getElementById('persona-emoji').value.trim() || ':)';
  const prompt = document.getElementById('persona-prompt').value.trim();
  if (!name) { toast('name required', 'error'); return; }
  await fetch('/api/personas', { method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, emoji, system_prompt: prompt }) });
  ['persona-name','persona-emoji','persona-prompt'].forEach(id => document.getElementById(id).value = '');
  toast('persona added', 'success');
  loadPersonas();
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

// ── mcp servers ───────────────────────────────────────────────────────────────
export async function loadMcpServers() {
  const el = document.getElementById('mcp-server-list');
  if (!el) return;
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

window._rmMcp = async btn => {
  await fetch(`/api/mcp/servers/${btn.dataset.id}`, { method: 'DELETE' });
  loadMcpServers();
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
  el.innerHTML = hooks.map(h => `
    <div class="settings-list-row">
      <span class="status-dot" style="background:${h.enabled ? 'var(--green)' : 'var(--faint)'}"></span>
      <span class="row-name">${_esc(h.name)}</span>
      <span class="row-meta">${h.events.join(', ')}</span>
      <button class="act-btn" data-id="${h.id}" onclick="window._rmWebhook(this)">remove</button>
    </div>`).join('');
}

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
