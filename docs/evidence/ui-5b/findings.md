# ui-5b — files icon unification (findings)

## Audit (before)

Files mixed three glyph sources like the rest of the pre-overhaul app:
- smart-folder bar: 🕘 🖼 📄 📦 emoji + 📈 🧬 ★ 🗑
- row hover actions: ☆/★ ↓ ⇗ 💬 ⏱ ⊙ ✎ ✕
- scattered: grid/list toggle ☰/▦, sort arrows ↑/↓, trash empty-state 🗑, ↩ restore,
  dedup delete ✕, documents row 📄, comment badge 💬, comment-thread ✓/○ + ✕, a lone 🎉.

These don't match the Stage-0 central icon set used everywhere else now.

## Fix

All swapped to `window.icon(name)` (via a small `_si()` load-order guard) in `static/js/files.js`,
mapped to existing catalog entries — no new icons needed. `star`→`star-fill` on toggle so the filled
state reads as a real icon, not a different glyph. CSS sizes the inline SVGs in each control
(`.file-act .ic`, `.files-smart .ic`, `.files-sort .ic`, `.file-comment .ic`, `.file-cacts button .ic`,
`#files-view-toggle .ic`) and switches the host buttons to `inline-flex` so icon + label align.

## Verify (after)

`verify.py` against an isolated server (`.tmp_5b`, :8872): seeded one upload, then confirmed the
smart bar + every row action render real `<svg class="ic">`, the star toggle swaps to the filled icon,
no emoji/Unicode glyph survives anywhere in `#files-view`, 0 console errors. Screenshot: `smart.png`.
Gate: `tests/test_files_icons.py` (8 source-contract tests).
