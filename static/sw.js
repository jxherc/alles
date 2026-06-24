/* alles service worker — offline shell + web push */
const VERSION = 'v126';   // vault 2fa switch + passkey unlock, journal reflect auth
const CACHE = `alles-${VERSION}`;
const STAMP = '152';   // keep in sync with index.html ?v= / const _v

// 1b: mutating writes that should be queued when offline
const MUTATING = ['POST', 'PUT', 'PATCH', 'DELETE'];
const NOQUEUE = ['/api/auth', '/api/chat', '/api/agent', '/api/share', '/api/vault', '/api/carddav'];   // auth / streaming / vault — never queue

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

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;

  // 1b: queue mutating /api writes when offline so nothing is lost (multipart uploads skipped)
  if (MUTATING.includes(e.request.method) && url.pathname.startsWith('/api/') &&
      !NOQUEUE.some(p => url.pathname.startsWith(p))) {
    const ct = e.request.headers.get('content-type') || '';
    if (!ct.includes('multipart/form-data')) { e.respondWith(handleWrite(e.request)); return; }
  }

  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/sw.js') return;   // never cache
  // public share viewers must always be live so a revoked link can't resolve from cache
  if (url.pathname.startsWith('/s/') || url.pathname.startsWith('/sv/')) return;

  // vendor bundles: stale-while-revalidate — serve cache instantly for speed +
  // offline, but always refetch in the background so a rebuilt bundle (the file
  // name isn't content-hashed) gets picked up on the next load
  if (url.pathname.startsWith('/static/vendor/')) {
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
    // offline (or network down) → stash it and tell the UI; pretend it went through
    try { await queueRequest(req); await notifyClients(); } catch (e) {}
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

async function flushOutbox() {
  let items = [];
  try { items = await _all(); } catch (e) { return; }
  for (const it of items) {
    try {
      const r = await fetch(it.url, { method: it.method, headers: it.headers, body: it.body || undefined });
      if (r.ok || (r.status >= 400 && r.status < 500)) await _del(it.id);  // done, or a permanent client error
      else break;                                                          // server error → keep, retry later
    } catch (err) { break; }                                              // still offline → stop
  }
  await notifyClients();
}

async function notifyClients() {
  let n = 0;
  try { n = (await _all()).length; } catch (e) {}
  const at = Date.now();   // stamp at read time so a stale count can't clobber a fresher one
  const cs = await self.clients.matchAll({ includeUncontrolled: true });
  cs.forEach(c => c.postMessage({ type: 'alles-sync', pending: n, at }));
}

self.addEventListener('message', e => {
  if (!e.data) return;
  if (e.data.type === 'alles-flush') e.waitUntil(flushOutbox());
  else if (e.data.type === 'alles-pending') e.waitUntil(notifyClients());
});
