import { createSettingsPane } from './pane.js';
import { toast } from '../util.js';

// ── Home customization ───────────────────────────────────────────────────────
const HOME_SECTION_KEYS = ['needs_you', 'today', 'in_progress', 'briefs', 'shortcuts'];
const HOME_SHORTCUT_KEYS = ['plan', 'inbox', 'wiki', 'files', 'library', 'health', 'finance', 'vault', 'system'];
const HOME_DEFAULT_SHORTCUTS = ['plan', 'wiki', 'files'];
const HOME_SHORTCUT_LABELS = { plan: 'plan', inbox: 'inbox', wiki: 'docs', files: 'files', library: 'library', health: 'health', finance: 'finance', vault: 'vault', system: 'server' };
const HOME_SHORTCUT_ALIASES = { calendar: 'plan', tasks: 'plan', days: 'plan', reminders: 'plan', mail: 'inbox', contacts: 'inbox', notes: 'wiki', journal: 'wiki', photos: 'files', gallery: 'files', books: 'library', read: 'library', habits: 'health', money: 'finance', subs: 'finance', secrets: 'vault', server: 'system', watch: 'system', activity: 'system' };
let _homeSettingsState = null;
let _homeSettingsChanges = 0;
let _homeSettingsLoadGeneration = 0;
let _homeSettingsBusy = false;
let _homeSettingsSaving = false;

function _homeRows(id) {
  const list = document.getElementById(id);
  return list ? [...list.querySelectorAll(':scope > .home-settings-row')] : [];
}

export function _mergeHomeShortcutOrder(
  enabledShortcuts,
  original = _homeSettingsState?.shortcutOrder || [],
) {
  const enabled = [...new Set(enabledShortcuts.filter(key => HOME_SHORTCUT_KEYS.includes(key)))];
  const enabledSet = new Set(enabled);
  const retained = original.filter(
    key => !HOME_SHORTCUT_KEYS.includes(key) || enabledSet.has(key),
  );
  let knownIndex = 0;
  const merged = retained.map(
    key => HOME_SHORTCUT_KEYS.includes(key) ? enabled[knownIndex++] : key,
  );
  return [...merged, ...enabled.slice(knownIndex)];
}

function _normalizeHomeSettingsPreferences(value = {}) {
  const raw = value && typeof value === 'object' ? value : {};
  const order = [...new Set(Array.isArray(raw.order) ? raw.order.filter(key => HOME_SECTION_KEYS.includes(key)) : [])];
  for (const key of HOME_SECTION_KEYS) if (!order.includes(key)) order.push(key);
  const visible = [...new Set(Array.isArray(raw.visible) ? raw.visible.filter(key => HOME_SECTION_KEYS.includes(key)) : HOME_SECTION_KEYS)];
  if (!visible.includes('needs_you')) visible.unshift('needs_you');
  const sourceShortcuts = Array.isArray(raw.shortcuts) ? raw.shortcuts : HOME_DEFAULT_SHORTCUTS;
  const shortcuts = [...new Set(sourceShortcuts
    .map(value => String(value || '').trim().toLowerCase())
    .map(value => HOME_SHORTCUT_ALIASES[value] || value)
    .filter(value => HOME_SHORTCUT_KEYS.includes(value)))].slice(0, 20);
  return {
    order,
    visible,
    density: raw.density === 'compact' ? 'compact' : 'comfortable',
    shortcuts,
  };
}

function _setHomeSettingsSwitch(button, on) {
  if (!button) return;
  button.setAttribute('aria-checked', String(!!on));
  const row = button.closest('.home-settings-row');
  if (row) row.dataset.enabled = String(!!on);
}

function _setHomeSettingsStatus(message) {
  const status = document.getElementById('home-settings-save-state');
  if (status) status.textContent = message;
}

function _setHomeSettingsBusy(busy) {
  _homeSettingsBusy = busy;
  const workbench = document.getElementById('home-settings-workbench');
  const reset = document.getElementById('home-settings-reset');
  const save = document.getElementById('home-settings-save');
  if (workbench) {
    workbench.inert = busy;
    workbench.setAttribute('aria-busy', String(busy));
  }
  if (reset) reset.disabled = busy;
  if (save) save.disabled = busy;
}

function _markHomeSettingsChanged(message) {
  _homeSettingsChanges += 1;
  _setHomeSettingsStatus(`${_homeSettingsChanges} unsaved ${_homeSettingsChanges === 1 ? 'change' : 'changes'} · ${message}`);
}

function _updateHomeMoveButtons(list) {
  const rows = [...list.querySelectorAll(':scope > .home-settings-row')];
  rows.forEach((row, index) => {
    row.querySelector('[data-home-move="up"]').disabled = index === 0;
    row.querySelector('[data-home-move="down"]').disabled = index === rows.length - 1;
  });
}

