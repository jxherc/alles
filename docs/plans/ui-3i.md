# ui-3i — custom right-click context menu (Word-like)

The docs editor (live + source) now shows a **custom** menu on right-click instead of the native one
(`openDocsContextMenu` in `static/js/vaultmd.js`, reusing the app `.ctx-menu` chrome):

- **cut / copy / paste** (clipboard; paste via `navigator.clipboard`)
- **format**: bold / italic / code / link (the existing `wrapSel` / `insertLink`)
- **headings**: heading 1 / heading 2 (`toggleLinePrefix`)
- **AI on the selection**: rewrite / summarize / fix-grammar → new backend `POST /api/vault-md/ai-snippet`
  (`routes/vault_md.py`) which runs `simple_complete` over just the selected text and replaces it in place
  (distinct from `ai-edit`, which rewrites the whole doc). Disabled items grey out when there's no selection.

Tests: `tests/test_docs_ai_snippet.py` (6, backend: no-endpoint/empty 400, rewrite returns text, strips
fences, action→prompt mapping, unknown→rewrite) + `tests/test_docs.py::ContextMenuTests` (4) +
`docs/evidence/ui-3i/verify.py` (menu opens with all items, bold wraps the selection, closes after action,
0 console errors) + `menu.png`.
