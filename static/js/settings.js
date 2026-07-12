import { toast } from './util.js';
import { confirm as _dlgConfirm, prompt as _dlgPrompt } from './dialog.js';
import { loadModels, addEndpoint, renderModelList } from './models.js?v=209';
import { initCustomDropdowns, getDropdownValue, setDropdownValue, populateDropdown } from './dropdown.js?v=210';
import { initMemoryPanel } from './memory.js';
import {
  sensitiveBlurEnabled, textOnlyEmojisEnabled, welcomeEnabled,
  setSensitiveBlur, setTextOnlyEmojis, setWelcomeEnabled,
} from './privacy.js';
import { loadShortcuts, saveShortcuts, eventToShortcut, isReservedShortcut } from './shortcuts.js';
import { setAccent as _themeSetAccent, resetToDefault as _resetToDefault, getAppearance as _getAppearance, renderThemeEditorInto, isBasePreset } from './theme.js';
import { parsePrivateLines } from './mcp-config.js';
import { configureLocalization } from './i18n.js';

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
  if (!el) return;
  _setSwitch(el, getter());
  // onclick keeps pane re-open from stacking handlers
  el.onclick = () => {
    const next = !el.classList.contains('on');
    _setSwitch(el, next);
    setter(next);
  };
}

// ── pane navigation ───────────────────────────────────────────────────────────
let _activePane = 'models';