function _updateHomeSettingsPreview() {
  const sectionRows = _homeRows('home-settings-sections');
  const preview = document.getElementById('home-settings-preview-list');
  let visibleCount = 0;
  for (const row of sectionRows) {
    const item = preview?.querySelector(`[data-home-preview="${CSS.escape(row.dataset.homeSection)}"]`);
    if (!item) continue;
    preview.appendChild(item);
    item.hidden = row.dataset.enabled !== 'true';
    if (!item.hidden) visibleCount += 1;
  }
  const count = document.getElementById('home-settings-preview-count');
  if (count) count.textContent = `${visibleCount} ${visibleCount === 1 ? 'section' : 'sections'}`;

  const enabledShortcuts = _homeRows('home-settings-shortcuts')
    .filter(row => row.dataset.enabled === 'true')
    .map(row => row.dataset.homeShortcut);
  const labels = _mergeHomeShortcutOrder(enabledShortcuts)
    .map(key => HOME_SHORTCUT_LABELS[key] || key);
  const shortcutPreview = document.getElementById('home-settings-preview-shortcuts');
  if (shortcutPreview) shortcutPreview.textContent = labels.length ? labels.join(' · ') : 'no pinned apps selected';

  const sections = document.getElementById('home-settings-sections');
  const shortcuts = document.getElementById('home-settings-shortcuts');
  if (sections) _updateHomeMoveButtons(sections);
  if (shortcuts) _updateHomeMoveButtons(shortcuts);
}

function _chooseHomeDensity(button, announce = true) {
  document.querySelectorAll('[data-home-density]').forEach(choice => {
    const active = choice === button;
    choice.setAttribute('aria-checked', String(active));
    choice.tabIndex = active ? 0 : -1;
  });
  if (_homeSettingsState) _homeSettingsState.density = button.dataset.homeDensity;
  if (announce) _markHomeSettingsChanged(`${button.dataset.homeDensity} density`);
}

function _renderHomeSettingsPreferences(value) {
  const normalized = _normalizeHomeSettingsPreferences(value);
  const sectionList = document.getElementById('home-settings-sections');
  const shortcutList = document.getElementById('home-settings-shortcuts');
  if (!sectionList || !shortcutList) return;

  normalized.order.forEach(key => {
    const row = sectionList.querySelector(`[data-home-section="${CSS.escape(key)}"]`);
    if (row) sectionList.appendChild(row);
  });
  const visible = new Set(normalized.visible);
  _homeRows('home-settings-sections').forEach(row => {
    _setHomeSettingsSwitch(row.querySelector('[role="switch"]'), visible.has(row.dataset.homeSection));
  });

  const knownOrder = normalized.shortcuts.filter(key => HOME_SHORTCUT_KEYS.includes(key));
  for (const key of HOME_SHORTCUT_KEYS) if (!knownOrder.includes(key)) knownOrder.push(key);
  knownOrder.forEach(key => {
    const row = shortcutList.querySelector(`[data-home-shortcut="${CSS.escape(key)}"]`);
    if (row) shortcutList.appendChild(row);
  });
  const enabledShortcuts = new Set(normalized.shortcuts);
  _homeRows('home-settings-shortcuts').forEach(row => {
    _setHomeSettingsSwitch(row.querySelector('[role="switch"]'), enabledShortcuts.has(row.dataset.homeShortcut));
  });

  _homeSettingsState = {
    ...normalized,
    shortcutOrder: [...normalized.shortcuts],
  };
  _chooseHomeDensity(document.querySelector(`[data-home-density="${normalized.density}"]`), false);
  _homeSettingsChanges = 0;
  _setHomeSettingsStatus('no unsaved changes');
  _updateHomeSettingsPreview();
}

function _homeSettingsPayload() {
  const visible = _homeRows('home-settings-sections')
    .filter(row => row.dataset.enabled === 'true')
    .map(row => row.dataset.homeSection);
  if (!visible.includes('needs_you')) visible.unshift('needs_you');
  return {
    order: _homeRows('home-settings-sections').map(row => row.dataset.homeSection),
    visible,
    density: document.querySelector('[data-home-density][aria-checked="true"]')?.dataset.homeDensity || 'comfortable',
    shortcuts: _mergeHomeShortcutOrder(
      _homeRows('home-settings-shortcuts')
        .filter(row => row.dataset.enabled === 'true')
        .map(row => row.dataset.homeShortcut),
    ),
  };
}

