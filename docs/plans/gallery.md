# Phase 5 — gallery / photos (`photos.js` + `routes/photos.py` + `services/photos_store.py` + `services/photo_sync.py`)

## Audit (2026-06-18)

Target: Apple Photos. The gallery app is the **photos** view (`photos.js`; `gallery.js` is the separate
AI-image gallery). Verified working (DO NOT rebuild): library grid grouped into moments by date, search
(filename/EXIF/date), albums (CRUD + assign), upload, folder sync + macOS PhotoKit pull, thumbnails,
favorite flag (PATCH), lightbox. EXIF is read on import (`_read_exif`) into `Photo.exif`. UI 0 console
errors.

Spec asks: "image detail + metadata (full exif, info panel), and extend the existing photo sync toward
Apple/Google Photos." Confirmed gaps: EXIF extraction is **limited** (Make/Model/lens/exposure/ISO/focal
only — **no GPS**, no orientation/software/flash); the **lightbox shows no metadata** (no info panel); no
**favorite toggle in the UI** and no favorites filter; sync **ignores Google Takeout sidecar metadata**.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **gallery-1 Full EXIF + GPS.** Extend `_read_exif` to capture a richer tag set + decimal GPS lat/lon
  (`_gps_to_decimal` helper over the GPS IFD). *Why: "full exif" + location are the heart of a photo
  info panel.*
- **gallery-2 Info panel + favorites.** Lightbox info panel (dimensions, date taken, camera/lens,
  exposure/ISO/focal, a map link when GPS present) + a favorite heart toggle; add a `favorites` filter to
  `GET /api/photos/list` and a Favorites view. *Why: Apple Photos' Info (⌘I) + Favorites; both backend
  bits exist but are invisible.*
- **gallery-3 Google Takeout sync.** `parse_takeout_sidecar` + `sync_folder` reads `<image>.json` /
  `.supplemental-metadata.json` sidecars (photoTakenTime, geoData) to set `taken_at` + GPS on import.
  *Why: "extend sync toward Google Photos" — Takeout is the realistic self-host path.*

## Out of scope

Image editing (spec says not required), iCloud/live-photo sync, face recognition, on-device ML albums.
