let _incognitoMode = false;

// ── agent permission mode ─────────────────────────────────────────────
const PERM_KEY = 'aide-perm-mode';
let _perm = localStorage.getItem(PERM_KEY) || 'approve';   // approve | full_auto | plan

export function getPermMode() { return _perm; }

export function permLabel(m = _perm) {
  return m === 'plan' ? 'plan' : m === 'full_auto' ? 'auto' : 'approve';
}

export function setPermMode(m) {
  _perm = m;
  localStorage.setItem(PERM_KEY, m);
  const btn = document.getElementById('perm-mode-btn');
  if (btn) {
    const label = btn.querySelector('.perm-label');
    if (label) label.textContent = permLabel(m);
    else btn.textContent = permLabel(m);
    btn.classList.toggle('perm-plan', m === 'plan');
    btn.classList.toggle('perm-auto', m === 'full_auto');
  }
}

// ── reasoning effort (PER MODEL) ────────────────────────────────────────────
// low | medium | high | xhigh | max. each model remembers its own effort; pass the
// model id to read/write its setting. drives agent turns + the model's reasoning.
export const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];
const EFFORT_MAP_KEY = 'aide-effort-by-model';
const EFFORT_LAST_KEY = 'aide-effort';        // global fallback / last used
const DEFAULT_EFFORT = 'medium';
const _effMap = () => { try { return JSON.parse(localStorage.getItem(EFFORT_MAP_KEY) || '{}'); } catch { return {}; } };

export function getEffort(modelKey) {
  const m = _effMap();
  if (modelKey && m[modelKey]) return m[modelKey];
  return localStorage.getItem(EFFORT_LAST_KEY) || DEFAULT_EFFORT;
}

export function setEffort(val, modelKey) {
  if (modelKey) { const m = _effMap(); m[modelKey] = val; localStorage.setItem(EFFORT_MAP_KEY, JSON.stringify(m)); }
  localStorage.setItem(EFFORT_LAST_KEY, val);
  const el = document.querySelector('#effort-btn .effort-label');
  if (el) el.textContent = val;
}

export function isIncognitoMode() {
  return _incognitoMode;
}

export function setIncognitoMode(on) {
  _incognitoMode = !!on;
  document.body.classList.toggle('is-incognito', _incognitoMode);   // screen-edge glow
  // incognito = you're not using history, so tuck the sidebar away (like Claude)
  if (document.body.classList.contains('is-aide'))
    document.body.classList.toggle('sidebar-hidden', _incognitoMode);
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
