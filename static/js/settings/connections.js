import { createSettingsPane } from './pane.js';
import { getDropdownValue } from '../dropdown.js?v=212';
import { toast } from '../util.js';
import { confirm as _dlgConfirm } from '../dialog.js';
import { parsePrivateLines } from '../mcp-config.js';
import { resolvedTimeZone, t } from '../i18n.js';
import { _setSwitch, _bindSwitch, _patchSetting, _patchSettings, _esc, _escAttr, _fetchWithRecentOwner } from './shared.js';

const _connectionLoads = new Map();
let _agentRootsDirty = false;
let _agentRootsRevision = 0;
let _agentRootsSaving = false;
let _connectionAdding = false;
let _connectionDraftRevision = 0;
const _connectionPending = new Map();
const _connectionServices = new Map();
let _mcpAdding = false;
let _mcpDraftRevision = 0;
const _mcpRemoving = new Set();
const _mcpPresetAdding = new Set();
let _permRuleAdding = false;
let _permDraftRevision = 0;
let _permRulesSaving = false;
let _permRulesKnown = false;

function _connectionService() {
  const selected = document.getElementById('conn-service')?.value;
  return (selected === 'custom' ? document.getElementById('conn-custom')?.value : selected || '').trim().toLowerCase();
}

function _syncConnectionPending() {
  const add = document.getElementById('conn-add-btn');
  if (add) add.disabled = _connectionAdding || _connectionPending.has(_connectionService());
  document.querySelectorAll('#conn-list button[data-id]').forEach(button => {
    const action = _connectionPending.get(_connectionServices.get(button.dataset.id));
    button.disabled = !!action;
    button.textContent = action === 'delete' ? 'disconnecting…' : 'disconnect';
  });
}

function _syncMcpPending() {
  document.querySelectorAll('#mcp-server-list button[data-id]').forEach(button => {
    button.disabled = _mcpRemoving.has(button.dataset.id);
    button.textContent = button.disabled ? 'removing…' : 'remove';
  });
  document.querySelectorAll('#mcp-presets button[data-id]').forEach(button => {
    button.disabled = _mcpPresetAdding.has(button.dataset.id);
  });
}

function _syncPermPending() {
  const add = document.getElementById('perm-rule-add-btn');
  if (add) {
    add.disabled = _permRulesSaving || !_permRulesKnown;
    add.textContent = _permRuleAdding ? 'saving…' : 'add rule';
  }
  document.querySelectorAll('#perm-rules-list button').forEach(button => { button.disabled = _permRulesSaving; });
}

function _connectionRead(name, isCurrent) {
  const generation = (_connectionLoads.get(name) || 0) + 1;
  _connectionLoads.set(name, generation);
  return () => _connectionLoads.get(name) === generation && isCurrent();
}

