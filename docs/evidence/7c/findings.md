# 7c — gallery: share & motion — findings

Audited the gallery's sharing/video/sync surface by reading the code and running an isolated server
(`ALLES_DATA=/tmp/alles7c PORT=8863 AUTH_ENABLED=false python app.py`) with curl + Playwright.

## Audit — state before the build
- 1a share primitive already lists `album` in `VALID_KINDS`; generic `/api/share` mints/lookups/revokes an
  album token. But `/s/{token}` only rendered doc/file/folder/photo — **no album viewer**.
- **No video support** anywhere (`photos_store._ALLOWED` was images only; lightbox was `<img>`).
- **No ffmpeg** on this box → adapted: videos are stored + played (browser `<video>`, `<video preload>`
  poster in the grid + a ▶ badge), no server-side frame extraction.
- `photo_sync.sync_folder` did manual imports; **no watch-folder job**.
- `/api/settings` PATCH whitelists fields via `SettingsPatch` — a new key needs adding there (found while
  wiring the watch-folder setting; the UI saved but the value was silently dropped until added).

## Built (gaps only)
- **7c-1 shared albums** (`routes/shared.py`): `/s/{token}` album viewer = read-only photo grid (excl
  hidden + deleted); confined child route `/s/{token}/{photo_id}` serves a member image only (404 for
  non-members, hidden, deleted, unknown).
- **7c-2 video assets** (`core/database.py`, `services/photos_store.py`, `routes/photos.py`):
  `Photo.is_video`; `import_media` dispatches mp4/mov/m4v/webm → stored as-is (no decode); `_fmt` carries
  `is_video`; list/search include videos; `original` serves them with a `video/*` content-type.
- **7c-3 watch-folder** (`services/photo_sync.py`, `app.py`, `routes/settings.py`): `run_watch()` reads the
  `photos_watch_folder` setting and syncs it (no-ops when unset/missing, dedups via sync state); registered
  as a 300s job; setting added to `SettingsPatch`.
- **7c-4 frontend** (`static/js/photos.js`, `appsettings.js`, `index.html`, `style.css`): share-album button
  (mints + copies the link); video ▶ badge + `<video>` poster in the grid; `<video controls>` in the
  lightbox (img/video swap, edit hidden for video); watch-folder input in the gallery cog. Stamps → v63 / SW v37.

## Exercised with real input
- `POST /api/share {album}` → token; `/s/{token}` renders the album's photos read-only (see `shared-album.png`).
  Child route serves members, 404s non-members/hidden/deleted (unit `test_share_album`, 10/10).
- Upload `clip.mp4` → `is_video:true`, served as `video/mp4`; lightbox plays it (`video-lightbox.png`).
- `run_watch` imports a watched folder, idempotent on rerun, ignores non-images, respects a limit
  (`test_photo_watch`, 8/8).

## Bugs / imperfections found
- **Real bug fixed:** `/api/settings` dropped `photos_watch_folder` because `SettingsPatch` didn't declare
  it — the cog input appeared to save but didn't persist. Added the field; verified end to end.
- Test-only: the public album grid assertion reads page HTML (the images load via the confined child route).
- `routes/settings.py` has a pre-existing `I001` import-sort warning on its import block (present on HEAD,
  not introduced here) — left out of scope per CLAUDE.md.
- Adaptation (documented): no ffmpeg → no server-side video thumbnails; the grid uses a `<video preload>`
  poster + ▶ badge instead. Video playback itself is fully working.

## Evidence
`audit_dumps.txt` (7b file reused dir has its own), `pw_photos_share_7c.txt` (8/8), `shared-album.png`,
`video-lightbox.png`. Unit: `test_share_album` 10, `test_photos_video` 9, `test_photo_watch` 8.
