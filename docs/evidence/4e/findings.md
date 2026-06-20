# 4e audit — subs intelligence

Live `:8837`. Much of 4e already shipped in 1f / earlier microversions:
- `GET /api/subscriptions/detect` → `{candidates:[]}` (auto-detect from txns) ✓
- `/trials` (cancel-by), `/upcoming`, `/duplicates`, `/forecast`, price-history, paid/undo ✓
- money `RecurringTxn` + `/alerts` `upcoming_bills` cover non-sub bill reminders ✓

## Gaps (net-new)
- `GET /api/subscriptions/unused` → **405** (no route) — no unused-subscription detection.
- `Subscription` has `url` + `notes` + `trial_end` but **no explicit `cancel_url`** for the
  cancellation helper.
- `Account` has **no low-balance threshold**; money `/alerts` has no `low_balance` list.

Plan: docs/plans/4e.md (4e-1 backend, 4e-2 frontend). Adopt-from-detected is a thin frontend POST
to the existing `/subscriptions` create endpoint — no new backend needed.
