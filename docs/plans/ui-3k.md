# ui-3k — move Canvas / Board / Bookmark / Tasks out of the in-doc toolbar

The in-doc docs toolbar was overloaded. Moved the document-agnostic actions to the **docs home**:

- Removed `#wiki-canvas-btn`, `#wiki-board-btn`, `#wiki-taskroll-btn`, `#wiki-bookmark-btn` from the editor
  toolbar (`static/index.html`).
- Added **+ new canvas**, **+ new board**, **tasks** to the docs-home actions, wired to the existing
  `openCanvas` / `openBoard` / `toggleTaskRoll` (`static/js/vaultmd.js`).
- **Bookmark now works from outside a doc**: each home doc card has a star (`.docs-card-star`) that calls the
  new path-based `_bookmarkPath(path)` (factored out of the old in-doc `toggleBookmark`) and repaints the
  bookmarks strip. Removed the now-dead `toggleBookmark` / `_syncBookmarkBtn`.

Tests: `tests/test_docs.py::MovedToHomeTests` (4) + `docs/evidence/ui-3k/verify.py` (home has the 3 new
buttons, cards render with stars, star bookmarks + shows the strip, all 4 in-doc buttons gone, 0 errors).
