# ui-3q — recently-opened tabs redesign

Browser/Helium-style strip (`static/style.css`, `static/js/vaultmd.js`):

- The **open** tab gets a squircle outline (`border-radius:7px`, accent border + faint accent fill); inactive
  tabs are plain text (`border:1px solid transparent`) with a **hairline separator** only between two
  adjacent inactive tabs (`.wiki-tab:not(.active) + .wiki-tab:not(.active)::before`). Outline-on-open instead
  of the old full border-swap.
- Removed the **dead left gutter** (`padding: 0 clamp(1.5rem,12%,7rem)` → `0.18rem 0.8rem 0`).
- The close × only appears on hover / the active tab.
- **Deleted docs leave the strip**: `deleteCurrent` now routes through `closeTab(p)`, and the tree-row delete
  filters `_tabs` (a deleted folder drops every doc under it).

Tests: `tests/test_docs.py::TabsRedesignTests` (4) + `docs/evidence/ui-3q/verify.py` (open tab squircle +
accent outline, inactive plain, small left padding, deleting a doc removes it from tabs while the other
survives, 0 errors) + `tabs.png`.
