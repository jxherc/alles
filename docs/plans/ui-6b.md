# ui-6b — gallery icon unification

Every emoji/Unicode glyph in the gallery now comes from the Stage-0 central icon set, matching the rest
of the app. `static/js/photos.js` gained a `_si()` `window.icon` guard.

- **Header** (`static/index.html`): 🔗 share / ✨ generate / 🗑 trash → inline `<svg class="ic">`
  (share / sparkles / trash), `.ic-btn-lbl` sizes icon+label.
- **Cells**: video badge ▶ → `play`; favorite badge ♥ moved off the CSS `::after` glyph onto a real
  `.photos-fav-badge` heart-icon element (injected both in `_cellHtml` and on inline favorite-toggle).
- **Lightbox actions**: favorite ♥/♡ → `heart`/`heart-fill`, hide → `eye-off`/`eye`, edit → `edit`,
  download → `download`, delete → `trash`, close → `close` (decorated in `openLightbox`).
- **Album dropdown**: ★/🔒/🗺/✨ option-label emoji → the dropdown's per-option `_iconHtml` map
  (star/lock/map-pin/sparkles); labels are now plain text.
- **Misc**: location 📍 → `map-pin`, locked-album empty states 🔒 → `lock`, collage ✨ → `sparkles`,
  trash-back ← → `chevron-left`, restore ↩ → `undo`.

Tests: `tests/test_photos_icons.py` (8 source-contract: no emoji in js/markup, header inline icons,
lightbox/js decoration, fav badge is an icon not a CSS glyph, album icon map, video play badge) +
`docs/evidence/ui-6b/verify.py` (seeds a photo; header + lightbox + fav-badge render real `<svg class=ic>`,
no emoji, 0 console errors) + `lightbox.png`.
