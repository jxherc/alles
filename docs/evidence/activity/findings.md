# activity — audit findings (2026-06-18)

Drove `activity.localhost:8799`. Feed + summary + filters render with real cross-app events, zero console
errors. Before/after screenshots saved.

## The imbalance (confirmed, Image #4)
- `.activity-filters { margin-left:auto }` crammed the whole filter cluster against the right edge
  (measured x=353→1247) while the "activity" title sat alone far-left with a huge dead gap.
- `.act-search { margin-left:auto }` was a redundant *second* auto-margin, and the search was 200px (over-
  sized vs the other controls), pushed to x=1047.
- `.act-sum-busy { margin-left:auto }` isolated "busiest" alone at the far right of the summary (x=1174).

## Fix (`activity-ui-1`, style.css)
- `#activity-view .page-view-head { flex-wrap:wrap }` + `.activity-filters { flex-basis:100%; margin-top }`
  → the filter bar drops to its own left-aligned row beneath the title (no more right-cram / dead gap).
- `.act-search`: keep a single `margin-left:auto` (right-aligns it on the filter row) and narrow 200→160.
- `.act-sum-busy`: drop `margin-left:auto` so the summary reads left-to-right
  (`N events · per-source chips · busiest …`) with nothing stranded right.

**Verify (`pw_activity_balance.py`, 7 assertions, screenshot, 0 console err):** filters_below_title,
filters_left_aligned (x<60), search_narrowed (≤170), search_right_of_filters_same_row, summary_busy_flows_left,
chips_one_baseline, zero_console_errors.
