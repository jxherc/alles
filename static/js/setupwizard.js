// server-owned first-run setup: resumable across browsers and safe to dismiss.
import { toast, plainError } from './util.js';
import { requestWithRecentOwner } from './recent_owner.js';
import { addEndpoint } from './models.js?v=215';
import { resolvedTimeZone, t } from './i18n.js';
import { wireChoiceGroup } from './kokuen.js?v=4';
import { API_TYPES, authFor, mountProviderPicker } from './model_providers.js';
const STEPS = ['basics', 'access', 'files', 'ai_search', 'protection'];
const _titles = () => ({ basics: t('setup.step_basics'), access: t('setup.step_access'), files: t('common.files'), ai_search: t('setup.step_ai_search'), protection: t('setup.step_protection') });
let _state = null;
let _step = 0;
let _pickedModel = null;
let _auth = { enabled: false };
let _filesSaved = false;
let _savedFilesSignature = '';
let _obsidian = null;
let _returnFocus = null;
let _background = null;
let _loadSequence = 0;
let _dismissedThisSession = false;

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

async function _api(path, options = {}, { recentOwner = false } = {}) {
  const response = recentOwner
    ? await requestWithRecentOwner(fetch, path, options)
    : await fetch(path, options);
  let payload = {};
  try { payload = await response.json(); } catch { /* retain the status fallback */ }
  if (!response.ok) throw new Error(payload.message || payload.detail || t('common.request_failed'));
  return payload;
}

function _json(method, body) {
  return { method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) };
}

function _anotherDialogOpen(modal) {
  return [...document.querySelectorAll('[role="dialog"]')]
    .some(dialog => dialog !== modal && dialog.offsetParent !== null);
}

