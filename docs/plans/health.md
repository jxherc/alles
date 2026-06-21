# health log (next-version workstream 6)

A simple health/fitness log: one row per measurement (weight, sleep hours, workout minutes, meds, custom),
with latest reading + trend chart per metric over a selectable range.

## Tasks

### health-1 — backend · TDD
- `HealthEntry` model in `core/database.py` (int rowid; kind, date, value, unit, note, label).
- `routes/health.py`: pure `latest_per_kind`, `series_for`. Endpoints: CRUD, `GET /health/overview?days=`
  (latest-per-kind ignoring the window + trend series within the window). Wired via include_router.
- **Tests** (`tests/test_health.py`, 13): latest_per_kind (+empty), series sort/filter, create/validate
  (bad kind 400, missing value 422, default date), list, overview latest+series, range exclusion, delete,
  patch.

### health-2 — frontend
- `static/js/health.js`: range chips (7d/30d/90d/1y), per-metric cards (latest number + hand-drawn SVG
  trend line), quick-add form (kind dropdown auto-sets unit), recent-entries list with delete.
- Wiring: subdomain/app.js (`_VIEW_IDS`, `showHealthView`, navigateTo, `_ICON.health`, HOME_TILES),
  index.html (`#health-view` + stamp 101), sw v75, style.css (`#health-*` block).
- **Audit** (`docs/evidence/health/`): cards/charts, range, add, narrow screenshots, 0 console errors.

## Verification
- `python -m unittest tests.test_health` (13) + full suite green.
- `ruff` clean; `node --check` on touched JS.
- `audit.py 8917` PASS; regression sweep (21 hosts incl. health) green.
