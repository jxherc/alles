# Post-workstream regression — after `watch` (next-version WS1) — 2026-06-20

Isolated server `:8912`, fresh `ALLES_DATA`, real seeded data.

1. **Full unittest suite** — `python -m unittest discover -s tests` → **Ran 2547 tests, OK** (+25 watch).
2. **Broad + deep sweep** — `docs/evidence/ui-9/sweep.py 8912` → **ALL GREEN: 17 hosts + 6 deep
   click-throughs, 0 real console errors** (added `watch` host + a "watch add monitor" deep step to the
   canonical sweep). One transient `days` goto-timeout on the first run cleared on re-run (untouched app,
   page-load contention).
3. **ruff** — `routes/watch.py`, `tests/test_watch.py` clean (`check` + `format --check`).
4. **node --check** — `watch.js`, `app.js`, `subdomain.js` OK.

Nothing regressed. Cache stamps bumped (`?v`/`_v` → 96, sw → v70) so open tabs pick up the new app.
