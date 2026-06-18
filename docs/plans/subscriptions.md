# Phase 8 — subscriptions (`subs.js` + `routes/subscriptions.py`)

## Audit (2026-06-18)

Verified working (DO NOT rebuild): subs CRUD, billing cycles (weekly/monthly/quarterly/yearly/custom),
due rollover, monthly/yearly normalized totals + by-category analytics, push reminders before renewal,
optional auto-post of the charge to a money account, pause/resume, inline edit. UI 0 console errors.

**mark-paid bug:** `_advance` IS cycle-correct (monthly→+1mo, yearly→+1yr), but mark-paid advances
exactly one cycle from `next_due` — so a subscription that's several periods **overdue** lands in the
past after one click (you must click N times). The fix: advance by full cycles to the next due strictly
after today, so one click always lands on the correct upcoming period.

Other gaps: no **free-trial / cancel-by** tracking (easy to forget to cancel a trial); no **upcoming-
renewals** view (what's due in the next N days + the total).

## Tasks (each ≥8 unittest cases, RED→GREEN, + Playwright UI verify)

- **subs-1 Fix mark-paid (cycle-correct + overdue rollforward).** advance one cycle, then keep advancing
  full cycles while still ≤ today; cycle-correct for all cycles. *Why: the spec's required fix.*
- **subs-2 Free-trial / cancel-by tracking.** `trial_end` column + surface "cancel by / trial ends in N
  days" in list + analytics; GET filter for trials ending soon. *Why: forgetting to cancel a trial is the
  #1 subscription-manager pain.*
- **subs-3 Upcoming renewals.** GET `/api/subscriptions/upcoming?days=` (active subs due in the next N
  days, soonest first, with the summed cost) + an upcoming strip in the UI. *Why: "what's hitting my card
  this week and how much" isn't answerable today.*

## Out of scope

Bank/email auto-detection of subscriptions, multi-currency conversion, shared/family plans.

---

# subscriptions — sane payments + feasible extras (2026-06-18)

Evidence: `docs/evidence/subscriptions/`. The reported bug: `mark_paid` advanced `next_due` every click
with no due-guard → infinite advancing. New tables `sub_payments` + `sub_price_changes`.

## subs-fix-1 — sane mark-paid + payment log + undo  (done)
`paid` only when due (`days_until<=0`, else 400 + UI "not due"); each pay writes a `SubPayment` (+links the
money txn); `GET /…/{id}/payments`, `POST /…/{id}/payments/undo` (drops txn + steps next_due back). UI:
paid gated on `payable`, "⤺ N" history popover with undo.
Tests: `test_subs_payments.py` (12) + corrected `test_subs_paid` + `pw_subs_pay.py` (8/8).

## subs-fix-2 — price history + hike flag
On a PATCH that changes `price`, record `SubPriceChange(old,new,date)`; expose `price_increased` + last
change in `_fmt`; UI "↑ price up" badge. Tests `test_subs_price.py` (≥8).

## subs-fix-3 — cash-flow forecast
`GET /api/subscriptions/forecast?months=6` → per-month projected totals across each active sub's cycle
(+ grand total). UI mini month strip. Tests `test_subs_forecast.py` (≥8).

## subs-fix-4 — duplicate detection
`GET /api/subscriptions/duplicates` → groups of subs with normalized-similar names / same url host. UI
"possible duplicate" hint. Tests `test_subs_duplicates.py` (≥8).
