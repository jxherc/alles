# Post-workstream regression — after habits (next-version WS3) — 2026-06-20

Isolated server `:8914`, seeded habits.

1. **Full unittest suite** — **Ran 2584 tests, OK** (+18 habits).
2. **18-host sweep** — `docs/evidence/ui-9/sweep.py 8914` → **ALL GREEN: 18 hosts + 6 deep
   click-throughs, 0 real console errors** (added `habits` host + "habits add+toggle" deep step).
3. **Habits audit** — `docs/evidence/habits/audit.py 8914` → PASS, 0 console errors.
4. **ruff** clean on `routes/habits.py`, `tests/test_habits.py`; **node --check** on `habits.js`, `app.js`,
   `subdomain.js`.

Cache stamps bumped (`?v`/`_v` → 98, sw → v72). Nothing regressed.
