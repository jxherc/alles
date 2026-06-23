# stage 4c - photos / files / vault depth - audit findings (2026-06-23)

## current state
- `Share` (token -> kind/ref, level view|download) has NO expiry and NO password: a shared link lives
  forever and anyone with the URL gets in. `mint` is idempotent by (kind, ref).
- `Photo` carries rich EXIF (`taken_at`, `exif` json, `keywords`) but there are NO smart albums: you
  can't auto-group by month/day taken or pull "everything from June" without manual albums.

## scope (highest-value testable cores)
1. shareable links with expiry + password (extend the Share model + resolve path).
2. smart albums: pure EXIF-date grouping + date-range / keyword virtual albums.
DEFERRED: folder-sync albums, EXIF-preserving format conversion, gallery<->photos merge, vault-attachment
indexing (rides 0d blob adoption) - heavier/file-IO surfaces.

## fix
- migration m0007: `Share.expires_at` + `Share.password_hash`.
- `services/share.py`: `mint(..., expires_at=None, password=None)`; `is_expired(share, now)`,
  `check_password(share, pw)`, `resolve(db, token, password="")` -> the share only if live + auth'd.
- `services/smart_albums.py` (pure over photo dicts {id, taken_at, keywords}): `group_by_period(photos,
  period)` (month/day buckets), `in_range(photos, start, end)`, `by_keyword(photos, kw)`.
- routes: extend share mint to pass expiry/password; /photos/smart?period=&from=&to=&keyword=.

tested: mint stores expiry+pw, resolve live vs expired, password required/correct/wrong, no-pw share open,
group_by_period month buckets, in_range filter, by_keyword, missing-taken_at bucketed as unknown.
