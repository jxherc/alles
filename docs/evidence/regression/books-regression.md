# Post-workstream regression — after books (next-version WS5) — 2026-06-20

Isolated server `:8916`, seeded books with OpenLibrary covers.

1. **Full unittest suite** — **Ran 2615 tests, OK** (+13 books).
2. **20-host sweep** — `docs/evidence/ui-9/sweep.py 8916` → **ALL GREEN: 20 hosts + 6 deep
   click-throughs, 0 real console errors** (added `books` host + "books add" deep step).
3. **Books audit** — `docs/evidence/books/audit.py 8916` → PASS, 0 console errors.
4. **ruff** clean on `routes/books.py`, `tests/test_books.py`; **node --check** on `books.js`, `app.js`,
   `subdomain.js`.

Cache stamps bumped (`?v`/`_v` → 100, sw → v74). Nothing regressed.
