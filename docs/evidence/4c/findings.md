# 4c audit — money: forecast & investments (Simplifi)

`routes/money.py` has 0 references to forecast/holding/watch/networth. Live `:8833`: `/forecast`,
`/networth-history`, `/holdings`, `/alerts` all **404**. All net-new.

## Reusable baseline
- `RecurringTxn` + `_advance(d, cycle, cycle_days)` + `_post_due_recurring` already model scheduled
  txns → reuse `_advance` to project recurring occurrences forward for the forecast.
- `summary` already builds a 6-month income/expense `trend`; net-worth history is the balance
  analogue (running balance at each month-end).
- `_balances(db)` gives per-account running balance.

## Gaps (net-new)
1. **Spending-plan forecast** — project end-of-month balance from today's balance + remaining
   recurring occurrences.
2. **Net-worth history** — net worth at each month-end over N months.
3. **Investment holdings** — manual holdings (symbol/qty/cost/price) → value + unrealized gain.
4. **Watchlists + alerts** — watch a payee/category; alerts for large purchases, upcoming bills,
   and watch matches.
5. **Customizable dashboard** — hide/reorder summary cards (frontend, persisted).

## Plan (docs/plans/4c.md)
- **4c-1 backend**: `Holding` + `Watch` models; `GET /forecast?month=&as_of=` (start balance +
  projected recurring → month-end, with a daily line); `GET /networth-history?months=`; holdings
  CRUD + value/gain; `GET /alerts` (large purchases, upcoming bills, watch matches). ≥10 unittest.
- **4c-2 frontend**: forecast stat + projected line on the trend area; net-worth history graph;
  holdings card (add/edit/remove, value + gain); alerts strip; dashboard card hide/reorder
  persisted in localStorage. ≥8 pw.
