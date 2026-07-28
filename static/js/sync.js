// offline write-queue client (1b). the service worker stashes mutating /api writes
// in an IndexedDB outbox when offline; this side flushes them on reconnect and
// shows a small "pending" badge so you know something's waiting to sync.

function _sw() {
  return navigator.serviceWorker;
}

function flush() {
  _sw()?.controller?.postMessage({ type: 'alles-flush' });
}

function ping() {
  _sw()?.controller?.postMessage({ type: 'alles-pending' });
}

function updateBadge(n, blocked = 0) {
  const el = document.getElementById('sync-indicator');
  if (!el) return;
  el.replaceChildren();
  if (n > 0) {
    const status = document.createElement('span');
    status.textContent = blocked > 0
      ? `${blocked} blocked offline change${blocked === 1 ? '' : 's'}`
      : `⟳ ${n} pending`;
    el.appendChild(status);
    if (blocked > 0) {
      const discard = document.createElement('button');
      discard.type = 'button';
      discard.textContent = 'discard blocked';
      discard.title = 're-enter these changes if needed, then remove the blocked copies';
      discard.addEventListener('click', () => {
        discard.disabled = true;
        _sw()?.controller?.postMessage({ type: 'alles-discard-blocked' });
      });
      el.appendChild(discard);
    }
    el.style.display = '';
    el.title = blocked > 0
      ? 'an older version queued changes that are no longer safe to replay automatically'
      : `${n} change(s) queued offline - will sync when you reconnect`;
  } else {
    el.style.display = 'none';
  }
}

export function initSync() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('/sw.js').catch(() => {});

  let lastAt = 0;
  navigator.serviceWorker.addEventListener('message', e => {
    if (e.data && e.data.type === 'alles-sync') {
      const at = e.data.at || 0;
      if (at >= lastAt) { lastAt = at; updateBadge(e.data.pending, e.data.blocked); }   // ignore stale counts
    }
  });

  window.addEventListener('online', () => { flush(); ping(); });
  window.addEventListener('offline', ping);

  // on boot: ask for the current count and, if we're online, drain anything left over
  navigator.serviceWorker.ready.then(() => {
    ping();
    if (navigator.onLine) flush();
  });
  // controller can arrive a tick after ready on a first load
  navigator.serviceWorker.addEventListener('controllerchange', () => { ping(); if (navigator.onLine) flush(); });
}
