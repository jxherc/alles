// server-owned first-run setup: resumable across browsers and safe to dismiss.
import { toast } from './util.js';
import { addEndpoint } from './models.js?v=212';
import { resolvedTimeZone } from './i18n.js';

const MODEL_PRESETS = [
  { name: 'DeepSeek', url: 'https://api.deepseek.com', key: 'sk-…' },
  { name: 'Anthropic', url: 'https://api.anthropic.com', key: 'sk-ant-…' },
  { name: 'OpenAI', url: 'https://api.openai.com', key: 'sk-…' },
  { name: 'Gemini', url: 'https://generativelanguage.googleapis.com/v1beta/openai', key: 'AIza…' },
  { name: 'Moonshot', url: 'https://api.moonshot.ai', key: 'sk-…' },
  { name: 'Ollama (local)', url: 'http://localhost:11434', key: '' },
];
const STEPS = ['basics', 'access', 'files', 'ai_search', 'protection'];
const TITLES = { basics: 'basics', access: 'access', files: 'files', ai_search: 'AI + search', protection: 'protection' };
let _state = null;
let _step = 0;
let _pickedModel = null;
let _auth = { enabled: false };
let _filesSaved = false;
let _savedFilesSignature = '';
let _obsidian = null;
let _returnFocus = null;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

async function _api(path, options = {}) {
  const response = await fetch(path, options);
  let payload = {};
  try { payload = await response.json(); } catch { /* retain the status fallback */ }
  if (!response.ok) throw new Error(payload.message || payload.detail || 'request failed');
  return payload;
}

function _json(method, body) {
  return { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) };
}

export async function openSetupWizard({ resume = false, status = null } = {}) {
  const modal = $('setup-wizard');
  if (!modal) return;
  if (modal.style.display !== 'flex' && document.activeElement instanceof HTMLElement) {
    _returnFocus = document.activeElement;
  }
  modal.style.display = 'flex';
  delete modal.dataset.loadFailed;
  modal.setAttribute('aria-busy', 'true');
  $('setup-wizard-body').innerHTML = '<div class="setup-loading">loading setup…</div>';
  _bindModal();
  try {
    if (resume) await _api('/api/setup/resume', { method: 'POST' });
    const response = status || await _api('/api/setup/status');
    _state = response.setup;
    if (_state.next_step === 'done' && !_state.completed) {
      const completed = await _api('/api/setup/complete', { method: 'POST' });
      _state = completed.setup;
    }
    _auth = await _api('/api/auth/me');
    _step = Math.max(0, STEPS.indexOf(_state.next_step));
    if (_state.next_step === 'done') _step = STEPS.length;
    _pickedModel = null;
    _filesSaved = Boolean(_state.files_companion_pending);
    _savedFilesSignature = _filesSaved
      ? `${_state.vault_preview}\n${_state.files_preview}\n${Boolean(_state.keep_vault_inside_alles)}`
      : '';
    _obsidian = null;
    _render();
  } catch (error) {
    modal.dataset.loadFailed = '1';
    $('setup-wizard-body').innerHTML = `<div class="setup-error" role="alert">
      <p>${esc(error.message || 'setup could not load')}</p>
      <div class="setup-actions">
        <button class="btn" type="button" id="sw-load-close">close</button>
        <button class="btn primary" type="button" id="sw-load-retry">retry</button>
      </div>
    </div>`;
    $('sw-load-close')?.addEventListener('click', _close);
    $('sw-load-retry')?.addEventListener('click', () => openSetupWizard());
  } finally {
    modal.setAttribute('aria-busy', 'false');
  }
}

