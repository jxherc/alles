# 1b — Offline & sync engine — audit (2026-06-19)

Server: `ALLES_DATA=…/alles1b_data PORT=8812 AUTH_ENABLED=false python app.py`.

## What I exercised
- Read `static/sw.js` (the only SW). Today it does **offline shell + GET caching only**:
  - `fetch` handler returns early for any non-GET and for any `/api/*` (lines 17–18) → mutating
    requests are never touched by the SW.
  - GET: network-first with cache fallback; vendor bundles stale-while-revalidate; navigations fall
    back to the cached `/` shell. Push + notificationclick handlers present.
- `static/js/util.js:api()` is the central fetch wrapper (JSON encode + error throw), but many modules
  also call `fetch` directly — so the robust interception seam is the **service worker**, not `api()`.
- SW is registered via `push.js:registerServiceWorker()` (called in `app.js:init()` at line 118).
- Confirmed `POST /api/tasks` works online (curl → 200 with the new task).

## Gap (the 1b work)
- **Offline writes are silently lost.** With the SW controlling the page, a mutating `/api/*` request
  made while offline just rejects; nothing is queued, nothing replays. There is no IndexedDB outbox,
  no replay-on-reconnect, and no "pending sync" indicator. This blocks offline doc/journal/task editing
  (2e) and the mobile PWA (11b).

## Plan (1b-1) — SW write-queue + page indicator
1. `static/sw.js`: intercept mutating `/api/*` (POST/PUT/PATCH/DELETE, excluding `/api/auth`,
   `/api/chat`, `/api/agent` streaming, and multipart uploads). Try the network; on failure, store the
   serialized request in an IndexedDB `alles-sync/outbox` store and return a synthetic
   `200 {queued:true,offline:true}` so the UI doesn't error. Add `flush()` (FIFO replay, drop on 2xx or
   permanent 4xx), `message` handlers (`alles-flush`, `alles-pending`), and `notifyClients()` posting the
   pending count.
2. `static/js/sync.js` (`initSync`): register SW, listen for `alles-sync` messages → update a
   `#sync-indicator` badge; on `online` + on load → post `alles-flush`/`alles-pending`.
3. `static/index.html`: a `#sync-indicator` chip (hidden by default) + CSS.
4. Wire `initSync()` in `app.js` after `registerServiceWorker()`; bump `?v`/`_v`/SW VERSION.

## Verify (`tests/pw_sync_1b.py`, Playwright, ≥9 assertions, RED→GREEN)
sw_controls, offline_write_returns_queued, outbox_has_entry, indicator_shows_pending,
queue_survives_reload, online_replays_drains_outbox, server_received_write, indicator_clears,
zero_console_errors.
