# 7a audit — gallery: organize & recover

Read the gallery end to end (routes/photos.py, services/photos_store.py, static/js/photos.js,
Photo/Album models).

## Already shipped (do NOT rebuild)
- **Trash + restore (1d)** — `DELETE /api/photos/{id}` soft-deletes (`deleted_at` + TrashItem),
  `GET /api/photos/trash`, `POST /api/photos/{id}/restore`; UI has a trash view with restore.
- **Favorites filter** — `GET /api/photos/list?favorites=true`, the `__fav__` album option, the heart
  toggle in the lightbox, and the `.fav` cell class are all present.
- **Albums CRUD**, **EXIF/date/filename search**, EXIF GPS map link, image editor, AI generate.

## Genuine gaps (build these)
- **Captions / keywords / tags** — `Photo` has no caption or keywords column; nothing editable or
  searchable. Add `caption` + `keywords` (csv) columns, expose in `_fmt`, edit in the lightbox,
  include in `/search`.
- **Hidden / locked album** — no `hidden` flag and no gating. Add a `hidden` column, exclude hidden
  from `/list`, and a `GET /api/photos/hidden` gated behind the **vault unlock** (`_master_pw`
  dependency from routes/vault.py → 403 when locked). UI: a hide button + a "hidden" album that
  prompts for the master password.

## Plan
docs/plans/7a.md. Backend TDD `tests/test_photos_organize.py`; UI `tests/pw_photos_organize_7a.py`.

---

## Verification (resume pass)
The build was completed by the prior autorun (backend + frontend both present and working) but left
both tasks `pending` and had no UI test / evidence. This pass verified it end to end and closed it out.
Nothing was rebuilt.

### Exercised with real input
Backend (`api_dumps.txt`), isolated server on :8861:
- upload real PNG → PATCH `caption`/`keywords=["Beach","Sunset","beach"]` → normalizes to
  `["beach","sunset"]` (lowercase/trim/dedup). ✓
- `/search?q=sunset` (caption) → 1; `/search?q=beach` (keyword) → 1. ✓
- PATCH `hidden=true` → `/list` count 0 (excluded). ✓
- `GET /hidden` no token → **403**; after `/vault/unlock` with the token → 1. ✓
- PATCH `favorite=true` → `/list?favorites=true` → 1. ✓

Frontend (`pw_photos_organize_7a.txt`, 8/8; screenshots):
caption+keywords save & persist on reopen · favorites filter shows ♥ and excludes non-favs · hide
removes from grid · 🔒 hidden album prompts for the master password and lists after unlock · zero
console errors.

### Bugs found
- **App bugs: none.**
- Test-only fixes while writing the Playwright test (not app issues): made assertions relative to the
  run's own photo ids (idempotent on a dirty DB) and fixed a reload race (wait until a known non-favorite
  drops out of the grid before reading the filtered list). Green on clean DB, idempotent across reruns.

### Evidence
`api_dumps.txt`, `pw_photos_organize_7a.txt`, `gallery-grid.png`, `lightbox-editor.png`, `hidden-album.png`.
