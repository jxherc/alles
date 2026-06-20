# 4d audit — money: goals, reports, currency

`routes/money.py`: 0 references to goals/report/networth-base/fx. Live `:8835`: `/goals`,
`/report`, `/networth-base` all **404**. All net-new.

## Reusable baseline
- `Transaction.date` is ISO `YYYY-MM-DD` → string range filters work for custom ranges.
- `_spending_by_cat` distributes splits + excludes transfers (reuse the `_distribute` helper over a
  date range for the report).
- existing `export.csv` shows the formula-injection-safe CSV pattern to copy for the range export.
- `Account.currency` holds a symbol (default `$`); FX needs codes → map symbols → ISO codes.

## Gaps (net-new)
1. Savings/debt-payoff **goals** (progress + ETA).
2. Custom-range **reports** + CSV export.
3. Multi-currency **FX roll-up** of net worth to a base currency.

Plan: docs/plans/4d.md (4d-1 backend, 4d-2 frontend).
