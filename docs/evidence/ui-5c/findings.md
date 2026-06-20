# ui-5c — calendar segmented view switcher (findings)

## Audit (before)

The calendar's month/week/day/agenda/year switcher was five `.btn.cal-view-btn` buttons forced
together with bespoke radius-stitching CSS (`.cal-view-btn:first-child`/`:last-child`) — a one-off that
didn't match activity's already-unified `.seg` segmented control.

## Fix

Swapped it for the shared Stage-0c `.seg`/`.seg-opt` component (`#cal-view`), with a slightly larger
`.seg-cal` size variant. `calendar.js` selectors moved from `.cal-view-btn` → `#cal-view .seg-opt`
(click binding + active-sync); the dead `.cal-view-toggle`/`.cal-view-btn` CSS is gone.

## Verify (after)

`verify.py` on `calendar.localhost:8872`: the switcher is a single `.seg.seg-cal`, all five views
present in order, and clicking each one highlights exactly that option (`.active`), leaves the others
inactive, and persists `cal-view` to localStorage — month/week/day/agenda/year all switch the render.
0 console errors. Screenshot: `switcher.png`.
