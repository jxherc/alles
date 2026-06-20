# ui-0a — central icon system — findings

## Audited
- Scanned all `static/js/*.js` + `index.html` for non-ASCII glyphs → `glyph_inventory.txt`.
  135 distinct non-ASCII chars. After excluding box-drawing `─` (×4346, comment separators) and
  typographic chars (`— … · → × " ' – ← ↑ • °`, real text), ~90 are genuine UI icons drawn as
  emoji/Unicode from no shared system: `✓ ★ ☆ ✕ 🔗 🔒 📎 ✈ 🗑 💬 📅 ⚙ 👁 ✨ ♥ ♡` + mood emoji
  `😄🙂😐😕😢😠😴🤔🥳😍🔥` + media `🔊🎙📹` etc.

## Built
- `static/js/icons.js` — 86-icon SF-style monochrome set + `icon(name,opts)` / `iconEl()` /
  `ICON_NAMES`. Contract: `viewBox 0 0 24 24`, `fill none`, `stroke currentColor`, `stroke-width
  1.6`, round caps; sized by font-size, colored by currentColor. Unknown name → safe fallback glyph.
- `static/style.css` — `.ic` (1em box, currentColor) + `.ic-glow` (drop-shadow in currentColor, for
  the live/brand dots later).
- `static/js/app.js` — imports the module and exposes `window.icon/iconEl/ICON_NAMES` so the
  inline-HTML feature modules can adopt it without each importing.

## Scope note
ui-0a ships the *system* + wiring. Per-app emoji are swapped to it inside each app's own stage
(home/chrome ui-1, aide ui-2f, docs ui-3, mail ui-4, files ui-5b, gallery ui-6b, contacts/journal
ui-7, secrets ui-8) — where that file is already being edited, avoiding a double pass. Box-drawing and
typographic chars are deliberately left alone.

## Verified
- `python -m unittest tests.test_icons` → 10/10 OK (catalog coverage, monochrome contract, size/class
  opts, unknown-fallback, node runtime render, glow style).
- `node --check static/js/icons.js` → OK.
- Playwright on `aide.localhost:8870`: `window.icon('search')` returns a real `<svg>`, 86 names
  exposed, **0 console errors**.
