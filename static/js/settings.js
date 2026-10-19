import { _setSwitch, _bindSwitch, _patchSettings, _patchSetting, _esc, _escAttr, _fetchWithRecentOwner } from './settings/shared.js';
import { homePane } from './settings/home.js';
import { languagePane } from './settings/language.js';
import { creditsPane } from './settings/credits.js';
import { createBackupPane } from './settings/backups.js';
import { providersPane, _endpointJson } from './settings/providers.js';
import { loadSearchEngines, wireSearchEngines } from './settings/search_engines.js';
import { connectionsPane } from './settings/connections.js';
export { _mergeHomeShortcutOrder } from './settings/home.js';
export { normalizeWebdavBackupConfig, webdavBackupConfigPayload, webdavBackupsFromResponse, normalizeS3BackupConfig, s3BackupConfigPayload, s3BackupsFromResponse } from './settings/backups.js';
export { loadMcpServers, loadConnections, loadDiscordConnection } from './settings/connections.js';
import { toast } from './util.js';
import { confirm as _dlgConfirm } from './dialog.js';
import { initCustomDropdowns, closeCustomDropdowns, getDropdownValue, setDropdownValue, populateDropdown } from './dropdown.js?v=212';
import { initMemoryPanel } from './memory.js';
import {
  sensitiveBlurEnabled, textOnlyEmojisEnabled, welcomeEnabled,
  setSensitiveBlur, setTextOnlyEmojis, setWelcomeEnabled,
} from './privacy.js';
import { loadShortcuts, saveShortcuts, eventToShortcut, isReservedShortcut } from './shortcuts.js';
import { setAccent as _themeSetAccent, resetToDefault as _resetToDefault, getAppearance as _getAppearance, renderThemeEditorInto, isBasePreset } from './theme.js';
import {
  formatDate,
} from './i18n.js';

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

// ── pane navigation ───────────────────────────────────────────────────────────
let _activePane = 'general';
let _developerOpening = 0;
const _ownedPanes = {
  home: homePane,
  notifications: languagePane,
  credits: creditsPane,
  models: providersPane,
  tools: connectionsPane,
  backup: createBackupPane(closeSettings),
};

function _closeSectionPicker(returnFocus = false) {
  const trigger = document.getElementById('settings-section-trigger');
  const wasOpen = trigger?.getAttribute('aria-expanded') === 'true';
  trigger?.setAttribute('aria-expanded', 'false');
  document.querySelector('.s-navigation')?.classList.remove('is-open');
  const list = document.getElementById('settings-section-list');
  if (list) list.style.maxHeight = '';
  if (returnFocus && wasOpen && trigger?.offsetParent !== null) trigger?.focus();
}

function _openSectionPicker() {
  const trigger = document.getElementById('settings-section-trigger');
  const list = document.getElementById('settings-section-list');
  if (!trigger || !list) return;
  document.querySelector('.s-navigation')?.classList.add('is-open');
  trigger.setAttribute('aria-expanded', 'true');
  const rect = trigger.getBoundingClientRect();
  const modalBottom = document.querySelector('#settings-modal .s-modal')?.getBoundingClientRect().bottom || innerHeight;
  list.style.maxHeight = `${Math.max(44, Math.min(innerHeight, modalBottom) - rect.bottom - 8)}px`;
  list.querySelector('.active')?.focus();
}

function _switchPane(name) {
  const pickerWasOpen = document.getElementById('settings-section-trigger')?.getAttribute('aria-expanded') === 'true';
  _closeSectionPicker(pickerWasOpen);
  closeCustomDropdowns(document.getElementById('settings-modal'));
  _ownedPanes[_activePane]?.dispose();
  _invalidateRetainedReads(_activePane);
  // unknown pane key (e.g. a stale 'appearance') would leave every pane inactive →
  // a blank modal. fall back to the consolidated General pane.
  if (!document.getElementById(`s-pane-${name}`)) name = 'general';
  const paneChanged = name !== _activePane;
  _activePane = name;
  const selected = document.querySelector(`.s-nav-item[data-pane="${CSS.escape(name)}"]`);
  const context = document.getElementById('settings-pane-title');
  if (context) context.textContent = selected?.textContent.trim() || '';
  const sectionTrigger = document.getElementById('settings-section-trigger');
  if (sectionTrigger) {
    const label = selected?.textContent.trim() || '';
    sectionTrigger.firstElementChild.textContent = label;
    sectionTrigger.setAttribute('aria-label', `settings section: ${label}`);
  }
  document.querySelectorAll('.s-nav-item').forEach(n =>
    n.classList.toggle('active', n.dataset.pane === name));
  document.querySelectorAll('.s-nav-item').forEach(n =>
    n.setAttribute('aria-current', n.dataset.pane === name ? 'page' : 'false'));
  document.querySelectorAll('.s-pane').forEach(p =>
    p.classList.toggle('active', p.id === `s-pane-${name}`));
  const content = document.querySelector('#settings-modal .s-content');
  if (paneChanged && content) content.scrollTop = 0;
  _onPaneOpen(name);
}

function _onPaneOpen(name) {
  _ownedPanes[name]?.load();
  if (name === 'ai')         loadAiPane();
  if (name === 'memory')     { initMemoryPanel(); loadOwnerInstructions(); }
  if (name === 'search')     loadSearchPane();
  if (name === 'general' || name === 'security' || name === 'themes') loadAppearancePane();
  if (name === 'themes')     loadThemesPane();
  if (name === 'voice')      loadVoicePane();
  if (name === 'personas')   { loadPersonas(); loadCookbook(); }
  if (name === 'developer')  { loadTokens(); loadWebhooks(); loadShortcutSettings(); }
  if (name === 'rules')      loadRulesPane();
  if (name === 'recall')     loadRecallPane();
  if (name === 'proactive')  loadProactivePane();
  if (name === 'intelligence') loadIntelligencePane();
}

// ── open / close ──────────────────────────────────────────────────────────────
let _bound = false;
let _settingsReturnFocus = null;
let _settingsReturnFocusId = '';

export function openSettings(pane, _allesOnly = false) {
  const modal = document.getElementById('settings-modal');
  if (!modal) return;
  const wasClosed = modal.style.display === 'none';
  if (wasClosed && document.activeElement instanceof HTMLElement) {
    _settingsReturnFocus = document.activeElement;
    _settingsReturnFocusId = document.activeElement.id;
  }
  modal.style.display = 'flex';
  // Phase 3 has one settings home. Keep the second argument only for old callers.
  modal.classList.remove('alles-scope');
  const title = document.querySelector('#settings-modal .s-title');
  if (title) title.textContent = 'alles settings';
  if (!pane) pane = 'general';
  if (!_bound) { _initSettings(); _bound = true; }
  // update compat url labels
  const port = location.port || '6769';
  const base = `${location.protocol}//${location.hostname}:${port}/v1`;
  document.getElementById('s-compat-url')?.setAttribute('data-val', base);
  document.getElementById('s-compat-url')?.replaceChildren(document.createTextNode(base));
  document.getElementById('s-compat-url2')?.replaceChildren(document.createTextNode(base));

  _switchPane(pane);
  requestAnimationFrame(() => {
    const picker = document.getElementById('settings-section-trigger');
    const target = (picker?.offsetParent !== null ? picker : null)
      || document.querySelector(`.s-nav-item[data-pane="${CSS.escape(_activePane)}"]`)
      || document.getElementById('settings-modal-close');
    target?.focus();
  });
}

export function closeSettings() {
  const modal = document.getElementById('settings-modal');
  if (!modal || modal.style.display === 'none') return;
  closeCustomDropdowns(document.getElementById('settings-modal'));
  _closeSectionPicker(false);
  _ownedPanes[_activePane]?.dispose();
  _invalidateRetainedReads(_activePane);
  modal.style.display = 'none';
  const target = _settingsReturnFocus?.isConnected
    ? _settingsReturnFocus
    : (_settingsReturnFocusId ? document.getElementById(_settingsReturnFocusId) : null);
  _settingsReturnFocus = null;
  _settingsReturnFocusId = '';
  target?.focus();
}

// expose for playwright tests + external callers
window._openSettings = openSettings;

