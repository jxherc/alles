# 0064 plan's three tabs and the app rail

date: 2026-11-01. bullets u.06 and u.07 (oct 30 ux pass).

## plan has three tabs

plan showed 7 tabs for 2 things: agenda, week, task board, calendar, tasks, reminders and
countdowns. now it has today (the agenda, its next seven days inside), calendar (day, week and
month were already inside it) and tasks. under tasks, two pill switches pick what it lists
(tasks, reminders, countdowns) and how (list or board, tasks only). the choice rule (0050): 3 and
2 options, so pill switches. the tasks screen's own 5 views (all, today, upcoming, someday,
history) are one dropdown.

the sections stay as they were inside `specialist_groups.js` (`groupTabFor` maps them onto the 3
tabs), so every `?view=` link (plan-week, plan-board, reminders, days) still opens its view.

## the app rail

ipad landscape and desktop (1024px and wider) get a 72px rail at the left of the shell: home,
aide, the owner's pinned apps (home's pinned apps list) and "more" at the bottom, which opens the
app sheet. a phone (700px and narrower) gets a bottom bar of 5: home, aide, the first 2 pinned
apps and more. ipad portrait keeps the app name button. labels are role 13, every item a 44px
target or more, the open app marked with `aria-current="page"` and weight, no fill.

on a phone every screen's height is `--k-shell-height` (100dvh less the bar), so composers and
entry rows end above the bar.

amended nov 2 (the last gates): the first bar sat at z-index 200 over every floating layer and
over what the page pins to the screen's bottom, so it covered the files transfers and their
"start", andromeda's idle "settings", and the lower items of aide's actions menu at 200% zoom;
its top line also stacked 6px under a server log row's divider. now:
- `--k-bar-h` is the bar's height on a phone (0 elsewhere) and `--k-shell-height` is built from
  it.
- the bar sits at z-index 20: over the page, under every menu, drawer, sheet and dialog (25 and
  up).
- what's pinned to the bottom edge (toasts, the sync badge, mail's undo, andromeda's idle footer,
  the ongoing call, the speaking wave) rides `--k-bar-h` up in one rule; the files transfers dock
  adds it to its own bottom.
- the bar parts from the page by the panel fill, not a top line, so a list's divider can't
  stack on it.
- `tests/pw_kit_rules.py` checks `bar-covers`: no control whose visible middle the bar covers.

the app sheet keeps working and drops its "move through alles" heading (kept for screen readers)
and the subtitle under every app (no helper text).

## not done: keep the shell loaded

the plan asked to keep the shell loaded when a switch takes over about 300 ms. measured on
throwaway data at 1180x820: plan to health is 1.7 s across subdomains (a full page load) and
0.84 s in one host (`127.0.0.1`), where ~0.76 s pass idle before health's first request. that idle
wait is not a timer or a fetch from page code; its cause wasn't found in this pass. keeping the
shell across subdomains needs one origin (subdomains are separate origins), so it is a routing
change for its own pass.