// ── agent + mcp servers ───────────────────────────────────────────────────────
async function loadAgentStatus(isCurrent = () => true) {
  const current = _connectionRead('agent', isCurrent);
  const grid = document.getElementById('agent-status-grid');
  const list = document.getElementById('agent-tool-list');
  const runsEl = document.getElementById('agent-run-list');
  if (!grid || !list) return;
  const cfg = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  if (!current()) return;
  _bindSwitch(document.getElementById('s-agent-ctx-toggle'),
    () => cfg.agent_context_files !== false, v => _patchSetting('agent_context_files', v));
  _bindSwitch(document.getElementById('s-agent-sandbox-toggle'),
    () => !!cfg.agent_sandbox, v => _patchSetting('agent_sandbox', v));
  _bindSwitch(document.getElementById('s-agent-computer-toggle'),
    () => !!cfg.agent_computer_use, v => _patchSetting('agent_computer_use', v));
  _bindSwitch(document.getElementById('s-agent-subagents-toggle'),
    () => cfg.agent_subagents !== false, v => _patchSetting('agent_subagents', v));
  const roots = document.getElementById('s-agent-roots');
  if (roots && !_agentRootsDirty) roots.value = (cfg.agent_allowed_roots || []).join('\n');
  const rootsSave = document.getElementById('s-agent-roots-save');
  if (rootsSave) rootsSave.disabled = _agentRootsSaving;
  if (rootsSave && !rootsSave.dataset.bound) {
    rootsSave.dataset.bound = '1';
    rootsSave.addEventListener('click', async () => {
      if (_agentRootsSaving) return;
      const revision = _agentRootsRevision;
      const values = (roots?.value || '').split('\n').map(value => value.trim()).filter(Boolean);
      const returnFocus = document.activeElement === rootsSave;
      _agentRootsSaving = true;
      rootsSave.disabled = true;
      rootsSave.textContent = 'saving…';
      rootsSave.setAttribute('aria-busy', 'true');
      try {
        const response = await _fetchWithRecentOwner('/api/settings', {
          method: 'PATCH', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ agent_allowed_roots: values }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || 'approved roots could not be saved');
        if (revision === _agentRootsRevision) {
          _agentRootsDirty = false;
          if (roots) roots.value = (data.agent_allowed_roots || []).join('\n');
        }
        toast('approved roots saved', 'success');
      } catch (error) {
        toast(error.message || 'approved roots could not be saved', 'error');
      } finally {
        _agentRootsSaving = false;
        rootsSave.disabled = false;
        rootsSave.textContent = 'save approved roots';
        rootsSave.removeAttribute('aria-busy');
        if (returnFocus && document.activeElement === document.body && rootsSave.offsetParent) rootsSave.focus();
      }
    });
  }
  try {
    const [s, runs] = await Promise.all([
      fetch('/api/agent/status').then(r => r.json()),
      fetch('/api/agent/runs?limit=5').then(r => r.json()).catch(() => []),
    ]);
    if (!current()) return;
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
      <div><span>connections</span><strong>${_esc((s.connections || []).join(', ') || 'none')}</strong></div>
    `;
    list.innerHTML = (s.tools || []).map(t => `<span>${_esc(t)}</span>`).join('');

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
    if (!current()) return;
    grid.innerHTML = '<div class="settings-row-empty">agent status unavailable</div>';
    list.innerHTML = '';
    if (runsEl) runsEl.innerHTML = '';
  }
}

export async function loadMcpServers(isCurrent = () => true) {
  const current = _connectionRead('mcp', isCurrent);
  const el = document.getElementById('mcp-server-list');
  if (!el) return;
  _loadMcpPresets(isCurrent);  // 10d — render presets regardless of how many servers exist
  try {
    const response = await fetch('/api/mcp/servers');
    if (!response.ok) throw new Error();
    const servers = await response.json();
    if (!current() || _mcpRemoving.size || _mcpAdding || _mcpPresetAdding.size) return;
    if (!servers.length) { el.innerHTML = '<div class="settings-row-empty">no servers</div>'; return; }
    el.innerHTML = servers.map(s => `
      <div class="settings-list-row">
        <span class="status-dot" style="background:${s.connected ? 'var(--green)' : 'var(--faint)'}"></span>
        <span class="row-name">${_esc(s.name)}</span>
        <span class="row-meta">${s.tools.length} tools</span>
        <button class="act-btn" data-id="${s.id}" onclick="window._rmMcp(this)">remove</button>
      </div>`).join('');
  } catch {
    if (current() && !_mcpRemoving.size && !_mcpAdding && !_mcpPresetAdding.size) el.innerHTML = '<div class="settings-row-empty">failed to load</div>';
  }
}

// 11a — macOS native integration status (available only on the Mac mini)
async function loadMacosStatus(isCurrent = () => true) {
  const current = _connectionRead('macos', isCurrent);
  const box = document.getElementById('macos-status');
  if (!box) return;
  let cap;
  try { cap = await fetch('/api/macos/status').then(r => r.json()); }
  catch { if (current()) box.innerHTML = '<div class="settings-row-empty">status unavailable</div>'; return; }
  if (!current()) return;
  const dot = ok => `<span class="status-dot" style="background:${ok ? 'var(--green)' : 'var(--faint)'}"></span>`;
  const row = (label, ok) => `<div class="macos-row">${dot(ok)}<span>${label}</span></div>`;
  if (!cap.available) {
    box.innerHTML = `<div class="settings-row-empty">unavailable on ${_esc(cap.platform)}. `
      + 'macOS native integration runs on the Mac mini.</div>';
    return;
  }
  box.innerHTML = '<div class="macos-avail">✓ available</div>'
    + row('Keychain', cap.keychain)
    + row('Calendar / Reminders (EventKit)', cap.eventkit)
    + row(`Photos (PhotoKit)${cap.photokit_authorization && !cap.photokit_ready ? `: ${_esc(cap.photokit_authorization.replace('_', ' '))}` : ''}`, cap.photokit_ready)
    + row('iCloud Drive', cap.icloud);
}

// 10d — one-click connector presets
async function _loadMcpPresets(isCurrent = () => true) {
  const current = _connectionRead('presets', isCurrent);
  const box = document.getElementById('mcp-presets');
  if (!box) return;
  let presets;
  try { presets = await fetch('/api/mcp/presets').then(r => r.json()); }
  catch { if (current() && !_mcpPresetAdding.size) box.innerHTML = ''; return; }
  if (!current() || _mcpPresetAdding.size) return;
  box.innerHTML = presets.map(p =>
    `<button class="btn mcp-preset" data-id="${_escAttr(p.id)}" title="${_escAttr(p.description)}">+ ${_esc(p.name)}</button>`
  ).join('');
  box.querySelectorAll('.mcp-preset').forEach(b => b.onclick = () => _addMcpPreset(b.dataset.id));
  _syncMcpPending();
}

async function _addMcpPreset(id) {
  if (_mcpPresetAdding.has(id)) return;
  _mcpPresetAdding.add(id);
  _syncMcpPending();
  toast('adding connector…');
  try {
    const r = await _fetchWithRecentOwner(`/api/mcp/presets/${encodeURIComponent(id)}`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ params: {} }),
    });
    if (!r.ok) throw new Error(r.status);
    toast('connector added: edit its args if it needs a path/key', 'success');
  } catch { toast('could not add connector', 'error'); }
  finally {
    _mcpPresetAdding.delete(id);
    _syncMcpPending();
    loadMcpServers();
  }
}

window._rmMcp = async btn => {
  const id = btn.dataset.id;
  if (_mcpRemoving.has(id)) return;
  const returnFocus = document.activeElement === btn;
  _mcpRemoving.add(id);
  _syncMcpPending();
  try {
    const response = await _fetchWithRecentOwner(`/api/mcp/servers/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error();
  } catch { toast('could not remove mcp server', 'error'); }
  finally {
    _mcpRemoving.delete(id);
    _syncMcpPending();
    await loadMcpServers();
    const control = document.querySelector(`#mcp-server-list button[data-id="${id}"]`);
    if (returnFocus && document.activeElement === document.body && control?.offsetParent) control.focus();
  }
};