// ── init (runs once) ──────────────────────────────────────────────────────────
function _initSettings() {
  initCustomDropdowns(document.getElementById('settings-modal') || document);
  document.getElementById('general-setup-btn')?.addEventListener('click', () => {
    closeSettings();
    window._openSetupWizard?.({ resume: true });
  });

  const sectionTrigger = document.getElementById('settings-section-trigger');
  sectionTrigger?.addEventListener('click', () => {
    if (sectionTrigger.getAttribute('aria-expanded') === 'true') _closeSectionPicker(true);
    else _openSectionPicker();
  });
  sectionTrigger?.addEventListener('keydown', event => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    _openSectionPicker();
  });
  document.addEventListener('pointerdown', event => {
    if (!event.target.closest('.s-navigation')) _closeSectionPicker(false);
  });
  window.addEventListener('resize', () => _closeSectionPicker(true));
  document.querySelector('.s-navigation')?.addEventListener('focusout', event => {
    if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget)) _closeSectionPicker(false);
  });

  // nav clicks
  document.querySelectorAll('.s-nav-item').forEach(n => {
    n.setAttribute('role', 'button');
    n.tabIndex = 0;
    n.addEventListener('click', () => _switchPane(n.dataset.pane));
    n.addEventListener('keydown', event => {
      if (sectionTrigger?.offsetParent !== null && ['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const items = [...document.querySelectorAll('.s-nav-item')];
        const index = items.indexOf(n);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
          : (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length;
        items[next]?.focus();
        return;
      }
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      _switchPane(n.dataset.pane);
    });
  });

  // overlay close
  const modal = document.getElementById('settings-modal');
  modal.addEventListener('click', e => { if (e.target === modal) closeSettings(); });
  modal.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      if (sectionTrigger?.getAttribute('aria-expanded') === 'true') _closeSectionPicker(true);
      else closeSettings();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusable = [...modal.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), details > summary, [tabindex]:not([tabindex="-1"])',
    )].filter(el => !el.hidden && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
  document.getElementById('settings-modal-close')?.addEventListener('click', closeSettings);

  // ── ai pane ──
  document.getElementById('settings-save-btn')?.addEventListener('click', saveAiDefaults);
  document.querySelectorAll('[data-chat-behavior]').forEach(button => {
    button.addEventListener('click', () => saveDefaultChatBehavior(button.dataset.chatBehavior));
  });
  document.getElementById('s-owner-instructions-save')?.addEventListener('click', saveOwnerInstructions);
  document.getElementById('settings-owner-instructions')?.addEventListener('input', event => {
    event.currentTarget.dataset.dirty = '1';
  });

  // ── search pane ──
  wireSearchEngines();
  document.getElementById('s-andromeda-verifier-mode')?.addEventListener('change', event => {
    _patchSetting('andromeda_verifier_mode', getDropdownValue(event.currentTarget));
  });
  document.getElementById('s-andromeda-band')?.addEventListener('change', event => {
    _patchSetting('andromeda_model_band', event.currentTarget.value);
  });
  document.querySelectorAll('.s-andromeda-model').forEach(select => {
    select.addEventListener('change', saveAndromedaModelBands);
  });
  document.getElementById('s-andromeda-qualify')?.addEventListener('click', qualifyAndromedaAutoModel);

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
  _tempBar?.addEventListener('keydown', _onTempKeydown);
  document.getElementById('persona-temp-pin')?.addEventListener('click', _togglePersonaTempPin);
  _renderTempBar();   // paint the empty/auto track on first open
  document.getElementById('persona-default')?.addEventListener('click', e => e.currentTarget.classList.toggle('on'));
  document.getElementById('persona-mode')?.addEventListener('click', e => {
    const opt = e.target.closest('.seg-opt'); if (!opt) return;
    opt.parentElement.querySelectorAll('.seg-opt').forEach(o => o.classList.toggle('active', o === opt));
  });
  document.getElementById('cookbook-add-btn')?.addEventListener('click', addCookbookEntry);

  // ── tools (mcp) ──
  document.getElementById('persona-doc-add')?.addEventListener('click', _addPersonaDoc);
  document.getElementById('persona-share-btn')?.addEventListener('click', _sharePersona);

  // ── developer ──
  document.getElementById('token-add-btn')?.addEventListener('click', generateToken);
  document.querySelectorAll('[data-token-scope]').forEach(btn => {
    btn.addEventListener('click', () => btn.classList.toggle('active'));
  });
  document.getElementById('wh-add-btn')?.addEventListener('click', addWebhook);

  document.querySelectorAll('.shortcut-input').forEach(inp => {
    inp.addEventListener('keydown', e => {
      if (e.key === 'Tab') return;
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
      if (isReservedShortcut(combo)) { toast(`${combo} is a system/browser shortcut: pick another`, 'error'); return; }
      inp.value = combo;
      saveShortcuts({ [inp.dataset.shortcut]: combo });
      toast('shortcut saved', 'success');
    });
  });
}

// ── ai pane ───────────────────────────────────────────────────────────────────
async function loadAiPane() {
  try {
    const s = await _endpointJson(await fetch('/api/settings'));
    if (!s || !Number.isFinite(s.context_limit)) throw new Error('settings response was incomplete');
    _renderChatBehavior(s.default_chat_behavior || 'automatic_tools');
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
  } catch (error) {
    toast(`could not load chat settings: ${error.message || 'server unavailable'}. reopen this section to retry.`, 'error');
  }
}

async function saveAiDefaults() {
  const patch = {
    context_limit: parseInt(document.getElementById('settings-context-limit').value) || 40,
  };
  await _patchSettings(patch);
}

function _renderChatBehavior(value) {
  const selected = value === 'answer_only' ? 'answer_only' : 'automatic_tools';
  document.querySelectorAll('[data-chat-behavior]').forEach(button => {
    const active = button.dataset.chatBehavior === selected;
    button.classList.toggle('active', active);
    button.setAttribute('aria-checked', String(active));
  });
}

async function saveDefaultChatBehavior(value) {
  const previous = document.querySelector('[data-chat-behavior][aria-checked="true"]')?.dataset.chatBehavior || 'automatic_tools';
  _renderChatBehavior(value);
  try {
    const response = await fetch('/api/settings', {
      method: 'PATCH', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ default_chat_behavior: value }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'chat behavior could not be saved');
    _renderChatBehavior(data.default_chat_behavior || value);
    toast('default chat behavior saved', 'success');
  } catch (error) {
    _renderChatBehavior(previous);
    toast(error.message || 'chat behavior could not be saved', 'error');
  }
}

let _ownerInstructionsRead = 0;
async function loadOwnerInstructions() {
  const textarea = document.getElementById('settings-owner-instructions');
  if (!textarea) return;
  const read = ++_ownerInstructionsRead;
  try {
    const settings = await _endpointJson(await fetch('/api/settings'));
    if (typeof settings.owner_instructions !== 'string') throw new Error('could not load owner instructions; reopen this section to retry');
    if (read === _ownerInstructionsRead && textarea.dataset.dirty !== '1') textarea.value = settings.owner_instructions;
  } catch (error) {
    if (read === _ownerInstructionsRead) toast(error.message || 'could not load owner instructions; reopen this section to retry', 'error');
  }
}

async function saveOwnerInstructions() {
  const button = document.getElementById('s-owner-instructions-save');
  const textarea = document.getElementById('settings-owner-instructions');
  if (!button || !textarea || button.disabled) return;
  const value = textarea.value;
  ++_ownerInstructionsRead;
  button.disabled = true;
  button.textContent = 'saving…';
  try {
    const settings = await _endpointJson(await fetch('/api/settings', {
      method: 'PATCH', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ owner_instructions: value }),
    }));
    if (settings.owner_instructions !== value.trim()) throw new Error('save could not be verified; your instructions are still here. try saving again.');
    if (textarea.value === value) textarea.dataset.dirty = '0';
    toast(textarea.value === value ? 'owner instructions saved' : 'earlier instructions saved; your latest edits still need saving', 'success');
  } catch (error) {
    toast(error.message || 'owner instructions could not be saved', 'error');
  } finally {
    ++_ownerInstructionsRead;
    button.disabled = false;
    button.textContent = 'save instructions';
  }
}

// ── search pane ───────────────────────────────────────────────────────────────
async function loadSearchPane() {
  try {
    const s = await _loadPaneSettings('search');
    if (!s) return;
    if (s.searxng_url)     document.getElementById('s-searxng-url').placeholder = s.searxng_url;
    if (s.google_pse_cx)   document.getElementById('s-gpse-cx').value = s.google_pse_cx;
    if (s.google_pse_api_key_configured) document.getElementById('s-gpse-key').placeholder = 'configured: enter a replacement';
    await loadSearchEngines(s);
    await loadAndromedaSearchSettings(s);
  } catch { toast('could not load search settings; reopen this section to retry', 'error'); }
}

let _andromedaModelChoices = new Map();
let _andromedaModelBands = {};

async function loadAndromedaSearchSettings(settings) {
  for (const [id, key] of [['s-andromeda-results', 'andromeda_normal_results'],
    ['s-andromeda-overview', 'andromeda_overview'], ['s-andromeda-verification', 'andromeda_verification_enabled']]) {
    _bindSwitch(document.getElementById(id), () => settings[key] !== false, value => _patchSetting(key, value));
  }
  const verifierMode = document.getElementById('s-andromeda-verifier-mode');
  if (verifierMode) setDropdownValue(verifierMode, settings.andromeda_verifier_mode || 'freshness-sensitive');
  const band = document.getElementById('s-andromeda-band');
  if (band) setDropdownValue(band, settings.andromeda_model_band || 'standard');
  _andromedaModelBands = settings.andromeda_model_bands || {};
  let endpoints = [];
  try { endpoints = await _endpointJson(await fetch('/api/models')); } catch {}
  _andromedaModelChoices = new Map();
  let index = 0;
  document.querySelectorAll('.s-andromeda-model').forEach(select => {
    const options = [{ value: '', label: select.dataset.band === 'standard' ? 'use answer role' : 'not configured' }];
    let selected = '';
    for (const endpoint of endpoints) {
      for (const model of endpoint.models || []) {
        const key = String(++index);
        _andromedaModelChoices.set(`${select.dataset.band}:${key}`, { endpoint_id: endpoint.id, model });
        options.push({ value: key, label: `${model} · ${endpoint.name}` });
        const current = _andromedaModelBands[select.dataset.band] || {};
        if (current.endpoint_id === endpoint.id && current.model === model) selected = key;
      }
    }
    populateDropdown(select, options, selected);
  });
}

