# advanced theme editor (next-version workstream 2)

Replace alles' two-control appearance (dark/light + one accent) with a full theme editor on par with
odysseus: presets, every base color, fonts, density, animated backgrounds, frosted glass, custom themes,
import/export, harmony generator. Pure color algos + canvas patterns ported from odysseus; the apply
engine + editor UI are alles-native, mapped to alles tokens (bg/text/panel/faint/accent).

## Tasks

### theme-1 — backend + apply engine · TDD
- `services/appearance.py` (pure): `default_appearance`, `normalize` (enum validation, hex check,
  intensity/size clamp), `from_legacy` / `to_legacy` (sync with old theme/accent), `effective`.
- `routes/appearance.py`: `GET /api/appearance` (effective + `_stored` flag), `PUT /api/appearance`
  (normalize + persist under settings['appearance'] + sync legacy theme/accent). Wired via include_router.
- `static/js/theme.js` apply engine: `applyAppearance` (sets CSS vars, derives --muted, data-theme by
  luminance, font/density/frosted/pattern), `initAppearance` (cache-first, server adopts only when
  `_stored`). Generalized `_syncAppearance` in app.js + pre-paint head script in index.html.
- **Tests** (`tests/test_appearance.py`, 19): default shape, normalize fills/validates/clamps, hex
  drop/keep, legacy round-trip, API get/put/roundtrip/legacy-fallback/legacy-sync.

### theme-2 — editor UI + color picker + canvas
- `static/js/colorpicker.js`: in-house picker (HSV square, hue, hex, eyedropper, recent, suggestions),
  ported from odysseus, wraps `<input type=color>`.
- `static/js/theme.js` editor: presets gallery, base-color pickers w/ live preview, harmony generator,
  font/density segments, background pattern picker + intensity + effect color, frosted toggle, custom
  themes (save/apply/delete), import/export. 5 ported canvas effects (synapse/rain/constellations/
  sparkles/petals) + CSS dots. Opened from settings appearance pane (`#s-open-theme-editor`).
- CSS (`style.css`): `.cp-*` picker, `.te-*` editor, density classes, frosted-glass rules, dots, font var
  on html/body. Cache stamps `?v`/`_v` → 97, sw → v71.
- **Tests / evidence**: Playwright audit `docs/evidence/theme/audit.py` (9 screenshotted states +
  persistence + 0 console errors); fixed a persistence bug (server clobbering local — see findings).

## Verification
- `python -m unittest tests.test_appearance` (19) + full suite green (2566).
- `ruff check`/`format --check` clean on new python; `node --check` on all touched JS.
- `audit.py 8913` PASS (0 console errors); 17-host regression sweep green.
