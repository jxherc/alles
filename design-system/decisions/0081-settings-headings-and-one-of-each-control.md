# settings headings, and one of each control

amends 0050 (choice controls) and 0057 (settings homes).

## context

the nov 10 audit of settings found 14 panes with section headings at one size and weight (role 14,
500) and two panes at another (role 16, 580), some headings with an icon and most without, eight
panes whose first heading repeated the pane's own name (the header already shows it, and on a
phone the pane dropdown shows it a third time), and several things offered twice at once: dark
or light mode in two places, a live preview that repeated the values the rows already show, a
"home outline" that repeated the order of the list beside it, and a "search" pane that held only
custom engines.

## decision

- a section heading in settings is the section title role: 1rem (role 16), weight 600, text color.
  one rule draws every one (`.s-card-head`, and the h3 of the home, language and credits panes).
  no icon sits on a heading.
- a pane's first heading never repeats the pane's name. the header and the pane dropdown name it.
- a status that has nothing to say takes no room (`.settings-pane-state:empty`), and on a phone it
  shows like on any other screen.
- one control per job, one copy per fact: a thing is picked in one place, and a preview that shows
  what the rows already show is not drawn.