async function saveAndromedaModelBands() {
  const choices = {};
  document.querySelectorAll('.s-andromeda-model').forEach(select => {
    const choice = _andromedaModelChoices.get(`${select.dataset.band}:${getDropdownValue(select)}`);
    if (choice) choices[select.dataset.band] = choice;
  });
  _andromedaModelBands = choices;
  try {
    if (!await _patchSettings({ andromeda_model_bands: choices })) return;
    const status = document.getElementById('s-andromeda-model-status');
    if (status) status.textContent = 'exact choices saved';
  } catch (error) { toast(error.message || 'model choices could not be saved', 'error'); }
}

async function qualifyAndromedaAutoModel() {
  const select = document.getElementById('s-andromeda-model-auto');
  const choice = _andromedaModelChoices.get(`auto:${getDropdownValue(select)}`);
  const status = document.getElementById('s-andromeda-model-status');
  if (!choice) { if (status) status.textContent = 'choose an exact local Auto model first'; return; }
  const button = document.getElementById('s-andromeda-qualify');
  if (button) button.disabled = true;
  if (status) status.textContent = 'running the citation fixture locally…';
  try {
    const result = await _endpointJson(await fetch('/api/andromeda/models/qualify', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(choice),
    }));
    if (status) status.textContent = result.passed
      ? `passed · ${result.supported_claims}/${result.required_claims} supported claims`
      : `not qualified · ${result.supported_claims}/${result.required_claims} supported claims`;
  } catch (error) { if (status) status.textContent = error.message || 'fixture failed'; }
  if (button) button.disabled = false;
}

