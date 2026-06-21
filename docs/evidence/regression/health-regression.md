# Post-workstream regression — after health log (next-version WS6) — 2026-06-20

Isolated server `:8917`, seeded health data.

1. **Full unittest suite** — **Ran 2628 tests, OK** (+13 health).
2. **21-host sweep** — `docs/evidence/ui-9/sweep.py 8917` → **ALL GREEN: 21 hosts + 6 deep
   click-throughs, 0 real console errors** (added `health` host + "health log entry" deep step).
3. **Health audit** — `docs/evidence/health/audit.py 8917` → PASS, 0 console errors.
4. **ruff** clean on `routes/health.py`, `tests/test_health.py`; **node --check** on `health.js`, `app.js`,
   `subdomain.js`.

Cache stamps bumped (`?v`/`_v` → 101, sw → v75). Nothing regressed.
