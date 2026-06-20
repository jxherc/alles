# UI/UX polish run — final regression (2026-06-18)

Branch `autorun`. Isolated server (`:8799`, `ALLES_DATA`), real seeded data across every app.

## Scope delivered (12 tasks, phases 16–26 + docs follow-up)
1. **files** (`files-ui-1`) — merged breadcrumb + sort into one aligned row; dropped the redundant root crumb.
2. **docs** (`docs-ui-1`) — per-doc `?doc=` URL routing (refresh/deep-link restore) + editor-head left-align.
3. **calendar** (`cal-ui-1`) — toolbar stays on intact wrapping rows (nowrap month/buttons, no cog overflow).
4. **secrets** (`secrets-cat-1`) — per-category field schema (settings store + category-driven form + field picker).
5. **subscriptions** — `subs-fix-1` sane mark-paid (due-guard, no infinite advance) + payment log + undo;
   `subs-fix-2` price history + hike badge; `subs-fix-3` cash-flow forecast; `subs-fix-4` duplicate detection.
6. **days** (`days-ui-1`) — edit card stays in its section (no jump to the first grid).
7. **export/import** (`io-ui-1`) — unified `<a>` export links with `<button>` imports (no underline, identical size).
8. **activity** (`activity-ui-1`) — filters on their own left row, summary reads left-to-right (no stranded item).
9. **journal** (`journal-ui-1`) — fixed a merged-selector flex bug → centered writing column + **vertical** full-year heatmap.
10. **system** (`system-ui-1`) — flush bottom edge (proc column stretches to match the left graph stack).
- **docs follow-up** (user request mid-run): `docs-page-1` center the editor as a Google-Docs page + fix the
  full-bleed text selection; `docs-home-1` Google-Docs-style docs home (card gallery + search + "all docs" home button).

## Regression layers (all clean)
1. **Full unittest suite** — 1012 tests pass (1 skipped). `final-unittest.log`.
2. **Broad load sweep** (`pw_sweep.py`) — all 15 subdomains load, **zero** real console errors. `final-sweep.log`.
3. **Deep interaction sweep** — re-ran all 13 per-module Playwright verifies; every assertion passes. `final-deep.log`.
   (`pw_docs_ui1`'s `head_buttons_grouped` assertion was updated to measure the action cluster after
   `docs-home-1` added the left "all docs" nav button — the head layout itself is correct, screenshot-verified.)

## Gate
`python check_progress.py` → **exit 0** — 71/71 tasks done. Every per-module change has audit evidence,
TDD (≥8 cases for backend-logic tasks; ≥7 Playwright structural assertions for UI tasks), a per-task commit
(author jxherc), and a per-module sweep. `system` behavior preserved (CSS-only; canvases untouched).