function _bindModal() {
  const modal = $('setup-wizard');
  if (modal.dataset.bound) return;
  modal.dataset.bound = '1';
  $('setup-skip').addEventListener('click', _dismiss);
  modal.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      if (modal.dataset.loadFailed) _close();
      else _dismiss();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = [...modal.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter(element => !element.hidden && element.offsetParent !== null);
    if (!items.length) return;
    const first = items[0];
    const last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

function _close() {
  const modal = $('setup-wizard');
  if (modal) modal.style.display = 'none';
  const firstRun = $('home-firstrun');
  if (firstRun) firstRun.style.display = 'none';
  const target = _returnFocus;
  _returnFocus = null;
  if (target?.isConnected) target.focus();
}

async function _dismiss() {
  try {
    const response = await _api('/api/setup/dismiss', { method: 'POST' });
    _state = response.setup;
    _close();
    toast('setup paused. resume it from settings anytime.', 'success');
  } catch (error) { toast(error.message, 'error'); }
}

function _progress() {
  const progress = $('setup-dots');
  if (!progress) return;
  const current = Math.min(_step + 1, STEPS.length);
  progress.textContent = _step >= STEPS.length
    ? 'setup complete'
    : `${current} / ${STEPS.length} · ${TITLES[STEPS[_step]]}`;
}

function _render() {
  _progress();
  const body = $('setup-wizard-body');
  if (!body) return;
  $('setup-skip').style.display = _step >= STEPS.length ? 'none' : '';
  if (_step === 0) _renderBasics(body);
  else if (_step === 1) _renderAccess(body);
  else if (_step === 2) _renderFiles(body);
  else if (_step === 3) _renderAiSearch(body);
  else if (_step === 4) _renderProtection(body);
  else _renderDone(body);
}

function _setStep(next) {
  _step = Math.max(0, Math.min(STEPS.length, next));
  _render();
}

function _actions(back = true, label = 'save + continue') {
  return `<div class="setup-actions">
    ${back ? '<button class="btn" type="button" id="sw-back">back</button>' : '<span></span>'}
    <button class="btn primary" type="button" id="sw-save">${esc(label)}</button>
  </div><div class="setup-status" id="sw-status" role="status" aria-live="polite"></div>`;
}

function _bindActions(save) {
  $('sw-back')?.addEventListener('click', () => _setStep(_step - 1));
  $('sw-save')?.addEventListener('click', save);
}

function _busy(button, on, message = '') {
  if (button) button.disabled = on;
  const status = $('sw-status');
  if (status) status.textContent = message;
}

async function _saveStep(step, values) {
  const response = await _api('/api/setup/step', _json('PATCH', { step, values }));
  _state = response.setup;
  return response;
}

function _browserDefaults() {
  const locale = navigator.language || 'en';
  let region = '';
  let timezone = '';
  try { region = new Intl.Locale(locale).region || ''; } catch {
    region = locale.split('-').slice(1).find(part => /^(?:[A-Za-z]{2}|\d{3})$/.test(part)) || '';
  }
  timezone = resolvedTimeZone();
  return { region: region.toUpperCase(), timezone };
}

function _renderBasics(body) {
  const defaults = _browserDefaults();
  const regionText = defaults.region
    ? `region <strong>${esc(defaults.region)}</strong> is detected automatically from this browser.`
    : 'region follows this browser automatically.';
  body.innerHTML = `
    <div class="setup-title" id="setup-title">make alles yours</div>
    <div class="setup-sub"><span id="sw-region-status">${regionText}</span> Check your name and timezone. English is the reviewed interface language for now.</div>
    <label class="setup-field"><span>your name</span><input class="settings-input setup-input" id="sw-name" autocomplete="name" value="${esc(_state.username)}"></label>
    <label class="setup-field"><span>timezone</span><input class="settings-input setup-input" id="sw-timezone" placeholder="Asia/Taipei" value="${esc(_state.timezone || defaults.timezone)}"></label>
    ${_actions(false)}`;
  $('sw-name').focus();
  _bindActions(async () => {
    const button = $('sw-save');
    _busy(button, true, 'saving…');
    try {
      await _saveStep('basics', {
        username: $('sw-name').value.trim(), language: 'en',
        region: defaults.region, timezone: $('sw-timezone').value.trim(),
      });
      _setStep(1);
    } catch (error) { _busy(button, false, error.message); }
  });
}

function _choiceGroup(id, choices, selected) {
  return `<div class="setup-choice-group" id="${id}" role="radiogroup">${choices.map((choice, index) => `
    <button type="button" role="radio" aria-checked="${choice.value === selected}" tabindex="${choice.value === selected || (!selected && index === 0) ? '0' : '-1'}" data-value="${esc(choice.value)}">
      <strong>${esc(choice.label)}</strong><small>${esc(choice.note)}</small>
    </button>`).join('')}</div>`;
}

function _bindChoiceGroup(id, onChange) {
  const group = $(id);
  if (!group) return;
  const choose = button => {
    group.querySelectorAll('[role="radio"]').forEach(item => {
      const active = item === button;
      item.setAttribute('aria-checked', String(active));
      item.tabIndex = active ? 0 : -1;
    });
    onChange?.(button.dataset.value);
  };
  group.addEventListener('click', event => {
    const button = event.target.closest('[role="radio"]');
    if (button) choose(button);
  });
  group.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const items = [...group.querySelectorAll('[role="radio"]')];
    const current = Math.max(0, items.indexOf(document.activeElement));
    const direction = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
    const next = items[(current + direction + items.length) % items.length];
    choose(next); next.focus();
  });
}

