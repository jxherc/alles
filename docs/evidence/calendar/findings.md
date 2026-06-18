# calendar — audit findings (2026-06-18)

Drove `calendar.localhost:8799` in Playwright at 1280 / 1000 / 820 px. Screenshots: head-1280, head-1000,
head-820. Console log in `audit.json`. Month renders with real events (team lunch, 1:1 with Sam, Review
PR, Dentist, Pay rent) + a task overlay; mini-calendar + "my calendars" sidebar render. Zero console errors.

## What was exercised
- month grid renders real events + task chips; nav (‹ today ›), view toggle (month/week/day), quick-add,
  export/import, find-time, sync, +event, settings cog all present; sidebar search + mini-cal + calendars list.

## Header balance — confirmed at narrower widths
- At **1280 / 1000** the toolbar is a single 65px row, every control vertically centered on one baseline
  (center-Y identical once the hidden file-input is excluded). Looks fine wide.
- At **820** (a normal split-window width) it breaks (`head-820.png`):
  - `cal-month-title` "June 2026" **wraps to two lines** ("June" / "2026") — no `white-space:nowrap`.
  - `find time` and `+ event` buttons **wrap their labels** (`.btn` has no nowrap).
  - the row does **not** wrap as a unit, so `+ event` and the **settings cog overflow off the right edge**
    (cog cut off / unreachable) — the head has no `flex-wrap`.
  This ragged wrap + overflow is the "calendar… not in the same line" complaint.
- Minor: sidebar `search events…` top sits ~10px off the grid's weekday-header row.
- Minor (handled in module 7): `export` is an `<a>` and renders underlined next to the plain `import`.

## Fix (one task → `cal-ui-1`)
- `.cal-month-title { white-space:nowrap }` — never split the month label.
- `#calendar-view .page-view-head { flex-wrap:wrap }` + nowrap on its `.btn`/`.cal-view-btn` — labels stay
  intact and the toolbar wraps into clean rows instead of pushing the cog off-screen.
- trim `.cal-quick` min-width so it stops forcing overflow.
- align `.cal-sidebar` top padding with `.cal-main` so the sidebar search lines up with the weekday header.

Verified via Playwright at 1280 + 820 (≥8 assertions, RED→GREEN) + screenshots, zero console errors.
