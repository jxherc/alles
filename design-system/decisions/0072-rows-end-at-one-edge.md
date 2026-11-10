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

## where

- `static/js/tasks.js` (row, swipe), `static/js/specialist_groups.js` (agenda row),
  `static/style.css` (`.task-due`, agenda row grid), `static/revamp.css` (soft due chip removed).

## checked

webkit at ipad landscape and phone, both themes: every task row's more button ends at the same x
(1185 and 374), due is 0px border, 0px radius, transparent fill. menu "tomorrow" and a swipe left
both move the task, and a swipe left on a later task does nothing.
