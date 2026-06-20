# ui-3r — outline clarity

The outline already parsed `#…######` headings; this makes it read clearly (`static/js/vaultmd.js`
`updateOutline`, CSS):

- **Level emphasis**: `.lvl1` headings read as headings (full text colour, weight 500), `.lvl2` recede,
  `.lvl3+` get smaller + a left guide-rail and deeper indent (`0.7 + (level-1)*0.85rem`).
- Header now shows the count ("outline · N headings").
- **Empty explainer** is actually helpful: "no headings yet — start a line with `#` (or `##`, `###`…) and it
  shows up here as a jump-to link" (was a bare "no headings"). Clicking an item still jumps the editor +
  preview to that heading.

Tests: `tests/test_docs.py::OutlineClarityTests` (4) + `docs/evidence/ui-3r/verify.py` (empty doc shows the
explainer; a heading-rich doc lists the headings with the count, deeper ones indented more, top-level
emphasised, clicking jumps; 0 errors) + `outline.png`.
