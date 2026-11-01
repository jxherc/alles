# one entry row and one date field

## context

the add rows looked like five different designs (28.03, 28.04, 28.18, 28.19). tasks, contacts,
countdown and subscriptions shared one rule with `6px 6px 6px 8px` padding, so add sat 6px from
the edges and was crammed into the corner. countdown and subscriptions then put an inline 8px gap
between their fields, so their fields floated apart while the others sat flush with a divider.
reminders had its own copy of the rule with square fields and its own phone grid. the task editor's
due date was a plain text box that wanted YYYY-MM-DD, and a task's time (S1 added `due_time`) had
no way in from the screen.

## decision

- one entry row, `.k-entry-row` in `revamp.css`: a 12px panel with 4px of padding on every side.
  fields inside are bare (44px, 12px text inset, 8px corners for their hover fill) and split by a
  1px divider. the button is 44px tall with an 8px radius (12 minus 4), so it sits 4px from the
  top, end and bottom, and 8px after the last field (`--k-control-gap`). on a phone a row with two
  or more fields stacks them under quiet rules and add takes the last line, 8px under them.
- tasks, contacts, countdown, subscriptions and reminders use it. no inline gaps or widths on the
  fields; subscriptions keeps its grid for placement only.
- one date field: `.date-input` with `datepick.js`, never native. three types: `date`,
  `datetime` and `due`, a date with an optional time. `due` writes `YYYY-MM-DD` until "add time"
  is pressed in the panel, then `YYYY-MM-DDTHH:MM`; "no time" in the panel footer takes it away
  and keeps the day. `joinDue` and `splitDue` turn it into a task's `due_date` and `due_time`.
- the panel's hour, minute and year boxes are the one field (0049): filled, their own ring, focus
  recolors it. no line under the digits.
- a timed task shows its time on its row, in the calendar and in the agenda, and goes overdue at
  that time (the server's `overdue` flag).

## where

- `static/revamp.css` "one entry row", `static/index.html` add rows, `static/js/datepick.js`,
  `static/js/tasks.js` (editor and add row), `static/js/capture.js`, `static/js/calendar.js`,
  `routes/tasks.py` (`/api/tasks/quick` takes the add row's `due`).

## checked

measured in webkit at 1280, 1180, 820 and 390 wide: add 4px from the top, end and bottom of every
row, 8px radius, 8px after the last field, nothing outside the row.
