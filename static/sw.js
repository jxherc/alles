/* alles service worker — offline shell + web push */
const VERSION = 'v5';   // bumped with the ?v=31 asset stamp so clients drop the stale style.css for good
const CACHE = `alles-${VERSION}`;

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/sw.js') return;   // never cache

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
