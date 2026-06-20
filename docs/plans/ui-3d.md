# ui-3d — images: live render + insert dialog

Live rendering of `![alt](url)` and `![[file]]` embeds landed in ui-3c. This adds the **insert UX**:

- The toolbar **img** button (`data-fmt="image"`) now opens `openImageDialog(btn)` (`static/js/vaultmd.js`)
  instead of dropping a raw `![](url)` placeholder.
- The dialog (a themed `.wiki-img-pop`, mirroring `openExportMenu`) offers **paste a URL** → inserts
  `![](url)`, or **upload from device** → a hidden `<input type=file accept=image/*>` → `uploadImage()` →
  vault asset → inserts `![[asset]]` (same route paste/drop already use).
- Enter inserts, Esc / outside-click closes.

Tests: `tests/test_docs.py::ImageDialogTests` (4) + `docs/evidence/ui-3d/verify.py` (dialog opens, url field,
upload option, url inserted as markdown image, closes after insert, no console errors).
