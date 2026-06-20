# 7b — gallery: places & memories — findings

Audited the gallery's GPS/places/memories area by reading the code and hitting an isolated server
(`ALLES_DATA=/tmp/alles7b PORT=8862 AUTH_ENABLED=false python app.py`) with curl + Playwright.

## Audit — state before the build
- GPS EXIF → decimal lat/lon already extracted (`photos_store._gps_to_decimal`, surfaced as
  `exif.lat/lon`); the lightbox already shows a per-photo OpenStreetMap **link**.
- No **map view**, no **memories** ("on this day"), no **collage** — confirmed by `GET /api/photos/map`,
  `GET /api/photos/memories`, `POST /api/photos/collage` all returning 405 (the path fell through to the
  `/{pid}` route — i.e. unimplemented). See `audit_dumps.txt`.
- `static/vendor/` had only `cm6.bundle.js`. unpkg reachable for vendoring Leaflet; OSM tiles reachable
  with a normal browser UA.

## Built (only the gaps)
Backend (`routes/photos.py`, `services/photos_store.py`):
- `GET /api/photos/map` → `{points:[{id,lat,lon,thumb,original,caption,taken_at}],count}`, located photos
  only, excludes hidden + deleted.
- `GET /api/photos/memories?date=YYYY-MM-DD` (default today) → `{groups:[{years_ago,year,date,items}],count}`,
  same month/day in strictly earlier years, grouped + sorted most-recent-first, excludes hidden + deleted.
- `POST /api/photos/collage {ids,cols?}` → `photos_store.make_collage` builds a square-cell PIL grid and it
  is saved as a new photo; empty ids → 400, unknown ids skipped, no usable images → 400.

Frontend (`static/js/photos.js`, `static/style.css`, `static/index.html`, `static/vendor/leaflet/*`):
- Vendored Leaflet 1.9.4 (js + css + marker images). Lazy-loaded only when the map opens.
- Album dropdown gains `🗺 map` and `✨ memories` virtual views (same pattern as favorites/hidden).
- Map view: full-width OSM map, an accent `circleMarker` per located photo, click → lightbox.
- Memories view: "N years ago" sections of on-this-day photos, each with a make-collage button.
- Cache stamps bumped: `?v=62`, `_v='62'`, SW `v36`.

## Exercised with real input (live, see `audit_dumps.txt`)
- `/map` → 1 located point (37.7749,-122.4194). `/memories` → "1 yr ago 2025-06-19 → 2 photos".
- `/collage` of the two memory photos → new 1200×400 photo (3 cols default, 2 imgs → 1 row). Empty ids → 400.

## Bugs / imperfections found
- **App bugs: none.** Both views and collage work end to end.
- Test-only fixes while writing the Playwright test (not app issues):
  - Leaflet sets the `leaflet-container` class on the target element itself, not a child — my first
    descendant selector never matched; corrected to `#photos-mapview.leaflet-container`.
  - a `wait_for_function` whose predicate returned a `fetch().then()` Promise resolved immediately
    (a Promise is always truthy) → replaced with an explicit Python poll of the photo count.
- Environment note: OSM map **tiles** render grey in the sandboxed headless browser (external tile fetch
  blocked there); the map structure, marker, controls, and attribution all render. Tiles load normally in a
  real deployment with internet. Tile-load failures are in the console-error ignore list, so the sweep stays clean.

## UI notes
Map and memories are on-theme (accent `#818cf8` marker, dark zoom controls/attribution, 3px radii) — see
`map.png`, `memories.png`. Playwright `pw_photos_places_7b.txt`: 8/8.

## Evidence
`audit_dumps.txt`, `pw_photos_places_7b.txt`, `map.png`, `memories.png`.
