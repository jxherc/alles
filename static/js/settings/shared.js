import { toast } from '../util.js';
import { confirmRecentOwner, fetchWithRecentOwner } from '../recent_owner.js';
import { t } from '../i18n.js';
import { esc as _esc } from '../escape.js';
export { _esc };

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
      toast(error.message || t('settings.setting_save_failed_retry'), 'error');
    } finally {
      if (revision === state.revision) _setSwitch(el, state.confirmed);
      if (--state.pending === 0) el.removeAttribute('aria-busy');
    }
  };
}

// a status line shows only while something is happening; ms > 0 clears it by itself
// (an older timer never wipes a newer message)
export function setStatusLine(el, message, ms = 0) {
  if (!el) return;
  clearTimeout(el._statusTimer);
  el.textContent = message;
  if (ms > 0 && message) el._statusTimer = setTimeout(() => { if (el.textContent === message) el.textContent = ''; }, ms);
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
      setStatusLine(status, message, state === 'saved' ? 3000 : 0);
      status.dataset.state = state;
    }
  };
  show(t('common.saving'), 'saving');
  // Capture each patch now and issue it only after the preceding write settles.
  // A failed write must not poison the queue or turn the next save into a no-op.
  const pending = _settingsWriteQueue.then(async () => {
    try {
      const response = await fetch('/api/settings', {
        method: 'PATCH', headers: { 'content-type': 'application/json' }, body,
      });
      const settings = await response.json();
      if (!response.ok) throw new Error(settings?.detail || t('settings.setting_save_failed'));
      if (!settings || typeof settings.context_limit !== 'number' || typeof settings.language !== 'string') {
        throw new Error(t('settings.save_unconfirmed'));
      }
      show(t('common.saved'), 'saved');
      return settings;
    } catch (error) {
      const message = t('settings.save_failed_try_again', { message: error.message || t('settings.save_unconfirmed') });
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

export function _escAttr(s = '') {
  return _esc(s).replace(/"/g,'&quot;');
}

// the one password prompt lives in recent_owner.js; these keep the names settings code uses
export async function _confirmRecentOwner() {
  try { return await confirmRecentOwner(); }
  catch (error) { toast(error.message || t('settings.reauth_failed'), 'error'); return false; }
}

export function _fetchWithRecentOwner(input, init) {
  return fetchWithRecentOwner(input, init);
}
window._fetchWithRecentOwner = _fetchWithRecentOwner;