function _renderAccess(body) {
  const selected = _state.access_profile || 'device';
  body.innerHTML = `
    <div class="setup-title" id="setup-title">choose where alles answers</div>
    <div class="setup-sub">Device-only is the safe default. Network access takes effect after the server restarts.</div>
    ${_choiceGroup('sw-access', [
      { value: 'device', label: 'this device', note: 'localhost only' },
      { value: 'lan', label: 'home network', note: 'other devices on your LAN' },
      { value: 'public', label: 'public domain', note: 'HTTPS reverse proxy required' },
    ], selected)}
    <div id="sw-access-details"></div>
    ${_actions()}`;
  const details = profile => {
    const host = $('sw-access-details');
    if (profile === 'public') {
      host.innerHTML = `
        <label class="setup-field"><span>public HTTPS origin</span><input class="settings-input setup-input" id="sw-public-url" placeholder="https://alles.example.com" value="${esc(_state.public_url)}"></label>
        <label class="setup-field"><span>base domain</span><input class="settings-input setup-input" id="sw-base-domain" placeholder="alles.example.com" value="${esc(_state.base_domain)}"></label>
        <label class="setup-field"><span>trusted hosts</span><input class="settings-input setup-input" id="sw-trusted-hosts" placeholder="alles.example.com,*.alles.example.com" value="${esc(_state.trusted_hosts)}"></label>
        <label class="setup-field"><span>trusted proxy IP or CIDR</span><input class="settings-input setup-input" id="sw-proxies" placeholder="127.0.0.1/32" value="${esc(_state.forwarded_allow_ips)}"></label>`;
    } else host.innerHTML = '';
    if (profile !== 'device' && !_auth.enabled) host.insertAdjacentHTML('beforeend', `
      <label class="setup-field"><span>owner password</span><input class="settings-input setup-input" id="sw-owner-password" type="password" autocomplete="new-password" minlength="12" placeholder="12 or more characters"></label>`);
    else if (profile !== 'device') host.insertAdjacentHTML('beforeend', '<p class="setup-note">owner password lock is already on.</p>');
  };
  details(selected);
  _bindChoiceGroup('sw-access', details);
  _bindActions(async () => {
    const profile = $('sw-access').querySelector('[aria-checked="true"]')?.dataset.value || 'device';
    const password = $('sw-owner-password')?.value || '';
    if (profile !== 'device' && !_auth.enabled && password.length < 12) {
      $('sw-status').textContent = 'network access needs an owner password of at least 12 characters'; return;
    }
    const button = $('sw-save'); _busy(button, true, 'checking access policy…');
    try {
      if (profile !== 'device' && !_auth.enabled) {
        await _api('/api/auth/config', _json('POST', { enabled: true, password }));
        _auth = { ..._auth, enabled: true };
      }
      await _saveStep('access', {
        profile,
        public_url: $('sw-public-url')?.value.trim() || '',
        base_domain: $('sw-base-domain')?.value.trim() || '',
        trusted_hosts: $('sw-trusted-hosts')?.value.trim() || '',
        forwarded_allow_ips: $('sw-proxies')?.value.trim() || '',
      });
      _setStep(2);
    } catch (error) { _busy(button, false, error.message); }
  });
}

function _switch(id, label, checked, note) {
  return `<div class="setup-switch-row"><div><strong>${esc(label)}</strong><small>${esc(note)}</small></div>
    <button class="home-settings-switch" type="button" role="switch" id="${id}" aria-label="${esc(label)}" aria-checked="${checked}"></button></div>`;
}

function _bindSwitch(id, onChange) {
  const button = $(id);
  button?.addEventListener('click', () => {
    const next = button.getAttribute('aria-checked') !== 'true';
    button.setAttribute('aria-checked', String(next));
    onChange?.(next);
  });
}

