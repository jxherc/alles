# journal — audit findings (2026-06-18)

Drove `journal.localhost:8799`. Editor + mood picker + heatmap + reflect all work, zero console errors.
Before/after screenshots saved.

## Problems (confirmed, user: "ui is fucked up … why is the thing on the left most side")
1. **Editor jammed left + dead right half.** A CSS authoring bug merged the intended
   `#journal-view .page-view-head/.page-view-body { max-width:none }` rule into `.jrnl-wrap` (a comment
   swallowed the rule body), so the journal **body became `display:flex`** and the editor never filled the
   width — measured `.jrnl-main` width = 426px starting at x=0, with the whole wrap ending at x≈698 and the
   right ~580px of the viewport empty.
2. **Year heatmap clipped.** `.jrnl-heatmap` was a horizontal row of 53 week-columns (scrollWidth 581) inside
   the 250px sidebar with `overflow-x:auto` → only ~22 of 53 weeks visible without scrolling.

## Fix (`journal-ui-1`)
- `static/style.css`: split the broken selector — `#journal-view .page-view-head, .page-view-body { max-width:none }`
  as its own rule (body is no longer a flex container); `.jrnl-main { max-width:760px; margin:0 auto }`
  (comfortable centered writing column); `.jrnl-side` 250→280px.
- **Heatmap → vertical**: `static/js/journal.js` emits week **rows** (`.jrnl-hrow`) instead of columns, and
  `.jrnl-heatmap { flex-direction:column }` (+ `.jrnl-hrow{display:flex}`, no `overflow-x`). Weeks stack
  top→bottom, weekday columns — the **full year** fits the sidebar with no horizontal scroll.

**Verify (`pw_journal_layout.py`, 10 assertions, screenshot, 0 console err):** heatmap_vertical (taller than
wide), heatmap_no_hscroll, heatmap_full_year (≥365 cells), weeks_as_rows (≥52), no_old_columns,
editor_constrained (≤780) + editor_centered (x>60), side_on_right (≥260px), heatmap_fits_sidebar,
zero_console_errors.
