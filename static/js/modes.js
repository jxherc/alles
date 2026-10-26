import { t } from './i18n.js';

let _incognitoMode = false;
let _incognitoSidebarWasHidden = false;

// ── agent permission mode ─────────────────────────────────────────────
const PERM_KEY = 'aide-perm-mode';
const PERM_MODES = ['full_access', 'full_auto', 'approve', 'plan'];
const normalizePermMode = value => value === null ? 'full_auto' : (PERM_MODES.includes(value) ? value : 'approve');
let _perm = normalizePermMode(localStorage.getItem(PERM_KEY));

export function getPermMode() { return _perm; }

export function permLabel(m = _perm) {
  if (m === 'full_access') return t('aide.perm_full_access');
  if (m === 'full_auto') return t('aide.perm_auto_mode');
  if (m === 'plan') return t('aide.perm_plan');
  return t('aide.ask_approval');
}

const EFFORT_LABELS = {
  '': () => t('common.automatic'),
  low: () => t('aide.effort_low'),
  medium: () => t('aide.effort_medium'),
  high: () => t('aide.effort_high'),
  xhigh: () => t('aide.effort_xhigh'),
  max: () => t('aide.effort_max'),
  deep_work: () => t('aide.effort_deep_work'),
  custom: () => t('aide.effort_custom'),
};

export function effortLabel(value = DEFAULT_EFFORT) {
  const effort = normalizeEffort(value);
  return EFFORT_LABELS[effort]?.() ?? effort.replace('_', ' ');
}

export function setPermMode(m) {
  _perm = normalizePermMode(m);
  localStorage.setItem(PERM_KEY, _perm);
  const btn = document.getElementById('perm-mode-btn');
  if (btn) {
    const label = btn.querySelector('.perm-label');
    if (label) label.textContent = permLabel(m);
    else btn.textContent = permLabel(m);
    btn.classList.toggle('perm-auto', m === 'full_auto');
    btn.classList.toggle('perm-full', m === 'full_access');
    btn.setAttribute('aria-label', t('aide.perm_aria_label', { mode: permLabel(m) }));
    btn.setAttribute('aria-expanded', 'false');
  }
}

// ── reasoning effort (PER MODEL) ────────────────────────────────────────────
// '' (automatic) | low | medium | high | xhigh | max | deep_work | custom. each model remembers
// its own effort; pass the model id to read/write its setting. low..max are provider levels and
// only count on a model that takes them (see usableEffort); deep_work and custom are local
// profiles that work on every model.
export const PROVIDER_EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];
export const EFFORTS = [...PROVIDER_EFFORTS, 'deep_work', 'custom'];
export const REASONING_MODES = ['automatic', 'on', 'off'];
const EFFORT_MAP_KEY = 'aide-effort-by-model';
const EFFORT_LAST_KEY = 'aide-effort';        // global fallback / last used
const REASONING_MAP_KEY = 'aide-reasoning-by-model';
const CUSTOM_MAP_KEY = 'aide-custom-effort-by-model';
const DEFAULT_EFFORT = '';
const DEFAULT_CUSTOM = Object.freeze({
  maxTurns: 24,
  verification: 'standard',
  delegation: 'off',
  workflows: 'off',
});
const _effMap = () => { try { return JSON.parse(localStorage.getItem(EFFORT_MAP_KEY) || '{}'); } catch { return {}; } };
const _jsonMap = key => { try { return JSON.parse(localStorage.getItem(key) || '{}'); } catch { return {}; } };
const normalizeEffort = value => EFFORTS.includes(value) ? value : DEFAULT_EFFORT;
const normalizeReasoning = value => REASONING_MODES.includes(value) ? value : 'automatic';
const oneOf = (value, allowed, fallback) => allowed.includes(value) ? value : fallback;

function normalizeCustom(value = {}) {
  const turns = Number.parseInt(value.maxTurns, 10);
  return {
    maxTurns: Math.min(64, Math.max(1, Number.isFinite(turns) ? turns : DEFAULT_CUSTOM.maxTurns)),
    verification: oneOf(value.verification, ['quick', 'standard', 'thorough'], DEFAULT_CUSTOM.verification),
    delegation: oneOf(value.delegation, ['off', 'auto'], DEFAULT_CUSTOM.delegation),
    workflows: oneOf(value.workflows, ['off', 'auto'], DEFAULT_CUSTOM.workflows),
  };
}

