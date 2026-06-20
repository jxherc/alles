# ui-7b — CardDAV → contacts settings + sync interval

Moved CardDAV out of the contacts toolbar into a proper per-app settings pane, and gave it a real
**auto-sync interval** (off / hourly / daily) instead of being manual-only.

## Backend (`services/carddav_sync.py`, `routes/carddav.py`, `app.py`)
- `status()` now reports `interval`; `set_interval()`, `stamp_sync()`, `due_for_sync(now)` added.
  `save_cfg` keeps `interval`/`last_sync` sticky across connect/disconnect.
- `sync()` stamps `last_sync` on real (non-injected-client) syncs.
- `POST /api/carddav/interval` sets it.
- `app.py` registers a `carddav_auto` job (ticks every 10 min, syncs only when `due_for_sync`).

## Frontend (`static/index.html`, `static/js/contacts.js`, `appsettings.js`)
- Removed the toolbar `CardDAV` button; added a contacts `app-cog`.
- New `contacts` spec in appsettings with a `CardDAV sync` action → `window._contactsCardDav`.
- Reworked `showCardDav` into a settings pane: status (with check icon), help text, connect/sync/
  disconnect, and an auto-sync `.seg` control wired to `/api/carddav/interval`. Unified ✓/← glyphs.

Tests: `tests/test_carddav_interval.py` (10: status default, set/reject, connect-preserve, due-for-sync
off/unconnected/hourly/daily, + 2 API) and `tests/test_contacts_settings.py` (6 frontend contract) +
`docs/evidence/ui-7b/verify.py` (cog → popover → CardDAV pane → interval persists, 0 console errors).
