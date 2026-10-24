# boxes sit on the edge

## context

Decision 0031 moves inline text actions and chip rows back by their padding, so the label lines up
with the column and the hover box hangs past it. The daily-use pass (2026-10-23) found the same
pull-back on things that show a box at rest, where the box itself pokes out: mail's phone "refresh"
starts at 4px against a 16px gutter, the setup wizard's filled "back" sits 13px outside the content,
Library's picked "everything" chip juts 12px left of its card, compose's lined "back to messages"
sits 12px in, and the docs phone "import document" box starts at 4px. On a phone the edge is the
first thing the eye checks, so a box past it reads as broken.

## decision

- A box that is visible at rest (a filled or lined button, a picked chip, a raised segment) sits on
  the content edge. Its border lines up with the column, not its label.
- Only bare text actions, with no box until hover, move back by their padding (0031 still holds
  for those).
- Chip rows don't move back, since the picked chip can be the first one.

## kept

- 0031's bare-text grammar, the 44px target, and the settings outline pass.
