# ui-3l — history popup spacing / redesign

The version-history panel was built from cramped inline-styled rows. Rebuilt it with real classes +
spacing (`static/js/vaultmd.js` `loadHistory` / `_renderDiff`, CSS in `static/style.css`):

- `#wiki-history` widened to 290px with `0.7rem 0.8rem` padding and a "VERSION HISTORY" label.
- Each `.wiki-rev-row` is a flex row: `when` + `size` left, `diff` / `restore` pushed right
  (`.wiki-rev-btn:nth-of-type(1){margin-left:auto}`), divider between rows.
- The unified diff renders in a padded, readable `.wiki-rev-diff-pre` (add=green / remove=red / hunk=accent).

Tests: `tests/test_docs.py::HistoryPanelTests` (4) + `docs/evidence/ui-3l/verify.py` (panel shown + padded +
roomy, label, ≥1 row with timestamp + 2 buttons, diff renders in a block, 0 errors) + `history.png`.
