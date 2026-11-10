# calendar on a phone, the view dropdown, chips a row gap apart

amends 0050 (the calendar's view switch is a dropdown), 0051 (more stacks join the row gap) and
0056 (reminders are pick several).

## context

the nov 10 audit of the calendar found, on an ipad and a phone:

- chips in a month cell, the all-day stack in the week view and the sidebar's calendar rows touched
  each other (0 to 2px), and the switch beside a calendar's name touched the name.
- a one hour event block was 42px tall, under a 44px target (the tap area behind it hid this from
  the old measure).
- the five views were a row of five buttons, which 0050 says is a dropdown.
- on a phone the toolbar was five stacked rows and the month grid started at y=370, and a month cell
  was about 54px wide, so a chip read "Mom 's..." and the cell showed no more than a count.
- the event editor put "calendar" beside its dropdown while every other label sits on top, kept
  reminders as six bare text chips, left "find free time" 3px under the start field, had no visible
  way to leave but a "back" at the very bottom, and drew the title with a gold underline when focused.

## decision

- a stack of chips is one stack: `.cal-cell-events`, `.cal-tg-allday` and `#cal-cals-list` use
  `gap: var(--k-row-gap)`, and the chips start a row gap under the date strip. a calendar row's
  switch and name sit `--k-control-gap` apart. a month cell is at least tall enough for the date
  strip, a row gap and one chip, so the day's first event never hides behind "+N".
- the week and day grid keep an hour 48px tall and a block ends 4px (`--k-row-gap`) before its hour,
  so a one hour event is a 44px target with a gap to the next one. a block under an hour keeps its
  real length (its tap area still reaches 44px).
- the view switch is the kokuen dropdown (`#cal-view`, `.custom-select`), on every size. the saved
  view still comes back after a reload.
- phone toolbar, 760px and narrower: row one is previous, the month, next and today at the end. row
  two is the view dropdown, tools, a 44px search button (aria-label "search events") and "+ event" at
  the end. at 720px and narrower the search field stays shut until the button opens it as a row of its
  own with focus in it; escape or an emptied field shuts it again and returns focus to the button.
  wider screens keep the field in the sidebar. the head's top padding is a control gap here, so the
  grid starts at y=220, not 370.
- phone month, 700px and narrower: a day is its number and up to 3 dots (6px) in its calendars'
  colors, no chip text and no "+N". the whole cell is one `.cal-day-open` button that opens the day,
  and its aria-label names the count ("tuesday, nov 10, 7 events"). the dots are not targets. wider
  screens keep text chips.
- the event editor follows the shared rules: the calendar label sits above its dropdown, reminders
  are the pick several dropdown (0056) with the picks as text in the trigger, find free time is a
  grid item under the start field on the grid's left edge (a control gap down; after the end field in
  one column), the footer's back is a cancel button, and the title is a normal field with the
  0049 focus ring.

## checks

- `tests/pw_calendar_toolbar.py`: the view dropdown picks every view with keys and clicks and keeps
  focus; on a phone the search button is 44px, the field is hidden, the grid starts at or above 230px,
  rows start on the 16px gutter, and the field opens and closes with the button and escape.
- `tests/pw_calendar_workflows.py`, `pw_calendar_multiday.py`, `pw_calendar_birthdays.py`: a phone
  month shows dots and a day button with the event count; events open from the day.
- `tests/pw_calendar_time_grid.py`: a one hour block is 48px minus 4px, blocks stay 4px apart.
- `tests/test_calendar_seg.py`: the five views are the dropdown's options, no segmented css left.