// a saved provider level the model doesn't take falls back to automatic. levels undefined =
// not known, so nothing is filtered.
export function usableEffort(value, levels) {
  const effort = normalizeEffort(value);
  if (!PROVIDER_EFFORTS.includes(effort) || !Array.isArray(levels)) return effort;
  return levels.includes(effort) ? effort : DEFAULT_EFFORT;
}

export function getEffort(modelKey, levels) {
  const m = _effMap();
  const saved = modelKey && Object.hasOwn(m, modelKey) ? m[modelKey] : localStorage.getItem(EFFORT_LAST_KEY);
  return usableEffort(saved, levels);
}

// what the selected model supports, from the catalog the server sent (window._endpoints)
export function modelSupport(selection) {
  const endpoints = (typeof window !== 'undefined' && window._endpoints) || [];
  const endpoint = endpoints.find(ep => ep.id === selection?.endpointId);
  const model = selection?.model;
  return {
    effortLevels: (endpoint?.effort_levels && model && endpoint.effort_levels[model]) || [],
    reasoningControl: !!(model && endpoint?.reasoning_control?.includes(model)),
  };
}

export function setEffort(val, modelKey) {
  const effort = normalizeEffort(val);
  if (modelKey) { const m = _effMap(); m[modelKey] = effort; localStorage.setItem(EFFORT_MAP_KEY, JSON.stringify(m)); }
  localStorage.setItem(EFFORT_LAST_KEY, effort);
  const el = document.querySelector('#effort-btn .effort-label');
  if (el) el.textContent = effortLabel(effort);
}

// reasoning on/off only counts where the model can be switched; else it stays automatic
export function getReasoningMode(modelKey = '', switchable) {
  if (switchable === false) return 'automatic';
  const map = _jsonMap(REASONING_MAP_KEY);
  return normalizeReasoning(map[modelKey || '_default']);
}

export function setReasoningMode(value, modelKey = '') {
  const map = _jsonMap(REASONING_MAP_KEY);
  map[modelKey || '_default'] = normalizeReasoning(value);
  localStorage.setItem(REASONING_MAP_KEY, JSON.stringify(map));
}

export function getCustomEffort(modelKey = '') {
  const map = _jsonMap(CUSTOM_MAP_KEY);
  return normalizeCustom(map[modelKey || '_default']);
}

export function setCustomEffort(modelKey = '', value = {}) {
  const map = _jsonMap(CUSTOM_MAP_KEY);
  map[modelKey || '_default'] = normalizeCustom(value);
  localStorage.setItem(CUSTOM_MAP_KEY, JSON.stringify(map));
}

if (typeof window !== 'undefined') {
  window.addEventListener('alles:localization-change', () => {
    setPermMode(_perm);
    if (window._refreshEffortLabel) window._refreshEffortLabel();
    else {
      const effort = document.querySelector('#effort-btn .effort-label');
      if (effort) effort.textContent = effortLabel(getEffort());
    }
  });
}

export function isIncognitoMode() {
  return _incognitoMode;
}

export function setIncognitoMode(on) {
  const next = !!on;
  const previous = _incognitoMode;
  if (next && !_incognitoMode) {
    _incognitoSidebarWasHidden = document.body.classList.contains('sidebar-hidden');
  }
  _incognitoMode = next;
  document.body.classList.toggle('is-incognito', _incognitoMode);   // dedicated private screen state
  // Incognito hides history while active, then restores the user's prior layout.
  if (document.body.classList.contains('is-aide') && (next || previous)) {
    if (_incognitoMode) document.body.classList.add('sidebar-hidden');
    else document.body.classList.toggle('sidebar-hidden', _incognitoSidebarWasHidden);
    document.getElementById('sidebar-toggle-btn')?.setAttribute(
      'aria-expanded', String(!document.body.classList.contains('sidebar-hidden')),
    );
  }
  const btn = document.getElementById('incognito-btn');
  if (btn) {
    btn.classList.toggle('active', _incognitoMode);
    btn.setAttribute('aria-pressed', String(_incognitoMode));
    btn.title = _incognitoMode
      ? t('aide.incognito_active_title')
      : t('aide.incognito_enable');
  }
}
