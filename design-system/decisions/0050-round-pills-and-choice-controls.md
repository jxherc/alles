# picked pills are round; pill switch and number row

## context

the owner on the finance tabs (28.10, 28.15): the pills "aren't real pills, they look cut off at
the top and bottom". a browser check showed it was the shape, not clipping: an 8px corner on a
36px pill reads as a box with its corners shaved. andromeda's tabs were a 1px underline instead,
and the aide header's "conversation / code" (27.11) looked like neither. after a demo of choice
controls the owner picked card a (c.03): 2 or 3 options flipped often are a pill switch, a rating
is a row of numbers, everything else picked from a list is the dropdown.

## decision

- a row of tabs or segments is a track of round pills. motion.js marks such a group
  `data-pill-shape="round"`; its sliding pill and its items (so the focus ring) take
  `--k-radius-pill`. the pill sits 4px inside the 44px target, even above and below. a stack of
  rows (the settings nav) keeps the 8px row corner.
- andromeda's tabs drop the underline and use the same pill. the locale segmented control and
  pill switches join motion.js's item list.
- FOUNDATIONS shape table: tabs, segments and pill switches move from 8px to round. fields,
  buttons and rows keep 8px, surfaces 12px, composers 16px, so each role keeps its own shape.
- pill switch: `<div class="k-pill-switch" data-kokuen-choice="switch" aria-label="unit">` with
  2 or 3 buttons. kokuen.js makes it a `radiogroup` of `radio`s with arrow keys, Home and End
  (`wireChoiceGroup`); the round pill slides to the pick. each option is a full 44px target and the
  pill sits 4px inside it, so it shows 4px from the track's edge all round.
- number row: `<div class="k-number-row" data-kokuen-choice="rating" data-min="1" data-max="10"
  data-labels="..." data-words="easy,,,,,,,,,max" aria-label="effort">`. 44px round numbers, one
  tap, every value visible, a radiogroup. the end words sit on the numbers' own grid, each
  centered under its number. a readout under them names the pick ("7, hard") and is announced.
  a row of more than 5 wraps to two rows of 5 under 520px; there the end words hide and the
  readout stays.
- both fire a bubbling `change` event: a pill switch's `detail.value` is the option's
  `data-value` (or its label), a number row's is the number.

## checks

- `tests/pw_kit_rules.py`: every picked pill in a row group is fully round and fully inside its
  clipping parents while its tab is in view.
- the kit page (`static/kit.html`) shows tabs, segments, both switches and both number rows.
