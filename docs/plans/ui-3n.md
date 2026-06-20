# ui-3n — remove Publish + CSS buttons

Per the brief: export already covers sharing, and per-vault CSS is an odd power-feature. Removed from the
docs editor:

- `#wiki-publish-btn` (+ `togglePublish` / `_syncPublishBtn` and the now-unused `shareResource` /
  `unshareResource` / `shareState` imports).
- `#wiki-theme-btn` ("css") + the `#wiki-theme` panel + `toggleTheme` / `saveTheme` / `_injectVaultTheme`
  and the dead `.wiki-theme-input` style. (The `/api/vault-md/theme-css` backend route is left in place but
  no longer wired to any UI.)

Toolbar now reads: …history ☆ 💬 split export ▾ delete — no publish, no css.

Tests: `tests/test_docs.py::RemovedButtonsTests` (3) + `.tmp` toolbar probe (`docs/evidence/ui-3n/toolbar.png`:
both buttons + panel absent, 0 console errors).
