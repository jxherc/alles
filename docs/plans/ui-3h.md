# ui-3h — selection bleed → content-column constraint

The fix was to cap the **whole** `.cm-editor` to the centered 820px column (not just `.cm-content`), so
CodeMirror's selection layer is laid out inside the column and selecting/copying never spans the empty side
gutters (`static/style.css` `.wiki-live` centers; `.wiki-live .cm-editor { max-width: 820px }`). This
microversion verifies it holds: select-all in live mode and the selection rects stay within the editor's
left/right edges.

Tests: `tests/test_docs.py::SelectionColumnTests` (2) + `docs/evidence/ui-3h/verify.py` (editor capped +
centered, selection left/right edges stay within the column).
