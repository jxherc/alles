# one way to write dates, and rows that act in place

## context

the oct 30 ux pass (u.04) found five date styles on one walk: tasks showed "2026-11-01" chips,
health "2026-10-30", plan's agenda header "2026-10-30", home "friday, october 30", the task
editor "2026-10-28", reminders "oct 24, 2026, 9:00 am" and money "10-29". home listed a 10:30 am
class as upcoming at 11:46 pm (u.02), overdue tasks sat between later ones (u.03), and the only
way to check off or move a task was to open it in another app (u.01). a trash icon sat on every
task row (u.10).

## decision

- every date the ui draws goes through `static/js/when.js`: today, tomorrow, yesterday; the
  weekday inside the next week ("sun"); "in 9 days" or "3 days ago" inside two weeks; then the
  short date ("nov 12", the year only when it isn't this one). times through `whenTime` in the
  owner's 12/24 hour setting, lowercase. built on `Intl.RelativeTimeFormat` and the locale
  formatters in i18n.js, so every interface language gets its own words.
- the full date is the `title` of a `<time data-when>` (hover) and replaces the short words for 3
  seconds on a half second press (touch has no hover).
- overdue leads every task list and home's schedule, as its own group with "move all to today".
- a task row acts where it is: a check (done in one tap, undo in the row), "tomorrow" on its
  right when it's due today or earlier, and everything else (other days, add subtask, delete) in
  the row's more menu (`wireActionMenu`, the ctx-menu look). delete never asks; it shows undo in
  the row for 6 seconds, the habits pattern from S5b.
- home reads the clock: what's over (an event past its end, a reminder past its time) fades
  under "earlier today", a "now" line sits before the next timed thing, and from 8 pm tomorrow
  comes first.

## not yet

the side panel for details and swipe on touch (u.01), plan's 3 tabs (u.06), numbers with change
(u.05), the app rail (u.07), mail and files dates (S6). the static lint for raw iso dates exists now: `tests/test_raw_dates_lint.py`.