function _switchPane(name) {
  // unknown pane key (e.g. a stale 'appearance') would leave every pane inactive →
  // a blank modal. fall back to 'general', which exists in both scopes.
  if (!document.getElementById(`s-pane-${name}`)) name = 'general';
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
  if (name === 'general' || name === 'security' || name === 'themes') loadAppearancePane();
  if (name === 'themes')     loadThemesPane();
  if (name === 'voice')      loadVoicePane();
  if (name === 'personas')   { loadPersonas(); loadCookbook(); }
  if (name === 'tools')      { loadAgentStatus(); loadMcpServers(); loadConnections(); loadPermRules(); loadMacosStatus(); }
  if (name === 'developer')  { loadTokens(); loadWebhooks(); loadShortcutSettings(); }
  if (name === 'rules')      loadRulesPane();
  if (name === 'recall')     loadRecallPane();
  if (name === 'proactive')  loadProactivePane();
  if (name === 'intelligence') loadIntelligencePane();
  if (name === 'backup')     { loadWebdavBackup(); loadS3Backup(); }
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
  if (!pane) pane = allesOnly ? 'general' : 'models';
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
    n.setAttribute('role', 'button');
    n.tabIndex = 0;
    n.addEventListener('click', () => _switchPane(n.dataset.pane));
    n.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      _switchPane(n.dataset.pane);
    });
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
      setDropdownValue(document.getElementById('s-ep-adapter'), _adapterForPreset(btn.dataset.name));
      _showManualEndpointFields();
      document.getElementById('s-ep-key').focus();
    });
  });
  document.getElementById('s-ep-adapter')?.addEventListener('change', _showManualEndpointFields);
  document.getElementById('s-role-save-btn')?.addEventListener('click', saveModelRoles);
  document.getElementById('s-ep-add-btn')?.addEventListener('click', async () => {
    const name = document.getElementById('s-ep-name').value.trim();
    const url  = document.getElementById('s-ep-url').value.trim();
    const key  = document.getElementById('s-ep-key').value.trim();
    const adapter = getDropdownValue(document.getElementById('s-ep-adapter')) || 'auto';
    const manualModels = (document.getElementById('s-ep-manual')?.value || '')
      .split(',').map(value => value.trim()).filter(Boolean);
    if (!name || !url) { toast('name and url required', 'error'); return; }
    if (adapter === 'manual' && !manualModels.length) {
      toast('add at least one manual model', 'error'); return;
    }
    const btn = document.getElementById('s-ep-add-btn');
    btn.textContent = 'probing…'; btn.disabled = true;
    try {
      const ep = await addEndpoint(name, url, key, adapter, manualModels);
      const visionRaw = document.getElementById('s-ep-vision')?.value.trim() || '';
      if (visionRaw && ep?.id) {
        const visionList = visionRaw.split(',').map(s => s.trim()).filter(Boolean);
        await fetch(`/api/models/endpoint/${ep.id}`, {
          method: 'PATCH', headers: {'content-type':'application/json'},
          body: JSON.stringify({ vision_models: JSON.stringify(visionList) }),
        });
      }
      ['s-ep-name','s-ep-url','s-ep-key','s-ep-vision','s-ep-manual'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
      setDropdownValue(document.getElementById('s-ep-adapter'), 'auto');
      _showManualEndpointFields();
      document.getElementById('s-ep-add-details').open = false;
      toast('endpoint added', 'success');
      loadEpList();
      loadModels();
      renderModelList();
    } catch (e) { toast(`failed: ${e.message}`, 'error'); }
    btn.disabled = false;
    _showManualEndpointFields();
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
  document.getElementById('conn-rotate-key')?.addEventListener('click', rotateCredentialKey);
  document.getElementById('persona-doc-add')?.addEventListener('click', _addPersonaDoc);
  document.getElementById('persona-share-btn')?.addEventListener('click', _sharePersona);
  document.getElementById('agent-status-refresh-btn')?.addEventListener('click', loadAgentStatus);

  // ── developer ──
  document.getElementById('token-add-btn')?.addEventListener('click', generateToken);
  document.querySelectorAll('[data-token-scope]').forEach(btn => {
    btn.addEventListener('click', () => btn.classList.toggle('active'));
  });
  document.getElementById('wh-add-btn')?.addEventListener('click', addWebhook);

  // ── backup ──
  document.getElementById('backup-export-btn')?.addEventListener('click', async () => {
    if (await _confirmRecentOwner()) window.location = '/api/backup';
  });
  document.getElementById('backup-key-export-btn')?.addEventListener('click', async () => {
    if (await _confirmRecentOwner()) window.location = '/api/backup/recovery-key';
  });
  document.getElementById('backup-recovery-key-input')?.addEventListener('change', e => {
    const name = document.getElementById('backup-recovery-key-name');
    if (name) name.textContent = e.target.files[0]?.name || 'no separate key selected';
  });
  document.getElementById('backup-restore-input')?.addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    const status = document.getElementById('backup-restore-status');
    if (status) { status.hidden = false; status.textContent = 'checking backup…'; }
    const fd = new FormData(); fd.append('file', file);
    const keyInput = document.getElementById('backup-recovery-key-input');
    if (keyInput?.files[0]) fd.append('recovery_key', keyInput.files[0]);
    const r = await fetch('/api/backup/restore', { method: 'POST', body: fd });
    const data = await r.json().catch(() => ({}));
    if (r.ok) {
      const command = data.apply_command || 'alles restore apply <restore-id>';
      if (status) status.textContent = `verified and staged. live data is unchanged. stop Alles, then run: ${command}`;
      toast('backup verified and staged', 'success');
    } else {
      if (status) status.textContent = data.detail || 'backup check failed';
      toast(data.detail || 'backup check failed', 'error');
    }
    e.target.value = '';
    if (keyInput) keyInput.value = '';
    const keyName = document.getElementById('backup-recovery-key-name');
    if (keyName) keyName.textContent = 'no separate key selected';
  });
  document.getElementById('webdav-backup-save-btn')?.addEventListener('click', saveWebdavBackup);
  document.getElementById('webdav-backup-disconnect-btn')?.addEventListener('click', disconnectWebdavBackup);
  document.getElementById('webdav-backup-run-btn')?.addEventListener('click', runWebdavBackup);
  document.getElementById('webdav-backup-refresh-btn')?.addEventListener('click', () => loadWebdavBackups(true));
  document.getElementById('webdav-backup-list')?.addEventListener('change', renderWebdavSelection);
  document.getElementById('webdav-backup-recovery-key-btn')?.addEventListener('click', () => {
    document.getElementById('webdav-backup-recovery-key')?.click();
  });
  document.getElementById('webdav-backup-recovery-key')?.addEventListener('change', event => {
    const label = document.getElementById('webdav-backup-recovery-key-name');
    if (label) label.textContent = event.target.files[0]?.name || 'no separate key selected';
  });
  document.getElementById('webdav-backup-restore-btn')?.addEventListener('click', restoreWebdavBackup);
  document.getElementById('s3-backup-save-btn')?.addEventListener('click', saveS3Backup);
  document.getElementById('s3-backup-disconnect-btn')?.addEventListener('click', disconnectS3Backup);
  document.getElementById('s3-backup-run-btn')?.addEventListener('click', runS3Backup);
  document.getElementById('s3-backup-refresh-btn')?.addEventListener('click', () => loadS3Backups(true));
  document.getElementById('s3-backup-list')?.addEventListener('change', renderS3Selection);
  document.getElementById('s3-backup-recovery-key-btn')?.addEventListener('click', () => {
    document.getElementById('s3-backup-recovery-key')?.click();
  });
  document.getElementById('s3-backup-recovery-key')?.addEventListener('change', event => {
    const label = document.getElementById('s3-backup-recovery-key-name');
    if (label) label.textContent = event.target.files[0]?.name || 'no separate key selected';
  });
  document.getElementById('s3-backup-restore-btn')?.addEventListener('click', restoreS3Backup);

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

// ── webdav backup ────────────────────────────────────────────────────────────
let _webdavConfigured = false;
let _webdavBackups = [];
let _webdavLoadGeneration = 0;

export function normalizeWebdavBackupConfig(payload = {}) {
  const value = payload && typeof payload.webdav === 'object' ? payload.webdav : payload;
  return {
    configured: value?.configured === true,
    url: String(value?.url || ''),
    username: String(value?.username || ''),
    last_backup_at: String(value?.last_backup_at || ''),
    last_verified_at: String(value?.last_verified_at || ''),
    last_filename: String(value?.last_filename || ''),
    last_bytes: Number.isFinite(Number(value?.last_bytes)) ? Number(value.last_bytes) : null,
    error: String(value?.error || ''),
  };
}

export function webdavBackupConfigPayload(url, username, password, hasSavedPassword = false) {
  const urlValue = String(url || '').trim();
  const usernameValue = String(username || '').trim();
  const passwordValue = String(password || '');
  if (!urlValue) throw new Error('add the WebDAV https url');
  let parsed;
  try { parsed = new URL(urlValue); } catch { throw new Error('enter a valid WebDAV url'); }
  if (parsed.protocol !== 'https:') throw new Error('the WebDAV url must use https');
  if (parsed.username || parsed.password) throw new Error('keep the username and password out of the url');
  if (!usernameValue) throw new Error('add the WebDAV username');
  if (!passwordValue && !hasSavedPassword) throw new Error('add the WebDAV password');
  const result = { url: parsed.toString(), username: usernameValue };
  if (passwordValue) result.password = passwordValue;
  return result;
}

export function webdavBackupsFromResponse(payload = {}) {
  const values = Array.isArray(payload) ? payload : payload?.backups;
  if (!Array.isArray(values)) return [];
  return values.map(value => {
    if (typeof value === 'string') return { filename: value, bytes: null, modified_at: '' };
    const bytes = Number(value?.bytes);
    return {
      filename: String(value?.filename || ''),
      bytes: Number.isFinite(bytes) && bytes >= 0 ? bytes : null,
      modified_at: String(value?.modified_at || ''),
    };
  }).filter(value => value.filename).sort((left, right) => {
    const leftTime = Date.parse(left.modified_at);
    const rightTime = Date.parse(right.modified_at);
    if (!Number.isFinite(leftTime) || !Number.isFinite(rightTime)) return 0;
    return rightTime - leftTime;
  });
}

function _formatWebdavTime(value) {
  if (!value) return 'never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'unknown' : date.toLocaleString();
}

function _formatWebdavBytes(value) {
  if (!Number.isFinite(value) || value < 0) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

async function _webdavResponseJson(response) {
  return response.json().catch(() => ({}));
}

function _webdavError(data, fallback, secrets = []) {
  let message = typeof data?.detail === 'string' && data.detail.trim() ? data.detail.trim() : fallback;
  for (const secret of secrets) {
    if (secret) message = message.split(secret).join('[hidden]');
  }
  return message;
}

function _setWebdavStatus(message, kind = '') {
  const status = document.getElementById('webdav-backup-status');
  if (!status) return;
  status.textContent = message;
  status.style.color = kind === 'error' ? 'var(--error)' : (kind === 'success' ? 'var(--green)' : 'var(--muted)');
}

function _applyWebdavConfig(config) {
  _webdavConfigured = config.configured;
  const url = document.getElementById('webdav-backup-url');
  const username = document.getElementById('webdav-backup-username');
  const password = document.getElementById('webdav-backup-password');
  if (url) url.value = config.url;
  if (username) username.value = config.username;
  if (password) password.value = '';
  const save = document.getElementById('webdav-backup-save-btn');
  if (save) save.textContent = config.configured ? 'save connection' : 'connect and save';
  const disconnect = document.getElementById('webdav-backup-disconnect-btn');
  if (disconnect) {
    disconnect.hidden = !config.configured && !config.error;
    disconnect.textContent = config.error ? 'remove broken settings' : 'disconnect';
  }
  const run = document.getElementById('webdav-backup-run-btn');
  if (run) run.disabled = !config.configured;
  const refresh = document.getElementById('webdav-backup-refresh-btn');
  if (refresh) refresh.disabled = !config.configured;
  const lastSuccess = document.getElementById('webdav-backup-last-success');
  if (lastSuccess) lastSuccess.textContent = _formatWebdavTime(config.last_backup_at);
  const lastVerified = document.getElementById('webdav-backup-last-verified');
  if (lastVerified) lastVerified.textContent = _formatWebdavTime(config.last_verified_at);
  if (config.error) _setWebdavStatus(config.error, 'error');
  else _setWebdavStatus(config.configured ? 'connected' : 'not connected', config.configured ? 'success' : '');
  if (!config.configured) renderWebdavBackups([]);
}

async function loadWebdavBackup() {
  if (!document.getElementById('webdav-backup-card')) return;
  const generation = ++_webdavLoadGeneration;
  _setWebdavStatus('checking connection…');
  try {
    const response = await fetch('/api/backup/webdav');
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'could not check WebDAV'));
    if (generation !== _webdavLoadGeneration) return;
    const config = normalizeWebdavBackupConfig(data);
    _applyWebdavConfig(config);
    if (config.configured) await loadWebdavBackups(false);
  } catch (error) {
    if (generation !== _webdavLoadGeneration) return;
    _webdavConfigured = false;
    _setWebdavStatus(error.message || 'could not check WebDAV', 'error');
    renderWebdavBackups([]);
  }
}

