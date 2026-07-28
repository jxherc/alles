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
  if (m === 'full_access') return 'full access';
  if (m === 'full_auto') return 'auto mode';
  if (m === 'plan') return 'plan';
  return t('aide.ask_approval');
}

export function effortLabel(value = DEFAULT_EFFORT) {
  const effort = normalizeEffort(value);
  return effort === 'medium' ? t('aide.effort_medium') : effort.replace('_', ' ');
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
    btn.setAttribute('aria-label', `permission: ${permLabel(m)}`);
    btn.setAttribute('aria-expanded', 'false');
  }
}

// ── reasoning effort (PER MODEL) ────────────────────────────────────────────
// low | medium | high | xhigh | max. each model remembers its own effort; pass the
// model id to read/write its setting. drives agent turns + the model's reasoning.
export const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max', 'deep_work', 'custom'];
export const REASONING_MODES = ['automatic', 'on', 'off'];
const EFFORT_MAP_KEY = 'aide-effort-by-model';
const EFFORT_LAST_KEY = 'aide-effort';        // global fallback / last used
const REASONING_MAP_KEY = 'aide-reasoning-by-model';
const CUSTOM_MAP_KEY = 'aide-custom-effort-by-model';
const DEFAULT_EFFORT = 'medium';
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

export function getEffort(modelKey) {
  const m = _effMap();
  if (modelKey && m[modelKey]) return normalizeEffort(m[modelKey]);
  return normalizeEffort(localStorage.getItem(EFFORT_LAST_KEY));
}

export function setEffort(val, modelKey) {
  const effort = normalizeEffort(val);
  if (modelKey) { const m = _effMap(); m[modelKey] = effort; localStorage.setItem(EFFORT_MAP_KEY, JSON.stringify(m)); }
  localStorage.setItem(EFFORT_LAST_KEY, effort);
  const el = document.querySelector('#effort-btn .effort-label');
  if (el) el.textContent = effortLabel(effort);
}

export function getReasoningMode(modelKey = '') {
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
    const effort = document.querySelector('#effort-btn .effort-label');
    if (effort) effort.textContent = effortLabel(getEffort());
  });
}

export function isIncognitoMode() {
  return _incognitoMode;
}

export function setIncognitoMode(on) {
  const next = !!on;
  if (next && !_incognitoMode) {
    _incognitoSidebarWasHidden = document.body.classList.contains('sidebar-hidden');
  }
  _incognitoMode = next;
  document.body.classList.toggle('is-incognito', _incognitoMode);   // dedicated private screen state
  // Incognito hides history while active, then restores the user's prior layout.
  if (document.body.classList.contains('is-aide')) {
    if (_incognitoMode) document.body.classList.add('sidebar-hidden');
    else document.body.classList.toggle('sidebar-hidden', _incognitoSidebarWasHidden);
  }
  const btn = document.getElementById('incognito-btn');
  if (btn) {
    btn.classList.toggle('active', _incognitoMode);
    btn.setAttribute('aria-pressed', String(_incognitoMode));
    btn.title = _incognitoMode
      ? 'incognito mode active - click to disable'
      : 'enable incognito mode';
  }
}

export function toggleIncognitoMode() {
  setIncognitoMode(!_incognitoMode);
  return _incognitoMode;
}
