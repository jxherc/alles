# Post-workstream regression — after advanced theme editor (next-version WS2) — 2026-06-20

Isolated server `:8913`, fresh data.

1. **Full unittest suite** — `python -m unittest discover -s tests` → **Ran 2566 tests, OK** (+19 appearance).
2. **17-host sweep** — `docs/evidence/ui-9/sweep.py 8913` → **ALL GREEN: 17 hosts + 6 deep click-throughs,
   0 real console errors**. theme.js now loads at boot on every host (via `_syncAppearance` →
   `initAppearance`); no console errors anywhere.
3. **Theme editor audit** — `docs/evidence/theme/audit.py 8913` → PASS, 0 console errors; persistence
   across reload verified after fixing the server-clobbers-local bug.
4. **ruff** — `services/appearance.py`, `routes/appearance.py`, `tests/test_appearance.py` clean.
5. **node --check** — `theme.js`, `colorpicker.js`, `app.js`, `settings.js` OK.

Defaults unchanged (comfortable/sans/no background), so non-users of the editor see no difference. Cache
stamps bumped (`?v`/`_v` → 97, sw → v71). Nothing regressed.
