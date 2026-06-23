# stage 2b - forecast with category breakdown + what-if - audit findings (2026-06-23)

## current `/forecast` (routes/money.py)
projects end-of-month balance = net worth at `as_of` + the remaining RecurringTxn occurrences
in the month. returns month, start_balance, projected, recurring[], line[] (balance over time).
single-dimensional: one balance line.

## the gap
- **no per-category projection**: it never says "you'll likely spend ~$420 on groceries,
  ~$80 on coffee this month" from historical averages + scheduled recurring.
- **no what-if scenarios**: can't model "skip this bill", "if income changes", "pause a sub" and
  see the revised projection.

## fix - new `services/forecast.py` (pure, testable) + extend the endpoint
- `category_averages(db, *, months=3, as_of)` - avg monthly SPEND per category over the last N
  complete months (income/positive amounts excluded).
- `project_month_categories(db, month, *, months=3, as_of)` - per-category projection = historical
  avg blended with any recurring spend scheduled in the month, per category.
- `apply_scenario(occ, *, skip_payees=(), income_delta=0.0)` - drop occurrences whose payee
  matches a skip term; add an income adjustment occurrence. returns the adjusted occ list.
- `/forecast` gains a `categories` field, and accepts `skip` (comma payees) + `income_delta`
  (float) query params that adjust `projected`/`line` via apply_scenario.

deterministic math, fully testable without an LLM. verified: single balance line, no category
projection, no scenarios.
