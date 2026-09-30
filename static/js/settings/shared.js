import { toast } from '../util.js';
import { prompt as _dlgPrompt } from '../dialog.js';

// ── switch helpers ────────────────────────────────────────────────────────────
export function _setSwitch(el, on) {
  if (!el) return;
  el.classList.toggle('on', !!on);
  if (el.hasAttribute('role')) el.setAttribute('aria-checked', String(!!on));
}

const _switchWrites = new WeakMap();
export function _bindSwitch(el, getter, setter) {
  if (!el) return;
  let state = _switchWrites.get(el);
  if (!state?.pending) {
    state = { confirmed: !!getter(), revision: 0, pending: 0 };
    _switchWrites.set(el, state);
    _setSwitch(el, state.confirmed);
  }
  // onclick keeps pane re-open from stacking handlers
  el.onclick = async () => {
    const revision = ++state.revision;
    ++state.pending;
    const next = !el.classList.contains('on');
    _setSwitch(el, next);
    el.setAttribute('aria-busy', 'true');
    try {
      if (await setter(next) !== null) state.confirmed = next;
    } catch (error) {
      toast(error.message || 'setting could not be saved; try again', 'error');
    } finally {
      if (revision === state.revision) _setSwitch(el, state.confirmed);
      if (--state.pending === 0) el.removeAttribute('aria-busy');
    }
  };
}

// ── helpers ───────────────────────────────────────────────────────────────────
let _settingsWriteQueue = Promise.resolve();
let _settingsWriteRevision = 0;
export function _patchSettings(patch) {
  const body = JSON.stringify(patch);
  const pane = document.querySelector('#settings-modal .s-pane.active');
  const revision = String(++_settingsWriteRevision);
  let status = pane?.querySelector('.settings-save-state');
  if (pane && !status) {
    status = document.createElement('p');
    status.className = 'settings-save-state';
    status.setAttribute('role', 'status');
    pane.prepend(status);
  }
  if (pane) pane.dataset.saveRevision = revision;
  const show = (message, state) => {
    if (status && pane.dataset.saveRevision === revision) {
      status.textContent = message;
      status.dataset.state = state;
    }
  };
  show('saving…', 'saving');
  // Capture each patch now and issue it only after the preceding write settles.
  // A failed write must not poison the queue or turn the next save into a no-op.
  const pending = _settingsWriteQueue.then(async () => {
    try {
      const response = await fetch('/api/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' }, body,
      });
      const settings = await response.json();
      if (!response.ok) throw new Error(settings?.detail || 'setting could not be saved');
      if (!settings || typeof settings.context_limit !== 'number' || typeof settings.language !== 'string') {
        throw new Error('save could not be confirmed');
      }
      show('saved', 'saved');
      return settings;
    } catch (error) {
      const message = `${error.message || 'save could not be confirmed'}. Try the control again.`;
      show(message, 'error');
      toast(message, 'error');
      return null;
    }
  });
  _settingsWriteQueue = pending;
  return pending;
}

export function _patchSetting(key, val) {
  return _patchSettings({ [key]: val });
}

export function _esc(s = '') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function _escAttr(s = '') {
  return _esc(s).replace(/"/g,'&quot;');
}

export async function _confirmRecentOwner() {
  const me = await fetch('/api/auth/me').then(r => r.json()).catch(() => null);
  if (me && me.enabled === false) return true;
  const password = await _dlgPrompt('enter your Alles password to continue', '', { secret: true });
  if (password == null) return false;
  const r = await fetch('/api/auth/reauth', {
    method: 'POST', headers: {'content-type':'application/json'},
    body: JSON.stringify({ password }),
  });
  if (!r.ok) { toast('password confirmation failed', 'error'); return false; }
  return true;
}

export async function _fetchWithRecentOwner(input, init) {
  let r = await fetch(input, init);
  if (r.status === 403 && await _confirmRecentOwner()) r = await fetch(input, init);
  return r;
}
window._fetchWithRecentOwner = _fetchWithRecentOwner;
