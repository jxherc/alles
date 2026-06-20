# ui-0a — central SF-style icon system

## Problem
Icons are pulled from three sources with no central system: a few inline SVGs (`files.js:_ic`),
~90 distinct Unicode symbols, and emoji. They look mismatched and "from different sources" (the
user's words across mail, files, gallery, contacts, vault). SF Symbols can't be embedded in a web
app (Apple-platform font, license, won't render on Docker/non-Apple), so we build our own.

## Scope
- New `static/js/icons.js`: a single SF-style monochrome inline-SVG set + `icon(name, opts)` helper.
- Visual language (locked): `viewBox 0 0 24 24`, `fill none`, `stroke currentColor`, `stroke-width
  1.6`, round caps/joins. Sizes via `font-size`/`width:1em`. A `.ic-glow` variant for live/brand dots.
- Replace glyphs in the **shared/global chrome** as proof + immediate win: topbar/sidebar, model
  dot/live dot, the app-cog (already SVG, leave), nav. Per-app emoji are replaced inside each app's
  own stage (mail ui-4, files ui-5b, gallery ui-6b, contacts/journal ui-7, secrets ui-8, docs ui-3).
- NOT touched: box-drawing `─` and typographic `— … · → × " ' – ← ↑ • °` (comments + real text).

## Catalog (semantic names, not glyphs)
search, plus, close, check, check-circle, x-circle, star, star-fill, eye, eye-off, lock, unlock,
gear, trash, edit, copy, link, share, download, upload, refresh, chevron-left/right/up/down, calendar,
clock, mail, paperclip, comment, image, file, folder, tag, bell, play, pause, stop, mic, volume,
video, grid, list, map-pin, plane, shield, sun, moon, send, archive, snooze, mute, sparkles, heart,
heart-fill, columns, board, palette, history, bookmark, bookmark-fill, menu, key, fingerprint, more,
drag, info, warning, sigma, target, scale, fire, undo, redo, dollar, cake, gift, party.

## Tests (≥8) — `tests/test_icons.py` (scans the JS as text + structure)
1. `icons.js` exists and defines `export function icon(`.
2. Every catalog name resolves to a registered path entry (parse the `ICONS` map).
3. `icon('search')` text output contains `<svg` and `viewBox="0 0 24 24"`.
4. Output uses `stroke="currentColor"` and `fill="none"` (monochrome contract).
5. `icon(name, {size})` injects a width/height/font-size for the size.
6. `icon(name, {cls})` adds the class onto the svg.
7. Unknown name → falls back to a default glyph (not a crash / empty string).
8. `.ic-glow` style exists in `style.css`.
9. Shared-chrome guard: the topbar/sidebar region of `index.html` no longer hardcodes a replaced
   emoji from the shared set (regression guard so chrome stays on the icon system).
10. Catalog has ≥ 60 distinct icons (coverage floor for later stages).

## Verify
`python -m unittest tests.test_icons`; `node --check static/js/icons.js`; boot + Playwright screenshot
the topbar/home to confirm the chrome icons render (no tofu/boxes), 0 console errors.
