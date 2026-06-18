# subscriptions — audit findings (2026-06-18)

Drove `subs.localhost:8799`. Real seeded subs (iCloud+, NYT, Netflix, Disney+ trial …) render with an
"upcoming 7 days" strip, a spend-by-category bar, and per-row price/cycle/due. Zero console errors.

## The reported bug (confirmed)
`mark_paid` advanced `next_due` by one cycle on **every** call with **no due-guard**. So clicking "paid"
on a sub that isn't due yet pushed its date a cycle into the future — click it five times and it's five
cycles out. Exactly the user's "you could just infinitely click paid and it will go on and on".
(`test_subs_paid.py` even *asserted* this old behavior — that test was wrong and is now corrected.)

## Fixes (4 tasks)
- **subs-fix-1 (done): sane mark-paid + payment log + undo.** `paid` now refuses when not due
  (`days_until > 0` → 400) and is exposed in the UI only when `payable` (else a muted "not due" tag).
  Each pay writes a `SubPayment` (date + amount, links the money txn if posted); `GET /…/{id}/payments`
  lists them; `POST /…/{id}/payments/undo` drops the last payment + its txn and steps `next_due` back.
  UI: per-row "⤺ N" history popover with "undo last".
  Tests: `tests/test_subs_payments.py` (12) + corrected `test_subs_paid` + Playwright `pw_subs_pay.py` (8/8).
- **subs-fix-2: price history + hike flag.** (SubPriceChange on PATCH price change; ↑ badge.)
- **subs-fix-3: cash-flow forecast.** (`GET /forecast?months=` per-month projection + UI strip.)
- **subs-fix-4: duplicate detection.** (`GET /duplicates` normalized name/url grouping + UI hint.)

New tables `sub_payments` + `sub_price_changes` (core/database.py, via `create_all`).
