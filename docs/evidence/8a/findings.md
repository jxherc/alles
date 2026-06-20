# 8a — calendar: views & scheduling — findings

Audited by running an isolated server (`ALLES_DATA=/tmp/alles8a PORT=8864 AUTH_ENABLED=false python app.py`)
with curl + Playwright over the calendar.

## Audit — state before the build
- Backend had `/calendar` list, tasks overlay, duplicate, `/calendar/free`, `/calendar/agenda` (existed,
  **no UI**), quick, CRUD, `export.ics`, `import` (pasted ICS only — **no URL subscribe**).
- Frontend `render()` only handled month / week / day. **No agenda or year view**, no working-hours
  shading, no secondary timezone, no ICS-URL subscriptions.
- Creating an event with a start but no end left `end_dt` null (**no default duration**).
- `services/ics.py` has `parse_ics` (reused for subscriptions). `SettingsPatch` whitelists keys — new
  ones had to be added.

## Built (gaps only)
- **8a-1 ICS URL subscriptions** (`core/database.py`, `routes/calendar.py`, `app.py`):
  `CalendarSubscription` model + `CalendarEvent.subscription_id`; `refresh_subscription` full-replaces a
  feed's events; `fetch_ics` isolated for testing; GET/POST/DELETE + `/refresh`; hourly `ics_subscriptions`
  job. webcal:// normalized to https.
- **8a-2 default duration** (`routes/calendar.py`, `cal_default_duration_min` setting): create + quick-add
  set `end = start + default` when not all-day and no end given; NL "for 2h" still wins.
- **8a-3 frontend** (`static/js/calendar.js`, `appsettings.js`, `index.html`, `style.css`,
  `routes/settings.py`): agenda view (from `/calendar/agenda`), year view (12 mini-months, today ringed,
  event dots), working-hours shading in the week/day grid (`cal_work_start`/`cal_work_end`), a secondary
  timezone world clock (`cal_secondary_tz`), and an ICS-feed subscription panel in the sidebar (add/list/
  delete). New settings exposed in the calendar cog. Stamps → v64 / SW v38.

## Exercised with real input
- Subscriptions: create → refresh imports parsed events → re-refresh replaces (no dupes) → changed feed
  reflects → delete removes sub + events; last_synced/last_status set; fetch error → status "error" (unit
  `test_calendar_subscriptions`, 10/10).
- Default duration: create no-end → +60; explicit end kept; all-day none; custom 30/45; quick no-duration →
  +60; "for 2h" kept; invalid → 60 (unit `test_calendar_duration`, 9/9).
- UI (Playwright `pw_calendar_views_8a`, 8/8): agenda + year render, view buttons present, week grid shows
  off-hours shading, London world clock shows, an ICS feed subscribed via the two-step prompt and listed.

## Bugs / imperfections found
- **Real fix:** `SettingsPatch` had to gain `cal_default_duration_min`, `cal_work_start`, `cal_work_end`,
  `cal_secondary_tz` (same class of bug as 7c's watch-folder — un-whitelisted keys are silently dropped).
- **App bugs: none** beyond that. Pre-existing `I001` import-sort on `routes/settings.py` left out of scope
  (present on HEAD).
- Screenshots: `agenda.png`, `year.png`, `feeds.png`.

## Evidence
`pw_calendar_views_8a.txt` (8/8), `agenda.png`, `year.png`, `feeds.png`. Unit: 19 tests across two files.