function _renderFiles(body) {
  const keep = Boolean(_state.keep_vault_inside_alles);
  body.innerHTML = `
    <div class="setup-title" id="setup-title">put your files where you can see them</div>
    <div class="setup-sub">Alles never moves an existing Vault. The companion for Obsidian is a separate, explicit choice after these paths are saved.</div>
    ${_switch('sw-keep-vault', 'keep Vault and Files inside Alles', keep, 'recommended: ~/Alles/Vault and ~/Alles/Files')}
    <label class="setup-field"><span>Vault folder</span><input class="settings-input setup-input" id="sw-vault" value="${esc(_state.vault_preview)}"></label>
    <label class="setup-field"><span>Files folder</span><input class="settings-input setup-input" id="sw-files" value="${esc(_state.files_preview)}"></label>
    <div id="sw-obsidian"></div>
    ${_actions(true, _filesSaved ? 'continue' : 'save locations')}`;
  _bindSwitch('sw-keep-vault');
  if (_filesSaved) _renderObsidianChoice();
  $('sw-back')?.addEventListener('click', () => _setStep(1));
  $('sw-save').addEventListener('click', async () => {
    const filesSignature = `${$('sw-vault').value.trim()}\n${$('sw-files').value.trim()}\n${$('sw-keep-vault').getAttribute('aria-checked') === 'true'}`;
    const locationsChanged = _filesSaved && filesSignature !== _savedFilesSignature;
    const advance = _filesSaved && !locationsChanged;
    const button = $('sw-save'); _busy(button, true, 'checking folders…');
    try {
      if (!advance) _obsidian = null;
      await _saveStep('files', {
        keep_vault_inside_alles: $('sw-keep-vault').getAttribute('aria-checked') === 'true',
        vault_path: $('sw-vault').value.trim(), files_path: $('sw-files').value.trim(),
        companion_reviewed: advance,
      });
      _filesSaved = true;
      // Compare the next click with the server's canonical paths. On macOS a
      // valid /var path is returned as /private/var; retaining the pre-save
      // spelling makes the new Continue control look dead for one click.
      _savedFilesSignature = `${_state.vault_preview}\n${_state.files_preview}\n${Boolean(_state.keep_vault_inside_alles)}`;
      if (advance) { _setStep(3); return; }
      try { _obsidian = await _api('/api/setup/obsidian'); } catch { _obsidian = null; }
      _renderFiles(body);
    } catch (error) { _busy(button, false, error.message); }
  });
}

function _renderObsidianChoice() {
  const host = $('sw-obsidian');
  if (!host) return;
  const installed = Boolean(_obsidian?.companion_installed);
  host.innerHTML = `<div class="setup-companion">
    <div><strong>Obsidian companion</strong><small>${installed ? 'installed and verified' : 'optional; nothing was added automatically'}</small></div>
    ${installed ? '' : '<button class="btn" type="button" id="sw-install-obsidian">install companion</button>'}
  </div>`;
  $('sw-install-obsidian')?.addEventListener('click', async () => {
    const button = $('sw-install-obsidian'); button.disabled = true;
    try {
      _obsidian = await _api('/api/setup/obsidian', _json('POST', { approve: true }));
      _renderObsidianChoice(); toast('Obsidian companion installed', 'success');
    } catch (error) { button.disabled = false; $('sw-status').textContent = error.message; }
  });
}

