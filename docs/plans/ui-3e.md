# ui-3e — links: hide URL + custom (non-native) UI

URL-hiding + theme-coloured anchor rendering landed in ui-3c (only the link text shows; the `](url)` is
hidden off the cursor line; editing the text no longer shows both). This adds the **interaction**:

- `static/js/vaultmd.js`: on `#wiki-live`, a capture-phase `mousedown` — **⌘/ctrl-click** on a rendered
  `a.cm-link` (or `.wikilink`) opens it (external → new tab; wiki → `openByName`); a plain single click is
  left to CM so the line reveals raw for editing (Obsidian behaviour).
- **Hover tooltip** (`showUrlTip`/`#wiki-url-tip`, `.wiki-url-tip`) shows the real destination + a
  "⌘-click to open" hint — no native blue, no native click affordance.

Tests: `tests/test_docs.py::LinkInteractionTests` (4) + `docs/evidence/ui-3e/verify.py` (anchor, accent
colour not native blue, hover tooltip shows destination, ⌘-click opens href, no console errors).
