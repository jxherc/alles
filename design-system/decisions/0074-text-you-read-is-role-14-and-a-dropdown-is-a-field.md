# text you read is role 14, a dropdown is a field, card rows part by space

amends 0044 (which text may be role 13), 0049 (what counts as a field) and 0051 (rows in a card).

## context

the nov 10 audit measured 574 pieces of text under 16px on a phone across 16 screens, all at
14.95px: role 13 at the touch root. most of it was not metadata. task titles, file names, tab
labels, account names, amounts, button labels and empty state sentences were all role 13,
because one old floor rule (`style.css`, "never smaller than 12px") pinned every button, field,
tab and dropdown in an app to role 13 with `!important`. it even beat the tab rule's own role 14.

the same audit found 7 dropdown triggers drawn as bare text with a chevron (plan's task view,
appearance's two pickers, language, region, timezone and currency) next to boxed text fields,
because the field look hung on the optional `.settings-input` class. dropdown text was 14.95px
in most of settings, 18.4px in language and 16.1px in the apps.

in money, every row inside a card drew a line and moved 12px out of the card's padding for a
hover fill those rows never had, so each line started 12px left of the words. an account with
one move in a month drew a flat line with a step in it.

## decision

- controls and fields in the apps are role 14 (16.1px on touch, 15.3px on a computer). the floor
  rule now says so and no longer reaches view tabs.
- text someone reads is role 14 or larger: a row's name and its value (`.specialist-group-row`),
  empty state sentences, journal snippets, home's capture mode. role 13 stays for what sits
  beside it: times, counts, tags, the change under a figure, column heads, the bottom bar's
  labels.
- a view tab is role 14, and role 13 at 760px and narrower so four views fit a phone's row
  without the scroll arrows.
- a dropdown trigger is a field by its role: `.custom-select[role="combobox"]` joins the one
  field rule and reads role 14 on every screen. an entry row still clears the fields inside it.
- rows inside a card part by space: no line under a row, no pull out of the card's padding. the
  card's own edge is the one boundary.
- a sparkline needs three different values. two values are a change, and the change is already
  printed beside it. a list where no row has a line gives the line's room back, so its figures
  end on the card's edge.

## checks

- `floor.py` (webkit, 390x844, touch): text under 16px per screen, before and after.
- `ddsweep.py`: 35 visible dropdown triggers on 26 screens and 19 settings panes, every one 44px
  tall with the field fill and ring at 16.1px; the 3 inside entry rows stay bare.
- `fit.py` before and after at phone and ipad: no new control off screen and no new clipped
  label; finance's four tabs fit a 390px row.
- `tests/js/numbers.test.mjs`: one move in a month draws no line.
- the kit rules gate has the rule `text-under-13`: any visible text under 13px, on any route at
  any of its four sizes, fails the gate. the 16px reading size is not gated, because a rule
  can't tell a label from a sentence.