// ── connections (github etc) ────────────────────────────────────────────────
export async function loadConnections(isCurrent = () => true) {
  const current = _connectionRead('connections', isCurrent);
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
    const response = await fetch('/api/connections');
    if (!response.ok) throw new Error();
    const conns = await response.json();
    if (!current() || _connectionPending.size) return;
    _connectionServices.clear();
    conns.forEach(connection => _connectionServices.set(connection.id, connection.service.trim().toLowerCase()));
    if (!conns.length) { el.innerHTML = '<div class="settings-row-empty">nothing connected</div>'; return; }
    el.innerHTML = conns.map(c => `
      <div class="settings-list-row">
        <span class="status-dot" style="background:${c.connected ? 'var(--green)' : 'var(--faint)'}"></span>
        <span class="row-name">${_esc(c.service)}</span>
        <span class="row-meta">${_esc(c.token_masked || '')}</span>
        <button class="act-btn" data-svc="${_esc(c.service)}" onclick="window._testConn(this)">test</button>
        <button class="act-btn" data-id="${c.id}" onclick="window._rmConn(this)">disconnect</button>
      </div>`).join('');
    _syncConnectionPending();
  } catch { if (current() && !_connectionPending.size) el.innerHTML = '<div class="settings-row-empty">failed to load</div>'; }
}