function _renderAiSearch(body) {
  _pickedModel = null;
  const selectedSearch = ['duckduckgo', 'searxng'].includes(_state.search_provider)
    ? _state.search_provider : 'duckduckgo';
  body.innerHTML = `
    <div class="setup-title" id="setup-title">connect the tools you want</div>
    <div class="setup-sub">A model is optional. Search defaults to DuckDuckGo and needs no account.</div>
    <div class="setup-section-label">AI model, optional</div>
    <div class="setup-provider-grid" id="sw-models">${MODEL_PRESETS.map((provider, index) => `<button type="button" class="setup-provider" data-index="${index}" aria-pressed="false">${esc(provider.name)}</button>`).join('')}</div>
    <div id="sw-model-fields"></div>
    <div class="setup-section-label">web search</div>
    ${_choiceGroup('sw-search', [
      { value: 'duckduckgo', label: 'DuckDuckGo', note: 'works without setup' },
      { value: 'searxng', label: 'SearXNG', note: 'connect an existing instance' },
    ], selectedSearch)}
    <div id="sw-search-fields"></div>
    ${_actions()}`;
  $('sw-models').addEventListener('click', event => {
    const button = event.target.closest('[data-index]'); if (!button) return;
    _pickedModel = MODEL_PRESETS[Number(button.dataset.index)];
    $('sw-models').querySelectorAll('button').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    $('sw-model-fields').innerHTML = `
      <label class="setup-field"><span>base URL</span><input class="settings-input setup-input" id="sw-model-url" value="${esc(_pickedModel.url)}"></label>
      <label class="setup-field"><span>API key</span><input class="settings-input setup-input" id="sw-model-key" type="password" autocomplete="off" placeholder="${esc(_pickedModel.key || 'not required')}"></label>`;
    $('sw-model-key').focus();
  });
  const searchFields = value => {
    $('sw-search-fields').innerHTML = value === 'searxng' ? `
      <label class="setup-field"><span>SearXNG URL</span><input class="settings-input setup-input" id="sw-searxng-url" placeholder="https://search.example.com" value="${esc(_state.searxng_url || '')}"></label>` : '';
  };
  searchFields(selectedSearch);
  _bindChoiceGroup('sw-search', searchFields);
  _bindActions(async () => {
    const button = $('sw-save'); _busy(button, true, 'connecting…');
    try {
      if (_pickedModel) {
        const url = $('sw-model-url').value.trim();
        if (!url) throw new Error('the model base URL is required');
        await addEndpoint(_pickedModel.name, url, $('sw-model-key').value.trim());
        _pickedModel = null;
      }
      const provider = $('sw-search').querySelector('[aria-checked="true"]')?.dataset.value || 'duckduckgo';
      await _saveStep('ai_search', {
        search_provider: provider,
        searxng_url: $('sw-searxng-url')?.value.trim() || '',
      });
      _setStep(4);
    } catch (error) { _busy(button, false, error.message || 'the connection could not be verified'); }
  });
}

function _renderProtection(body) {
  const enabled = Boolean(_state.automatic_backup_enabled);
  body.innerHTML = `
    <div class="setup-title" id="setup-title">keep a way back</div>
    <div class="setup-sub">Alles can make one encrypted local backup per day and keep the latest seven. Store the recovery key separately.</div>
    ${_switch('sw-auto-backup', 'automatic encrypted backups', enabled, 'daily, with seven-backup retention')}
    <div id="sw-backup-fields"></div>
    ${_actions()}`;
  const fields = on => {
    $('sw-backup-fields').innerHTML = on ? `
      <label class="setup-field"><span>backup folder</span><input class="settings-input setup-input" id="sw-backup-dir" value="${esc(_state.automatic_backup_dir)}"></label>
      <p class="setup-note">This folder must be outside Alles data. Download the recovery key from Settings → Backup after setup.</p>` : '';
  };
  fields(enabled);
  _bindSwitch('sw-auto-backup', fields);
  _bindActions(async () => {
    const button = $('sw-save'); _busy(button, true, 'saving protection…');
    try {
      await _saveStep('protection', {
        automatic_backup_enabled: $('sw-auto-backup').getAttribute('aria-checked') === 'true',
        automatic_backup_dir: $('sw-backup-dir')?.value.trim() || _state.automatic_backup_dir,
      });
      const completed = await _api('/api/setup/complete', { method: 'POST' });
      _state = completed.setup;
      _step = STEPS.length; _render();
    } catch (error) { _busy(button, false, error.message); }
  });
}

function _renderDone(body) {
  body.innerHTML = `
    <div class="setup-title" id="setup-title">alles is ready</div>
    <div class="setup-sub">Your choices are saved on the server. You can change them later in Settings.</div>
    <div class="setup-summary">
      <span>access</span><strong>${esc(_state.access_profile || 'device')}</strong>
      <span>Vault</span><strong>${esc(_state.vault_preview || 'not connected')}</strong>
      <span>backup</span><strong>${_state.automatic_backup_enabled ? 'daily encrypted' : 'off'}</strong>
    </div>
    <div class="setup-actions"><span></span><button class="btn primary" type="button" id="sw-start">open alles</button></div>`;
  $('sw-start').addEventListener('click', _close);
  $('sw-start').focus();
}

export const _setupInternals = { _choiceGroup, STEPS };
