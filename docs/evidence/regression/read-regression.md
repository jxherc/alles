# Post-workstream regression — after read-later (next-version WS4) — 2026-06-20

Isolated server `:8915`, seeded real articles.

1. **Full unittest suite** — **Ran 2602 tests, OK** (+18 read).
2. **19-host sweep** — `docs/evidence/ui-9/sweep.py 8915` → **ALL GREEN: 19 hosts + 6 deep
   click-throughs, 0 real console errors** (added `read` host + "read save link" deep step).
3. **Read audit** — `docs/evidence/read/audit.py 8915` → PASS, 0 console errors.
4. **ruff** clean on `routes/read.py`, `tests/test_read.py`; **node --check** on `read.js`, `app.js`,
   `subdomain.js`.

Cache stamps bumped (`?v`/`_v` → 99, sw → v73). Nothing regressed.
