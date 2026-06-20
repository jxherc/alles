# ui-5c — calendar view switcher → segmented control

The month/week/day/agenda/year switcher was a row of five stuck-together `.btn.cal-view-btn`
buttons with its own ad-hoc CSS (`.cal-view-toggle` / `.cal-view-btn`). Replaced it with the
Stage-0c shared segmented control (`.seg` / `.seg-opt`, the same component activity uses), sized a
touch larger than `seg-sm` via a new `.seg.seg-cal` variant.

- Markup (`static/index.html`): `<div class="seg seg-cal" id="cal-view">` with five
  `<button class="seg-opt" data-view="…">`.
- JS (`static/js/calendar.js`): the click binding and `_syncViewBtns` now target `#cal-view .seg-opt`
  (was `.cal-view-btn`); state still flows through the `.active` class the seg component highlights.
- CSS: dropped the dead `.cal-view-toggle`/`.cal-view-btn` rules; added `.seg.seg-cal .seg-opt`
  (`padding: .26rem .7rem; font-size: .7rem`).

Tests: `tests/test_calendar_seg.py` (5 source-contract) + `docs/evidence/ui-5c/verify.py` (switcher is a
single `.seg.seg-cal`, all 5 views present, each click highlights exactly one option + persists to
localStorage, 0 console errors) + `switcher.png`.