// ── appearance pane ───────────────────────────────────────────────────────────
function loadAppearancePane() {
  const v = loadVis();
  document.querySelectorAll('.s-vis-toggle').forEach(sw => {
    const key = sw.dataset.visKey;
    _setSwitch(sw, key in v ? v[key] : true);
  });
  _bindSwitch(document.getElementById('s-sensitive-blur-toggle'), sensitiveBlurEnabled, setSensitiveBlur);
  _bindSwitch(document.getElementById('s-text-emoji-toggle'), textOnlyEmojisEnabled, setTextOnlyEmojis);
  _bindSwitch(document.getElementById('s-welcome-toggle'), welcomeEnabled, setWelcomeEnabled);
  _bindSwitch(document.getElementById('s-ui-compact-toggle'),
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

function _syncInlineThemeEditor() {
  const host = document.getElementById('theme-editor-inline');
  if (host && _inlineEditorBuilt) renderThemeEditorInto(host, { onChange: _refreshThemeLock });
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
    note.textContent = locked ? `mode + accent are set by the "${preset}" theme: pick "default" below to customize them` : '';
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
const DEFAULT_ACCENT = '#9298ff';
// accent + mode now live in the unified appearance object (theme.js), so they survive reload
// and stop fighting presets. these read/write through that, not the old aide-* localStorage.
const _curAccent = () => {
  let a; try { a = _getAppearance(); } catch { /* default */ }
  return ((a && a.colors && a.colors.accent) || DEFAULT_ACCENT).toLowerCase();
};

function applyAccent(hex) {
  _themeSetAccent(hex || '');                 // writes colors.accent into the appearance object
  _syncInlineThemeEditor();
  _markAccent();
  window._updateFavicon?.();
}
function applyThemeMode(mode) {
  // "default theme" = a clean slate: reset every fancy extra (frosted/pattern/density/font/
  // effect) to default for the chosen base, same as the default preset tile. leaving a fancy
  // preset also drops its accent tint back to default; a plain base keeps the accent you set.
  _resetToDefault(mode === 'light' ? 'light' : 'dark');
  _syncInlineThemeEditor();
  _markMode();
  _markAccent();   // the tint may have reset — re-mark the active swatch
  window._updateFavicon?.();
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
  document.querySelectorAll('.theme-mode-btn').forEach(b => {
    const selected = b.dataset.themeMode === cur;
    b.classList.toggle('active', selected);
    b.setAttribute('aria-pressed', String(selected));
  });
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
      `<button type="button" class="accent-swatch" data-hex="${hex}" title="${name}" aria-label="${name} accent" style="background:${hex}"></button>`).join('');
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
    const initialValue = uname.value;
    let revision = 0;
    fetch('/api/auth/me').then(async r => {
      if (!r.ok) throw new Error('username read failed');
      const m = await r.json();
      if (typeof m?.username !== 'string') throw new Error('invalid username response');
      if (!revision && uname.value === initialValue && document.activeElement !== uname) uname.value = m.username;
    }).catch(() => {});
    let t; uname.addEventListener('input', () => {
      ++revision;
      const username = uname.value.trim();
      clearTimeout(t);
      t = setTimeout(() => _patchSettings({ username }), 400);
    });
  }
  // change password — bind once
  const pwBtn = document.getElementById('s-pw-save');
  if (pwBtn && !pwBtn.dataset.bound) {
    pwBtn.dataset.bound = '1';
    const fields = ['s-pw-old', 's-pw-new', 's-pw-new2'].map(id => document.getElementById(id));
    let revision = 0;
    fields.forEach(field => field?.addEventListener('input', () => { ++revision; }));
    pwBtn.addEventListener('click', async () => {
      if (pwBtn.disabled) return;
      const submitted = fields.map(field => field?.value ?? '');
      const [oldp, newp, conf] = submitted;
      if (newp.length < 12) { toast('new password must be at least 12 characters', 'error'); return; }
      if (newp !== conf) { toast("passwords don't match", 'error'); return; }
      const savingRevision = revision;
      pwBtn.disabled = true;
      try {
        const result = await _endpointJson(await fetch('/api/auth/change-password', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ old_password: oldp, new_password: newp }) }));
        if (result?.ok !== true) throw new Error('password change could not be confirmed');
        toast('password changed', 'success');
        if (revision === savingRevision && fields.every((field, i) => (field?.value ?? '') === submitted[i])) {
          fields.forEach(field => { if (field) field.value = ''; });
        }
      } catch (error) { toast(error.message || 'failed to change password', 'error'); }
      finally { pwBtn.disabled = false; }
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

function loadShortcutSettings() {
  const shortcuts = loadShortcuts();
  document.querySelectorAll('.shortcut-input').forEach(inp => {
    inp.value = shortcuts[inp.dataset.shortcut] || '';
    inp.placeholder = 'press keys · Esc = none';
    inp.readOnly = true;   // it's a key-capture field, not free text
  });
}

// ── voice pane ────────────────────────────────────────────────────────────────
let _voiceReadGeneration = 0;
let _voiceMicReadGeneration = 0;
let _voiceLoaded = false;
let _voiceWrite = null;
const _voiceDrafts = new WeakMap();
const _voiceFields = [
  ['stt-select', 'stt_provider', true],
  ['tts-select', 'tts_provider', true],
  ['s-tts-voice', 'tts_voice', true],
  ['s-tts-speed', 'tts_speed', true],
  ['s-stt-language', 'stt_language', false],
  ['settings-openai-key', 'openai_api_key', false],
];

function _trackVoiceDrafts() {
  return _voiceFields.flatMap(([id, key, dropdown]) => {
    const el = document.getElementById(id);
    if (!el) return [];
    let draft = _voiceDrafts.get(el);
    if (!draft) {
      draft = { revision: 0, dirty: false };
      _voiceDrafts.set(el, draft);
      el.addEventListener(dropdown ? 'change' : 'input', () => {
        ++draft.revision;
        draft.dirty = true;
        if (_voiceLoaded && !_voiceWrite) _showVoiceState('unsaved voice changes', 'dirty');
      });
    }
    return [{ el, key, dropdown, draft }];
  });
}

function _showVoiceState(message, state, retry = false) {
  const pane = document.getElementById('s-pane-voice');
  if (!pane) return;
  let status = pane.querySelector('.settings-save-state');
  if (!status) {
    status = document.createElement('p');
    status.className = 'settings-save-state';
    status.setAttribute('role', 'status');
    pane.prepend(status);
  }
  let button = document.getElementById('s-voice-retry-btn');
  if (!button) {
    button = document.createElement('button');
    button.id = 's-voice-retry-btn';
    button.type = 'button';
    button.className = 'btn';
    button.textContent = 'retry voice settings';
    button.onclick = () => button.getAttribute('aria-disabled') !== 'true' && loadVoicePane();
    pane.prepend(button);
    pane.prepend(status);
  }
  status.textContent = message;
  status.dataset.state = state;
  // Retain retry focus while its request is running, then return to the form.
  const retryFocused = document.activeElement === button;
  button.hidden = !retry && !(state === 'loading' && retryFocused);
  // Native disabled blurs a focused button before the read completes.
  button.setAttribute('aria-disabled', String(state === 'loading'));
  if (button.hidden && retryFocused) document.getElementById('stt-select')?.focus();
}

function _refreshVoiceActions() {
  const unavailable = !_voiceLoaded || !!_voiceWrite;
  const save = document.getElementById('s-voice-save-btn');
  if (save) save.disabled = unavailable;
  const autoplay = document.getElementById('s-tts-enabled-toggle');
  if (autoplay) {
    autoplay.inert = unavailable;
    autoplay.setAttribute('aria-disabled', String(unavailable));
  }
}

async function loadVoicePane() {
  const read = ++_voiceReadGeneration;
  const fields = _trackVoiceDrafts();
  _voiceLoaded = false;
  _refreshVoiceActions();
  const pane = document.getElementById('s-pane-voice');
  // An earlier save receipt must not replace this opening's loading/error state.
  if (pane) pane.dataset.saveRevision = `voice-read-${read}`;
  _showVoiceState('loading voice settings…', 'loading');
  _loadMicDevices(++_voiceMicReadGeneration);
  try {
    // Reopening during a write must not read its old server baseline.
    if (_voiceWrite) await _voiceWrite;
    if (read !== _voiceReadGeneration) return;
    const s = await _endpointJson(await fetch('/api/settings'));
    if (read !== _voiceReadGeneration) return;
    if (!s || typeof s.stt_provider !== 'string' || typeof s.tts_provider !== 'string'
        || typeof s.tts_voice !== 'string' || typeof s.stt_language !== 'string'
        || !Number.isFinite(s.tts_speed) || typeof s.tts_auto_play !== 'boolean') {
      throw new Error('incomplete voice settings');
    }
    for (const { el, key, dropdown, draft } of fields) {
      // The API key is write-only. A read must never populate or clear its draft.
      if (draft.dirty || key === 'openai_api_key') continue;
      if (dropdown) setDropdownValue(el, String(s[key]));
      else el.value = s[key];
    }
    _bindSwitch(document.getElementById('s-tts-enabled-toggle'),
      () => s.tts_auto_play,
      on => _writeVoiceSettings({ tts_auto_play: on })
    );
    _voiceLoaded = true;
    _updateTtsVoiceRow();
    const dirty = fields.some(({ draft }) => draft.dirty);
    _showVoiceState(dirty ? 'unsaved voice changes' : 'voice settings loaded', dirty ? 'dirty' : 'loaded');
  } catch {
    if (read === _voiceReadGeneration) {
      _showVoiceState('could not load voice settings. retry to load your saved choices.', 'error', true);
    }
  } finally {
    if (read === _voiceReadGeneration) _refreshVoiceActions();
  }
}

// Populate device choices without requesting recording permission. Labels become
// available after the owner grants access through an explicit recording action.
async function _loadMicDevices(read = _voiceMicReadGeneration) {
  const el = document.getElementById('s-mic-select');
  if (!el || !navigator.mediaDevices?.enumerateDevices) return;
  if (!el.dataset.micBound) {
    el.dataset.micBound = '1';
    el.addEventListener('change', () => localStorage.setItem('alles-mic-id', getDropdownValue(el) || ''));
  }
  const devices = await navigator.mediaDevices.enumerateDevices().catch(() => null);
  if (!devices || read !== _voiceMicReadGeneration) return;
  const mics = devices.filter(d => d.kind === 'audioinput');
  const opts = [{ value: '', label: 'default microphone' },
    ...mics.map((m, i) => ({ value: m.deviceId, label: m.label || `microphone ${i + 1}` }))];
  const saved = localStorage.getItem('alles-mic-id') || '';
  populateDropdown(el, opts, opts.some(o => o.value === saved) ? saved : '');
}

function _updateTtsVoiceRow() {
  const tts = getDropdownValue(document.getElementById('tts-select'));
  const row = document.getElementById('s-tts-voice-row');
  if (row) row.style.display = tts === 'openai' ? 'flex' : 'none';
}

async function saveVoiceSettings() {
  if (!_voiceLoaded || _voiceWrite) return;
  const submitted = _trackVoiceDrafts().map(field => ({ ...field, revision: field.draft.revision }));
  const patch = {
    tts_provider: getDropdownValue(document.getElementById('tts-select')) || 'browser',
    stt_provider: getDropdownValue(document.getElementById('stt-select')) || 'browser',
    tts_voice:    getDropdownValue(document.getElementById('s-tts-voice')) || 'alloy',
    tts_speed:    parseFloat(getDropdownValue(document.getElementById('s-tts-speed')) || '1.0'),
    stt_language: document.getElementById('s-stt-language')?.value.trim() || '',
  };
  const key = document.getElementById('settings-openai-key')?.value.trim();
  if (key && submitted.some(field => field.key === 'openai_api_key' && field.draft.dirty)) patch.openai_api_key = key;
  if (await _writeVoiceSettings(patch, submitted)) {
    const dirty = submitted.some(({ draft }) => draft.dirty);
    toast(dirty ? 'earlier voice settings saved; your latest edits still need saving' : 'voice settings saved', 'success');
  }
}

async function _writeVoiceSettings(patch, submitted = []) {
  if (!_voiceLoaded || _voiceWrite) return null;
  const read = ++_voiceReadGeneration;
  const pending = _patchSettings(patch);
  _voiceWrite = pending;
  _refreshVoiceActions();
  try {
    const settings = await pending;
    if (settings) {
      for (const { draft, revision } of submitted) {
        if (draft.revision === revision) draft.dirty = false;
      }
      if (read === _voiceReadGeneration) {
        const dirty = _trackVoiceDrafts().some(({ draft }) => draft.dirty);
        _showVoiceState(dirty ? 'earlier voice settings saved; your latest edits still need saving' : 'saved', dirty ? 'dirty' : 'saved');
      }
    }
    return settings;
  } finally {
    if (_voiceWrite === pending) _voiceWrite = null;
    _refreshVoiceActions();
  }
}

// ── personas ──────────────────────────────────────────────────────────────────
let _personaCache = [];
let _editingPersona = null;
let _personaSavePending = false;
let _personaSavingId = null;
let _personaDocSavingId = null;
let _personaReadGeneration = 0;
let _personaDocsReadGeneration = 0;
const _personaDeletes = new Set();
const _personaDocDeletes = new Set();
const _personaDuplicates = new Set();

function _isSettingsPaneOpen(name) {
  const modal = document.getElementById('settings-modal');
  return _activePane === name && !!modal && modal.style.display !== 'none';
}

function _invalidateRetainedReads(name) {
  if (name === 'voice') {
    ++_voiceReadGeneration;
    ++_voiceMicReadGeneration;
    _voiceLoaded = false;
  } else if (name === 'memory') {
    ++_ownerInstructionsRead;
  } else if (name === 'personas') {
    ++_personaReadGeneration;
    ++_personaDocsReadGeneration;
    ++_cookbookReadGeneration;
  } else if (name === 'developer') {
    ++_developerOpening;
    ++_tokenReadGeneration;
    ++_webhookReadGeneration;
  }
}

function _personaRemovalPending(id) {
  return _personaDeletes.has(id) || _personaSavingId === id || _personaDocSavingId === id;
}

function _refreshPersonaPendingControls() {
  const save = document.getElementById('persona-add-btn');
  if (save) save.disabled = _personaSavePending || _personaDeletes.has(_editingPersona);
  const addDoc = document.getElementById('persona-doc-add');
  if (addDoc) addDoc.disabled = !!_personaDocSavingId || _personaDeletes.has(_editingPersona);
  document.querySelectorAll('#persona-list [data-persona-remove]').forEach(button => {
    button.disabled = _personaRemovalPending(button.dataset.id);
  });
  document.querySelectorAll('#persona-list [data-persona-duplicate]').forEach(button => {
    button.disabled = _personaDuplicates.has(button.dataset.id);
  });
}

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
  bar.setAttribute('aria-valuenow', _tempVal.toFixed(1));
  bar.setAttribute('aria-valuetext', _tempOn ? _tempVal.toFixed(1) : 'auto');
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

function _onTempKeydown(e) {
  let next;
  if (e.key === 'Home') next = 0;
  else if (e.key === 'End') next = 2;
  else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = _tempVal + TEMP_STEP;
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = _tempVal - TEMP_STEP;
  else return;
  e.preventDefault();
  _setPersonaTemp(next);
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
    '<button type="button" class="pa-swatch pa-none" data-hex="" title="no override: use your theme accent">default</button>' +
    PERSONA_ACCENTS.map(([hex, name]) =>
      `<button type="button" class="pa-swatch" data-hex="${hex}" title="${name}" style="background:${hex}"></button>`).join('');
  box.querySelectorAll('.pa-swatch').forEach(s => s.addEventListener('click', () => {
    _setPersonaAccent(s.dataset.hex);
    // live preview the re-theme as you pick (reset/save restores the real active accent)
    document.documentElement.style.setProperty('--accent', s.dataset.hex || ((JSON.parse(localStorage.getItem('alles-appearance')||'{}').colors||{}).accent || '#9298ff'));
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
  const opts = [{ value: '', label: "use chat's model (default)" }];
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
  const read = ++_personaReadGeneration;
  let personas;
  try {
    const response = await fetch('/api/personas');
    if (!response.ok) throw new Error('personas read failed');
    personas = await response.json();
    if (!Array.isArray(personas)) throw new Error('invalid personas response');
  } catch {
    if (read === _personaReadGeneration && _isSettingsPaneOpen('personas'))
      toast('personas could not be loaded', 'error');
    return;
  }
  if (read !== _personaReadGeneration || !_isSettingsPaneOpen('personas')) return;
  _personaCache = personas;
  if (!_personaCache.length) { el.innerHTML = '<div class="settings-row-empty">no personas yet</div>'; return; }
  el.innerHTML = _personaCache.map(p => {
    const prev = (p.system_prompt || '').replace(/\s+/g, ' ').trim();
    return `
    <div class="settings-list-row persona-row${_editingPersona === p.id ? ' editing' : ''}" data-id="${p.id}" onclick="window._editPersona('${p.id}')">
      <span class="row-name">${_esc(p.name)}${p.is_default ? ' <span class="row-tag">default</span>' : ''}</span>
      <span class="row-meta">${_esc(prev.slice(0, 60))}${prev.length > 60 ? '…' : ''}</span>
      <button type="button" class="act-btn" data-persona-edit aria-label="edit ${_escAttr(p.name)}" onclick="event.stopPropagation();window._editPersona('${p.id}')">edit</button>
      <button class="act-btn" data-id="${p.id}" data-persona-duplicate ${_personaDuplicates.has(p.id) ? 'disabled' : ''} onclick="event.stopPropagation();window._dupPersona('${p.id}')">duplicate</button>
      <button class="act-btn" data-id="${p.id}" data-persona-remove ${_personaRemovalPending(p.id) ? 'disabled' : ''} onclick="event.stopPropagation();window._rmPersona(this)">remove</button>
    </div>`;
  }).join('');
}

window._editPersona = id => {
  const p = _personaCache.find(x => x.id === id);
  if (!p) return;
  ++_personaDocsReadGeneration;
  if (_editingPersona !== id) document.getElementById('persona-docs')?.replaceChildren();
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
  _refreshPersonaPendingControls();
  document.getElementById('persona-prompt').focus();
};

// 10d — persona knowledge files + share
async function _loadPersonaDocs(pid) {
  const box = document.getElementById('persona-docs');
  if (!box) return;
  const read = ++_personaDocsReadGeneration;
  let docs;
  try {
    const response = await fetch(`/api/personas/${pid}/docs`);
    if (!response.ok) throw new Error('knowledge files read failed');
    docs = await response.json();
    if (!Array.isArray(docs)) throw new Error('invalid knowledge files response');
  } catch {
    if (read === _personaDocsReadGeneration && _editingPersona === pid && _isSettingsPaneOpen('personas'))
      toast('knowledge files could not be loaded', 'error');
    return;
  }
  if (read !== _personaDocsReadGeneration || _editingPersona !== pid || !_isSettingsPaneOpen('personas')) return;
  box.innerHTML = docs.length
    ? docs.map(d => `<div class="persona-doc-row"><span>📄 ${_esc(d.title)}</span>` +
        `<button class="act-btn" data-id="${_escAttr(d.id)}" data-persona-doc-remove ${_personaDocDeletes.has(`${pid}/${d.id}`) ? 'disabled' : ''}>remove</button></div>`).join('')
    : '<div class="settings-row-empty">no knowledge files yet</div>';
  box.querySelectorAll('.act-btn').forEach(b => b.onclick = async () => {
    const id = b.dataset.id;
    const key = `${pid}/${id}`;
    if (_personaDocDeletes.has(key)) return;
    _personaDocDeletes.add(key);
    ++_personaDocsReadGeneration;
    b.disabled = true;
    try {
      const response = await fetch(`/api/personas/${pid}/docs/${id}`, { method: 'DELETE' });
      if (!response.ok) { toast('knowledge file could not be removed', 'error'); return; }
      if (_editingPersona === pid) _loadPersonaDocs(pid);
    } catch { toast('knowledge file could not be removed', 'error'); }
    finally {
      _personaDocDeletes.delete(key);
      b.disabled = false;
      box.querySelectorAll('[data-persona-doc-remove]').forEach(button => {
        if (button.dataset.id === id) button.disabled = false;
      });
    }
  });
}

async function _addPersonaDoc() {
  const pid = _editingPersona;
  if (!pid || _personaDocSavingId || _personaDeletes.has(pid)) return;
  const fields = ['persona-doc-title', 'persona-doc-content'];
  const submitted = fields.map(id => document.getElementById(id).value);
  const [title, content] = submitted.map(value => value.trim());
  if (!content) { toast('paste some text first', 'error'); return; }
  _personaDocSavingId = pid;
  ++_personaDocsReadGeneration;
  _refreshPersonaPendingControls();
  try {
    const response = await fetch(`/api/personas/${pid}/docs`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title: title || 'untitled', content }),
    });
    if (!response.ok) { toast('knowledge file could not be added', 'error'); return; }
    if (_editingPersona === pid) {
      if (fields.every((id, index) => document.getElementById(id).value === submitted[index]))
        fields.forEach(id => { document.getElementById(id).value = ''; });
      _loadPersonaDocs(pid);
    }
    toast('knowledge file added', 'success');
  } catch { toast('knowledge file could not be added', 'error'); }
  finally { _personaDocSavingId = null; _refreshPersonaPendingControls(); }
}

async function _sharePersona() {
  if (!_editingPersona) return;
  try {
    const response = await fetch(`/api/personas/${_editingPersona}/share`, { method: 'POST' });
    if (!response.ok) { toast('share failed', 'error'); return; }
    const r = await response.json();
    if (typeof r.url !== 'string' || !r.url) { toast('share failed', 'error'); return; }
    const url = location.origin + r.url;
    try { await navigator.clipboard.writeText(url); toast('share link copied', 'success'); }
    catch { toast(url, ''); }
  } catch { toast('share failed', 'error'); }
}

function _resetPersonaForm() {
  ++_personaDocsReadGeneration;
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
  _refreshPersonaPendingControls();
  loadPersonas();
}

window._rmPersona = async btn => {
  const id = btn.dataset.id;
  if (_personaRemovalPending(id)) return;
  _personaDeletes.add(id);
  ++_personaReadGeneration;
  if (_editingPersona === id) ++_personaDocsReadGeneration;
  _refreshPersonaPendingControls();
  try {
    const response = await fetch(`/api/personas/${id}`, { method: 'DELETE' });
    if (!response.ok) { toast('persona could not be removed', 'error'); return; }
    if (_editingPersona === id) _resetPersonaForm();
    else loadPersonas();
    window._refreshPersonaBtn?.();
  } catch { toast('persona could not be removed', 'error'); }
  finally {
    _personaDeletes.delete(id);
    btn.disabled = false;
    _refreshPersonaPendingControls();
  }
};

window._dupPersona = async id => {
  if (_personaDuplicates.has(id)) return;
  _personaDuplicates.add(id);
  ++_personaReadGeneration;
  _refreshPersonaPendingControls();
  try {
    const response = await fetch(`/api/personas/${id}/duplicate`, { method: 'POST' });
    if (!response.ok) { toast('persona could not be duplicated', 'error'); return; }
    toast('duplicated', 'success'); loadPersonas(); window._refreshPersonaBtn?.();
  } catch { toast('persona could not be duplicated', 'error'); }
  finally { _personaDuplicates.delete(id); _refreshPersonaPendingControls(); }
};

function _personaDraft() {
  return {
    editing: _editingPersona,
    fields: {
      name: document.getElementById('persona-name').value,
      system_prompt: document.getElementById('persona-prompt').value,
      initial_message: document.getElementById('persona-initial')?.value || '',
      model: document.getElementById('persona-model')?.value || '',
      temperature: _tempOn ? _tempVal : null,
      is_default: !!document.getElementById('persona-default')?.classList.contains('on'),
      default_mode: _getPersonaMode(),
      accent: _getPersonaAccent(),
    },
    docTitle: document.getElementById('persona-doc-title')?.value || '',
    docContent: document.getElementById('persona-doc-content')?.value || '',
  };
}

async function addPersona() {
  if (_personaSavePending || _personaDeletes.has(_editingPersona)) return;
  const submitted = _personaDraft();
  const payload = { ...submitted.fields, name: submitted.fields.name.trim(),
    system_prompt: submitted.fields.system_prompt.trim(),
    initial_message: submitted.fields.initial_message.trim() };
  if (!payload.name) { toast('name required', 'error'); return; }
  _personaSavePending = true;
  _personaSavingId = submitted.editing;
  ++_personaReadGeneration;
  _refreshPersonaPendingControls();
  try {
    const response = await fetch(submitted.editing ? `/api/personas/${submitted.editing}` : '/api/personas', {
      method: submitted.editing ? 'PATCH' : 'POST', headers: {'content-type':'application/json'},
      body: JSON.stringify(payload),
    });
    if (!response.ok) { toast('persona could not be saved', 'error'); return; }
    toast(submitted.editing ? 'persona updated' : 'persona added', 'success');
    if (JSON.stringify(_personaDraft()) === JSON.stringify(submitted)) _resetPersonaForm();
    else loadPersonas();
    window._refreshPersonaBtn?.();
  } catch { toast('persona could not be saved', 'error'); }
  finally { _personaSavePending = false; _personaSavingId = null; _refreshPersonaPendingControls(); }
}

// ── cookbook ──────────────────────────────────────────────────────────────────
let _cookbookSavePending = false;
let _cookbookReadGeneration = 0;
const _cookbookDeletes = new Set();

export async function loadCookbook() {
  const el = document.getElementById('cookbook-list');
  if (!el) return;
  const read = ++_cookbookReadGeneration;
  let entries;
  try {
    const response = await fetch('/api/cookbook');
    if (!response.ok) throw new Error('commands read failed');
    entries = await response.json();
    if (!Array.isArray(entries)) throw new Error('invalid commands response');
  } catch {
    if (read === _cookbookReadGeneration && _isSettingsPaneOpen('personas'))
      toast('commands could not be loaded', 'error');
    return;
  }
  if (read !== _cookbookReadGeneration || !_isSettingsPaneOpen('personas')) return;
  if (!entries.length) { el.innerHTML = '<div class="settings-row-empty">no commands: type / in chat to use</div>'; return; }
  el.innerHTML = entries.map(e => `
    <div class="settings-list-row">
      <span class="row-name" style="color:var(--accent)">/${_esc(e.name)}</span>
      <span class="row-meta">${_esc(e.description || e.prompt.slice(0,40))}</span>
      <button class="act-btn" data-id="${e.id}" data-cookbook-remove ${_cookbookDeletes.has(e.id) ? 'disabled' : ''} onclick="window._rmCookbook(this)">remove</button>
    </div>`).join('');
}

window._rmCookbook = async btn => {
  const id = btn.dataset.id;
  if (_cookbookDeletes.has(id)) return;
  _cookbookDeletes.add(id);
  ++_cookbookReadGeneration;
  btn.disabled = true;
  try {
    const response = await fetch(`/api/cookbook/${id}`, { method: 'DELETE' });
    if (!response.ok) { toast('command could not be removed', 'error'); return; }
    loadCookbook();
  } catch { toast('command could not be removed', 'error'); }
  finally {
    _cookbookDeletes.delete(id);
    btn.disabled = false;
    document.querySelectorAll('#cookbook-list [data-cookbook-remove]').forEach(button => {
      if (button.dataset.id === id) button.disabled = false;
    });
  }
};

async function addCookbookEntry() {
  if (_cookbookSavePending) return;
  const fields = ['cookbook-name','cookbook-desc','cookbook-prompt'];
  const submitted = fields.map(id => document.getElementById(id).value);
  const [name, description, prompt] = submitted.map(value => value.trim());
  if (!name || !prompt) { toast('name + prompt required', 'error'); return; }
  const button = document.getElementById('cookbook-add-btn');
  _cookbookSavePending = true;
  ++_cookbookReadGeneration;
  button.disabled = true;
  try {
    const response = await fetch('/api/cookbook', { method: 'POST', headers: {'content-type':'application/json'},
      body: JSON.stringify({ name, description, prompt }) });
    if (!response.ok) { toast('command could not be saved', 'error'); return; }
    if (fields.every((id, index) => document.getElementById(id).value === submitted[index]))
      fields.forEach(id => document.getElementById(id).value = '');
    toast('added', 'success');
    loadCookbook();
  } catch { toast('command could not be saved', 'error'); }
  finally { _cookbookSavePending = false; button.disabled = false; }
}

// (session templates were merged into personas — a persona's "starter message" now
//  does what a template's initial message did; see openPersonaPicker in app.js)

// ── api tokens ────────────────────────────────────────────────────────────────
let _tokenCreatePending = false;
let _tokenReadGeneration = 0;
const _tokenRevokes = new Set();
async function loadTokens() {
  const el = document.getElementById('token-list');
  if (!el) return;
  const read = ++_tokenReadGeneration;
  let tokens;
  try {
    const response = await fetch('/api/tokens');
    if (!response.ok) throw new Error('tokens read failed');
    tokens = await response.json();
    if (!Array.isArray(tokens)) throw new Error('invalid tokens response');
  } catch {
    if (read === _tokenReadGeneration && _isSettingsPaneOpen('developer'))
      toast('tokens could not be loaded', 'error');
    return;
  }
  if (read !== _tokenReadGeneration || !_isSettingsPaneOpen('developer')) return;
  if (!tokens.length) { el.innerHTML = '<div class="settings-row-empty">no tokens</div>'; return; }
  el.innerHTML = tokens.map(t => `
    <div class="settings-list-row">
      <span class="row-name" style="font-family:monospace;font-size:0.75rem">${t.prefix}…</span>
      <span class="row-meta">${_esc(t.name)}</span>
      <span class="row-meta">${(t.scopes || []).map(_esc).join(', ') || 'no access'}</span>
      <span class="row-meta">${t.last_used_at ? 'used ' + formatDate(t.last_used_at) : 'never used'}</span>
      <button class="act-btn" data-id="${t.id}" data-token-revoke ${_tokenRevokes.has(t.id) ? 'disabled' : ''} onclick="window._rmToken(this)">revoke</button>
    </div>`).join('');
}

window._rmToken = async btn => {
  const id = btn.dataset.id;
  if (_tokenRevokes.has(id)) return;
  const restoreFocus = document.activeElement === btn;
  const opening = _developerOpening;
  _tokenRevokes.add(id);
  ++_tokenReadGeneration;
  btn.disabled = true;
  try {
    const response = await _fetchWithRecentOwner(`/api/tokens/${id}`, { method: 'DELETE' });
    if (!response.ok) { toast('token could not be revoked', 'error'); return; }
    loadTokens();
  } catch { toast('token could not be revoked', 'error'); }
  finally {
    _tokenRevokes.delete(id);
    btn.disabled = false;
    let currentButton = btn;
    document.querySelectorAll('#token-list [data-token-revoke]').forEach(button => {
      if (button.dataset.id === id) { button.disabled = false; currentButton = button; }
    });
    if (restoreFocus && opening === _developerOpening && _isSettingsPaneOpen('developer') &&
        document.activeElement === document.body && currentButton.isConnected && !currentButton.disabled)
      currentButton.focus({ preventScroll: true });
  }
};

async function generateToken() {
  if (_tokenCreatePending) return;
  const input = document.getElementById('token-name');
  const submittedName = input.value;
  const name = submittedName.trim();
  if (!name) { toast('name required', 'error'); return; }
  const scopes = [...document.querySelectorAll('[data-token-scope].active')]
    .map(btn => btn.dataset.tokenScope);
  if (!scopes.length) { toast('choose at least one permission', 'error'); return; }
  const button = document.getElementById('token-add-btn');
  const restoreFocus = document.activeElement === button;
  const opening = _developerOpening;
  _tokenCreatePending = true;
  ++_tokenReadGeneration;
  button.disabled = true;
  try {
    const r = await _fetchWithRecentOwner('/api/tokens', {
      method: 'POST', headers: {'content-type':'application/json'},
      body: JSON.stringify({ name, scopes }),
    });
    const data = await r.json();
    if (!r.ok) { toast(data?.detail || 'token could not be created', 'error'); return; }
    if (typeof data?.token !== 'string' || !data.token) throw new Error('invalid token receipt');
    const currentScopes = [...document.querySelectorAll('[data-token-scope].active')]
      .map(btn => btn.dataset.tokenScope);
    if (input.value === submittedName && JSON.stringify(currentScopes) === JSON.stringify(scopes)) input.value = '';
    const reveal = document.getElementById('token-reveal');
    reveal.style.display = 'block';
    reveal.textContent = data.token;
    reveal.title = 'click to copy';
    reveal.onclick = () => _copySettingsValue(reveal, 'token');
    toast('token generated: copy it now, shown once', 'success');
    loadTokens();
  } catch { toast('token could not be created', 'error'); }
  finally {
    _tokenCreatePending = false;
    button.disabled = false;
    if (restoreFocus && opening === _developerOpening && _isSettingsPaneOpen('developer') &&
        document.activeElement === document.body && button.isConnected &&
        document.getElementById('token-add-btn') === button)
      button.focus({ preventScroll: true });
  }
}

const _settingsCopies = new WeakSet();
async function _copySettingsValue(target, label) {
  if (_settingsCopies.has(target)) return;
  const value = target.textContent;
  const opening = _developerOpening;
  const isCurrent = () => target.isConnected && target.textContent === value &&
    opening === _developerOpening && _isSettingsPaneOpen('developer');
  _settingsCopies.add(target);
  target.setAttribute('aria-busy', 'true');
  try {
    await navigator.clipboard.writeText(value);
    if (isCurrent()) toast(`${label} copied`, 'success');
  } catch {
    if (isCurrent()) toast('copy failed; select the shown value and copy manually, or try again', 'error');
  } finally {
    _settingsCopies.delete(target);
    target.removeAttribute('aria-busy');
  }
}

// ── webhooks ──────────────────────────────────────────────────────────────────
let _webhookSavePending = false;
let _webhookReadGeneration = 0;
const _webhookDeletes = new Set();
const _webhookTests = new Set();
function _refreshWebhookPendingControls() {
  document.querySelectorAll('#webhook-list [data-webhook-test], #webhook-list [data-webhook-remove]').forEach(button => {
    const id = button.dataset.id;
    button.disabled = _webhookTests.has(id) || _webhookDeletes.has(id);
    if (button.hasAttribute('data-webhook-test')) button.textContent = _webhookTests.has(id) ? '…' : 'test';
  });
}
async function loadWebhooks() {
  const el = document.getElementById('webhook-list');
  if (!el) return;
  const read = ++_webhookReadGeneration;
  let hooks;
  try {
    const response = await fetch('/api/webhooks');
    if (!response.ok) throw new Error('webhooks read failed');
    hooks = await response.json();
    if (!Array.isArray(hooks)) throw new Error('invalid webhooks response');
  } catch {
    if (read === _webhookReadGeneration && _isSettingsPaneOpen('developer'))
      toast('webhooks could not be loaded', 'error');
    return;
  }
  if (read !== _webhookReadGeneration || !_isSettingsPaneOpen('developer')) return;
  if (!hooks.length) { el.innerHTML = '<div class="settings-row-empty">no webhooks</div>'; return; }
  el.innerHTML = hooks.map(h => {
    const pending = _webhookTests.has(h.id) || _webhookDeletes.has(h.id);
    const st = h.last_status === 'ok' ? ' · ✓ ok'
      : h.last_status ? ` · ✕ ${_esc(h.last_error || h.last_status)}` : '';
    return `
    <div class="settings-list-row">
      <span class="status-dot" style="background:${h.enabled ? 'var(--green)' : 'var(--faint)'}"></span>
      <span class="row-name">${_esc(h.name)}</span>
      <span class="row-meta">${h.events.join(', ')}${st}</span>
      ${h.secret ? `<button type="button" class="wh-secret act-btn" aria-label="copy webhook signing key" title="HMAC-SHA256 signing key: verify the X-Alles-Signature header with this" style="font-family:monospace;font-size:0.75rem;color:var(--muted);max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;user-select:all;text-transform:none;letter-spacing:normal">${_esc(h.secret)}</button>` : ''}
      <button class="act-btn" data-id="${h.id}" data-webhook-test ${pending ? 'disabled' : ''} onclick="window._testWebhook(this)">${_webhookTests.has(h.id) ? '…' : 'test'}</button>
      <button class="act-btn" data-id="${h.id}" data-webhook-remove ${pending ? 'disabled' : ''} onclick="window._rmWebhook(this)">remove</button>
    </div>`;
  }).join('');
  el.querySelectorAll('.wh-secret').forEach(button => {
    button.addEventListener('click', () => _copySettingsValue(button, 'signing key'));
  });
}

window._testWebhook = async btn => {
  const id = btn.dataset.id;
  if (_webhookTests.has(id) || _webhookDeletes.has(id)) return;
  _webhookTests.add(id);
  ++_webhookReadGeneration;
  btn.disabled = true; const old = btn.textContent; btn.textContent = '…';
  _refreshWebhookPendingControls();
  try {
    const response = await fetch(`/api/webhooks/${id}/test`, { method: 'POST' });
    if (!response.ok) throw new Error('webhook test failed');
    const r = await response.json();
    toast(r.status === 'ok' ? 'webhook delivered ✓' : `failed: ${r.error || r.status}`, r.status === 'ok' ? 'success' : 'error');
  } catch { toast('test failed', 'error'); }
  finally {
    _webhookTests.delete(id);
    btn.disabled = false; btn.textContent = old;
    _refreshWebhookPendingControls();
  }
  loadWebhooks();
};

window._rmWebhook = async btn => {
  const id = btn.dataset.id;
  if (_webhookDeletes.has(id) || _webhookTests.has(id)) return;
  _webhookDeletes.add(id);
  ++_webhookReadGeneration;
  btn.disabled = true;
  _refreshWebhookPendingControls();
  try {
    const response = await fetch(`/api/webhooks/${id}`, { method: 'DELETE' });
    if (!response.ok) { toast('webhook could not be removed', 'error'); return; }
    loadWebhooks();
  } catch { toast('webhook could not be removed', 'error'); }
  finally {
    _webhookDeletes.delete(id);
    btn.disabled = false;
    _refreshWebhookPendingControls();
  }
};

async function addWebhook() {
  if (_webhookSavePending) return;
  const fields = ['wh-name','wh-url'];
  const submitted = fields.map(id => document.getElementById(id).value);
  const [name, url] = submitted.map(value => value.trim());
  if (!name || !url) { toast('name + url required', 'error'); return; }
  const button = document.getElementById('wh-add-btn');
  _webhookSavePending = true;
  ++_webhookReadGeneration;
  button.disabled = true;
  try {
    const response = await fetch('/api/webhooks', { method: 'POST', headers: {'content-type':'application/json'},
      body: JSON.stringify({ name, url, events: ['message'] }) });
    if (!response.ok) { toast('webhook could not be saved', 'error'); return; }
    if (fields.every((id, index) => document.getElementById(id).value === submitted[index]))
      fields.forEach(id => document.getElementById(id).value = '');
    toast('webhook added', 'success');
    loadWebhooks();
  } catch { toast('webhook could not be saved', 'error'); }
  finally { _webhookSavePending = false; button.disabled = false; }
}

// ── recall pane ───────────────────────────────────────────────────────────────
async function _loadPaneSettings(name) {
  try {
    const settings = await _endpointJson(await fetch('/api/settings'));
    if (!Number.isFinite(settings?.context_limit) || typeof settings.language !== 'string') throw new Error('incomplete settings');
    return settings;
  } catch (error) {
    toast(`could not load ${name} settings: ${error.message || 'server unavailable'}. reopen this section to retry.`, 'error');
    return null;
  }
}

async function loadRecallPane() {
  const s = await _loadPaneSettings('recall');
  if (!s) return;
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
  if (rb && !rb.dataset.bound) {
    rb.dataset.bound = '1';
    rb.addEventListener('click', async () => {
      if (rb.disabled) return;
      rb.disabled = true;
      try {
        await _endpointJson(await fetch('/api/recall/reindex', { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }));
        await loadRecallPane();
      } catch { toast('reindex failed; try again', 'error'); }
      finally { rb.disabled = false; }
    });
  }
  const cb = document.getElementById('s-pidx-clear');
  if (cb && !cb.dataset.bound) {
    cb.dataset.bound = '1';
    let pending = false;
    cb.addEventListener('click', async () => {
      if (pending) return;
      pending = true;
      try {
        if (!await _dlgConfirm('clear the recall index?')) return;
        cb.disabled = true;
        const result = await _endpointJson(await fetch('/api/recall/clear', { method: 'POST' }));
        if (!Number.isInteger(result?.removed) || result.removed < 0) throw new Error('clear result could not be confirmed');
        await loadRecallPane();
      } catch { toast('clear failed; try again', 'error'); }
      finally { pending = false; cb.disabled = false; }
    });
  }
}

async function loadProactivePane() {
  const s = await _loadPaneSettings('background checks');
  if (!s) return;
  const sw = (id, key, defOn) => {
    const el = document.getElementById(id);
    if (!el) return;
    _bindSwitch(el, () => s[key] === undefined ? defOn : !!s[key], value => _patchSetting(key, value));
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
    _bindSwitch(pushEl, () => s.pidx_proactive_channel === 'push',
      value => _patchSetting('pidx_proactive_channel', value ? 'push' : 'inapp'));
  }

  const run = document.getElementById('s-prox-run');
  const status = document.getElementById('s-prox-status');
  if (run && !run.dataset.bound) {
    run.dataset.bound = '1';
    run.addEventListener('click', async () => {
      if (run.disabled) return;
      run.disabled = true;
      if (status) status.textContent = 'thinking...';
      try {
        const r = await _endpointJson(await fetch('/api/proactive/run', { method: 'POST' }));
        if (!r || (r.ran !== true && r.ran !== false)
          || (r.ran && (!Number.isInteger(r.written) || r.written < 0 || !Number.isInteger(r.signals) || r.signals < 0))
          || (!r.ran && (typeof r.reason !== 'string' || !r.reason))) throw new Error('run result could not be confirmed');
        if (status) status.textContent = r.ran
          ? `done - ${r.written} new card${r.written === 1 ? '' : 's'} from ${r.signals} signal${r.signals === 1 ? '' : 's'}`
          : `not run (${r.reason.replaceAll('_', ' ')})`;
      } catch { if (status) status.textContent = 'run failed; try again'; }
      finally { run.disabled = false; }
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
  const s = await _loadPaneSettings('patterns & suggestions');
  if (!s) return;
  const sw = (id, key, defOn) => {
    const el = document.getElementById(id);
    if (!el) return;
    _bindSwitch(el, () => s[key] === undefined ? defOn : !!s[key], value => _patchSetting(key, value));
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
      if (b.disabled) return;
      b.disabled = true;
      if (status) status.textContent = 'thinking...';
      try {
        const r = await _endpointJson(await fetch(path, { method: 'POST' }));
        if (!r || (r.ran !== true && r.ran !== false)
          || (r.ran && (!Number.isInteger(r.count) || r.count < 0))
          || (!r.ran && (typeof r.reason !== 'string' || !r.reason))) throw new Error('run result could not be confirmed');
        if (status) status.textContent = r.ran
          ? `done - ${r.count} new ${label}`
          : `not run (${r.reason.replaceAll('_', ' ')})`;
      } catch { if (status) status.textContent = 'run failed; try again'; }
      finally { b.disabled = false; }
    });
  };
  runBtn('s-intel-insights-run', '/api/insights/run', 'insight(s)');
  runBtn('s-intel-distill-run', '/api/memory/distill/run', 'fact(s)');
}

// ── rules pane: personal automations ──────────────────────────────────────────
let _ruleOpts = null;
let _rulesWired = false;
let _editingRule = null;   // rule id being edited (null = adding a new one)
let _ruleSavePending = false;
let _ruleFormRevision = 0;
let _rulesRead = 0;
let _rulesPaneRead = 0;
const _ruleMutations = new Set();

// one-click starting points — prefill the form with a sensible rule to tweak
const _RULE_PRESETS = [
  { label: 'morning digest', trigger: 'daily_at', trigger_arg: '08:00', action: 'push_digest', action_arg: '', name: 'morning digest' },
  { label: 'briefing → discord/telegram', trigger: 'daily_at', trigger_arg: '08:00', action: 'notify_digest', action_arg: '', name: 'morning briefing' },
  { label: 'important email → task', trigger: 'mail_from', trigger_arg: '', action: 'create_task', action_arg: '{subject}: from {from}', name: '' },
  { label: 'renewal heads-up', trigger: 'sub_renewing', trigger_arg: '3', action: 'push', action_arg: '{name} renews in 3 days', name: 'renewal reminder' },
  { label: 'upcoming day', trigger: 'day_event_near', trigger_arg: '7', action: 'push', action_arg: '{name} is in a week', name: '' },
];

async function loadRulesPane() {
  const read = ++_rulesPaneRead;
  if (!_ruleOpts) {
    try {
      const options = await _endpointJson(await fetch('/api/automations/options'));
      if (!Array.isArray(options?.triggers) || !Array.isArray(options?.actions)) throw new Error('incomplete rule options');
      if (read !== _rulesPaneRead) return;
      _ruleOpts = options;
    } catch {
      if (read === _rulesPaneRead) toast('could not load rule options; reopen this section to retry', 'error');
      return;
    }
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
    ['rule-name', 'rule-trigger-arg', 'rule-action-arg'].forEach(id =>
      document.getElementById(id)?.addEventListener('input', () => { ++_ruleFormRevision; }));
    ['rule-trigger', 'rule-action'].forEach(id =>
      document.getElementById(id)?.addEventListener('change', () => { ++_ruleFormRevision; }));
    document.getElementById('rule-add-btn')?.addEventListener('click', _addRule);
    document.getElementById('rule-cancel-btn')?.addEventListener('click', _resetRuleForm);
    _renderRulePresets();
  }
  // delivery channels (discord / telegram) persist as settings; the notify actions use them
  const s = await _loadPaneSettings('rules & delivery');
  if (!s || read !== _rulesPaneRead) return;
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
  ++_ruleFormRevision;
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
  ++_ruleFormRevision;
  _editingRule = null;
  ['rule-trigger-arg', 'rule-action-arg', 'rule-name'].forEach(id => { const e = document.getElementById(id); if (e) e.value = ''; });
  document.getElementById('rule-add-btn').textContent = 'add rule';
  document.getElementById('rule-cancel-btn').style.display = 'none';
}

async function _renderRules() {
  const el = document.getElementById('rules-list');
  if (!el) return;
  const read = ++_rulesRead;
  let rules;
  try {
    rules = await _endpointJson(await fetch('/api/automations'));
    if (!Array.isArray(rules)) throw new Error('incomplete rules list');
  } catch {
    if (read === _rulesRead) toast('could not load rules; reopen this section to retry', 'error');
    return;
  }
  if (read !== _rulesRead) return;
  if (!rules.length) {
    el.innerHTML = '<div class="settings-row-empty">no rules yet: your first automation is one form away</div>';
    return;
  }
  const label = (list, v) => list.find(x => x.value === v)?.label || v;
  el.innerHTML = rules.map(r => `
    <div class="rule-row${r.enabled ? '' : ' off'}" data-id="${r.id}">
      <button type="button" class="rule-row-main" aria-label="edit rule ${_escAttr(r.name)}" style="background:none;border:0;color:inherit;font:inherit;text-align:left">
        <span class="rule-row-name">${_esc(r.name)}</span>
        <span class="rule-row-desc">${_esc(label(_ruleOpts.triggers, r.trigger))} <b>${_esc(r.trigger_arg)}</b> → ${_esc(label(_ruleOpts.actions, r.action))}${r.action_arg ? `: <i>${_esc(r.action_arg.slice(0, 60))}</i>` : ''}</span>
        ${r.last_attempt && r.last_attempt.status !== 'succeeded' ? `<span class="rule-row-desc" title="${_esc(r.last_attempt.error || '')}">last attempt: <b>${_esc(r.last_attempt.status)}</b></span>` : ''}
      </button>
      <button class="btn" data-act="test" title="run once with sample data">test</button>
      <button class="btn" data-act="toggle">${r.enabled ? 'pause' : 'resume'}</button>
      <button class="btn danger" data-act="del">×</button>
    </div>`).join('');
  el.querySelectorAll('.rule-row').forEach(row => {
    const id = row.dataset.id;
    row.querySelectorAll('button').forEach(button => { button.disabled = _ruleMutations.has(id); });
    row.querySelector('.rule-row-main')?.addEventListener('click', () => {
      const r = rules.find(x => x.id === id);
      if (r) _fillRuleForm(r, id);
    });
    row.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', async () => {
      if (b.dataset.act === 'del' || b.dataset.act === 'toggle') {
        if (_ruleMutations.has(id)) return;
        const deleting = b.dataset.act === 'del';
        const enabled = row.classList.contains('off');
        _ruleMutations.add(id);
        ++_rulesRead;
        row.querySelectorAll('button').forEach(button => { button.disabled = true; });
        try {
          const result = await _endpointJson(await fetch(`/api/automations/${id}`, deleting ? { method: 'DELETE' } : {
            method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled }),
          }));
          if (deleting ? result?.ok !== true : result?.id !== id || result.enabled !== enabled) throw new Error('rule change could not be confirmed');
          await _renderRules();
        } catch { toast(deleting ? 'rule could not be deleted; try again' : 'rule could not be updated; try again', 'error'); }
        finally {
          _ruleMutations.delete(id);
          el.querySelectorAll('.rule-row').forEach(current => {
            if (current.dataset.id === id) current.querySelectorAll('button').forEach(button => { button.disabled = false; });
          });
        }
        return;
      }
      if (b.dataset.act === 'test') {
        if (b.disabled) return;
        b.disabled = true;
        try {
          const result = await _endpointJson(await fetch(`/api/automations/${id}/test`, { method: 'POST' }));
          if (result?.ok !== true) throw new Error('test result could not be confirmed');
          toast('rule fired with sample data: check the result', 'success');
        } catch { toast('test failed; check the rule and try again', 'error'); }
        finally { b.disabled = false; }
      }
    }));
  });
}