async function loadHomeSettingsPane(isCurrent) {
  const workbench = document.getElementById('home-settings-workbench');
  const loadState = document.getElementById('home-settings-load-state');
  const save = document.getElementById('home-settings-save');
  if (!workbench || !loadState || !save) return;
  if (_homeSettingsBusy) return;
  if (_homeSettingsChanges > 0) {
    loadState.textContent = 'unsaved changes kept here';
    return;
  }
  const generation = ++_homeSettingsLoadGeneration;
  _setHomeSettingsBusy(true);
  loadState.textContent = 'loading preferences…';
  try {
    const response = await fetch('/api/today/preferences');
    if (!response.ok) throw new Error('preferences unavailable');
    const value = await response.json();
    if (generation !== _homeSettingsLoadGeneration || !isCurrent()) return;
    _renderHomeSettingsPreferences(value);
    loadState.textContent = 'saved on this Alles server';
  } catch {
    if (generation !== _homeSettingsLoadGeneration || !isCurrent()) return;
    loadState.textContent = 'preferences could not load';
    _setHomeSettingsStatus('Home settings are unavailable. Close Settings and try again.');
  } finally {
    if (generation === _homeSettingsLoadGeneration) _setHomeSettingsBusy(false);
  }
}

async function _saveHomeSettings() {
  const button = document.getElementById('home-settings-save');
  const loadState = document.getElementById('home-settings-load-state');
  if (!button || _homeSettingsBusy) return;
  const focusTarget = document.activeElement;
  _homeSettingsSaving = true;
  _setHomeSettingsBusy(true);
  _setHomeSettingsStatus('saving Home…');
  try {
    const response = await fetch('/api/today/preferences', {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(_homeSettingsPayload()),
    });
    const value = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(value.detail || 'Home settings could not save');
    _renderHomeSettingsPreferences(value);
    _setHomeSettingsStatus('saved just now');
    if (loadState) loadState.textContent = 'saved on this Alles server';
    window.dispatchEvent(new CustomEvent('alles:home-preferences-changed', { detail: value }));
  } catch (error) {
    _setHomeSettingsStatus(error.message || 'Home settings could not save');
    toast(error.message || 'Home settings could not save', 'error');
  } finally {
    _homeSettingsSaving = false;
    _setHomeSettingsBusy(false);
    if (focusTarget?.isConnected && document.getElementById('s-pane-home')?.classList.contains('active')
      && document.getElementById('settings-modal')?.style.display !== 'none') {
      focusTarget.focus({ preventScroll: true });
    }
  }
}

function _resetHomeSettings() {
  if (_homeSettingsBusy) return;
  _renderHomeSettingsPreferences({
    order: HOME_SECTION_KEYS,
    visible: HOME_SECTION_KEYS,
    density: 'comfortable',
    shortcuts: HOME_DEFAULT_SHORTCUTS,
  });
  _homeSettingsChanges = 1;
  _setHomeSettingsStatus('1 unsaved change · defaults restored');
}

function _wireHomeSettingsPane() {
  const pane = document.getElementById('s-pane-home');
  if (!pane) return;
  pane.addEventListener('click', event => {
    if (_homeSettingsBusy) return;
    const toggle = event.target.closest('[data-home-section-switch], [data-home-shortcut-switch]');
    if (toggle) {
      const next = toggle.getAttribute('aria-checked') !== 'true';
      _setHomeSettingsSwitch(toggle, next);
      _markHomeSettingsChanged(next ? 'item shown' : 'item hidden');
      _updateHomeSettingsPreview();
      return;
    }

    const move = event.target.closest('[data-home-move]');
    if (move && !move.disabled) {
      const row = move.closest('.home-settings-row');
      const target = move.dataset.homeMove === 'up' ? row.previousElementSibling : row.nextElementSibling;
      if (move.dataset.homeMove === 'up') row.parentElement.insertBefore(row, target);
      else row.parentElement.insertBefore(target, row);
      _markHomeSettingsChanged('order updated');
      _updateHomeSettingsPreview();
      const focusTarget = move.disabled
        ? row.querySelector('[data-home-move]:not(:disabled)') || row.querySelector('[role="switch"]')
        : move;
      focusTarget?.focus();
      return;
    }

    const density = event.target.closest('[data-home-density]');
    if (density) _chooseHomeDensity(density);
  });
  pane.querySelectorAll('[data-home-density]').forEach(button => {
    button.addEventListener('keydown', event => {
      if (_homeSettingsBusy) return;
      const keys = ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown', 'Home', 'End'];
      if (!keys.includes(event.key)) return;
      event.preventDefault();
      const choices = [...pane.querySelectorAll('[data-home-density]')];
      const index = choices.indexOf(button);
      let next = index;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + choices.length) % choices.length;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % choices.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = choices.length - 1;
      _chooseHomeDensity(choices[next]);
      choices[next].focus();
    });
  });
  document.getElementById('home-settings-reset')?.addEventListener('click', _resetHomeSettings);
  document.getElementById('home-settings-save')?.addEventListener('click', _saveHomeSettings);
}


export const homePane = createSettingsPane({
  init: _wireHomeSettingsPane,
  load: loadHomeSettingsPane,
  dispose() {
    _homeSettingsLoadGeneration += 1;
    if (!_homeSettingsSaving) _setHomeSettingsBusy(false);
  },
});