async function saveWebdavBackup() {
  const url = document.getElementById('webdav-backup-url');
  const username = document.getElementById('webdav-backup-username');
  const password = document.getElementById('webdav-backup-password');
  const button = document.getElementById('webdav-backup-save-btn');
  const passwordValue = password?.value || '';
  if (password) password.value = '';
  let payload;
  try {
    payload = webdavBackupConfigPayload(url?.value, username?.value, passwordValue, _webdavConfigured);
  } catch (error) {
    _setWebdavStatus(error.message, 'error');
    toast(error.message, 'error');
    return;
  }
  if (button) { button.disabled = true; button.textContent = 'saving…'; }
  _setWebdavStatus('checking and saving…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/webdav', {
      method: 'PUT',
      headers: {'content-type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'WebDAV connection was not saved', [passwordValue]));
    const config = normalizeWebdavBackupConfig(data);
    _applyWebdavConfig(config);
    _setWebdavStatus('connected and saved', 'success');
    toast('WebDAV connection saved', 'success');
    await loadWebdavBackups(false);
  } catch (error) {
    _setWebdavStatus(error.message || 'WebDAV connection was not saved', 'error');
    toast(error.message || 'WebDAV connection was not saved', 'error');
  } finally {
    if (button) { button.disabled = false; button.textContent = _webdavConfigured ? 'save connection' : 'connect and save'; }
  }
}

async function disconnectWebdavBackup() {
  if (!await _dlgConfirm('disconnect WebDAV backup? remote backups will stay on the server.')) return;
  const button = document.getElementById('webdav-backup-disconnect-btn');
  if (button) button.disabled = true;
  _setWebdavStatus('disconnecting…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/webdav', { method: 'DELETE' });
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'WebDAV could not be disconnected'));
    _applyWebdavConfig(normalizeWebdavBackupConfig({}));
    toast('WebDAV disconnected', 'success');
  } catch (error) {
    _setWebdavStatus(error.message || 'WebDAV could not be disconnected', 'error');
    toast(error.message || 'WebDAV could not be disconnected', 'error');
  } finally {
    if (button) button.disabled = false;
  }
}

async function runWebdavBackup() {
  if (!_webdavConfigured) return;
  const button = document.getElementById('webdav-backup-run-btn');
  if (button) { button.disabled = true; button.textContent = 'backing up…'; }
  _setWebdavStatus('creating and uploading encrypted backup…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/webdav/run', { method: 'POST' });
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'WebDAV backup failed'));
    const lastSuccess = document.getElementById('webdav-backup-last-success');
    if (lastSuccess) lastSuccess.textContent = _formatWebdavTime(data.last_backup_at);
    const lastVerified = document.getElementById('webdav-backup-last-verified');
    if (lastVerified) lastVerified.textContent = _formatWebdavTime(data.last_verified_at);
    const warning = String(data.status_warning || '');
    _setWebdavStatus(warning || 'backup uploaded and verified', warning ? '' : 'success');
    toast(warning || 'WebDAV backup complete', warning ? '' : 'success', warning ? 6000 : 3000);
    await loadWebdavBackups(false);
  } catch (error) {
    _setWebdavStatus(error.message || 'WebDAV backup failed', 'error');
    toast(error.message || 'WebDAV backup failed', 'error');
  } finally {
    if (button) { button.disabled = !_webdavConfigured; button.textContent = 'back up now'; }
  }
}

async function loadWebdavBackups(announce = false) {
  const refresh = document.getElementById('webdav-backup-refresh-btn');
  const selection = document.getElementById('webdav-backup-selection');
  if (!_webdavConfigured) {
    renderWebdavBackups([]);
    return;
  }
  if (refresh) { refresh.disabled = true; refresh.textContent = 'refreshing…'; }
  if (selection) selection.textContent = 'loading remote backups…';
  try {
    const response = await fetch('/api/backup/webdav/backups');
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'could not load remote backups'));
    renderWebdavBackups(webdavBackupsFromResponse(data));
    if (announce) toast('remote backups refreshed', 'success');
  } catch (error) {
    renderWebdavBackups([]);
    if (selection) selection.textContent = error.message || 'could not load remote backups';
    if (announce) toast(error.message || 'could not load remote backups', 'error');
  } finally {
    if (refresh) { refresh.disabled = !_webdavConfigured; refresh.textContent = 'refresh backups'; }
  }
}

function renderWebdavBackups(backups) {
  _webdavBackups = backups;
  const select = document.getElementById('webdav-backup-list');
  if (!select) return;
  const previous = select.value;
  select.replaceChildren();
  if (!backups.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'no remote backups found';
    select.appendChild(option);
    select.disabled = true;
  } else {
    for (const backup of backups) {
      const option = document.createElement('option');
      option.value = backup.filename;
      option.textContent = backup.filename;
      select.appendChild(option);
    }
    select.disabled = false;
    select.value = backups.some(backup => backup.filename === previous) ? previous : backups[0].filename;
  }
  renderWebdavSelection();
}

function renderWebdavSelection() {
  const select = document.getElementById('webdav-backup-list');
  const selected = _webdavBackups.find(backup => backup.filename === select?.value);
  const label = document.getElementById('webdav-backup-selection');
  const restore = document.getElementById('webdav-backup-restore-btn');
  if (restore) restore.disabled = !selected;
  if (!label) return;
  if (!selected) {
    label.textContent = _webdavConfigured ? 'no remote backups yet.' : 'connect WebDAV to list backups.';
    return;
  }
  const details = [selected.filename];
  const size = _formatWebdavBytes(selected.bytes);
  if (size) details.push(size);
  if (selected.modified_at) details.push(_formatWebdavTime(selected.modified_at));
  label.textContent = details.join(' · ');
}

