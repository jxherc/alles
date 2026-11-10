# rows end at one edge

amends 0064 (the phone control row, in the plan tasks part below) and keeps from 0052 the entry
row as it is.

## context

nov 10 design audit ("looks too AI"). a task row ended in a "tomorrow" text button only when the
task was due today or late, so those rows ended 84px before the rest. the due date was a tinted
chip, and every priority printed its word. home printed the same facts twice (the group, then the
row) and its two columns were a css column split that left one column empty.

## decision

- no text shortcut on only some rows. a task row ends in its more button and nothing else, so
  every row ends at the same x. today, tomorrow and next week sit in the more menu, and a swipe
  left on touch still moves a task that is due today or late to tomorrow. the plan agenda keeps
  its check on the left and loses its "tomorrow" button the same way: the row opens its details,
  which hold "tomorrow", and a swipe left does it on touch.
- the due date is plain text, no fill, no border, no radius: muted for a later day, the text
  color for today, the danger color only when overdue.
- priority shows only when it is high. medium and low print nothing on the row; they stay in
  the editor and the menu.
- the add row (`.k-entry-row`) stays as 0052 made it.
- home rows don't repeat what their group or the page says. overdue tasks sit under an "overdue"
  line and say the day once ("yesterday"). a task due today under the schedule doesn't print
  "today", an event doesn't print "calendar", a renewal or date that is today doesn't print
  "today", and a habit doesn't print "not done": its empty mark says it. what tells rows apart
  stays: the time, the day for other days, "in 4d". home's task rows lose the "tomorrow" button
  like the list's; the details and a swipe left keep it.
- a pinned app is its mark and name on one line, 44px tall. the helper line under it is gone.
- home on ipad landscape and desktop (1024px and wider) is a main column and a side column: the
  schedule takes the wide one (2fr), every other section stacks in the narrow one (1fr, 18rem
  at least) in the order set in settings > home. the sections stay direct children of
  `#today-sections`, so a phone and ipad portrait keep one column in that order. a section turned
  off leaves no hole, and with no schedule the sections take the full width. replaces the css
  columns, which left the right column holding one card.
- the "all open tasks" link is plain text like "ask aide about today"; hover underlines it.

## where

- `static/js/tasks.js` (row, swipe), `static/js/specialist_groups.js` (agenda row),
  `static/style.css` (`.task-due`, agenda row grid), `static/revamp.css` (soft due chip removed).
- home: `static/js/today.js` (rows, cards, swipe), `static/revamp.css` ("home" grid, pinned app
  tile), `static/style.css` (summary link, overdue line), `static/kokuen.css` (link hover).

## checked

webkit at ipad landscape and phone, both themes: every task row's more button ends at the same x
(1185 and 374), due is 0px border, 0px radius, transparent fill. menu "tomorrow" and a swipe left
both move the task, and a swipe left on a later task does nothing.

home, webkit at ipad landscape and phone, chromium at 1440, light and dark: main column 742px
and side 371px at 1210, 895 and 448 at 1440, the side sections start on the schedule's top line
and stack with no gap between; reordered, with the schedule off and with pinned apps off, no
hole; pinned app cards are 44px tall; the summary link has no resting underline.
