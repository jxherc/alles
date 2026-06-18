# Phase 3 — calendar (`calendar.js` + `routes/calendar.py` + `services/event_nl.py` + `services/recur.py`)

## Audit (2026-06-18)

Target: Google Calendar. Verified working (DO NOT rebuild): month/week/day/agenda/year views, full
recurrence (daily/weekly/monthly/yearly + interval + byday + count + until + per-occurrence exceptions,
expanded by `recur.py`), reminders, guests, all-day, drag/resize, per-event colors, multiple calendars
(layers/visibility), CalDAV sync, ICS import/export, and a natural-language `/calendar/quick` endpoint
(`event_nl.parse_event`). UI loads with 0 console errors.

Confirmed gaps vs Google Calendar: **tasks are not shown on the calendar** (the tasks app has due dates;
Google overlays Tasks); the **NL quick-add endpoint is never surfaced in the UI** (0 references in
calendar.js) and `event_nl` always makes events 1h (no duration parsing); **no duplicate-event**; **no
find-a-time / free-slot** helper.

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **cal-1 Tasks on the calendar.** GET `/api/calendar/tasks?start=&end=` → tasks with due dates as
  calendar items; overlay them on month/agenda cells, click to toggle done. *Why: Google shows Tasks on
  the calendar; here the two apps are siloed.*
- **cal-2 Quick-add in the UI + duration parsing.** Surface `/calendar/quick` with a quick-add box in the
  calendar header; extend `event_nl.parse_event` to honor "for 90 min" / "for 2 hours" / "1-2pm" instead
  of always 1h. *Why: the NL backend exists but is unreachable, and fixed 1h durations are wrong.*
- **cal-3 Duplicate event + find-a-time.** POST `/api/calendar/{eid}/duplicate` (clone an event) and GET
  `/api/calendar/free?date=&minutes=` (open slots that day avoiding existing events). UI: a "duplicate"
  action + a "find a time" helper. *Why: both are standard Google Calendar scheduling tools; neither
  exists.*

## Out of scope

Per-event time zones / world clock (niche for single-user self-host), appointment-scheduling pages,
free-busy across external calendars. Revisit if needed.