async function restoreWebdavBackup() {
  const select = document.getElementById('webdav-backup-list');
  const filename = select?.value || '';
  if (!filename) return;
  const keyInput = document.getElementById('webdav-backup-recovery-key');
  const keyFile = keyInput?.files[0];
  const status = document.getElementById('webdav-backup-restore-status');
  const button = document.getElementById('webdav-backup-restore-btn');
  const form = new FormData();
  form.append('filename', filename);
  if (keyFile) form.append('recovery_key', keyFile, keyFile.name);
  if (status) { status.hidden = false; status.textContent = 'downloading, verifying, and staging…'; }
  if (button) { button.disabled = true; button.textContent = 'staging…'; }
  try {
    const response = await _fetchWithRecentOwner('/api/backup/webdav/restore', { method: 'POST', body: form });
    const data = await _webdavResponseJson(response);
    if (!response.ok) throw new Error(_webdavError(data, 'remote backup could not be staged'));
    const command = data.apply_command || 'alles restore apply <restore-id>';
    if (status) status.textContent = `verified and staged. live data is unchanged. stop Alles, then run: ${command}`;
    toast('remote backup verified and staged', 'success');
  } catch (error) {
    if (status) status.textContent = error.message || 'remote backup could not be staged';
    toast(error.message || 'remote backup could not be staged', 'error');
  } finally {
    if (button) { button.disabled = !filename; button.textContent = 'verify and stage selected restore'; }
    if (keyInput) keyInput.value = '';
    const keyName = document.getElementById('webdav-backup-recovery-key-name');
    if (keyName) keyName.textContent = 'no separate key selected';
  }
}

// ── s3 backup ────────────────────────────────────────────────────────────────
let _s3Configured = false;
let _s3CredentialsSet = false;
let _s3Backups = [];
let _s3LoadGeneration = 0;

export function normalizeS3BackupConfig(payload = {}) {
  const value = payload && typeof payload.s3 === 'object' ? payload.s3 : payload;
  return {
    configured: value?.configured === true,
    endpoint: String(value?.endpoint || ''),
    region: String(value?.region || ''),
    bucket: String(value?.bucket || ''),
    prefix: String(value?.prefix || ''),
    addressing_style: value?.addressing_style === 'virtual' ? 'virtual' : 'path',
    credentials_set: value?.credentials_set === true,
    last_backup_at: String(value?.last_backup_at || ''),
    last_verified_at: String(value?.last_verified_at || ''),
    last_filename: String(value?.last_filename || ''),
    last_bytes: Number.isFinite(Number(value?.last_bytes)) ? Number(value.last_bytes) : null,
    error: String(value?.error || ''),
  };
}

export function s3BackupConfigPayload(
  endpoint,
  region,
  bucket,
  prefix,
  addressingStyle,
  accessKeyId,
  secretAccessKey,
  hasSavedCredentials = false,
) {
  const endpointValue = String(endpoint || '').trim();
  const regionValue = String(region || '').trim();
  const bucketValue = String(bucket || '').trim();
  const prefixValue = String(prefix || '').trim();
  const styleValue = String(addressingStyle || 'path');
  const accessKeyValue = String(accessKeyId || '');
  const secretValue = String(secretAccessKey || '');
  if (!endpointValue) throw new Error('add the S3 https endpoint');
  let parsed;
  try { parsed = new URL(endpointValue); } catch { throw new Error('enter a valid S3 endpoint'); }
  if (parsed.protocol !== 'https:') throw new Error('the S3 endpoint must use https');
  if (parsed.username || parsed.password) throw new Error('keep S3 credentials out of the endpoint');
  if (parsed.search || parsed.hash) throw new Error('the S3 endpoint cannot include a query or fragment');
  if (!regionValue) throw new Error('add the S3 region');
  if (!bucketValue) throw new Error('add the existing S3 bucket');
  if (!['path', 'virtual'].includes(styleValue)) throw new Error('choose path or virtual addressing');
  if (!!accessKeyValue !== !!secretValue) throw new Error('enter both S3 credentials together');
  if (!accessKeyValue && !hasSavedCredentials) throw new Error('add the S3 credential pair');
  const result = {
    endpoint: parsed.toString(),
    region: regionValue,
    bucket: bucketValue,
    prefix: prefixValue,
    addressing_style: styleValue,
  };
  if (accessKeyValue && secretValue) {
    result.access_key_id = accessKeyValue;
    result.secret_access_key = secretValue;
  }
  return result;
}

export function s3BackupsFromResponse(payload = {}) {
  const values = Array.isArray(payload) ? payload : payload?.backups;
  if (!Array.isArray(values)) return [];
  return values.map(value => {
    if (typeof value === 'string') return { filename: value, bytes: null, modified_at: '' };
    const bytes = Number(value?.bytes);
    return {
      filename: String(value?.filename || ''),
      bytes: Number.isFinite(bytes) && bytes >= 0 ? bytes : null,
      modified_at: String(value?.modified_at || value?.last_modified || ''),
    };
  }).filter(value => value.filename).sort((left, right) => {
    const leftTime = Date.parse(left.modified_at);
    const rightTime = Date.parse(right.modified_at);
    if (!Number.isFinite(leftTime) || !Number.isFinite(rightTime)) return 0;
    return rightTime - leftTime;
  });
}

function _formatS3Time(value) {
  if (!value) return 'never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'unknown' : date.toLocaleString();
}

