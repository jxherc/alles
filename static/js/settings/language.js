import { createSettingsPane } from './pane.js';
import { toast } from '../util.js';
import { formatDateForLocale, formatTimeForLocale, prepareLocalization, t } from '../i18n.js';

// ── Phase 10 locale Settings ─────────────────────────────────────────────────
const LOCALE_FALLBACK_OPTIONS = {
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
let _localeOpenMenu = '';
let _localeMenuHome = null;

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
  const optionKey = name === 'currency' ? 'currencies' : `${name}s`;
  return _localeOptions[optionKey] || [];
}

function _localeChoiceLabel(name, value) {
  if (!value) return t('common.automatic');
  return _localeChoiceOptions(name).find(item => item.value === value)?.label || value;
}

function _renderLocaleChoiceMenu(name) {
  const menu = document.querySelector(`[data-locale-menu="${name}"]`);
  if (!menu) return;
  const trigger = document.querySelector(`[data-locale-choice="${name}"]`);
  const value = trigger?.dataset.value || '';
  menu.replaceChildren(..._localeChoiceOptions(name).map(item => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'locale-choice-option';
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', String(item.value === value));
    button.tabIndex = item.value === value ? 0 : -1;
    button.dataset.value = item.value;
    button.textContent = item.value ? item.label : t('common.automatic');
    return button;
  }));
}

function _setLocaleChoiceValue(name, value, dirty = false) {
  const trigger = document.querySelector(`[data-locale-choice="${name}"]`);
  const valid = _localeChoiceOptions(name).some(item => item.value === value) ? value : '';
  if (trigger) {
    trigger.dataset.value = valid;
    trigger.textContent = _localeChoiceLabel(name, valid);
  }
  _renderLocaleChoiceMenu(name);
  if (dirty) _markLocaleSettingsChanged();
  _updateLocalePreview();
}

function _closeLocaleChoice(returnFocus = false) {
  if (!_localeOpenMenu) return;
  const name = _localeOpenMenu;
  const menu = document.querySelector(`[data-locale-menu="${name}"]`);
  const trigger = document.querySelector(`[data-locale-choice="${name}"]`);
  if (menu) {
    menu.hidden = true;
    _localeMenuHome?.append(menu);
    menu.removeAttribute('style');
  }
  _localeMenuHome = null;
  window.removeEventListener('resize', _positionLocaleChoice);
  window.removeEventListener('scroll', _positionLocaleChoice, true);
  if (trigger) trigger.setAttribute('aria-expanded', 'false');
  _localeOpenMenu = '';
  if (returnFocus) trigger?.focus();
}

function _positionLocaleChoice() {
  if (!_localeOpenMenu) return;
  const menu = document.querySelector(`[data-locale-menu="${_localeOpenMenu}"]`);
  const trigger = document.querySelector(`[data-locale-choice="${_localeOpenMenu}"]`);
  if (!menu || !trigger) return;
  const rect = trigger.getBoundingClientRect();
  const below = innerHeight - rect.bottom - 12;
  const above = rect.top - 12;
  const height = Math.min(264, menu.scrollHeight, Math.max(below, above));
  const width = Math.min(Math.max(rect.width, 180), innerWidth - 16);
  menu.style.width = `${width}px`;
  menu.style.maxHeight = `${Math.max(44, height)}px`;
  menu.style.left = `${Math.max(8, Math.min(rect.left, innerWidth - width - 8))}px`;
  menu.style.top = `${below >= height || below >= above ? rect.bottom + 4 : Math.max(8, rect.top - height - 4)}px`;
}

function _openLocaleChoice(name, edge = '') {
  _closeLocaleChoice(false);
  const menu = document.querySelector(`[data-locale-menu="${name}"]`);
  const trigger = document.querySelector(`[data-locale-choice="${name}"]`);
  if (!menu || !trigger) return;
  _renderLocaleChoiceMenu(name);
  _localeMenuHome = menu.parentElement;
  document.getElementById('settings-modal')?.append(menu);
  menu.hidden = false;
  trigger.setAttribute('aria-expanded', 'true');
  _localeOpenMenu = name;
  _positionLocaleChoice();
  window.addEventListener('resize', _positionLocaleChoice);
  window.addEventListener('scroll', _positionLocaleChoice, true);
  const options = [...menu.querySelectorAll('[role="option"]')];
  const target = edge === 'last'
    ? options.at(-1)
    : edge === 'first'
      ? options[0]
      : menu.querySelector('[aria-selected="true"]') || options[0];
  target?.focus();
}

function _chooseLocaleOption(name, option) {
  if (!option) return;
  _setLocaleChoiceValue(name, option.dataset.value || '', true);
  _closeLocaleChoice(true);
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
  _updateLocalePreview();
}

