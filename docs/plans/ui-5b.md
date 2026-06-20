# ui-5b — files icon unification

Every emoji/Unicode glyph in the files app is now drawn from the Stage-0 central icon set
(`window.icon`) so files matches the rest of the product. Swapped in `static/js/files.js`:

- **Smart-folder bar** (`SMART` + `_injectSmartFolders`): 🕘🖼📄📦 → `clock/image/file/archive`;
  📈 activity → `history`, 🧬 duplicates → `copy`, ★ starred → `star`, 🗑 trash → `trash`.
- **Row hover actions**: ☆/★ star → `star`/`star-fill`, ↓ download → `download`, ⇗ share → `share`,
  💬 comment → `comment`, ⏱ versions → `history`, ⊙ tag → `tag`, ✎ rename → `edit`, ✕ delete → `trash`.
- **Scattered glyphs**: trash empty-state 🗑 → `trash`, ↩ restore → `undo`, dedup delete ✕ → `trash`,
  documents row 📄 → `file`, grid/list toggle ☰/▦ → `list`/`grid`, sort arrows ↑/↓ → chevrons,
  comment badge 💬 → `comment`, comment-thread resolve ✓/○ → `check-circle`/`check`, delete ✕ → `trash`.
  Also dropped the lone 🎉 from the "no duplicates" empty state.

A small `_si(name)` wrapper guards `window.icon` load order. CSS (`.file-act .ic`, `.files-smart .ic`,
`.files-sort .ic`, `.file-comment .ic`, `.file-cacts button .ic`, `#files-view-toggle .ic`) sizes the
inline SVGs and switches the host buttons to `inline-flex` so icon + label align.

Tests: `tests/test_files_icons.py` (source contract: no leftover action emoji, every action renders via
`window.icon`/`_si`, all expected icon names present) + `docs/evidence/ui-5b/verify.py` (smart bar + row
actions render real `<svg class="ic">`, star toggles fill, 0 console errors) + `smart.png`.
