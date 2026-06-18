# Phase 11 — activity (`activity.js` + `routes/timeline.py`)

## Audit (2026-06-18)

Drove activity.localhost with real cross-app data (80 events: agent/doc/money/task/journal/photo) —
0 console errors. It's a read-time aggregator over every app's own tables (no event table to backfill).

Verified working (DO NOT rebuild): reverse-chron feed grouped by day; 9 source filters (toggle, persisted
to localStorage); range filter 7d/30d/90d/1y; recurrence-aware calendar expansion; click a row to jump to
its app; pulls from journal/tasks/calendar/money/mail/photos/docs/agent/subs.

Genuine, sensible gaps (it's a small app — two focused enhancements, no rebuild):

1. **No search.** With a busy feed there's no way to find "what did I do about X" — you can only toggle
   whole sources. A text filter over title/subtitle is the obvious missing control.
2. **No at-a-glance summary.** The feed answers "what, in order" but not "how much of each / when was I
   busiest" over the window. A per-source count + busiest-day summary is genuinely useful.
3. **No URL state.** The range and hidden-source filters aren't in the URL, so a refresh / shared link
   doesn't restore the view — violates the global routing rule.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **activity-1 Timeline search + URL state.** Add `q` to GET `/api/timeline` — case-insensitive filter
  over each event's title/subtitle, applied after aggregation, before the limit. UI: a search box in the
  filter bar; reflect the range (`?days=`) and hidden sources (`?hide=a,b`) in the URL so refresh /
  deep-link restores the exact view. *Why: the one obvious missing control on a feed, + the global
  routing rule.*
- **activity-2 Activity summary.** GET `/api/timeline/summary?days=&types=` → per-source counts (desc),
  total events, and the busiest day (date + count) over the window; a compact summary strip above the
  feed. *Why: "how much of each, and when was I busiest" isn't answerable today.*

## Out of scope

A real write-time event table (the read-time aggregator is correct-by-construction and the explicit
design), notifications/digests, cross-device sync.


---

# activity — UI/UX polish (2026-06-18)

Evidence: `docs/evidence/activity/` (findings + before/after).

## activity-ui-1 — rebalance filters + summary
Filters were crammed right (double `margin-left:auto`), 200px search oversized, "busiest" isolated far
right. Fix (`static/style.css`): filter bar on its own left-aligned row under the title
(`#activity-view .page-view-head{flex-wrap}` + `.activity-filters{flex-basis:100