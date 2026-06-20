# 11a — macOS / Mac mini integration seams

## What this microversion is
ROADMAP 11a: native macOS integration points for the Mac mini deploy target —
Keychain backing, EventKit (Calendar/Reminders) export, iCloud Drive watch-folder,
and a settings status card that honestly reports what's reachable on the host.

## Audit (by running)
- Booted isolated server `ALLES_DATA=.tmp_11a PORT=8878 AUTH_ENABLED=false`.
- `GET /api/macos/status` → `{"platform":"win32","available":false,"keychain":false,
  "eventkit":false,"photokit":false,"icloud":false}` — correct: this is a Windows box,
  every native seam reports unavailable (fails loud, doesn't pretend).
- Settings → tools pane renders the "macOS integration" status card (`#macos-status`),
  showing "unavailable" + the Mac-mini note. Screenshot: `macos-status.png`.

## Built / fixed
- `services/macos_bridge.py`: `icloud_drive_dir()`, `capabilities()`, `_parse_ical_output()`
  (bulleted icalBuddy output → structured rows); export_calendar/reminders return parsed rows.
- `routes/macos.py`: `GET /api/macos/status`, `POST /api/macos/calendar`, `POST /api/macos/reminders`
  (503 off-darwin). Mounted in app.py.
- `static/js/settings.js` `loadMacosStatus()` + tools-pane card; style `.macos-row`/`.macos-avail`.
- Cache stamps bumped v76 / SW v50.

## Tests
- Backend: `tests/test_macos.py` — status shape, off-darwin 503s, ical parser. (in full suite)
- UI: `tests/pw_macos_11a.py` — 8/8 assertions: macos_card_present, card_header_present,
  status_fetched, status_endpoint_reachable, available_matches_platform,
  shows_unavailable_off_darwin, mentions_mac_mini, zero_console_errors.

## Regression
`tests/pw_regression.py 8878 docs/evidence/11a/regression` — all 14 subdomain views render
clean (aide, apex, activity, calendar, days, docs, files, gallery, journal, mail, money,
subs, system, tasks). Screenshots in `regression/`.

## Suite
`python -m unittest discover -s tests` → Ran 1690 tests, OK (skipped=1).

## Verdict
11a done end-to-end. Honest unavailable-reporting on Windows; the seams are wired for the Mac.
