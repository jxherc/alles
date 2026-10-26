// web push — service worker registration + subscription management
import { toast } from './util.js';
import { t } from './i18n.js';

export function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

function _b64uToBytes(s) {
  const pad = '='.repeat((4 - s.length % 4) % 4);
  const raw = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, c => c.charCodeAt(0));
}

async function _currentSub() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

export async function initPushButton() {
  const btn = document.getElementById('push-enable-btn');
  if (!btn) return;
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    btn.style.display = 'none';   // unsupported browser
    return;
  }
  const sub = await _currentSub().catch(() => null);
  _setLabel(btn, !!sub);
  if (btn.dataset.wired) return;
  btn.dataset.wired = '1';
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      const sub = await _currentSub();
      if (sub) await _disable(sub); else await _enable();
      _setLabel(btn, !!(await _currentSub()));
    } catch (e) {
      toast(pushErrorText(e), 'error');
    }
    btn.disabled = false;
  });
}

// chromium with no push service (brave's default, electron, embedded views) throws
// "Registration failed - push service error", which means nothing to a person
export function pushErrorText(e) {
  const msg = String(e?.message || t('push.generic_error'));
  if (/push service/i.test(msg)) return t('push.unsupported');
  if (/permission denied/i.test(msg)) return t('push.blocked');
  return t('push.error_detail', { message: `${msg[0].toLowerCase()}${msg.slice(1)}` });
}

function _setLabel(btn, on) {
  btn.textContent = on ? t('push.on') : t('push.enable');
}

async function _enable() {
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') { toast(t('push.blocked'), 'error'); return; }
  const reg = await navigator.serviceWorker.ready;
  const { key } = await fetch('/api/push/vapid-key').then(r => r.json());
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: _b64uToBytes(key),
  });
  const j = sub.toJSON();
  const r = await fetch('/api/push/subscribe', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ endpoint: j.endpoint, keys: j.keys }),
  });
  if (!r.ok) { await sub.unsubscribe(); throw new Error('server rejected subscription'); }
  toast(t('push.enabled'), 'success');
}

async function _disable(sub) {
  await fetch('/api/push/unsubscribe', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ endpoint: sub.endpoint }),
  }).catch(() => {});
  await sub.unsubscribe();
  toast(t('push.disabled'), '');
}