function _formatS3Bytes(value) {
  if (!Number.isFinite(value) || value < 0) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

async function _s3ResponseJson(response) {
  return response.json().catch(() => ({}));
}

function _s3Error(data, fallback, secrets = []) {
  let message = typeof data?.detail === 'string' && data.detail.trim() ? data.detail.trim() : fallback;
  for (const secret of secrets) {
    if (secret) message = message.split(secret).join('[hidden]');
  }
  return message;
}

function _setS3Status(message, kind = '') {
  const status = document.getElementById('s3-backup-status');
  if (!status) return;
  status.textContent = message;
  status.style.color = kind === 'error' ? 'var(--error)' : (kind === 'success' ? 'var(--green)' : 'var(--muted)');
}

function _applyS3Config(config) {
  _s3Configured = config.configured;
  _s3CredentialsSet = config.credentials_set;
  const endpoint = document.getElementById('s3-backup-endpoint');
  const region = document.getElementById('s3-backup-region');
  const bucket = document.getElementById('s3-backup-bucket');
  const prefix = document.getElementById('s3-backup-prefix');
  const addressingStyle = document.getElementById('s3-backup-addressing-style');
  const accessKey = document.getElementById('s3-backup-access-key-id');
  const secretKey = document.getElementById('s3-backup-secret-access-key');
  if (endpoint) endpoint.value = config.endpoint;
  if (region) region.value = config.region;
  if (bucket) bucket.value = config.bucket;
  if (prefix) prefix.value = config.prefix;
  if (addressingStyle) addressingStyle.value = config.addressing_style;
  if (accessKey) accessKey.value = '';
  if (secretKey) secretKey.value = '';
  const save = document.getElementById('s3-backup-save-btn');
  if (save) save.textContent = config.configured ? 'save connection' : 'connect and save';
  const disconnect = document.getElementById('s3-backup-disconnect-btn');
  if (disconnect) {
    disconnect.hidden = !config.configured && !config.error;
    disconnect.textContent = config.error ? 'remove broken settings' : 'disconnect';
  }
  const run = document.getElementById('s3-backup-run-btn');
  if (run) run.disabled = !config.configured;
  const refresh = document.getElementById('s3-backup-refresh-btn');
  if (refresh) refresh.disabled = !config.configured;
  const lastSuccess = document.getElementById('s3-backup-last-success');
  if (lastSuccess) lastSuccess.textContent = _formatS3Time(config.last_backup_at);
  const lastVerified = document.getElementById('s3-backup-last-verified');
  if (lastVerified) lastVerified.textContent = _formatS3Time(config.last_verified_at);
  if (config.error) _setS3Status(config.error, 'error');
  else _setS3Status(config.configured ? 'connected' : 'not connected', config.configured ? 'success' : '');
  if (!config.configured) renderS3Backups([]);
}

async function loadS3Backup() {
  if (!document.getElementById('s3-backup-card')) return;
  const generation = ++_s3LoadGeneration;
  _setS3Status('checking connection…');
  try {
    const response = await fetch('/api/backup/s3');
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'could not check S3'));
    if (generation !== _s3LoadGeneration) return;
    const config = normalizeS3BackupConfig(data);
    _applyS3Config(config);
    if (config.configured) await loadS3Backups(false);
  } catch (error) {
    if (generation !== _s3LoadGeneration) return;
    _s3Configured = false;
    _s3CredentialsSet = false;
    _setS3Status(error.message || 'could not check S3', 'error');
    renderS3Backups([]);
  }
}

async function saveS3Backup() {
  const endpoint = document.getElementById('s3-backup-endpoint');
  const region = document.getElementById('s3-backup-region');
  const bucket = document.getElementById('s3-backup-bucket');
  const prefix = document.getElementById('s3-backup-prefix');
  const addressingStyle = document.getElementById('s3-backup-addressing-style');
  const accessKey = document.getElementById('s3-backup-access-key-id');
  const secretKey = document.getElementById('s3-backup-secret-access-key');
  const button = document.getElementById('s3-backup-save-btn');
  const accessKeyValue = accessKey?.value || '';
  const secretValue = secretKey?.value || '';
  if (accessKey) accessKey.value = '';
  if (secretKey) secretKey.value = '';
  let payload;
  try {
    payload = s3BackupConfigPayload(
      endpoint?.value,
      region?.value,
      bucket?.value,
      prefix?.value,
      addressingStyle?.value,
      accessKeyValue,
      secretValue,
      _s3CredentialsSet,
    );
  } catch (error) {
    _setS3Status(error.message, 'error');
    toast(error.message, 'error');
    return;
  }
  if (button) { button.disabled = true; button.textContent = 'checking…'; }
  _setS3Status('creating and removing a probe object…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/s3', {
      method: 'PUT',
      headers: {'content-type':'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'S3 connection was not saved', [accessKeyValue, secretValue]));
    const config = normalizeS3BackupConfig(data);
    _applyS3Config(config);
    _setS3Status('connected and saved', 'success');
    toast('S3 connection saved', 'success');
    await loadS3Backups(false);
  } catch (error) {
    _setS3Status(error.message || 'S3 connection was not saved', 'error');
    toast(error.message || 'S3 connection was not saved', 'error');
  } finally {
    if (button) { button.disabled = false; button.textContent = _s3Configured ? 'save connection' : 'connect and save'; }
  }
}

async function disconnectS3Backup() {
  if (!await _dlgConfirm('disconnect S3 backup? remote backups will stay in the bucket.')) return;
  const button = document.getElementById('s3-backup-disconnect-btn');
  if (button) button.disabled = true;
  _setS3Status('disconnecting…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/s3', { method: 'DELETE' });
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'S3 could not be disconnected'));
    _applyS3Config(normalizeS3BackupConfig({}));
    toast('S3 disconnected', 'success');
  } catch (error) {
    _setS3Status(error.message || 'S3 could not be disconnected', 'error');
    toast(error.message || 'S3 could not be disconnected', 'error');
  } finally {
    if (button) button.disabled = false;
  }
}

async function runS3Backup() {
  if (!_s3Configured) return;
  const button = document.getElementById('s3-backup-run-btn');
  if (button) { button.disabled = true; button.textContent = 'backing up…'; }
  _setS3Status('creating and copying encrypted backup…');
  try {
    const response = await _fetchWithRecentOwner('/api/backup/s3/run', { method: 'POST' });
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'S3 backup failed'));
    const lastSuccess = document.getElementById('s3-backup-last-success');
    if (lastSuccess) lastSuccess.textContent = _formatS3Time(data.last_backup_at);
    const lastVerified = document.getElementById('s3-backup-last-verified');
    if (lastVerified) {
      lastVerified.textContent = _formatS3Time(data.last_verified_at || data.completed_at || data.last_backup_at);
    }
    const warning = String(data.status_warning || '');
    _setS3Status(warning || 'backup copied and verified by read-back', warning ? '' : 'success');
    toast(warning || 'S3 backup complete', warning ? '' : 'success', warning ? 6000 : 3000);
    await loadS3Backups(false);
  } catch (error) {
    _setS3Status(error.message || 'S3 backup failed', 'error');
    toast(error.message || 'S3 backup failed', 'error');
  } finally {
    if (button) { button.disabled = !_s3Configured; button.textContent = 'back up now'; }
  }
}

async function loadS3Backups(announce = false) {
  const refresh = document.getElementById('s3-backup-refresh-btn');
  const selection = document.getElementById('s3-backup-selection');
  if (!_s3Configured) {
    renderS3Backups([]);
    return;
  }
  if (refresh) { refresh.disabled = true; refresh.textContent = 'refreshing…'; }
  if (selection) selection.textContent = 'loading remote backups…';
  try {
    const response = await fetch('/api/backup/s3/backups');
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'could not load remote backups'));
    renderS3Backups(s3BackupsFromResponse(data));
    if (announce) toast('remote backups refreshed', 'success');
  } catch (error) {
    renderS3Backups([]);
    if (selection) selection.textContent = error.message || 'could not load remote backups';
    if (announce) toast(error.message || 'could not load remote backups', 'error');
  } finally {
    if (refresh) { refresh.disabled = !_s3Configured; refresh.textContent = 'refresh backups'; }
  }
}

