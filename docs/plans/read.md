# read-later archive (next-version workstream 4)

Save a URL → fetch + store the readable page text → search it offline. Links don't rot. Reuses the
research extractor (`services/research/search.fetch_webpage_content`) instead of a new scraper.

## Tasks

### read-1 — backend · TDD
- `ReadItem` model in `core/database.py` (url, title, text, excerpt, site, image, read_minutes,
  added_at, read_at, fav, archived, tags).
- `routes/read.py`: pure `site_of` (host, strip www, reject non-domains), `make_excerpt`, `read_minutes`,
  `_norm_tags`. Endpoints: `POST /read` (fetch+store, keeps link on extraction failure), `GET /read`
  (filter all/unread/fav/archived + `q` full-text + `tag`), `GET /read/{id}` (full text), PATCH
  (tags/fav/archived), `POST /read/{id}/read` (toggle), DELETE. Wired via include_router.
- **Tests** (`tests/test_read.py`, 18): site_of variants, excerpt truncate/collapse, read_minutes, save
  stores text (mock extractor), save keeps link on failure, list, search title/body/no-match, get full,
  mark-read toggle, patch tags/fav, archive exclusion, delete.

### read-2 — frontend
- `static/js/read.js`: add-URL bar, filter chips, debounced search, cards (title/excerpt/site/read-time +
  star/read/archive/delete), and a clean reader view (capped column) with back + open-original.
- Wiring: subdomain/app.js (`_VIEW_IDS`, `showReadView`, navigateTo, `_ICON.read`, HOME_TILES),
  index.html (`#read-view` + stamp 99), sw v73, style.css (`#read-*` block).
- **Audit** (`docs/evidence/read/`): list/search/reader/star/narrow screenshots, 0 console errors.

## Verification
- `python -m unittest tests.test_read` (18) + full suite green.
- `ruff` clean; `node --check` on touched JS.
- `audit.py 8915` PASS; regression sweep (19 hosts incl. read) green.
