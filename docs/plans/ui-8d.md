# ui-8d — Watchtower: explain + real toggle + layout

Watchtower had no explanation, a flat layout, and its button just re-rendered the panel instead of
toggling. Fixed all three.

`static/js/vault.js` `showWatchtower`:
- **Real toggle** via a `_wtOpen` flag: re-clicking the watchtower button (or "back") hides the panel and
  returns to the entry list; the button gets `.active` while open (and is cleared on lock).
- **Explainer**: a one-line intro of what Watchtower does, plus a short description under each section
  (breached / reused / weak).
- Unified the ✓/← glyphs to the icon set.

`static/style.css`: sections are bordered cards with descriptions; `#vault-watchtower-btn.active` shows
the accent indication.

Tests: `tests/test_vault_watchtower_ui.py` (6 source-contract) + `docs/evidence/ui-8d/verify.py` (live:
open → button active + intro + 3 sections each with a description; re-click hides it and clears active).
