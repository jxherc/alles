# ui-3o — split view redesign

The split view was a fixed 42% pane that silently loaded the last-opened other doc (and its CSS selector
`.wiki-view.split-on` never even matched `#wiki-view`, so display was forced from JS). Rebuilt
(`static/js/vaultmd.js`, `static/index.html`, `static/style.css`):

- **Pick-a-doc**: turning split on opens `openSplitPicker()` — a popup with an **open docs / all docs** scope
  toggle and the matching doc list; the chosen doc loads on the right. A "change" button in the pane header
  reopens the picker.
- **~50/50** by default (`#wiki-view.split-on .wiki-split-pane { flex: 0 0 var(--split,50%) }`).
- **Draggable divider** (`#wiki-split-divider`, `_initSplitDivider` pointer drag) re-proportions the two
  sides, clamped 20–80%.

Tests: `tests/test_docs.py::SplitViewTests` (4) + `docs/evidence/ui-3o/verify.py` (picker opens with scope
tabs + doc list, pick loads ~half-width pane, divider shows + dragging widens the pane, 0 errors) + `split.png`.
