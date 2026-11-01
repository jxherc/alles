# busy shows on the box's own edge

## context

while aide worked, the composer drew a 1px moving light 12px in from its rounded corners
(`style.css` `.composer-box::after`), aide code's entry did the same (`aidecoding.css`), and the
what's new card drew a 2px accent bar across its rounded top. the owner called the first "just a
simple line above the bar ... ugly" and named the what's new one too (28.17). the steps strip under
an answer had an `inset 0 -1px` line under a rounded box, and a destructive step a 2px stripe on a
rounded card (28.07, 28.42). the owner picked "the whole border glows" softly, no bloom.

## decision

- the busy edge, one rule in `kokuen.css`: a `::before` inside the box on its edge (`inset: 0`,
  a transparent 1px border, `border-radius: inherit`, masked to that ring) with a conic tone that turns
  slowly around the corners (`@property --k-busy-turn`, 2.8s). no bloom, no blur, no line across
  the edge, never clipped by `overflow: hidden`. it stops the moment the busy state ends.
- reduced motion: a steady brighter edge.
- used by the aide composer (`body.aide-working`), aide code's entry (`data-busy="true"`) and any
  `.k-busy[data-busy="true"]`. the box needs `position: relative`.
- the what's new line goes with no replacement: it isn't a busy state.
- the steps strip has no line; sources and revert are 44px text actions like copy. a destructive
  step says so in danger text on its name, no stripe.
- the twin sweep keyframes (`aide-sweep`, `acw-sweep`) are gone; the running tool line uses
  `k-sweep`.

## checked

kit page in webkit: the edge follows the 16px radius and turns (`k-busy-turn` running, the angle
moving); reduced motion shows the steady edge. `tests/test_kit_part_two.py` fails the old sweeps,
a line under the steps strip and a stripe on a destructive step.
