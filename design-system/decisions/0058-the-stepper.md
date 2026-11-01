# the stepper

## context

the owner's set logger screenshots (oct 28, `set logger ipad landscape.png` and the phone ones)
put weight, reps, partial reps, bad reps and rest in big steppers: minus and plus inside one
field, the value large in the middle. the ux laws ask for "steppers big enough for a sweaty thumb"
and "one control per job across all 60 habits". the first gym logger built `.k-stepper` inside the
gym css with no kit entry, and two app-wide rules shrank its value: the important control size
floors (`style.css` `[data-specialist-app] input`, `revamp.css` `[data-specialist-app] :is(button,
input...)`) made it role 13, and the kit field focus ring (`kokuen.css`, important) drew a second
box inside the stepper's own focus edge (both read with getComputedStyle in webkit).

## decision

- one stepper for every number with a common step: `static/js/stepper.js` (`stepperHtml`,
  `wireSteppers`, `stepValue`), css in `revamp.css` next to the gym logger.
- 52px tall, 44px buttons inside the edge, the value role 22 semibold with tabular numbers (the
  reference's size and weight), centered. the value rule is important so the control floors can't
  shrink it.
- one focus indicator: the stepper's own edge brightens while anything in it has focus; the field
  ring is switched off on its input.
- minus is off at the floor and plus at the ceiling. empty and "?" (unknown) count from the floor.
  arrow up and down in the field step, so the keyboard doesn't need the buttons.
- a logger with its own model (the gym set logger: drafts, per side, rest as m:ss) uses the
  markup with `auto: false` and handles the presses itself.
- labels are `common.less_n` / `common.more_n` ("less, weight"), moved from the habit strings.

## checked

kit page (`#kit-stepper`) and the gym logger in webkit at 1180x820, dark and light: 52px tall,
44px buttons, 24px semibold value, one focus edge, plus and arrow keys step, minus off at 0, the
off stepper fades once. `tests/js/stepper.test.mjs` covers the step math and the markup.