function _localeRadioValue(name) {
  return document.querySelector(`[data-locale-format="${name}"][aria-checked="true"]`)?.dataset.value || 'auto';
}

function _selectedLocaleLanguage() {
  return document.querySelector('[data-locale-language][aria-checked="true"]')?.dataset.localeLanguage || 'en';
}

function _setLocaleLanguage(value) {
  const choices = [...document.querySelectorAll('[data-locale-language]')];
  const selected = choices.find(choice => choice.dataset.localeLanguage === value
    && choice.getAttribute('aria-disabled') !== 'true') || choices[0];
  choices.forEach(choice => {
    const active = choice === selected;
    choice.setAttribute('aria-checked', String(active));
    choice.tabIndex = active ? 0 : -1;
  });
  _updateLocalePreview();
}

function _applyLocaleOptions(options) {
  if (Array.isArray(options?.regions) && options.regions.length) _localeOptions.regions = options.regions;
  if (Array.isArray(options?.timezones) && options.timezones.length) _localeOptions.timezones = options.timezones;
  if (Array.isArray(options?.currencies) && options.currencies.length) _localeOptions.currencies = options.currencies;
  if (Array.isArray(options?.languages)) {
    for (const language of options.languages) {
      const row = document.querySelector(`[data-locale-language="${CSS.escape(language.id)}"]`);
      if (!row) continue;
      row.querySelector('strong').textContent = language.label;
      row.querySelector('small').textContent = language.english_name;
      const badge = row.querySelector('em');
      badge.dataset.i18n = language.available ? 'common.reviewed' : 'locale.catalog_reviewed_pending';
      badge.textContent = t(badge.dataset.i18n);
      row.setAttribute('aria-disabled', String(!language.available));
      row.dataset.direction = language.direction;
    }
  }
  _renderLocaleChoiceMenu('region');
  _renderLocaleChoiceMenu('timezone');
  _renderLocaleChoiceMenu('currency');
}

function _localePreviewTag(language, region) {
  const candidate = region ? `${language}-${region}` : language;
  try { return Intl.getCanonicalLocales(candidate)[0]; }
  catch { return 'en'; }
}

