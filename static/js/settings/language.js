import { createSettingsPane } from './pane.js';
import { toast } from '../util.js';
import { closeCustomDropdowns, populateDropdown } from '../dropdown.js?v=217';
import { setStatusLine } from './shared.js';
import { prepareLocalization, regionName, t } from '../i18n.js';

// ── Phase 10 locale Settings ─────────────────────────────────────────────────
const LOCALE_FALLBACK_OPTIONS = {
  languages: [{ value: 'en', label: 'English' }],
  regions: [
    { value: '', label: 'automatic' },
    { value: 'TW', label: 'Taiwan' },
    { value: 'US', label: 'United States' },
    { value: 'FR', label: 'France' },
    { value: 'ES', label: 'Spain' },
    { value: 'CN', label: 'China' },
    { value: 'JP', label: 'Japan' },
    { value: 'KR', label: 'South Korea' },
  ],
  timezones: [
    { value: '', label: 'automatic' },
    { value: 'Asia/Taipei', label: 'Asia/Taipei' },
    { value: 'Europe/Paris', label: 'Europe/Paris' },
    { value: 'America/New_York', label: 'America/New_York' },
    { value: 'UTC', label: 'UTC' },
  ],
  currencies: [
    { value: '', label: 'automatic' },
    { value: 'TWD', label: 'TWD' },
    { value: 'USD', label: 'USD' },
    { value: 'EUR', label: 'EUR' },
    { value: 'CNY', label: 'CNY' },
    { value: 'JPY', label: 'JPY' },
    { value: 'KRW', label: 'KRW' },
  ],
};

let _localeOptions = LOCALE_FALLBACK_OPTIONS;
let _localeSettings = null;
let _localeSettingsBusy = false;
let _localeSettingsSaving = false;
let _localeLoadGeneration = 0;
let _localeSettingsDirty = false;

function _browserRegion() {
  const locale = globalThis.navigator?.language || 'en';
  try {
    return new Intl.Locale(locale).maximize().region || '';
  } catch {
    const match = String(locale).match(/[-_]([A-Za-z]{2}|[0-9]{3})(?:$|-)/);
    return match?.[1]?.toUpperCase() || '';
  }
}

function _browserTimezone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; }
  catch { return 'UTC'; }
}

function _localeChoiceOptions(name) {
  const optionKey = name === 'currency' ? 'currencies' : name === 'language' ? 'languages' : `${name}s`;
  return _localeOptions[optionKey] || [];
}

function _optionText(name, item) {
  return name === 'region' && item.value ? regionName(item.value, item.label) : item.label;
}

// "automatic (CA)": the dropdown says what automatic picks on this browser
function _automaticLabel(name) {
  const detected = name === 'region' ? _browserRegion() : name === 'timezone' ? _browserTimezone() : '';
  return detected ? `${t('common.automatic')} (${detected})` : t('common.automatic');
}

// region, timezone and currency use the kit dropdown (dropdown.js): type to jump, the list on
// document.body, the same look as every other pick in alles
function _renderLocaleChoiceMenu(name) {
  const trigger = document.querySelector(`[data-locale-choice="${name}"]`);
  if (!trigger) return;
  const options = _localeChoiceOptions(name).map(item => ({
    value: item.value,
    label: item.value ? _optionText(name, item) : _automaticLabel(name),
  }));
  populateDropdown(trigger, options, trigger.dataset.value || '');
}

function _setLocaleChoiceValue(name, value, dirty = false) {
  const trigger = document.querySelector(`[data-locale-choice="${name}"]`);
  const valid = _localeChoiceOptions(name).some(item => item.value === value) ? value : (name === 'language' ? 'en' : '');
  if (trigger) trigger.dataset.value = valid;
  _renderLocaleChoiceMenu(name);
  if (dirty) _markLocaleSettingsChanged();
}

function _setLocaleRadioValue(name, value, dirty = false) {
  const choices = [...document.querySelectorAll(`[data-locale-format="${name}"]`)];
  const selected = choices.find(choice => choice.dataset.value === value) || choices[0];
  choices.forEach(choice => {
    const active = choice === selected;
    choice.setAttribute('aria-checked', String(active));
    choice.tabIndex = active ? 0 : -1;
  });
  if (dirty) _markLocaleSettingsChanged();
}

function _localeRadioValue(name) {
  return document.querySelector(`[data-locale-format="${name}"][aria-checked="true"]`)?.dataset.value || 'auto';
}

function _selectedLocaleLanguage() {
  return document.getElementById('s-language-trigger')?.dataset.value || 'en';
}

function _setLocaleLanguage(value) {
  _setLocaleChoiceValue('language', value);
}

function _applyLocaleOptions(options) {
  if (Array.isArray(options?.regions) && options.regions.length) _localeOptions.regions = options.regions;
  if (Array.isArray(options?.timezones) && options.timezones.length) _localeOptions.timezones = options.timezones;
  if (Array.isArray(options?.currencies) && options.currencies.length) _localeOptions.currencies = options.currencies;
  // only a language that is ready can be picked, so the list shows just those
  if (Array.isArray(options?.languages)) {
    const ready = options.languages.filter(language => language.available);
    if (ready.length) _localeOptions.languages = ready.map(language => ({ value: language.id, label: language.label }));
  }
  _renderLocaleChoiceMenu('language');
  _renderLocaleChoiceMenu('region');
  _renderLocaleChoiceMenu('timezone');
  _renderLocaleChoiceMenu('currency');
}

function _setLocaleSettingsBusy(busy) {
  _localeSettingsBusy = busy;
  const workbench = document.getElementById('locale-settings-workbench');
  const save = document.getElementById('s-locale-save');
  if (workbench) {
    workbench.inert = busy;
    workbench.setAttribute('aria-busy', String(busy));
  }
  if (save) save.disabled = busy;
}

