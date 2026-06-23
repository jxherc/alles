# stage 4a - calendar / contacts depth - audit findings (2026-06-23)

## current state
- `Contact` has fields (name/email/company/birthday/...) but NO relationship graph: you can't record
  that two contacts are spouses, colleagues, or that one reports to another. so "who's related to X?"
  and smart-invite ("inviting Ann? her manager Bob is also relevant") are impossible.
- `CalendarEvent` has start_dt/end_dt but NOTHING detects conflicts: two overlapping timed events both
  just show up; there's no overlap flag and no free-slot/scheduling advisor.

## scope (this stage - highest-value testable cores of a broad bullet)
1. contact relationship graph: typed edges + neighbor queries + reciprocal links.
2. calendar conflict detection + a free-slot scheduling advisor.
DEFERRED (noted): iCal two-way sync (export+import already exist one-way), multi-tz UI, CRM comms
history - frontend/sync-heavy, separate follow-ons.

## fix
- `ContactLink` model (new table -> create_all): from_id, to_id, kind.
- `services/contacts_graph.py`: `link` (with reciprocal inverse-kind edge), `unlink`, `neighbors`
  (optional kind filter), `related_for_invite` (people linked to the invitees). inverse map covers
  spouse/parent-child/manager-report/sibling/friend/colleague.
- `services/cal_conflict.py`: `conflicts(events)` (overlapping timed pairs, all-day ignored),
  `free_slots(events, day_start, day_end, duration_min)` (gaps a new event fits).
- routes: contact link CRUD + /contacts/{id}/related; calendar /conflicts + /free-slots.

tested: link creates reciprocal, inverse-kind, neighbors + kind filter, unlink, invite suggestions,
self/dup guard; conflict overlap detect, touching-not-overlap, all-day ignored, free-slot gaps, full-day.
