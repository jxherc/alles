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

// ── agent effort ──────────────────────────────────────────────────────────
const EFFORT_KEY = 'aide-effort';
let _effort = localStorage.getItem(EFFORT_KEY) || 'medium';   // low | medium | high

export function getEffort() { return _effort; }

export function setEffort(m) {
  _effort = m;
  localStorage.setItem(EFFORT_KEY, m);
  const el = document.querySelector('#effort-btn .effort-label');
  if (el) el.textContent = m;
}

export function isIncognitoMode() {
  return _incognitoMode;
}

export function setIncognitoMode(on) {
  _incognitoMode = !!on;
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
