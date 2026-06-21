# books (reading list) — audit findings

New reading list. Isolated server `:8916`, seeded 4 books across shelves via the keyless OpenLibrary
lookup (real covers + authors autofilled). `audit.py` drives the UI.

## What was exercised (works ✓)
- **Shelves** — reading / want-to-read / read, each a cover grid; header shows `4 books · 2 read this
  year` — `01-shelves`, `04-lookup` (covers loaded).
- **Covers** — real OpenLibrary cover images render (Dune, Sapiens, Project Hail Mary, Pragmatic
  Programmer); initial-letter placeholder when a book has none.
- **Star rating** — click a star to set 1–5 (accent-filled) — `02-rated`.
- **Move between shelves** — per-card buttons (want / reading / finished); moving to done auto-stamps the
  finish date and updates the year count — `03-after-move`.
- **Add + OpenLibrary lookup** — search a title → pick a candidate (autofills title/author/cover/isbn/year)
  → add; or type manually. Status segmented control — `04-lookup`, `05-after-add`.
- **Notes** — inline +note → textarea → save — `06-note`.
- **Delete** — confirm dialog.
- **Responsive** — single-column grid at 460px — `07-narrow`.
- **Breadcrumb / tile / subdomain** — `books` tile (book icon), `books.localhost`, breadcrumb `books / alles`.

## Notes (not bugs)
- Cover images can lag the first paint (external host `covers.openlibrary.org`, slow through this env's
  proxy) — `01-shelves` caught a few mid-load; they're present by `04-lookup`. Console errors from the
  external cover host are filtered (not our code).

## Console / errors
- `console.log` — **0 real console errors** across rate/move/lookup/add/notes/narrow.

## Verdict
Works and looks unified (kokuen tokens, accent stars, custom segmented control, cover grid). The keyless
OpenLibrary autofill makes adding books frictionless and is distinct from read-later's web-article archive.
