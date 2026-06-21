# books — reading list (next-version workstream 5)

A library tracker (distinct from read-later's web articles): shelves (want / reading / done), ratings,
notes, and a keyless OpenLibrary lookup to autofill cover + author.

## Tasks

### books-1 — backend · TDD
- `Book` model in `core/database.py` (title, author, status, rating, started, finished, cover, notes,
  isbn, year).
- `routes/books.py`: pure `clamp_rating`, `year_count`, `parse_ol_doc`. Endpoints: CRUD, `GET
  /books/overview` (shelves grouped by status + this-year finished count), `GET /books/lookup` (keyless
  OpenLibrary search → candidates). Status moves auto-stamp started/finished. Wired via include_router.
- **Tests** (`tests/test_books.py`, 13): clamp_rating, year_count, parse_ol_doc (+missing fields),
  create/validate, overview shelves + this_year, status→done auto-finish, rating clamp, notes, delete.

### books-2 — frontend
- `static/js/books.js`: shelves (reading/want/read) cover grids, clickable star ratings, per-card
  shelf-move buttons, inline notes editor, add form with OpenLibrary lookup (pick a candidate to
  autofill), cover-or-initial placeholder.
- Wiring: subdomain/app.js (`_VIEW_IDS`, `showBooksView`, navigateTo, `_ICON.books`, HOME_TILES),
  index.html (`#books-view` + stamp 100), sw v74, style.css (`#books-*` block).
- **Audit** (`docs/evidence/books/`): shelves/rate/move/lookup/add/notes/narrow screenshots, 0 console errors.

## Verification
- `python -m unittest tests.test_books` (13) + full suite green.
- `ruff` clean; `node --check` on touched JS.
- `audit.py 8916` PASS; regression sweep (20 hosts incl. books) green.
