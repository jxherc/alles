# stage 5a - reactive state + SWR fetch cache - audit findings (2026-06-23)

## current state
- the frontend is ~50 vanilla JS modules that each fetch + hold their own state ad hoc. there is NO
  shared reactive store (set a value -> subscribers re-render) and NO stale-while-revalidate fetch cache
  (every view re-fetches from scratch, no dedup of concurrent requests, no instant-cached-then-refresh).
- no build step (vanilla ES modules only), so the layer must be a plain importable module.

## the gap
- a tiny reactive store: get/set/on(key, fn), notify only on real change.
- an SWR fetch cache: return cached immediately, revalidate stale in the background, dedup concurrent
  requests for the same key, notify subscribers when fresh data lands, invalidate on demand.

## fix - new `static/js/reactive.js` (vanilla ESM, no DOM deps so it's node-testable)
- `createStore(initial)` -> {get, set, on, state}; set() fires per-key subscribers only when the value
  actually changes; on() returns an unsubscribe.
- `createSWR({fetcher, ttl, now})` -> {get, revalidate, peek, invalidate, on}; get() returns cached data
  instantly + kicks a background revalidate when stale; a missing key awaits the fetch; concurrent gets
  share one in-flight promise (dedup). `now` is injectable so tests control the clock.

tested via node --test with a fake fetcher + injected clock: store get/set/notify/no-notify-on-same/
unsubscribe; SWR first-fetch-caches, fresh-hit-no-refetch, stale-returns-cached-and-revalidates,
concurrent-dedup, invalidate-refetches, on-fires-after-revalidate.
