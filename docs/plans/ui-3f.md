# ui-3f — tables: live render + restyle

Delivered by the ui-3c block-widget engine. GFM pipe tables render in live mode as a real `<table class="cm-table">`
(built from the source rows by `TableWidget`), revealing raw `| col |` only when the cursor is inside the
table. Styling (`static/style.css` `.cm-table`): `border-collapse`, 1px `var(--faint)` cell borders,
`.4rem/.6rem` padding, header cells `font-weight:600` on a `var(--panel)` fill. The toolbar **table** button
still inserts a starter table, which then renders the same way.

Tests: `tests/test_docs.py::TableStyleTests` (4) + `docs/evidence/ui-3f/verify.py` (renders as cm-table,
2 header cells, 2 body rows, bordered, header emphasised + filled, no console errors).