function renderS3Backups(backups) {
  _s3Backups = backups;
  const select = document.getElementById('s3-backup-list');
  if (!select) return;
  const previous = select.value;
  select.replaceChildren();
  if (!backups.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'no remote backups found';
    select.appendChild(option);
    select.disabled = true;
  } else {
    for (const backup of backups) {
      const option = document.createElement('option');
      option.value = backup.filename;
      option.textContent = backup.filename;
      select.appendChild(option);
    }
    select.disabled = false;
    select.value = backups.some(backup => backup.filename === previous) ? previous : backups[0].filename;
  }
  renderS3Selection();
}

function renderS3Selection() {
  const select = document.getElementById('s3-backup-list');
  const selected = _s3Backups.find(backup => backup.filename === select?.value);
  const label = document.getElementById('s3-backup-selection');
  const restore = document.getElementById('s3-backup-restore-btn');
  if (restore) restore.disabled = !selected;
  if (!label) return;
  if (!selected) {
    label.textContent = _s3Configured ? 'no remote backups yet.' : 'connect S3 to list backups.';
    return;
  }
  const details = [selected.filename];
  const size = _formatS3Bytes(selected.bytes);
  if (size) details.push(size);
  if (selected.modified_at) details.push(_formatS3Time(selected.modified_at));
  label.textContent = details.join(' · ');
}

