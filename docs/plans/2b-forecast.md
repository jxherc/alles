# stage 2b - forecast: category breakdown + what-if

Audit: docs/evidence/2b-forecast. New pure helper + endpoint extension.

## design - services/forecast.py
- `category_averages(db, *, months=3, as_of=None) -> {cat: avg}` - avg monthly SPEND per category
  over the last N complete months (income excluded, non-archived accounts).
- `apply_scenario(occ, *, skip_payees=(), income_delta=0.0, at=None) -> occ'` - drop occurrences
  whose payee matches a skip term; append an income-adjustment occurrence when income_delta != 0.
- `routes/money.py:/forecast` gains `categories` (= category_averages) and accepts `skip` (comma
  payees) + `income_delta` (float) query params, applied to `occ` via apply_scenario before the
  balance line + projected are computed.

## tasks
### Task 2b-1 - the helper  (tests: tests/test_forecast.py)
RED tests (>=8): category_averages averages 3 months of a category; excludes income; empty
history -> {}; only counts the last N months (older txns ignored); apply_scenario skip removes a
matching-payee occurrence; skip is case-insensitive + substring; income_delta appends an income
occurrence with that amount; income_delta 0 is a no-op; non-archived scoping.

### Task 2b-2 - endpoint integration  (tests: tests/test_forecast.py cont.)
RED tests: /forecast returns a `categories` dict; `skip=<payee>` raises the projected (a bill is
skipped); `income_delta=500` raises projected by ~500; the base forecast (no scenario) is
unchanged from before.

## verification
- `python -m unittest tests.test_forecast` green; existing money forecast tests green; full suite green.