function _setLocaleSettingsStatus(message, ms = 0) {
  setStatusLine(document.getElementById('locale-settings-save-state'), message, ms);
}

function _markLocaleSettingsChanged() {
  _localeSettingsDirty = true;
  _setLocaleSettingsStatus(t('locale.unsaved'));
}

function _applyLocaleSettings(settings) {
  _localeSettings = settings;
  _setLocaleLanguage(settings.language || 'en');
  _setLocaleChoiceValue('region', settings.region || '');
  _setLocaleChoiceValue('timezone', settings.timezone || '');
  _setLocaleChoiceValue('currency', settings.currency || '');
  _setLocaleRadioValue('clock_format', settings.clock_format || 'auto');
  _setLocaleRadioValue('week_start', settings.week_start || 'auto');
  _localeSettingsDirty = false;
  _setLocaleSettingsStatus('');
}

async function loadLocaleSettingsPane(isCurrent) {
  const loadState = document.getElementById('locale-settings-load-state');
  if (!loadState || _localeSettingsBusy) return;
  if (_localeSettingsDirty) {
    loadState.textContent = t('locale.unsaved_kept');
    return;
  }
  const generation = ++_localeLoadGeneration;
  _setLocaleSettingsBusy(true);
  try {
    const [settingsResponse, optionsResponse] = await Promise.all([
      fetch('/api/settings'),
      fetch('/api/settings/localization/options'),
    ]);
    if (!settingsResponse.ok || !optionsResponse.ok) throw new Error(t('locale.load_error'));
    const [settings, options] = await Promise.all([settingsResponse.json(), optionsResponse.json()]);
    if (generation !== _localeLoadGeneration || !isCurrent()) return;
    _applyLocaleOptions(options);
    _applyLocaleSettings(settings);
    loadState.textContent = '';
  } catch (error) {
    if (generation !== _localeLoadGeneration || !isCurrent()) return;
    loadState.textContent = t('locale.load_failed');
    _setLocaleSettingsStatus(error.message || t('locale.load_error'));
  } finally {
    if (generation === _localeLoadGeneration) _setLocaleSettingsBusy(false);
  }
}

async function _saveLocaleSettings() {
  if (_localeSettingsBusy) return;
  const focusTarget = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;
  const loadState = document.getElementById('locale-settings-load-state');
  _localeSettingsSaving = true;
  _setLocaleSettingsBusy(true);
  _setLocaleSettingsStatus(t('locale.saving'));
  try {
    const response = await fetch('/api/settings', {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        language: _selectedLocaleLanguage(),
        region: document.getElementById('s-region-trigger')?.dataset.value || '',
        timezone: document.getElementById('s-timezone-trigger')?.dataset.value || '',
        currency: document.getElementById('s-currency-trigger')?.dataset.value || '',
        clock_format: _localeRadioValue('clock_format'),
        week_start: _localeRadioValue('week_start'),
      }),
    });
    const settings = await response.json().catch(() => null);
    if (!response.ok) throw new Error(settings?.detail || t('locale.save_error'));
    if (!settings || ['language', 'region', 'timezone', 'currency', 'clock_format', 'week_start']
      .some(key => typeof settings[key] !== 'string')) throw new Error(t('locale.save_error'));
    await prepareLocalization(settings);
    _applyLocaleSettings(settings);
    _setLocaleSettingsStatus(t('locale.saved_now'), 3000);
    if (loadState) loadState.textContent = '';
    toast(t('locale.saved'), 'success');
  } catch (error) {
    _setLocaleSettingsStatus(error.message || t('locale.save_error'));
    toast(error.message || t('locale.save_error'), 'error');
  } finally {
    _localeSettingsSaving = false;
    _setLocaleSettingsBusy(false);
    if (focusTarget?.isConnected && document.getElementById('s-pane-notifications')?.classList.contains('active') && document.getElementById('settings-modal')?.style.display !== 'none') {
      focusTarget.focus({ preventScroll: true });
    }
  }
}



function _wireLocaleSettingsPane() {
  const pane = document.getElementById('s-pane-notifications');
  if (!pane || pane.dataset.localeBound) return;
  pane.dataset.localeBound = '1';
  pane.querySelectorAll('[data-locale-choice]').forEach(trigger => {
    trigger.addEventListener('change', () => _setLocaleChoiceValue(trigger.dataset.localeChoice, trigger.dataset.value || '', true));
  });
  pane.addEventListener('click', event => {
    const format = event.target.closest('[data-locale-format]');
    if (format) _setLocaleRadioValue(format.dataset.localeFormat, format.dataset.value, true);
  });
  pane.addEventListener('keydown', event => {
    const format = event.target.closest('[data-locale-format]');
    if (format && ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const choices = [...pane.querySelectorAll(`[data-locale-format="${format.dataset.localeFormat}"]`)];
      const index = choices.indexOf(format);
      let next = index;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + choices.length) % choices.length;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % choices.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = choices.length - 1;
      _setLocaleRadioValue(format.dataset.localeFormat, choices[next].dataset.value, true);
      choices[next].focus();
    }
  });
  document.getElementById('s-locale-save')?.addEventListener('click', _saveLocaleSettings);
}


export const languagePane = createSettingsPane({
  init: _wireLocaleSettingsPane,
  load: loadLocaleSettingsPane,
  dispose() {
    closeCustomDropdowns(document.getElementById('s-pane-notifications'));
    _localeLoadGeneration += 1;
    if (!_localeSettingsSaving) _setLocaleSettingsBusy(false);
  },
});
