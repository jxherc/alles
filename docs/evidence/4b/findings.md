# 4b audit — money: envelope budgeting (YNAB)

Confirmed against the 4a-era money app + live `:8831`.

## State
- `routes/money.py` has **0** references to envelope/assign/funding/age-of-money.
- `GET /api/money/envelope` → **404**; `GET /api/money/age-of-money` → **404**.
- Existing `Budget(category, limit_amt)` is a simple monthly spending *cap*, not a YNAB envelope
  (no per-month assignment, no rollover, no funding target).
- 4a added `_spending_by_cat`-equivalent split distribution inline in `summary`; I'll factor that
  into a shared helper so the envelope view and summary agree on category spending.

## Gaps (net-new)
1. **Assigned-vs-spent** per category per month (envelope).
2. **Rollover** — available carries across months (assigned − spent, cumulative).
3. **Funding targets** — target amount + date per category, with funded %.
4. **Age of Money** — days between income arriving and being spent (FIFO).
5. **To Be Budgeted** banner — income not yet assigned.

## Plan (docs/plans/4b.md)
- **4b-1 backend**: `BudgetAssignment(category, month, assigned)` + `FundingTarget(category, amount,
  target_date)` models; `_spending_by_cat` helper (shared with summary); `GET /api/money/envelope?
  month=` (assigned/spent/available-with-rollover/target/funded + to_be_budgeted); `PUT
  /envelope/assign`; `PUT /envelope/target`; `GET /age-of-money`. ≥8 unittest.
- **4b-2 frontend**: envelope budgeting card — per-category rows (assign input, available bar,
  target progress), TBB banner, Age of Money stat. ≥8 pw.
