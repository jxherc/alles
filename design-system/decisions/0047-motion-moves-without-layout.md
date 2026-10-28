# motion moves things, it doesn't resize the page or loop on its own

## context

the oct 28 visual pass (impeccable, frontend-design-deslop, design-law) found 26 transitions on
layout or shadow properties (switch knobs on `left`, the strength meter and rails on `width`, the
coding rail on `grid-template-columns`, focus rings on `box-shadow`, one `transition: all`) and
three loops that never stop on the server monitor: a gradient shimmer with a glow on the system
logo (with `will-change` at rest), a blinking caret after "live", and a glowing pulse on a hot cpu
value. principle 17 already says motion is for feedback or continuity, never decoration alone.

## decision

- a moving part moves with `transform`/`translate` or fades with `opacity`. switch knobs keep
  `left: 5px` and slide with `translate: 18px 0` when on; the vault strength meter fills with
  `scaleX` from the inline start.
- a panel or rail that changes width (mail folders, the artifact panel, the coding rail, the
  lightbox stage) snaps to its new size; labels inside may still fade.
- focus and hover rings drawn with `box-shadow` change at once; background and text color may
  still ease.
- nothing decorative loops. the system logo is one solid accent, the live mark holds still, a hot
  cpu value is colored, not pulsing. motion that shows work in progress (streaming caret, working
  shimmer, spinners) stays, stops when the work does, and is off under reduced motion.

## kept

- the selection pill still slides and resizes to the picked item (MOTION.md "picked things"): one
  pseudo-element, on a user action, in the slide duration. that is continuity, not a loop.
- every reduced-motion rule.
