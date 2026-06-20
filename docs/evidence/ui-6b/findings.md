# ui-6b — gallery icon unification (findings)

## Audit
Gallery mixed emoji (🔗 ✨ 🗑 ♥ ♡ ▶ 🔒 🗺 📍 ★ ↩ ←) across the header, cells, lightbox, album
dropdown and empty states — three glyph sources, like the rest of the pre-overhaul app.

## Fix
All swapped to the Stage-0 central icon set via `window.icon`/`_si`. Header buttons use inline `<svg
class=ic>`; the favorite badge moved off a CSS `::after '♥'` onto a real heart-icon element; lightbox
actions are decorated on open; album options use the dropdown's per-option `_iconHtml` map.

## Verify
`verify.py` seeds a real PNG upload, then confirms the header (share/generate/trash), every lightbox
action (favorite/hide/edit/download/delete/close) and the on-cell favorite badge render real `<svg
class=ic>`, no emoji text survives in the header or album options, and favoriting injects the heart
badge. 0 console errors. Screenshot: `lightbox.png` (clean 2-col icon action grid).