function _updateLocalePreview() {
  const language = _selectedLocaleLanguage();
  const region = document.getElementById('s-region-trigger')?.dataset.value || '';
  const timezone = document.getElementById('s-timezone-trigger')?.dataset.value || '';
  const currency = document.getElementById('s-currency-trigger')?.dataset.value || '';
  const tag = _localePreviewTag(language, region || _browserRegion());
  const direction = document.querySelector(`[data-locale-language="${CSS.escape(language)}"]`)?.dataset.direction || 'ltr';
  const tagEl = document.getElementById('locale-preview-tag');
  const dateEl = document.getElementById('locale-preview-date');
  const pathEl = document.getElementById('locale-preview-path');
  if (tagEl) tagEl.textContent = tag;
  if (dateEl) {
    try {
      dateEl.textContent = formatDateForLocale(new Date(), tag, {
        weekday: 'long', month: 'long', day: 'numeric',
        ...(timezone ? { timeZone: timezone } : {}),
      });
    } catch { dateEl.textContent = ''; }
  }
  if (pathEl) {
    try {
      const clock = _localeRadioValue('clock_format');
      const time = formatTimeForLocale(new Date(), tag, {
        hour: '2-digit', minute: '2-digit',
        ...(clock === '12' ? { hour12: true } : clock === '24' ? { hour12: false } : {}),
        ...(timezone ? { timeZone: timezone } : {}),
      });
      pathEl.textContent = `alles/data · ${time}`;
    } catch { pathEl.textContent = 'alles/data'; }
  }
  const directionEl = document.getElementById('locale-preview-direction');
  const regionEl = document.getElementById('locale-preview-region');
  const timezoneEl = document.getElementById('locale-preview-timezone');
  const currencyEl = document.getElementById('locale-preview-currency');
  if (directionEl) directionEl.textContent = t(direction === 'rtl' ? 'locale.direction_rtl' : 'locale.direction_ltr');
  if (regionEl) regionEl.textContent = region
    ? _localeChoiceLabel('region', region)
    : `${t('common.automatic')} · ${_browserRegion() || t('common.unknown')}`;
  if (timezoneEl) timezoneEl.textContent = timezone || `${t('common.automatic')} · ${_browserTimezone()}`;
  if (currencyEl) currencyEl.textContent = currency || t('common.automatic');
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

function _setLocaleSettingsStatus(message) {
  const status = document.getElementById('locale-settings-save-state');
  if (status) status.textContent = message;
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
  const detectedRegion = document.getElementById('s-region-detected');
  const detectedTimezone = document.getElementById('s-timezone-detected');
  if (detectedRegion) detectedRegion.textContent = t('locale.detected_region', {
    region: _browserRegion() || t('common.unknown'),
  });
  if (detectedTimezone) detectedTimezone.textContent = t('locale.detected_timezone', {
    timezone: _browserTimezone(),
  });
  _localeSettingsDirty = false;
  _setLocaleSettingsStatus(t('locale.no_unsaved'));
  _updateLocalePreview();
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
  loadState.textContent = t('locale.loading');
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
    loadState.textContent = t('locale.saved_server');
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
    _setLocaleSettingsStatus(t('locale.saved_now'));
    if (loadState) loadState.textContent = t('locale.saved_server');
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

function _handleLocaleOptionKey(event) {
  const option = event.target.closest('[role="option"]');
  if (option) {
    const menu = option.closest('[data-locale-menu]');
    const options = [...menu.querySelectorAll('[role="option"]')];
    const index = options.indexOf(option);
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      _closeLocaleChoice(true);
      return;
    }
    if (event.key === 'Tab') {
      _closeLocaleChoice(true);
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      _chooseLocaleOption(menu.dataset.localeMenu, option);
      return;
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      let next = index;
      if (event.key === 'ArrowDown') next = (index + 1) % options.length;
      if (event.key === 'ArrowUp') next = (index - 1 + options.length) % options.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = options.length - 1;
      option.tabIndex = -1;
      options[next].tabIndex = 0;
      options[next].focus();
      return;
    }
  }
}


function _wireLocaleSettingsPane() {
  const pane = document.getElementById('s-pane-notifications');
  if (!pane || pane.dataset.localeBound) return;
  pane.dataset.localeBound = '1';
  pane.querySelectorAll('[data-locale-menu]').forEach(menu => {
    menu.addEventListener('click', event => {
      const option = event.target.closest('[role="option"]');
      if (option) _chooseLocaleOption(menu.dataset.localeMenu, option);
    });
    menu.addEventListener('keydown', _handleLocaleOptionKey);
  });
  pane.addEventListener('click', event => {
    const language = event.target.closest('[data-locale-language]');
    if (language) {
      if (language.getAttribute('aria-disabled') === 'true') {
        _setLocaleSettingsStatus(t('locale.language_unavailable', {
          language: language.querySelector('small')?.textContent || language.dataset.localeLanguage,
        }));
        return;
      }
      _setLocaleLanguage(language.dataset.localeLanguage);
      _markLocaleSettingsChanged();
      return;
    }
    const trigger = event.target.closest('[data-locale-choice]');
    if (trigger) {
      const name = trigger.dataset.localeChoice;
      if (_localeOpenMenu === name) _closeLocaleChoice(true);
      else _openLocaleChoice(name);
      return;
    }
    const format = event.target.closest('[data-locale-format]');
    if (format) _setLocaleRadioValue(format.dataset.localeFormat, format.dataset.value, true);
  });
  pane.addEventListener('keydown', event => {
    const language = event.target.closest('[data-locale-language]');
    if (language && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) {
      const choices = [...pane.querySelectorAll('[data-locale-language]')]
        .filter(choice => !choice.disabled && choice.getAttribute('aria-disabled') !== 'true');
      const index = choices.indexOf(language);
      if (index < 0) return;
      event.preventDefault();
      event.stopPropagation();
      const rtl = getComputedStyle(language.parentElement).direction === 'rtl';
      const backwards = event.key === 'ArrowUp'
        || (event.key === 'ArrowLeft' && !rtl) || (event.key === 'ArrowRight' && rtl);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? choices.length - 1
        : (index + (backwards ? -1 : 1) + choices.length) % choices.length;
      _setLocaleLanguage(choices[next].dataset.localeLanguage);
      _markLocaleSettingsChanged();
      choices[next].focus();
      return;
    }
    const trigger = event.target.closest('[data-locale-choice]');
    if (trigger && ['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      event.stopPropagation();
      _openLocaleChoice(trigger.dataset.localeChoice, event.key === 'ArrowUp' ? 'last' : 'first');
      return;
    }
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
  document.addEventListener('pointerdown', event => {
    if (!_localeOpenMenu) return;
    const wrap = document.querySelector(`[data-locale-choice="${_localeOpenMenu}"]`)?.closest('.locale-choice-wrap');
    const menu = document.querySelector(`[data-locale-menu="${_localeOpenMenu}"]`);
    if (wrap && !wrap.contains(event.target) && !menu?.contains(event.target)) _closeLocaleChoice(false);
  }, true);
  document.getElementById('s-locale-save')?.addEventListener('click', _saveLocaleSettings);
}


export const languagePane = createSettingsPane({
  init: _wireLocaleSettingsPane,
  load: loadLocaleSettingsPane,
  dispose() {
    _closeLocaleChoice(false);
    _localeLoadGeneration += 1;
    if (!_localeSettingsSaving) _setLocaleSettingsBusy(false);
  },
});