async function restoreS3Backup() {
  const select = document.getElementById('s3-backup-list');
  const filename = select?.value || '';
  if (!filename) return;
  const keyInput = document.getElementById('s3-backup-recovery-key');
  const keyFile = keyInput?.files[0];
  const status = document.getElementById('s3-backup-restore-status');
  const button = document.getElementById('s3-backup-restore-btn');
  const form = new FormData();
  form.append('filename', filename);
  if (keyFile) form.append('recovery_key', keyFile, keyFile.name);
  if (status) { status.hidden = false; status.textContent = 'downloading, verifying, and staging…'; }
  if (button) { button.disabled = true; button.textContent = 'staging…'; }
  try {
    const response = await _fetchWithRecentOwner('/api/backup/s3/restore', { method: 'POST', body: form });
    const data = await _s3ResponseJson(response);
    if (!response.ok) throw new Error(_s3Error(data, 'remote backup could not be staged'));
    const command = data.apply_command || 'alles restore apply <restore-id>';
    if (status) status.textContent = `verified and staged. live data is unchanged. stop Alles, then run: ${command}`;
    toast('remote backup verified and staged', 'success');
  } catch (error) {
    if (status) status.textContent = error.message || 'remote backup could not be staged';
    toast(error.message || 'remote backup could not be staged', 'error');
  } finally {
    if (button) { button.disabled = !filename; button.textContent = 'verify and stage selected restore'; }
    if (keyInput) keyInput.value = '';
    const keyName = document.getElementById('s3-backup-recovery-key-name');
    if (keyName) keyName.textContent = 'no separate key selected';
  }
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

const _MODEL_ROLE_COPY = {
  aide_chat: ['Aide Chat', 'normal chats and agent work'],
  andromeda: ['Andromeda', 'search answers and research'],
  jarvis: ['Jarvis', 'background checks and scheduled work'],
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
    select.addEventListener('change', () => {
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
    toast('model defaults saved', 'success');
    await loadEpList();
  } catch (error) {
    toast(error.message || 'defaults could not be saved', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'save defaults';
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
  if (!el) return;
  try {
    const [epsResponse, settingsResponse, rolesResponse] = await Promise.all([
      fetch('/api/models'), fetch('/api/settings'), fetch('/api/models/roles'),
    ]);
    const eps = await _endpointJson(epsResponse);
    const settings = await _endpointJson(settingsResponse);
    const roles = await _endpointJson(rolesResponse);
    _renderModelRoles(eps, settings, roles);
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
            <div class="s-ep-meta">${_esc(ep.base_url)} · ${ep.models?.length || 0} ready · ${_esc(ep.health_status || 'unverified')}${unavailable ? ` · ${unavailable} unavailable` : ''}</div>
          </div>
          <div class="s-ep-actions">
            <button class="btn" data-probe="${_escAttr(ep.id)}">refresh</button>
            <button class="btn" data-test-ep="${_escAttr(ep.id)}">test</button>
            <button class="btn" data-edit-list="${_escAttr(ep.id)}" aria-expanded="false">models</button>
            <button class="btn danger" data-del="${_escAttr(ep.id)}" aria-label="remove ${_escAttr(ep.name)}">×</button>
          </div>
        </div>
        <div class="s-ep-editor" data-editor="${_escAttr(ep.id)}" hidden>
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
        btn.disabled = true; btn.textContent = 'saving…';
        try {
          const patch = { provider_adapter: adapter };
          if (adapter === 'manual') patch.models = models;
          await _endpointJson(await fetch(`/api/models/endpoint/${btn.dataset.saveList}`, {
            method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(patch),
          }));
          if (adapter !== 'manual') {
            await _endpointJson(await fetch(`/api/models/endpoint/${btn.dataset.saveList}/probe`, { method: 'POST' }));
          }
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
          loadEpList(); loadModels(); renderModelList();
        } catch (error) { toast(error.message || 'catalog refresh failed', 'error'); }
        finally { btn.textContent = 'refresh'; btn.disabled = false; }
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
    el.querySelectorAll('[data-del]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!await _dlgConfirm('remove this endpoint?')) return;
        try {
          await _endpointJson(await fetch(`/api/models/endpoint/${btn.dataset.del}`, { method: 'DELETE' }));
          toast('endpoint removed', 'success');
          loadEpList(); loadModels(); renderModelList();
        } catch (error) { toast(error.message || 'endpoint could not be removed', 'error'); }
      });
    });
  } catch {
    el.innerHTML = '<div class="s-role-empty error">model settings could not be loaded.</div>';
    const roles = document.getElementById('s-model-roles');
    if (roles) roles.innerHTML = '<div class="s-role-empty error">model defaults could not be loaded.</div>';
  }
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
  const hasKey = keyField ? (s[keyField] || s[`${keyField}_configured`]) : true;
  const missing  = (keyField && !hasKey) || (urlField && !s[urlField]);
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
  // server-backed general settings
  fetch('/api/settings').then(r => r.json()).then(s => {
    _bindSwitchOnce(document.getElementById('s-memory-inject-toggle'),
      () => s.memory_auto_inject !== false,
      on => _patchSettings({ memory_auto_inject: on })
    );
    _bindLocalizationFields(s);
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
}

function _bindLocalizationFields(settings) {
  const language = document.getElementById('s-language');
  const region = document.getElementById('s-region');
  const timezone = document.getElementById('s-timezone');
  const detected = document.getElementById('s-timezone-detected');
  if (language) setDropdownValue(language, settings.language || 'en');
  if (region) region.value = settings.region || '';
  if (timezone) timezone.value = settings.timezone || '';
  if (detected) {
    const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'unknown';
    detected.textContent = `browser time zone: ${browserZone}`;
  }
  const save = document.getElementById('s-locale-save');
  if (!save || save.dataset.bound) return;
  save.dataset.bound = '1';
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      const response = await fetch('/api/settings', {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          language: getDropdownValue(language) || 'en',
          region: region?.value.trim() || '',
          timezone: timezone?.value.trim() || '',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'language settings could not be saved');
      configureLocalization(data);
      if (region) region.value = data.region || '';
      if (timezone) timezone.value = data.timezone || '';
      toast('language and region saved', 'success');
    } catch (error) {
      toast(error.message || 'language settings could not be saved', 'error');
    } finally {
      save.disabled = false;
    }
  });
}

// themes pane: the inline full editor + keeping the default-theme controls' lock state in
// sync (a fancy preset owns mode + accent, so those controls lock while it's active).
let _inlineEditorBuilt = false;
function loadThemesPane() {
  const host = document.getElementById('theme-editor-inline');
  if (host && !_inlineEditorBuilt) {
    _inlineEditorBuilt = true;
    renderThemeEditorInto(host, { onChange: _refreshThemeLock });
  }
  _refreshThemeLock();
}

// when a fancy preset is active, the default-theme mode + accent are dictated by it — lock
// those controls (visually + functionally) and say so; picking 'default' in the editor (or
// a mode button, which always drops to default) unlocks them.
function _refreshThemeLock() {
  let preset = 'dark';
  try { preset = _getAppearance().preset || 'dark'; } catch { /* default */ }
  const locked = !isBasePreset(preset) && preset !== 'custom';
  const note = document.getElementById('s-theme-lock-note');
  const dt = document.getElementById('s-default-theme');
  if (dt) dt.classList.toggle('locked', locked);
  if (note) {
    note.style.display = locked ? '' : 'none';
    note.textContent = locked ? `mode + accent are set by the "${preset}" theme — pick "default" below to customize them` : '';
  }
  _markAccent();
  _markMode();
}

// ── theme mode + accent color ─────────────────────────────────────────────────
const ACCENT_PRESETS = [
  ['#818cf8', 'indigo'], ['#a78bfa', 'purple'], ['#60a5fa', 'blue'], ['#22d3ee', 'cyan'],
  ['#34d399', 'emerald'], ['#4ade80', 'green'], ['#facc15', 'yellow'], ['#fb923c', 'orange'],
  ['#f87171', 'red'], ['#f472b6', 'pink'], ['#e879f9', 'fuchsia'], ['#e8e6e3', 'mono'],
];
const DEFAULT_ACCENT = '#818cf8';
// accent + mode now live in the unified appearance object (theme.js), so they survive reload
// and stop fighting presets. these read/write through that, not the old aide-* localStorage.
const _curAccent = () => {
  let a; try { a = _getAppearance(); } catch { /* default */ }
  return ((a && a.colors && a.colors.accent) || DEFAULT_ACCENT).toLowerCase();
};

function applyAccent(hex) {
  _themeSetAccent(hex || '');                 // writes colors.accent into the appearance object
  _markAccent();
  window._updateFavicon?.();
  _patchSettings({ accent: hex || '' });      // legacy mirror so other subdomains stay in sync
}
function applyThemeMode(mode) {
  // "default theme" = a clean slate: reset every fancy extra (frosted/pattern/density/font/
  // effect) to default for the chosen base, same as the default preset tile. leaving a fancy
  // preset also drops its accent tint back to default; a plain base keeps the accent you set.
  _resetToDefault(mode === 'light' ? 'light' : 'dark');
  _markMode();
  _markAccent();   // the tint may have reset — re-mark the active swatch
  window._updateFavicon?.();
  _patchSettings({ theme: mode === 'light' ? 'light' : '' });
  _refreshThemeLock();                        // switching to default unlocks the controls
}
function _markAccent() {
  const cur = _curAccent();
  document.querySelectorAll('#s-accent-swatches .accent-swatch').forEach(s =>
    s.classList.toggle('active', s.dataset.hex.toLowerCase() === cur));
  const hexInp = document.getElementById('s-accent-hex'); if (hexInp) hexInp.value = cur;
}
function _markMode() {
  const cur = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  document.querySelectorAll('.theme-mode-btn').forEach(b => b.classList.toggle('active', b.dataset.themeMode === cur));
}
function _loadThemeColorControls() {
  // theme mode buttons
  _markMode();
  document.querySelectorAll('.theme-mode-btn').forEach(b => {
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
    document.documentElement.style.setProperty('--accent', s.dataset.hex || ((JSON.parse(localStorage.getItem('alles-appearance')||'{}').colors||{}).accent || '#818cf8'));
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
  const cfg = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  _bindSwitchOnce(document.getElementById('s-agent-ctx-toggle'),
    () => cfg.agent_context_files !== false, v => _patchSetting('agent_context_files', v));
  _bindSwitchOnce(document.getElementById('s-agent-sandbox-toggle'),
    () => !!cfg.agent_sandbox, v => _patchSetting('agent_sandbox', v));
  _bindSwitchOnce(document.getElementById('s-agent-computer-toggle'),
    () => !!cfg.agent_computer_use, v => _patchSetting('agent_computer_use', v));
  _bindSwitchOnce(document.getElementById('s-agent-subagents-toggle'),
    () => cfg.agent_subagents !== false, v => _patchSetting('agent_subagents', v));
  const roots = document.getElementById('s-agent-roots');
  if (roots) roots.value = (cfg.agent_allowed_roots || []).join('\n');
  const rootsSave = document.getElementById('s-agent-roots-save');
  if (rootsSave && !rootsSave.dataset.bound) {
    rootsSave.dataset.bound = '1';
    rootsSave.addEventListener('click', async () => {
      const values = (roots?.value || '').split('\n').map(value => value.trim()).filter(Boolean);
      const response = await _fetchWithRecentOwner('/api/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ agent_allowed_roots: values }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) { toast(data.detail || 'approved roots could not be saved', 'error'); return; }
      if (roots) roots.value = (data.agent_allowed_roots || []).join('\n');
      toast('approved roots saved', 'success');
    });
  }
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
    + row(`Photos (PhotoKit)${cap.photokit_authorization && !cap.photokit_ready ? ` — ${_esc(cap.photokit_authorization.replace('_', ' '))}` : ''}`, cap.photokit_ready)
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
    const r = await _fetchWithRecentOwner(`/api/mcp/presets/${encodeURIComponent(id)}`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ params: {} }),
    });
    if (!r.ok) throw new Error(r.status);
    toast('connector added — edit its args if it needs a path/key', 'success');
    loadMcpServers();
  } catch { toast('could not add connector', 'error'); }
}

