# ui-3c-2 — live preview: block widgets

`WidgetType` replace-decorations in `.cmbuild/cm-entry.js`, provided from a `StateField` (block widgets
can't come from a ViewPlugin in CM6). Each reveals to raw markdown when the cursor is on its line(s).

- **Image** `![alt](url)` (lezer `Image`) and `![[file]]` embeds (regex; image ext only) → real `<img>`;
  vault assets resolve through `/api/vault-md/raw?path=`.
- **Table** (GFM `Table`) → real `<table>` built from the source rows.
- **Callout** `> [!type] title` (Blockquote whose first line matches) → styled callout block (type-coloured).
- **Quote** (plain Blockquote) → left-bar line style, `>` marker hidden off-line.
- **HR** `---` → `<hr>`.

Tests: `tests/test_docs_live.py::BlockWidgets3c2` + `verify.py` (table/callout/hr/two-images/raw-route render).
