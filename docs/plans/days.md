# Phase 13 — days (`days.js` + `routes/days.py`)

## Audit (2026-06-18)

Drove days.localhost and probed the API across edge cases (feb-29 birthdays, 31st-of-month repeats,
past/future dates, anniversary counting). Verified working (DO NOT touch): one-shot countdown→count-up
flip; yearly/monthly rollover with anniversary (nth) counting; feb-29 / 31st clamping; ymd breakdown;
per-cycle progress bar; pin; category; push reminders; client-side recompute against the viewer's local
midnight; midnight auto-refresh. Per the spec, this phase adds tasks **only for a real bug** — and the
audit found one.

### Bug found (reproduced against the live API)

A **recurring event whose original/start date is in the future** computes a bogus occurrence in the
*current* cycle — one that falls *before the event has ever happened* — with a negative anniversary:

- yearly, start `2028-06-18` (2 years out) → `target=2026-06-18`, `days=0`, `mode="today"`, `nth=-2`
  → the app screams "today! 🎉" for an event two years away.
- monthly, start `2026-07-28` (40 days out) → `target=2026-06-28` (before the start), `nth=-1`.

`_occurrence()` always snaps to `_clamp(today.year/month, orig.day)` and only ever rolls *forward*, so a
future `orig` yields an occurrence earlier than `orig` itself. This is a real correctness bug for a
common input: "add my wedding (in N months) and repeat it yearly". It also makes `check_day_events()`
fire a wrong "is today" push.

## Tasks (≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **days-1 Fix future-dated recurring occurrence.** In `_occurrence`, when `orig > today` the next
  occurrence is `orig` itself with anniversary `0` (the event hasn't had its first occurrence yet); only
  roll forward once `orig <= today`. Fixes yearly + monthly; the on-time and past cases stay unchanged;
  `nth` is never negative. *Why: the audit's reproduced correctness bug — future recurring events show
  "today!" / negative anniversaries and mis-fire reminders.*

## Out of scope

New features (the spec restricts this phase to bug fixes); the day-of-week one-shot repeat (not a
supported repeat type); timezone re-architecture (client already recomputes counts against local
midnight).


---

# days — UI/UX polish (2026-06-18)

Evidence: `docs/evidence/days/` (findings + before/after screenshots).

## days-ui-1 — edit card stays in its section (no jump to first grid)
`_render()` rendered the edit card at the top of a flat section-less list when editing. Fix: render the
normal `sections` layout always and swap `_editCard` for `_card` only for the editing row in place.
`static/js/days.js` `_render`. Verify `pw_days_edit.py` (7 assertions, RED->GREEN): edit_card_in_place +
section_header_before_edit + zero console errors.
