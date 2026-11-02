# act where you are: row actions, swipe and a details panel

## context

u.01 (oct 30 ux pass): checking a task off from plan's agenda took 3 taps (open the row, which
jumped to the tasks tab and its editor, close it, check), a habit on home loaded the whole health
app, and a task's details only lived in another app. 0063 put a check and "tomorrow" on home's
task rows; the agenda and habits still jumped away.

## decision

- one shared module, `static/js/act_row.js`, holds what a row can do in place: complete a task,
  move it to tomorrow, check a habit for today, swipe, and the details panel. home and the agenda
  use it; the task list keeps its own rows (0063) with the same two actions.
- a task row: the check on the left (44px target, 16px circle, the overdue colour when late),
  "tomorrow" on the right for anything due today or earlier, the title in the middle opens details.
- touch: a horizontal swipe past 72px, right is done, left is tomorrow. a mostly vertical drag is
  left to the page (`touch-action: pan-y`). mouse and pen use the two buttons, which do the same.
- details: a floating side panel on the right (the ask aide panel's layer: raised, one shadow,
  large radius), a bottom sheet under 761px. title, when, notes, then done, tomorrow and edit.
  edit goes on to the full editor. escape and close put focus back on the row; leaving the app
  closes it. not modal: the page behind stays usable.
- a plain check habit on home gets the same check with undo in the row. a habit with its own log
  (gym, water, sleep) still opens in health, where its logger lives.

## not done here

events in the details panel, a habit's logger inside the panel, and habit rows in the agenda.

## measured

taps in webkit at ipad landscape and phone (`.agent/evidence/u.01/taps-*.json`): check a task off
from the agenda 3 to 1, snooze an overdue task from home 1 to 1, log a habit from home 2 (and a
full page load) to 1.
