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

---

# calendar — UI/UX polish (2026-06-18)

Re-audit evidence: `docs/evidence/calendar/` (findings.md + 3 screenshots). Wide (1280/1000) the header is
one clean baseline-aligned row. At 820 the month label + `find time`/`+ event` labels wrap and the toolbar
overflows the cog off-screen. Single UI task.

## cal-ui-1 — keep the calendar toolbar on intact, wrapping rows (no label-splitting / cog overflow)

**Change (`static/style.css`):**
- `.cal-month-title { white-space:nowrap }`.
- `#calendar-view .page-view-head { flex-wrap:wrap }` and nowrap on its `.btn` / `.cal-view-btn`.
- trim `.cal-quick` min-width (180→150) so it stops forcing the row past the viewport.
- align `.cal-sidebar` top padding to `.cal-main` so the sidebar search lines up with the weekday header.

**Verify (Playwright `pw_cal_ui1.py` @1280 + @820, ≥8 assertions, RED→GREEN, screenshots, 0 console err):**
1. `month_single_line_1280` — month label height < 30px (one line).
2. `month_single_line_820` — month label still one line at 820 (no "June"/"2026" split).
3. `findtime_single_line_820` — "find time" button height < 30px (label not wrapped).
4. `plusevent_single_line_820` — "+ event" button height < 30px.
5. `cog_in_viewport_820` — settings cog right edge ≤ viewport width (not cut off).
6. `no_control_overflow_820` — every header control's right edge ≤ viewport width.
7. `one_row_1280` — head height ≤ 56px at 1280 (single row preserved).
8. `controls_centered_1280` — visible header controls share one center-Y (spread < 6px).
9. `search_aligns_weekday` — sidebar search top within 10px of the weekday-header row top.
10. `zero_console_errors` — no console/page errors; screenshots saved.
