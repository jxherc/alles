// 5a - tiny reactive state store + stale-while-revalidate fetch cache. vanilla ESM, no DOM deps,
// so views can share state + a fetch cache without a build step.

export function createStore(initial = {}) {
  const state = { ...initial };
  const subs = new Map(); // key -> Set(fn)

  function get(k) { return state[k]; }

  function set(k, v) {
    const old = state[k];
    if (old === v) return; // only notify on a real change
    state[k] = v;
    const set_ = subs.get(k);
    if (set_) for (const fn of set_) fn(v, old);
  }

  function on(k, fn) {
    if (!subs.has(k)) subs.set(k, new Set());
    subs.get(k).add(fn);
    return () => { const s = subs.get(k); if (s) s.delete(fn); };
  }

  return { get, set, on, state };
}

export function createSWR({ fetcher, ttl = 30000, now = () => Date.now() } = {}) {
  const cache = new Map();    // key -> {data, ts}
  const inflight = new Map(); // key -> promise (dedup concurrent fetches)
  const subs = new Map();     // key -> Set(fn)

  function notify(key, data) {
    const s = subs.get(key);
    if (s) for (const fn of s) fn(data);
  }

  function on(key, fn) {
    if (!subs.has(key)) subs.set(key, new Set());
    subs.get(key).add(fn);
    return () => { const s = subs.get(key); if (s) s.delete(fn); };
  }

  function revalidate(key, ...args) {
    if (inflight.has(key)) return inflight.get(key); // dedup
    const p = Promise.resolve()
      .then(() => fetcher(key, ...args))
      .then((data) => {
        cache.set(key, { data, ts: now() });
        inflight.delete(key);
        notify(key, data);
        return data;
      })
      .catch((e) => { inflight.delete(key); throw e; });
    inflight.set(key, p);
    return p;
  }

  function get(key, ...args) {
    const hit = cache.get(key);
    if (hit) {
      if (now() - hit.ts > ttl) revalidate(key, ...args); // stale: refresh in background
      return Promise.resolve(hit.data); // return cached immediately
    }
    return revalidate(key, ...args); // cold: await the fetch
  }

  function peek(key) { const h = cache.get(key); return h ? h.data : undefined; }
  function invalidate(key) { cache.delete(key); }

  return { get, revalidate, peek, invalidate, on };
}