async function addConnection() {
  if (_connectionAdding) return;
  const sel = document.getElementById('conn-service');
  let service = sel.value;
  if (service === 'custom') service = document.getElementById('conn-custom').value.trim();
  const token = document.getElementById('conn-token').value.trim();
  if (!service) { toast('pick a service', 'error'); return; }
  if (!token) { toast('token required', 'error'); return; }
  const owner = service.trim().toLowerCase();
  if (_connectionPending.has(owner)) return;
  const revision = _connectionDraftRevision;
  const btn = document.getElementById('conn-add-btn');
  _connectionAdding = true;
  _connectionPending.set(owner, 'connect');
  _syncConnectionPending();
  btn.disabled = true; btn.textContent = 'connecting…';
  try {
    const r = await _fetchWithRecentOwner('/api/connections', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ service, token }),
    });
    if (!r.ok) { toast('connect failed', 'error'); return; }
    toast(`${service} connected`, 'success');
    if (revision === _connectionDraftRevision) document.getElementById('conn-token').value = '';
  } catch { toast('connect failed', 'error'); }
  finally {
    _connectionAdding = false;
    _connectionPending.delete(owner);
    _syncConnectionPending();
    btn.textContent = 'connect';
    loadConnections();
  }
}

window._rmConn = async btn => {
  const id = btn.dataset.id;
  const service = _connectionServices.get(id) || id;
  if (_connectionPending.has(service)) return;
  const returnFocus = document.activeElement === btn;
  _connectionPending.set(service, 'delete');
  _syncConnectionPending();
  try {
    const response = await _fetchWithRecentOwner(`/api/connections/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error();
  } catch { toast('could not disconnect', 'error'); }
  finally {
    _connectionPending.delete(service);
    _syncConnectionPending();
    await loadConnections();
    const control = document.querySelector(`#conn-list button[data-id="${id}"]`);
    if (returnFocus && document.activeElement === document.body && control?.offsetParent) control.focus();
  }
};

window._testConn = async btn => {
  btn.textContent = '…';
  try {
    const r = await fetch(`/api/connections/${btn.dataset.svc}/test`).then(x => x.json());
    if (r.ok) toast(`${btn.dataset.svc} ok${r.user ? ': ' + r.user : ''}`, 'success');
    else toast(r.error || 'test failed', 'error');
  } catch { toast('test failed', 'error'); }
  btn.textContent = 'test';
};

// Jarvis is only the optional owner-scoped Discord connection. It uses Aide's
// normal model and background runtime; there is no separate in-app mode.
let _discordPairingCode = '';
let _discordBound = false;
let _discordGeneration = 0;
let _discordBusy = false;
let _discordMutationQueue = Promise.resolve();
const _discordDrafts = { channels: false, quiet: false };
const _discordDraftRevisions = { channels: 0, quiet: 0 };
let _discordTokenRevision = 0;
const _discordActionsPending = new Set();

function _setDiscordActionPending(action, pending) {
  if (pending) _discordActionsPending.add(action);
  else _discordActionsPending.delete(action);
  const ids = action === 'connect' ? ['jarvis-discord-connect'] : ['jarvis-discord-pair', 'jarvis-discord-revoke'];
  ids.forEach(id => { const button = document.getElementById(id); if (button) button.disabled = pending; });
}

function _discordLines(value = '') {
  return String(value).split(/\r?\n/).map(item => item.trim()).filter(Boolean);
}

function _discordJson(url, options = {}) {
  const mutate = async () => {
    _discordBusy = true;
    // Invalidate status reads without discarding a successful queued write on close.
    _discordGeneration += 1;
    try {
      const response = await _fetchWithRecentOwner(url, options);
      let body = {};
      try { body = await response.json(); } catch {}
      if (!response.ok) throw new Error(body.detail || body.message || 'Discord connection failed');
      return body;
    } finally {
      _discordBusy = false;
    }
  };
  const pending = _discordMutationQueue.then(mutate, mutate);
  _discordMutationQueue = pending.catch(() => {});
  return pending;
}

function _renderDiscordConnection(data) {
  if (!data) return;
  const view = document.getElementById('jarvis-discord-view');
  const setup = document.getElementById('jarvis-discord-setup');
  const manage = document.getElementById('jarvis-discord-manage');
  const head = document.getElementById('jarvis-discord-head-state');
  if (!view || !setup || !manage || !head) return;
  view.hidden = true;
  setup.hidden = !!data.configured;
  manage.hidden = !data.configured;
  head.textContent = data.configured ? (data.connection_state || 'disconnected') : 'not connected';
  if (!data.configured) return;

  document.getElementById('jarvis-discord-name').textContent = data.bot_name || 'Jarvis';
  const detail = data.paired
    ? `paired with ${data.owner_name || 'owner'}`
    : 'waiting for one owner to pair';
  document.getElementById('jarvis-discord-detail').textContent = detail;
  _setSwitch(document.getElementById('jarvis-discord-enabled'), !!data.enabled);
  const channels = document.getElementById('jarvis-discord-channels');
  if (!_discordDrafts.channels) channels.value = (data.allowed_channel_ids || []).join('\n');

  const pairCode = document.getElementById('jarvis-pairing-code');
  pairCode.hidden = !_discordPairingCode;
  pairCode.textContent = _discordPairingCode || '';
  document.getElementById('jarvis-discord-pair').textContent = data.paired
    ? 'replace pairing'
    : (data.pairing_available ? 'replace hidden code' : 'new pairing code');
  document.getElementById('jarvis-discord-revoke').hidden = !data.paired;

  const quiet = data.quiet_hours || {};
  const quietOn = !!quiet.enabled;
  const values = [
    ['jarvis-discord-quiet-start', quiet.start || '23:00'],
    ['jarvis-discord-quiet-end', quiet.end || '07:00'],
    ['jarvis-discord-timezone', quiet.timezone || resolvedTimeZone()],
  ];
  if (!_discordDrafts.quiet) {
    _setSwitch(document.getElementById('jarvis-discord-quiet'), quietOn);
    document.getElementById('jarvis-discord-quiet-fields').hidden = !quietOn;
    values.forEach(([id, value]) => {
      document.getElementById(id).value = value;
    });
  }
}

function _bindDiscordConnection() {
  if (_discordBound) return;
  _discordBound = true;
  document.getElementById('jarvis-discord-token')?.addEventListener('input', () => { _discordTokenRevision += 1; });
  document.getElementById('jarvis-discord-channels')?.addEventListener('input', () => {
    _discordDrafts.channels = true;
    _discordDraftRevisions.channels += 1;
  });
  for (const id of ['jarvis-discord-quiet-start', 'jarvis-discord-quiet-end', 'jarvis-discord-timezone']) {
    document.getElementById(id)?.addEventListener('input', () => {
      _discordDrafts.quiet = true;
      _discordDraftRevisions.quiet += 1;
    });
  }
  document.getElementById('jarvis-discord-connect')?.addEventListener('click', async () => {
    if (_discordActionsPending.has('connect')) return;
    const token = document.getElementById('jarvis-discord-token').value.trim();
    if (!token) { toast('bot token required', 'error'); return; }
    const tokenRevision = _discordTokenRevision;
    const channelsRevision = _discordDraftRevisions.channels;
    const quietRevision = _discordDraftRevisions.quiet;
    _setDiscordActionPending('connect', true);
    try {
      const data = await _discordJson('/api/jarvis/discord', {
        method: 'POST', headers: {'content-type':'application/json'},
        body: JSON.stringify({ bot_token: token }),
      });
      _discordPairingCode = data.pairing_code || '';
      if (channelsRevision === _discordDraftRevisions.channels) _discordDrafts.channels = false;
      if (quietRevision === _discordDraftRevisions.quiet) _discordDrafts.quiet = false;
      if (tokenRevision === _discordTokenRevision) document.getElementById('jarvis-discord-token').value = '';
      _renderDiscordConnection(data);
      toast('Jarvis connected', 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { _setDiscordActionPending('connect', false); }
  });
  document.getElementById('jarvis-discord-enabled')?.addEventListener('click', async event => {
    const next = !event.currentTarget.classList.contains('on');
    try {
      const data = await _discordJson('/api/jarvis/discord', {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify({ enabled: next }),
      });
      _renderDiscordConnection(data);
    } catch (error) { toast(error.message, 'error'); }
  });
  document.getElementById('jarvis-discord-pair')?.addEventListener('click', async () => {
    if (_discordActionsPending.has('pairing')) return;
    _setDiscordActionPending('pairing', true);
    try {
      const data = await _discordJson('/api/jarvis/discord/pairing-code', {
        method: 'POST', headers: {'content-type':'application/json'},
        body: JSON.stringify({ revoke_owner: false }),
      });
      _discordPairingCode = data.pairing_code || '';
      _renderDiscordConnection(data);
    } catch (error) { toast(error.message, 'error'); }
    finally { _setDiscordActionPending('pairing', false); }
  });
  document.getElementById('jarvis-discord-save-channels')?.addEventListener('click', async () => {
    const ids = _discordLines(document.getElementById('jarvis-discord-channels').value);
    if (ids.some(value => !/^\d+$/.test(value))) {
      toast('channel ids must contain numbers only', 'error'); return;
    }
    const draftRevision = _discordDraftRevisions.channels;
    try {
      const data = await _discordJson('/api/jarvis/discord', {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify({ allowed_channel_ids: ids }),
      });
      if (draftRevision === _discordDraftRevisions.channels) _discordDrafts.channels = false;
      _renderDiscordConnection(data);
      toast('approved channels saved', 'success');
    } catch (error) { toast(error.message, 'error'); }
  });
  document.getElementById('jarvis-discord-revoke')?.addEventListener('click', async () => {
    if (_discordActionsPending.has('pairing')) return;
    if (!await _dlgConfirm('Revoke the paired Discord owner?')) return;
    if (_discordActionsPending.has('pairing')) return;
    _setDiscordActionPending('pairing', true);
    try {
      const data = await _discordJson('/api/jarvis/discord/pairing-code', {
        method: 'POST', headers: {'content-type':'application/json'},
        body: JSON.stringify({ revoke_owner: true }),
      });
      _discordPairingCode = data.pairing_code || '';
      _renderDiscordConnection(data);
      toast('owner revoked; a new code is ready', 'success');
    } catch (error) { toast(error.message, 'error'); }
    finally { _setDiscordActionPending('pairing', false); }
  });
  document.getElementById('jarvis-discord-quiet')?.addEventListener('click', async event => {
    if (_discordBusy) return;
    const switchControl = event.currentTarget;
    const next = !switchControl.classList.contains('on');
    _discordDrafts.quiet = true;
    const draftRevision = ++_discordDraftRevisions.quiet;
    _setSwitch(switchControl, next);
    document.getElementById('jarvis-discord-quiet-fields').hidden = !next;
    if (!next) {
      try {
        const data = await _discordJson('/api/jarvis/discord', {
          method: 'PATCH', headers: {'content-type':'application/json'},
          body: JSON.stringify({ quiet_hours: { enabled: false } }),
        });
        if (draftRevision === _discordDraftRevisions.quiet) _discordDrafts.quiet = false;
        _renderDiscordConnection(data);
      } catch (error) {
        _setSwitch(switchControl, true);
        document.getElementById('jarvis-discord-quiet-fields').hidden = false;
        toast(error.message, 'error');
      }
    }
  });
  document.getElementById('jarvis-discord-save-quiet')?.addEventListener('click', async () => {
    const quiet_hours = {
      enabled: true,
      start: document.getElementById('jarvis-discord-quiet-start').value.trim(),
      end: document.getElementById('jarvis-discord-quiet-end').value.trim(),
      timezone: document.getElementById('jarvis-discord-timezone').value.trim(),
    };
    const draftRevision = _discordDraftRevisions.quiet;
    try {
      const data = await _discordJson('/api/jarvis/discord', {
        method: 'PATCH', headers: {'content-type':'application/json'},
        body: JSON.stringify({ quiet_hours }),
      });
      if (draftRevision === _discordDraftRevisions.quiet) _discordDrafts.quiet = false;
      _renderDiscordConnection(data);
      toast('quiet hours saved', 'success');
    } catch (error) { toast(error.message, 'error'); }
  });
  document.getElementById('jarvis-discord-disconnect')?.addEventListener('click', async () => {
    if (!await _dlgConfirm('Disconnect Jarvis from Discord?')) return;
    try {
      await _discordJson('/api/jarvis/discord', { method: 'DELETE' });
      _discordPairingCode = '';
      _discordDrafts.channels = false;
      _discordDrafts.quiet = false;
      _renderDiscordConnection({ configured: false });
      toast('Jarvis disconnected', 'success');
    } catch (error) { toast(error.message, 'error'); }
  });
}

export async function loadDiscordConnection(isCurrent = () => true) {
  const view = document.getElementById('jarvis-discord-view');
  if (!view) return;
  _bindDiscordConnection();
  if (_discordBusy) return;
  const generation = ++_discordGeneration;
  try {
    const data = await fetch('/api/jarvis/discord').then(response => {
      if (!response.ok) throw new Error();
      return response.json();
    });
    if (generation !== _discordGeneration || !isCurrent()) return;
    _renderDiscordConnection(data);
  } catch {
    if (generation !== _discordGeneration || !isCurrent()) return;
    view.hidden = false;
    view.innerHTML = '<div class="settings-row-empty">Discord status unavailable</div>';
    document.getElementById('jarvis-discord-setup').hidden = true;
    document.getElementById('jarvis-discord-manage').hidden = true;
  }
}

async function addMcpServer() {
  if (_mcpAdding) return;
  const name    = document.getElementById('mcp-name').value.trim();
  const command = document.getElementById('mcp-command').value.trim();
  const transport = document.getElementById('mcp-transport')?.value || 'stdio';
  const url = document.getElementById('mcp-url')?.value.trim() || '';
  if (!name || (transport === 'stdio' ? !command : !url)) {
    toast(transport === 'stdio' ? 'name + command required' : 'name + remote url required', 'error');
    return;
  }
  const parts = command.match(/(?:[^\s"]+|"[^"]*")+/g) || [];
  const cmd = parts[0] || '', args = parts.slice(1).map(a => a.replace(/^"|"$/g,''));
  let env, headers;
  try {
    env = parsePrivateLines(document.getElementById('mcp-env')?.value || '');
    headers = parsePrivateLines(document.getElementById('mcp-headers')?.value || '');
  } catch (error) { toast(error.message, 'error'); return; }
  const revision = _mcpDraftRevision;
  const btn = document.getElementById('mcp-add-btn');
  _mcpAdding = true;
  btn.disabled = true; btn.textContent = 'adding…';
  try {
    const response = await _fetchWithRecentOwner('/api/mcp/servers', {
      method: 'POST', headers: {'content-type':'application/json'},
      body: JSON.stringify({ name, transport, command: cmd, args, url, env, headers }),
    });
    if (!response.ok) { toast('could not add mcp server', 'error'); return; }
    if (revision === _mcpDraftRevision) {
      document.getElementById('mcp-name').value = '';
      document.getElementById('mcp-command').value = '';
      document.getElementById('mcp-url').value = '';
      document.getElementById('mcp-env').value = '';
      document.getElementById('mcp-headers').value = '';
    }
    toast('mcp server added', 'success');
    loadMcpServers();
  } catch { toast('could not add mcp server', 'error'); }
  finally {
    _mcpAdding = false;
    btn.disabled = false; btn.textContent = 'add server';
  }
}

async function rotateCredentialKey() {
  const button = document.getElementById('conn-rotate-key');
  button.disabled = true;
  button.textContent = 'rotating…';
  try {
    const response = await _fetchWithRecentOwner('/api/connections/rotate-key', { method: 'POST' });
    if (!response.ok) throw new Error(response.status);
    toast('credential key rotated', 'success');
  } catch { toast('credential key rotation failed; the old key was kept', 'error'); }
  finally { button.disabled = false; button.textContent = 'rotate credential key'; }
}


function _wireConnectionsPane() {
  for (const type of ['input', 'change']) {
    for (const id of ['conn-service', 'conn-custom', 'conn-token']) {
      document.getElementById(id)?.addEventListener(type, () => {
        _connectionDraftRevision += 1;
        _syncConnectionPending();
      });
    }
    for (const id of ['mcp-name', 'mcp-command', 'mcp-transport', 'mcp-url', 'mcp-env', 'mcp-headers']) {
      document.getElementById(id)?.addEventListener(type, () => { _mcpDraftRevision += 1; });
    }
    for (const id of ['perm-rule-tool', 'perm-rule-path', 'perm-rule-action']) {
      document.getElementById(id)?.addEventListener(type, () => { _permDraftRevision += 1; });
    }
  }
  document.getElementById('s-agent-roots')?.addEventListener('input', () => {
    _agentRootsDirty = true;
    _agentRootsRevision += 1;
  });
  document.getElementById('mcp-add-btn')?.addEventListener('click', addMcpServer);
  document.getElementById('conn-rotate-key')?.addEventListener('click', rotateCredentialKey);
  document.getElementById('agent-status-refresh-btn')?.addEventListener('click', () => loadAgentStatus());
  document.getElementById('perm-rule-add-btn')?.addEventListener('click', _addPermRule);
  _syncPermPending();
  _bindDiscordConnection();
}

// ── permission rules: per-tool/path allow|ask|deny, layered over the agent mode ──
let _permRules = [];
async function loadPermRules(isCurrent = () => true) {
  const current = _connectionRead('permissions', isCurrent);
  let rules;
  try {
    const response = await fetch('/api/settings');
    if (!response.ok) throw new Error();
    rules = (await response.json()).permission_rules || [];
  } catch {
    if (current() && !_permRulesSaving) toast('could not load permission rules', 'error');
    return;
  }
  if (!current() || _permRulesSaving) return;
  _permRules = rules;
  _permRulesKnown = true;
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
      : '<div style="font-size:0.75rem;color:var(--muted)">no rules: the agent follows the mode for everything</div>';
    el.querySelectorAll('.perm-rule-del').forEach(b => {
      const rule = _permRules[+b.dataset.i];
      b.onclick = () => _delPermRule(rule);
    });
  }
  _syncPermPending();
}
async function _addPermRule() {
  if (_permRulesSaving || !_permRulesKnown) return;
  const tool = document.getElementById('perm-rule-tool').value.trim();
  const path = document.getElementById('perm-rule-path').value.trim();
  const action = getDropdownValue(document.getElementById('perm-rule-action')) || 'ask';
  if (!tool) { toast('tool pattern required (use * for any)', 'error'); return; }
  const revision = _permDraftRevision;
  _permRuleAdding = true;
  _permRulesSaving = true;
  _syncPermPending();
  try {
    const next = [..._permRules, { tool, path, action }];
    const settings = await _patchSettings({ permission_rules: next });
    if (!settings) return;
    _permRules = settings.permission_rules || next;
    if (revision === _permDraftRevision) {
      document.getElementById('perm-rule-tool').value = '';
      document.getElementById('perm-rule-path').value = '';
    }
    toast('rule added', 'success');
  } finally {
    _permRuleAdding = false;
    _permRulesSaving = false;
    _syncPermPending();
    await loadPermRules();
  }
}
async function _delPermRule(rule) {
  if (_permRulesSaving || !_permRulesKnown || !_permRules.includes(rule)) return;
  _permRulesSaving = true;
  _syncPermPending();
  try {
    const next = _permRules.filter(candidate => candidate !== rule);
    const settings = await _patchSettings({ permission_rules: next });
    if (settings) _permRules = settings.permission_rules || next;
  } finally {
    _permRulesSaving = false;
    _syncPermPending();
    await loadPermRules();
  }
}


export const connectionsPane = createSettingsPane({
  init: _wireConnectionsPane,
  load: isCurrent => Promise.all([
    loadAgentStatus(isCurrent), loadMcpServers(isCurrent), loadConnections(isCurrent),
    loadDiscordConnection(isCurrent), loadPermRules(isCurrent), loadMacosStatus(isCurrent),
  ]),
  dispose() {
    for (const [name, generation] of _connectionLoads) _connectionLoads.set(name, generation + 1);
    _discordGeneration += 1;
  },
});
