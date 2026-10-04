/* alles service worker — offline shell + web push */
const VERSION = 'v291';   // Refresh the shell cache for independently owned settings panes.
const CACHE = `alles-${VERSION}`;
const STAMP = '427';   // keep in sync with index.html ?v= / const _v
const NETWORK_FIRST_STATIC = ['.js', '.mjs', '.css'];

// 1b: mutating writes that should be queued when offline
const MUTATING = ['POST', 'PUT', 'PATCH', 'DELETE'];
const NOQUEUE = ['/api/mail/', '/api/auth', '/api/chat', '/api/agent', '/api/jarvis', '/api/share', '/api/vault', '/api/vault-transfer', '/api/carddav', '/api/photos/sync', '/api/photos/rescan', '/api/files/operations', '/api/storage-locations', '/api/money', '/api/subscriptions', '/api/finance/actual', '/api/finance/imports', '/api/finance/connections', '/api/system/searxng', '/api/system/services', '/api/system/companions', '/api/system/host-services', '/api/system/policy'];   // auth / streaming / agent actions / native actions / vault / durable Files, storage, Finance authority, and every service or policy change — never queue

// 11b: precache the app shell on install so a cold offline load still boots (network-first
// only fills the cache after a visit; this guarantees the core shell survives an eviction).
const PRECACHE = [
  '/',
  '/manifest.json',
  `/static/style.css?v=${STAMP}`,
  `/static/js/app.js?v=${STAMP}`,
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    // ask the server for the full shell list (enumerates every js module so a cold offline
    // load boots) and fall back to the static core if that fetch can't be reached
    let urls = PRECACHE;
    try {
      const r = await fetch('/api/pwa/precache');
      if (r.ok) { const j = await r.json(); if (j.urls && j.urls.length) urls = j.urls; }
    } catch (e) {}
    // add one-by-one so a single 404 can't abort the whole precache (addAll is atomic)
    await Promise.all(urls.map(u => c.add(u).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function networkFirstStatic(request) {
  const c = await caches.open(CACHE);
  try {
    const resp = await fetch(request);
    if (resp.ok) {
      try { await c.put(request, resp.clone()); } catch {}
      return resp;
    }
    if (resp.status >= 500) {
      const hit = await c.match(request);
      if (hit) return hit;
    }
    return resp;
  } catch (err) {
    const hit = await c.match(request);
    if (hit) return hit;
    throw err;
  }
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  const replayPath = replayPolicyPathname(url);

  // 1b: queue mutating /api writes when offline so nothing is lost (multipart uploads skipped)
  if (MUTATING.includes(e.request.method) && replayPath?.startsWith('/api/') &&
      !NOQUEUE.some(p => replayPath.startsWith(p))) {
    const ct = e.request.headers.get('content-type') || '';
    if (!ct.includes('multipart/form-data')) { e.respondWith(handleWrite(e.request)); return; }
  }

  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/sw.js') return;   // never cache
  // public share viewers must always be live so a revoked link can't resolve from cache
  if (url.pathname.startsWith('/s/') || url.pathname.startsWith('/sv/')) return;

  // Network-first code and styles prevent a mixed old/new interface. The cache remains the
  // offline fallback, but an online reload must never draw yesterday's layout first.
  if (url.pathname.startsWith('/static/') &&
      NETWORK_FIRST_STATIC.some(ext => url.pathname.endsWith(ext))) {
    e.respondWith(networkFirstStatic(e.request));
    return;
  }

  // Other static assets stay stale-while-revalidate for fast repeat loads.
  if (url.pathname.startsWith('/static/')) {
    e.respondWith((async () => {
      const c = await caches.open(CACHE);
      const hit = await c.match(e.request);
      const fetching = fetch(e.request)
        .then(resp => { if (resp && resp.ok) c.put(e.request, resp.clone()); return resp; })
        .catch(() => null);
      if (hit) { e.waitUntil(fetching); return hit; }
      return (await fetching) || fetch(e.request);
    })());
    return;
  }

  // everything else: network-first, fall back to cache when offline
  e.respondWith((async () => {
    const c = await caches.open(CACHE);
    try {
      const resp = await fetch(e.request);
      if (resp.ok) c.put(e.request, resp.clone());
      return resp;
    } catch (err) {
      const hit = await c.match(e.request, { ignoreSearch: e.request.mode === 'navigate' });
      if (hit) return hit;
      if (e.request.mode === 'navigate') {
        const shell = await c.match('/');
        if (shell) return shell;
      }
      throw err;
    }
  })());
});

self.addEventListener('push', e => {
  let data = {};
  try { data = e.data.json(); }
  catch { data = { title: 'alles', body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(data.title || 'alles', {
    body: data.body || '',
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    tag: data.tag || undefined,
    data: { url: data.url || '/' },
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if ('focus' in c) { if (c.navigate) c.navigate(url); return c.focus(); }
      }
      return clients.openWindow(url);
    })
  );
});


// ── 1b offline write-queue (IndexedDB outbox) ─────────────────────────────────
async function handleWrite(req) {
  try {
    return await fetch(req.clone());
  } catch (err) {
    try {
      await queueRequest(req);
    } catch (e) {
      return new Response(JSON.stringify({
        detail: 'could not store this change offline. reconnect and try again.',
        queued: false, offline: true,
      }), { status: 503, headers: { 'content-type': 'application/json' } });
    }
    // The transaction committed. A failed notification must not invite a duplicate retry.
    try { await notifyClients(); } catch (e) {}
    return new Response(JSON.stringify({ queued: true, offline: true }), {
      status: 200, headers: { 'content-type': 'application/json' },
    });
  }
}

function _idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open('alles-sync', 1);
    r.onupgradeneeded = () => {
      if (!r.result.objectStoreNames.contains('outbox'))
        r.result.createObjectStore('outbox', { keyPath: 'id', autoIncrement: true });
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}

function _tx(db, mode, fn) {
  return new Promise((res, rej) => {
    const t = db.transaction('outbox', mode);
    const out = fn(t.objectStore('outbox'));
    t.oncomplete = () => res(out && out.result);
    t.onerror = () => rej(t.error);
    t.onabort = () => rej(t.error);
  });
}

async function queueRequest(req) {
  const headers = {};
  req.headers.forEach((v, k) => { if (k.toLowerCase() === 'content-type') headers[k] = v; });
  const body = await req.clone().text();
  const db = await _idb();
  await _tx(db, 'readwrite', s => s.add({ url: req.url, method: req.method, headers, body, ts: Date.now() }));
}

async function _all() { const db = await _idb(); return _tx(db, 'readonly', s => s.getAll()); }
async function _del(id) { const db = await _idb(); return _tx(db, 'readwrite', s => s.delete(id)); }
async function _put(item) { const db = await _idb(); return _tx(db, 'readwrite', s => s.put(item)); }

function replayPolicyPathname(url) {
  let pathname = url.pathname;
  try {
    while (/%[0-9a-f]{2}/i.test(pathname)) {
      const decoded = decodeURIComponent(pathname);
      if (decoded === pathname) break;
      pathname = decoded;
    }
  } catch (e) {
    return null;
  }
  if (/[\u0000-\u001f\u007f]/.test(pathname)) return null;
  const segments = [];
  for (const segment of pathname.split(/[\\/]/)) {
    if (!segment || segment === '.') continue;
    if (segment === '..') segments.pop();
    else segments.push(segment);
  }
  return `/${segments.join('/')}`;
}

function mustQuarantineOutboxItem(rawUrl) {
  if (typeof rawUrl !== 'string' || !rawUrl) return true;
  try {
    const url = new URL(rawUrl, self.location.origin);
    const pathname = replayPolicyPathname(url);
    return url.origin !== self.location.origin ||
      pathname === null || NOQUEUE.some(prefix => pathname.startsWith(prefix));
  } catch (e) {
    return true;
  }
}

// One worker may receive reconnect, boot and manual retry messages together.
// Serialize reads and mutations so two drains cannot send the same saved write.
let outboxWork = Promise.resolve();
function withOutbox(work) {
  const result = outboxWork.then(work, work);
  outboxWork = result.catch(() => {});
  return result;
}

async function replayError(response) {
  try {
    const data = await response.clone().json();
    const detail = data.detail || data.message;
    if (typeof detail === 'string') return detail.slice(0, 2000);
    if (Array.isArray(detail)) return detail.map(item => item.msg || '').filter(Boolean).join('; ').slice(0, 2000);
  } catch {}
  return '';
}

async function drainOutbox({ retryAuth = false, retryId = null } = {}) {
  const items = await _all();
  if (retryId !== null) {
    const eligible = items.filter(item => item.blocked_reason !== 'replay_policy_changed'
      && !mustQuarantineOutboxItem(item.url));
    if (eligible.findIndex(item => item.id === retryId) > 0) {
      throw Object.assign(new Error('resolve the earlier offline change before retrying this one.'), {
        code: 'earlier_change_pending',
      });
    }
  }
  for (const it of items) {
    if (retryId !== null && it.id !== retryId) continue;
    if (mustQuarantineOutboxItem(it.url)) {
      if (it.blocked_reason !== 'replay_policy_changed') {
        await _put({ ...it, blocked_reason: 'replay_policy_changed', blocked_at: Date.now() });
      }
      continue;
    }
    const selected = it.id === retryId && it.blocked_reason !== 'replay_policy_changed';
    const authenticated = retryAuth && it.blocked_reason === 'auth_required';
    if (it.blocked_reason && !selected && !authenticated) {
      if (it.blocked_reason === 'replay_policy_changed') continue;
      break;
    }
    try {
      const response = await fetch(it.url, {
        method: it.method, headers: it.headers, body: it.body || undefined,
      });
      if (response.ok) {
        await _del(it.id);
        continue;
      }
      const status = response.status;
      const blocked = status >= 400 && status < 500 && status !== 408 && status !== 429;
      await _put({
        ...it,
        blocked_reason: blocked
          ? (status === 401 ? 'auth_required' : status === 409 ? 'conflict'
            : status === 422 ? 'validation_failed' : 'request_rejected')
          : null,
        blocked_at: blocked ? Date.now() : null,
        response_status: status,
        response_detail: await replayError(response),
      });
      // Preserve ordering: later writes may depend on the rejected change.
      // Manual retries observe the same order, including still-pending writes.
      break;
    } catch { break; }
  }
}

async function flushOutbox(options = {}) {
  return withOutbox(async () => {
    try { await drainOutbox(options); }
    finally { await notifyClients(); }
  });
}

async function discardOutboxItem(id) {
  return withOutbox(async () => {
    // Only a reviewed, retained failure can be discarded. A successful drain
    // may already have removed it while the owner was reading the dialog.
    const item = (await _all()).find(row => row.id === id);
    if (item?.blocked_reason) await _del(id);
    await notifyClients();
  });
}

async function notifyClients() {
  let items = [];
  try { items = await _all(); } catch (e) { return; }
  const n = items.length;
  const blocked = items.filter(item => item.blocked_reason).length;
  const auth = items.filter(item => item.blocked_reason === 'auth_required').length;
  const at = Date.now();
  const cs = await self.clients.matchAll({ includeUncontrolled: true });
  cs.forEach(c => c.postMessage({ type: 'alles-sync', pending: n, blocked, auth, at }));
}

self.addEventListener('message', e => {
  if (!e.data) return;
  const { type, id } = e.data;
  let action;
  if (type === 'alles-flush') action = flushOutbox({ retryAuth: e.data.retryAuth === true });
  else if (type === 'alles-retry-outbox' && Number.isInteger(id)) action = flushOutbox({ retryId: id });
  else if (type === 'alles-discard-outbox' && Number.isInteger(id)) action = discardOutboxItem(id);
  else if (type === 'alles-pending') action = notifyClients();
  else if (type === 'alles-outbox-list') action = withOutbox(_all);
  if (!action) return;
  e.waitUntil(action.then(result => {
    e.ports?.[0]?.postMessage({ ok: true, items: type === 'alles-outbox-list' ? result : undefined });
  }).catch(error => {
    e.ports?.[0]?.postMessage({ ok: false, error: error?.code === 'earlier_change_pending'
      ? 'resolve the earlier offline change before retrying this one.'
      : 'could not read or update offline changes. try again.' });
  }));
});