async function _addRule() {
  if (_ruleSavePending) return;
  const button = document.getElementById('rule-add-btn');
  const fields = ['rule-name', 'rule-trigger-arg', 'rule-action-arg'].map(id => document.getElementById(id));
  const submitted = fields.map(field => field?.value || '');
  const body = {
    name: submitted[0].trim(),
    trigger: document.getElementById('rule-trigger')?.dataset.value,
    trigger_arg: submitted[1].trim(),
    action: document.getElementById('rule-action')?.dataset.value,
    action_arg: submitted[2].trim(),
  };
  const editing = _editingRule;
  const revision = _ruleFormRevision;
  _ruleSavePending = true;
  if (button) button.disabled = true;
  try {
    const result = await _endpointJson(await fetch(editing ? `/api/automations/${editing}` : '/api/automations', {
      method: editing ? 'PATCH' : 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }));
    if (!result?.id || (editing && result.id !== editing)) throw new Error('rule save could not be confirmed');
    if (_editingRule === editing && _ruleFormRevision === revision
      && fields.every((field, i) => (field?.value || '') === submitted[i])
      && document.getElementById('rule-trigger')?.dataset.value === body.trigger
      && document.getElementById('rule-action')?.dataset.value === body.action) _resetRuleForm();
    toast(editing ? 'rule updated' : 'rule added: it runs automatically from now on', 'success');
    await _renderRules();
  } catch (error) { toast(error.message || 'failed to save rule; try again', 'error'); }
  finally { _ruleSavePending = false; if (button) button.disabled = false; }
}