export async function openSetupWizard({ resume = false, status = null } = {}) {
  const modal = $('setup-wizard');
  if (!modal) return;
  if (!resume && _anotherDialogOpen(modal)) return;
  if (!resume && (_dismissedThisSession || status?.setup?.dismissed || status?.setup?.completed)) return;
  if (resume) _dismissedThisSession = false;
  const loadId = ++_loadSequence;
  const stillOpen = () => loadId === _loadSequence && modal.style.display === 'flex';
  if (modal.style.display !== 'flex' && document.activeElement instanceof HTMLElement) {
    _returnFocus = document.activeElement;
  }
  modal.style.display = 'flex';
  delete modal.dataset.loadFailed;
  modal.setAttribute('aria-busy', 'true');
  $('setup-wizard-body').innerHTML = `<div class="setup-loading">${esc(t('setup.loading'))}</div>`;
  if (!_background) {
    const node = document.querySelector('.app');
    if (node) { _background = { node, inert: node.inert }; node.inert = true; }
  }
  $('setup-skip')?.focus();
  _bindModal();
  try {
    if (resume) await _api('/api/setup/resume', { method: 'POST' });
    if (!stillOpen()) return;
    const response = status || await _api('/api/setup/status');
    if (!stillOpen()) return;
    if (!resume && (response.setup?.dismissed || response.setup?.completed)) {
      _close({ restoreFocus: false });
      return;
    }
    _state = response.setup;
    if (_state.next_step === 'done' && !_state.completed) {
      const completed = await _api('/api/setup/complete', { method: 'POST' });
      if (!stillOpen()) return;
      _state = completed.setup;
    }
    _auth = await _api('/api/auth/me');
    if (!stillOpen()) return;
    _step = Math.max(0, STEPS.indexOf(_state.next_step));
    if (_state.next_step === 'done') _step = STEPS.length;
    _pickedModel = null;
    _filesSaved = Boolean(_state.files_companion_pending);
    _savedFilesSignature = _filesSaved
      ? `${_state.vault_preview}\n${_state.files_preview}\n${Boolean(_state.keep_vault_inside_alles)}`
      : '';
    _obsidian = null;
    if (!resume && _anotherDialogOpen(modal)) {
      _close({ restoreFocus: false });
      return;
    }
    _render();
  } catch (error) {
    if (!stillOpen()) return;
    modal.dataset.loadFailed = '1';
    $('setup-wizard-body').innerHTML = `<div class="setup-error" role="alert">
      <p>${esc(plainError(error.message || t('setup.load_failed')))}</p>
      <div class="setup-actions">
        <button class="btn" type="button" id="sw-load-close">${esc(t('common.close'))}</button>
        <button class="btn primary" type="button" id="sw-load-retry">${esc(t('common.retry'))}</button>
      </div>
    </div>`;
    $('sw-load-close')?.addEventListener('click', _close);
    $('sw-load-retry')?.addEventListener('click', () => openSetupWizard({ resume }));
    $('sw-load-retry')?.focus();
  } finally {
    if (loadId === _loadSequence) modal.setAttribute('aria-busy', 'false');
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

function _close({ restoreFocus = true } = {}) {
  const modal = $('setup-wizard');
  _loadSequence += 1;
  _busy($('setup-skip'), false);
  if (modal) {
    modal.style.display = 'none';
    modal.setAttribute('aria-busy', 'false');
  }
  const firstRun = $('home-firstrun');
  if (firstRun) firstRun.style.display = 'none';
  if (_background) { _background.node.inert = _background.inert; _background = null; }
  const target = _returnFocus;
  _returnFocus = null;
  if (!restoreFocus) return;
  if (target?.isConnected && target !== document.body) target.focus();
  else _pageFocus();
}

// a wizard that opened on its own saved <body>: start on home's capture box. on a touch screen
// that would pop the keyboard open, so there the page heading takes focus instead
function _pageFocus() {
  const capture = $('today-capture-input');
  const touch = globalThis.matchMedia?.('(pointer: coarse)')?.matches;
  if (!touch && capture?.getClientRects().length) { capture.focus(); return; }
  const heading = [...document.querySelectorAll('.app h1, .app h2')].find(node => node.getClientRects().length);
  if (!heading) return;
  if (!heading.hasAttribute('tabindex')) heading.tabIndex = -1;
  heading.focus({ preventScroll: true });
}

async function _dismiss() {
  const button = $('setup-skip');
  if (button?.getAttribute('aria-busy') === 'true') return;
  _loadSequence += 1;
  _busy(button, true, t('setup.pausing'));
  try {
    const response = await _api('/api/setup/dismiss', { method: 'POST' });
    _state = response.setup;
    _dismissedThisSession = true;
    _close();
    toast(t('setup.paused'), 'success');
  } catch (error) {
    _busy(button, false, error.message);
    toast(error.message, 'error');
    // A refused pause must not replace a rendered form with its last saved values.
    // Only restart an initial load that the dismissal invalidated above.
    if ($('setup-wizard')?.getAttribute('aria-busy') === 'true') openSetupWizard();
    else button?.focus();
  }
}

function _progress() {
  const progress = $('setup-dots');
  if (!progress) return;
  const current = Math.min(_step + 1, STEPS.length);
  progress.textContent = _step >= STEPS.length
    ? t('setup.complete')
    : t('setup.progress', { current, total: STEPS.length, title: _titles()[STEPS[_step]] });
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
  if (!body.contains(document.activeElement)) {
    body.querySelector('input:not([disabled]), [role="radio"][aria-checked="true"], button:not([disabled])')?.focus();
  }
}

function _setStep(next) {
  _step = Math.max(0, Math.min(STEPS.length, next));
  _render();
}

// status sits in the button row, next to the action it reports on
function _actions(back = true, label = t('setup.save_continue')) {
  return `<div class="setup-actions">
    ${back ? `<button class="btn" type="button" id="sw-back">${esc(t('common.back'))}</button>` : ''}
    <div class="setup-status" id="sw-status" role="status" aria-live="polite"></div>
    <button class="btn primary" type="button" id="sw-save">${esc(label)}</button>
  </div>`;
}

function _bindActions(save) {
  $('sw-back')?.addEventListener('click', () => _setStep(_step - 1));
  $('sw-save')?.addEventListener('click', save);
}

function _formIsCurrent() {
  const body = $('setup-wizard-body');
  const first = body?.firstElementChild;
  return () => $('setup-wizard')?.style.display === 'flex'
    && body?.firstElementChild === first;
}

function _busy(button, on, message = '') {
  if (button) {
    button.disabled = on;
    if (on) button.setAttribute('aria-busy', 'true');
    else button.removeAttribute('aria-busy');
  }
  const status = $('sw-status');
  if (!status) return;
  status.textContent = message;
  // working text stays quiet; only a message left after the work ends is an error
  status.dataset.state = on ? 'busy' : message ? 'error' : '';
}

async function _saveStep(step, values, isCurrent = () => true) {
  const response = await _api('/api/setup/step', _json('PATCH', { step, values }));
  if (isCurrent()) _state = response.setup;
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
    ? t('setup.region_detected', { region: `<strong>${esc(defaults.region)}</strong>` })
    : t('setup.region_follows');
  body.innerHTML = `
    <div class="setup-title" id="setup-title">${esc(t('setup.basics_title'))}</div>
    <div class="setup-sub"><span id="sw-region-status">${regionText}</span> ${esc(t('setup.basics_hint'))}</div>
    <label class="setup-field"><span>${esc(t('common.username'))}</span><input class="settings-input setup-input" id="sw-name" autocomplete="username" aria-describedby="sw-name-help" value="${esc(_state.username)}"></label>
    <p class="setup-note" id="sw-name-help">${esc(t('setup.name_help'))}</p>
    <label class="setup-field"><span>${esc(t('locale.timezone'))}</span><input class="settings-input setup-input" id="sw-timezone" placeholder="Asia/Taipei" value="${esc(_state.timezone || defaults.timezone)}"></label>
    ${_actions(false)}`;
  $('sw-name').focus();
  _bindActions(async () => {
    const current = _formIsCurrent();
    const button = $('sw-save');
    _busy(button, true, t('common.saving'));
    try {
      await _saveStep('basics', {
        username: $('sw-name').value.trim(), language: 'en',
        region: defaults.region, timezone: $('sw-timezone').value.trim(),
      }, current);
      if (!current()) return;
      _setStep(1);
    } catch (error) { if (current()) _busy(button, false, error.message); }
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
  let selected = group.querySelector('[aria-checked="true"]')?.dataset.value;
  wireChoiceGroup(group);
  group.addEventListener('click', event => {
    const button = event.target.closest('[role="radio"]');
    if (button && group.contains(button) && button.dataset.value !== selected) {
      selected = button.dataset.value;
      onChange?.(selected);
    }
  });
}

function _renderAccess(body) {
  const selected = _state.access_profile || 'device';
  body.innerHTML = `
    <div class="setup-title" id="setup-title">${esc(t('setup.access_title'))}</div>
    <div class="setup-sub">${esc(t('setup.access_hint'))}</div>
    ${_choiceGroup('sw-access', [
      { value: 'device', label: t('setup.access_device'), note: t('setup.access_device_note') },
      { value: 'lan', label: t('setup.access_lan'), note: t('setup.access_lan_note') },
      { value: 'public', label: t('setup.access_public'), note: t('setup.access_public_note') },
    ], selected)}
    <div id="sw-access-details"></div>
    ${_actions()}`;
  const details = profile => {
    const host = $('sw-access-details');
    // a message about the last choice ("needs an owner password") goes when the choice changes
    if ($('sw-status')) $('sw-status').textContent = '';
    if (profile === 'public') {
      host.innerHTML = `
        <label class="setup-field"><span>${esc(t('setup.public_origin'))}</span><input class="settings-input setup-input" id="sw-public-url" placeholder="https://alles.example.com" value="${esc(_state.public_url)}"></label>
        <label class="setup-field"><span>${esc(t('setup.base_domain'))}</span><input class="settings-input setup-input" id="sw-base-domain" placeholder="alles.example.com" value="${esc(_state.base_domain)}"></label>
        <label class="setup-field"><span>${esc(t('setup.trusted_hosts'))}</span><input class="settings-input setup-input" id="sw-trusted-hosts" placeholder="alles.example.com,*.alles.example.com" value="${esc(_state.trusted_hosts)}"></label>
        <label class="setup-field"><span>${esc(t('setup.trusted_proxy'))}</span><input class="settings-input setup-input" id="sw-proxies" placeholder="127.0.0.1/32" value="${esc(_state.forwarded_allow_ips)}"></label>`;
    } else host.innerHTML = '';
    if (profile !== 'device' && !_auth.enabled) host.insertAdjacentHTML('beforeend', `
      <label class="setup-field"><span>${esc(t('setup.owner_password'))}</span><input class="settings-input setup-input" id="sw-owner-password" type="password" autocomplete="new-password" minlength="12" placeholder="${esc(t('setup.owner_password_placeholder'))}"></label>`);
    else if (profile !== 'device') host.insertAdjacentHTML('beforeend', `<p class="setup-note">${esc(t('setup.password_already_on'))}</p>`);
  };
  details(selected);
  _bindChoiceGroup('sw-access', details);
  _bindActions(async () => {
    const current = _formIsCurrent();
    const profile = $('sw-access').querySelector('[aria-checked="true"]')?.dataset.value || 'device';
    const password = $('sw-owner-password')?.value || '';
    if (profile !== 'device' && !_auth.enabled && password.length < 12) {
      _busy(null, false, t('setup.password_needed')); return;
    }
    const button = $('sw-save'); _busy(button, true, t('setup.checking_access'));
    try {
      if (profile !== 'device' && !_auth.enabled) {
        await _api('/api/auth/config', _json('POST', { enabled: true, password }));
        _auth = { ..._auth, enabled: true };
      }
      if (!current()) return;
      await _saveStep('access', {
        profile,
        public_url: $('sw-public-url')?.value.trim() || '',
        base_domain: $('sw-base-domain')?.value.trim() || '',
        trusted_hosts: $('sw-trusted-hosts')?.value.trim() || '',
        forwarded_allow_ips: $('sw-proxies')?.value.trim() || '',
      }, current);
      if (!current()) return;
      _setStep(2);
    } catch (error) { if (current()) _busy(button, false, error.message); }
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
    <div class="setup-title" id="setup-title">${esc(t('setup.files_title'))}</div>
    <div class="setup-sub">${esc(t('setup.files_hint'))}</div>
    ${_switch('sw-keep-vault', t('setup.keep_inside'), keep, t('setup.keep_inside_note'))}
    <label class="setup-field"><span>${esc(t('setup.document_folder'))}</span><input class="settings-input setup-input" id="sw-vault" value="${esc(_state.vault_preview)}"></label>
    <label class="setup-field"><span>${esc(t('setup.files_folder'))}</span><input class="settings-input setup-input" id="sw-files" value="${esc(_state.files_preview)}"></label>
    <div id="sw-obsidian"></div>
    ${_actions(true, _filesSaved ? t('common.continue') : t('setup.save_locations'))}`;
  _bindSwitch('sw-keep-vault');
  if (_filesSaved) _renderObsidianChoice();
  $('sw-back')?.addEventListener('click', () => _setStep(1));
  $('sw-save').addEventListener('click', async () => {
    const current = _formIsCurrent();
    const filesSignature = `${$('sw-vault').value.trim()}\n${$('sw-files').value.trim()}\n${$('sw-keep-vault').getAttribute('aria-checked') === 'true'}`;
    const locationsChanged = _filesSaved && filesSignature !== _savedFilesSignature;
    const advance = _filesSaved && !locationsChanged;
    const button = $('sw-save'); _busy(button, true, t('setup.checking_folders'));
    try {
      if (!advance) _obsidian = null;
      await _saveStep('files', {
        keep_vault_inside_alles: $('sw-keep-vault').getAttribute('aria-checked') === 'true',
        vault_path: $('sw-vault').value.trim(), files_path: $('sw-files').value.trim(),
        companion_reviewed: advance,
      }, current);
      if (!current()) return;
      _filesSaved = true;
      // Compare the next click with the server's canonical paths. On macOS a
      // valid /var path is returned as /private/var; retaining the pre-save
      // spelling makes the new Continue control look dead for one click.
      _savedFilesSignature = `${_state.vault_preview}\n${_state.files_preview}\n${Boolean(_state.keep_vault_inside_alles)}`;
      if (advance) { _setStep(3); return; }
      let companion = null;
      try { companion = await _api('/api/setup/obsidian'); } catch { /* optional status */ }
      if (!current()) return;
      _obsidian = companion;
      _render();
    } catch (error) { if (current()) _busy(button, false, error.message); }
  });
}

function _renderObsidianChoice() {
  const host = $('sw-obsidian');
  if (!host) return;
  const installed = Boolean(_obsidian?.companion_installed);
  host.innerHTML = `<div class="setup-companion">
    <div><strong>${esc(t('setup.companion'))}</strong><small>${esc(installed ? t('setup.companion_installed') : t('setup.companion_optional'))}</small></div>
    ${installed ? '' : `<button class="btn" type="button" id="sw-install-obsidian">${esc(t('setup.install_companion'))}</button>`}
  </div>`;
  $('sw-install-obsidian')?.addEventListener('click', async () => {
    const button = $('sw-install-obsidian');
    if (button?.getAttribute('aria-busy') === 'true') return;
    _busy(button, true, t('setup.installing_companion'));
    try {
      _obsidian = await _api('/api/setup/obsidian', _json('POST', { approve: true }), { recentOwner: true });
      _busy(button, false);
      _renderObsidianChoice(); toast(t('setup.companion_done'), 'success');
      $('sw-save')?.focus();
    } catch (error) {
      _busy(button, false, error.message);
      button?.focus();
    }
  });
}

function _renderAiSearch(body) {
  _pickedModel = null;
  const selectedSearch = ['duckduckgo', 'searxng'].includes(_state.search_provider)
    ? _state.search_provider : 'duckduckgo';
  body.innerHTML = `
    <div class="setup-title" id="setup-title">${esc(t('setup.ai_title'))}</div>
    <div class="setup-sub">${esc(t('setup.ai_hint'))}</div>
    <div class="setup-section-label">${esc(t('setup.ai_model_label'))}</div>
    <div class="model-provider-list" id="sw-models" aria-label="${esc(t('setup.model_providers'))}"></div>
    <div id="sw-model-fields"></div>
    <div class="setup-section-label">${esc(t('setup.web_search'))}</div>
    ${_choiceGroup('sw-search', [
      { value: 'duckduckgo', label: 'DuckDuckGo', note: t('setup.ddg_note') },
      { value: 'searxng', label: 'SearXNG', note: t('setup.searxng_note') },
    ], selectedSearch)}
    <div id="sw-search-fields"></div>
    ${_actions()}`;
  mountProviderPicker($('sw-models'), {
    onPick: provider => {
      if (_pickedModel === provider) return;
      _pickedModel = provider;
      $('sw-model-fields').innerHTML = `
        ${provider.custom ? `<label class="setup-field"><span>${esc(t('setup.connection_name'))}</span><input class="settings-input setup-input" id="sw-model-name" autocomplete="off"></label>` : ''}
        <label class="setup-field"><span>${esc(t('setup.base_url'))}</span><input class="settings-input setup-input" id="sw-model-url" type="url" spellcheck="false" value="${esc(provider.url)}"></label>
        ${provider.keyless ? '' : `<label class="setup-field"><span>${esc(provider.custom ? t('setup.api_key_optional') : t('setup.api_key'))}</span><input class="settings-input setup-input" id="sw-model-key" type="password" autocomplete="off"></label>`}
        ${provider.custom ? `<div class="setup-field"><span id="sw-model-type-label">${esc(t('setup.api_type'))}</span><div class="s-ep-type" id="sw-model-type" role="radiogroup" aria-labelledby="sw-model-type-label">${API_TYPES.map(([value, label], index) => `<button type="button" role="radio" data-value="${value}" aria-checked="${index === 0}" tabindex="${index ? -1 : 0}">${esc(label)}</button>`).join('')}</div></div>` : ''}`;
      if (provider.custom) wireChoiceGroup($('sw-model-type'));
      ($('sw-model-name') || $('sw-model-key') || $('sw-model-url')).focus();
    },
  });
  const searchFields = value => {
    $('sw-search-fields').innerHTML = value === 'searxng' ? `
      <label class="setup-field"><span>SearXNG URL</span><input class="settings-input setup-input" id="sw-searxng-url" placeholder="https://search.example.com" value="${esc(_state.searxng_url || '')}"></label>` : '';
  };
  searchFields(selectedSearch);
  _bindChoiceGroup('sw-search', searchFields);
  _bindActions(async () => {
    const current = _formIsCurrent();
    const button = $('sw-save'); _busy(button, true, t('setup.connecting'));
    try {
      if (_pickedModel) {
        const provider = _pickedModel;
        const url = $('sw-model-url').value.trim();
        if (!url) throw new Error(t('setup.model_url_required'));
        const key = $('sw-model-key')?.value.trim() || '';
        // a cloud provider without its key saves a connection that can never answer
        if (!provider.keyless && !provider.custom && !key) {
          $('sw-model-key')?.focus();
          throw new Error(t('setup.api_key_required', { provider: provider.label }));
        }
        const name = (provider.custom && $('sw-model-name')?.value.trim()) || provider.label;
        const adapter = provider.custom
          ? ($('sw-model-type')?.querySelector('[aria-checked="true"]')?.dataset.value || 'openai-compatible')
          : provider.adapter;
        await addEndpoint(name, url, key, adapter, [], { providerId: provider.provider, authType: authFor(provider, key) });
        if (!current()) return;
        _pickedModel = null;
      }
      const provider = $('sw-search').querySelector('[aria-checked="true"]')?.dataset.value || 'duckduckgo';
      await _saveStep('ai_search', {
        search_provider: provider,
        searxng_url: $('sw-searxng-url')?.value.trim() || '',
      }, current);
      if (!current()) return;
      _setStep(4);
    } catch (error) { if (current()) _busy(button, false, error.message || t('setup.connection_unverified')); }
  });
}

function _renderProtection(body) {
  const enabled = Boolean(_state.automatic_backup_enabled);
  body.innerHTML = `
    <div class="setup-title" id="setup-title">${esc(t('setup.backup_title'))}</div>
    <div class="setup-sub">${esc(t('setup.backup_hint'))}</div>
    ${_switch('sw-auto-backup', t('setup.auto_backup'), enabled, t('setup.auto_backup_note'))}
    <div id="sw-backup-fields"></div>
    ${_actions()}`;
  const fields = on => {
    $('sw-backup-fields').innerHTML = on ? `
      <label class="setup-field"><span>${esc(t('setup.backup_folder'))}</span><input class="settings-input setup-input" id="sw-backup-dir" value="${esc(_state.automatic_backup_dir)}"></label>
      <p class="setup-note">${esc(t('setup.backup_folder_note'))}</p>` : '';
  };
  fields(enabled);
  _bindSwitch('sw-auto-backup', fields);
  _bindActions(async () => {
    const current = _formIsCurrent();
    const button = $('sw-save'); _busy(button, true, t('setup.saving_protection'));
    try {
      await _saveStep('protection', {
        automatic_backup_enabled: $('sw-auto-backup').getAttribute('aria-checked') === 'true',
        automatic_backup_dir: $('sw-backup-dir')?.value.trim() || _state.automatic_backup_dir,
      }, current);
      if (!current()) return;
      const completed = await _api('/api/setup/complete', { method: 'POST' });
      if (!current()) return;
      _state = completed.setup;
      _step = STEPS.length; _render();
    } catch (error) { if (current()) _busy(button, false, error.message); }
  });
}

function _renderDone(body) {
  body.innerHTML = `
    <div class="setup-title" id="setup-title">${esc(t('setup.done_title'))}</div>
    <div class="setup-sub">${esc(t('setup.done_hint'))}</div>
    <div class="setup-summary">
      <span>${esc(t('setup.summary_access'))}</span><strong>${esc(_state.access_profile || 'device')}</strong>
      <span>${esc(t('setup.document_folder'))}</span><strong>${esc(_state.vault_preview || t('setup.not_connected'))}</strong>
      <span>${esc(t('setup.summary_backup'))}</span><strong>${esc(_state.automatic_backup_enabled ? t('setup.backup_daily') : t('setup.backup_off'))}</strong>
    </div>
    <div class="setup-actions"><button class="btn primary" type="button" id="sw-start" style="margin-left:auto">${esc(t('setup.open_alles'))}</button></div>`;
  $('sw-start').addEventListener('click', _close);
  $('sw-start').focus();
}