window._rmMcp = async btn => {
  await _fetchWithRecentOwner(`/api/mcp/servers/${btn.dataset.id}`, { method: 'DELETE' });
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
  const r = await _fetchWithRecentOwner('/api/connections', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ service, token }),
  });
  if (r.ok) { toast(`${service} connected`, 'success'); document.getElementById('conn-token').value = ''; loadConnections(); }
  else toast('connect failed', 'error');
}

window._rmConn = async btn => {
  await _fetchWithRecentOwner(`/api/connections/${btn.dataset.id}`, { method: 'DELETE' });
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
  const response = await _fetchWithRecentOwner('/api/mcp/servers', {
    method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, transport, command: cmd, args, url, env, headers }),
  });
  if (!response.ok) { toast('could not add mcp server', 'error'); return; }
  document.getElementById('mcp-name').value = '';
  document.getElementById('mcp-command').value = '';
  document.getElementById('mcp-url').value = '';
  document.getElementById('mcp-env').value = '';
  document.getElementById('mcp-headers').value = '';
  toast('mcp server added', 'success');
  loadMcpServers();
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
      <span class="row-meta">${(t.scopes || []).map(_esc).join(', ') || 'no access'}</span>
      <span class="row-meta">${t.last_used_at ? 'used ' + new Date(t.last_used_at).toLocaleDateString() : 'never used'}</span>
      <button class="act-btn" data-id="${t.id}" onclick="window._rmToken(this)">revoke</button>
    </div>`).join('');
}

window._rmToken = async btn => {
  const r = await _fetchWithRecentOwner(`/api/tokens/${btn.dataset.id}`, { method: 'DELETE' });
  if (!r.ok) { toast('token could not be revoked', 'error'); return; }
  loadTokens();
};

async function _confirmRecentOwner() {
  const me = await fetch('/api/auth/me').then(r => r.json()).catch(() => null);
  if (me && me.enabled === false) return true;
  const password = await _dlgPrompt('enter your Alles password to continue', '', { secret: true });
  if (password == null) return false;
  const r = await fetch('/api/auth/reauth', {
    method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ password }),
  });
  if (!r.ok) { toast('password confirmation failed', 'error'); return false; }
  return true;
}

async function _fetchWithRecentOwner(input, init) {
  let r = await fetch(input, init);
  if (r.status === 403 && await _confirmRecentOwner()) r = await fetch(input, init);
  return r;
}

async function generateToken() {
  const name = document.getElementById('token-name').value.trim();
  if (!name) { toast('name required', 'error'); return; }
  const scopes = [...document.querySelectorAll('[data-token-scope].active')]
    .map(btn => btn.dataset.tokenScope);
  if (!scopes.length) { toast('choose at least one permission', 'error'); return; }
  const create = () => _fetchWithRecentOwner('/api/tokens', {
    method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ name, scopes }),
  });
  const r = await create();
  const data = await r.json();
  if (!r.ok) { toast(data.detail || 'token could not be created', 'error'); return; }
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

  // learned per-category weights - shows the user the loop is actually adapting
  const learn = document.getElementById('s-prox-learning');
  if (learn) {
    const stats = await fetch('/api/proactive/stats').then(r => r.json()).catch(() => ({}));
    const cats = Object.entries(stats || {}).filter(([, c]) => (c.acted || 0) + (c.dismissed || 0) + (c.ignored || 0) > 0);
    learn.innerHTML = cats.length
      ? '<div class="s-prox-learn-h">learned from your clicks</div>' + cats
          .sort((a, b) => (b[1].act_rate || 0) - (a[1].act_rate || 0))
          .map(([cat, c]) => `<div class="prox-stat-row"><span class="prox-stat-cat">${_esc(cat)}</span><span class="prox-stat-nums">${Math.round((c.act_rate || 0) * 100)}% acted</span><span class="prox-stat-weight">x${(c.weight == null ? 1 : c.weight).toFixed(2)}</span></div>`).join('')
      : '';
  }
}

async function loadIntelligencePane() {
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
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
  sw('s-intel-insights', 'insights_enabled', false);
  sw('s-intel-insights-inject', 'insights_auto_inject', true);
  sw('s-intel-distill', 'user_model_distill', false);
  sw('s-intel-distill-inject', 'distilled_auto_inject', true);
  sw('s-intel-suggest', 'intent_suggestions', true);
  sw('s-intel-session', 'session_context_inject', true);

  const status = document.getElementById('s-intel-status');
  const runBtn = (id, path, label) => {
    const b = document.getElementById(id);
    if (!b || b.dataset.bound) return;
    b.dataset.bound = '1';
    b.addEventListener('click', async () => {
      b.disabled = true;
      if (status) status.textContent = 'thinking...';
      try {
        const r = await fetch(path, { method: 'POST' }).then(r => r.json());
        if (status) status.textContent = `done - ${r.count || 0} new ${label}`;
      } catch { if (status) status.textContent = 'run failed'; }
      b.disabled = false;
    });
  };
  runBtn('s-intel-insights-run', '/api/insights/run', 'insight(s)');
  runBtn('s-intel-distill-run', '/api/memory/distill/run', 'fact(s)');
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
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
  { label: '✈ briefing → discord/telegram', trigger: 'daily_at', trigger_arg: '08:00', action: 'notify_digest', action_arg: '', name: 'morning briefing' },
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
      actArg.style.display = ['push_digest', 'notify_digest'].includes(actEl.dataset.value) ? 'none' : '';
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
  // delivery channels (discord / telegram) persist as settings; the notify actions use them
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  for (const [id, key] of [['s-notify-discord', 'notify_discord_webhook'],
                           ['s-notify-tgtoken', 'notify_telegram_token'],
                           ['s-notify-tgchat', 'notify_telegram_chat_id']]) {
    const el = document.getElementById(id);
    if (!el) continue;
    if (s[key] !== undefined && document.activeElement !== el) el.value = s[key] || '';
    if (!el.dataset.bound) {
      el.dataset.bound = '1';
      let t;
      el.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => _patchSetting(key, el.value.trim()), 500); });
    }
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
        ${r.last_attempt && r.last_attempt.status !== 'succeeded' ? `<span class="rule-row-desc" title="${_esc(r.last_attempt.error || '')}">last attempt: <b>${_esc(r.last_attempt.status)}</b></span>` : ''}
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
