# ui-3c-3 — live preview: lists

In `.cmbuild/cm-entry.js`:

- **Bullet** `-`/`*`/`+` `ListMark` → a `•` widget (`.cm-bullet`) off-line.
- **Task** items: the dash is hidden and the `TaskMarker` `[ ]`/`[x]` becomes a real, interactive
  `<input type=checkbox>` (`.cm-task-checkbox`) — clicking it rewrites the source `[ ]`↔`[x]` (always live,
  Obsidian-style).
- **Numbered** lists keep their real `1.`/`2.` text (muted), so editing stays lossless.

Tests: `tests/test_docs_live.py::Lists3c3` + `verify.py` (two checkboxes, one checked, bullets render).
