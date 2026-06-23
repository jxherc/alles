# stage 2a - NL spending search + insights - audit findings (2026-06-23)

## current `_money_query` (services/agent_tools.py:1883-1921)
- lists accounts + balances + net worth (scoped to non-archived accounts - good).
- summary is **this month only** (`date.today().strftime("%Y-%m")`): income, spending, top 8
  categories.
- the query path: a substring match over `payee + category + notes` across **ALL** txns (no
  date filter), returning just `N txns, spent X`.

## the gap
- **no temporal parsing**: can't ask "last month", "this year", "in march", "year to date",
  "last 90 days". the summary is always this-month; the match ignores dates entirely.
- **no merchant rollup**: payees aren't normalized or ranked; can't answer "top merchants" or
  "how much at starbucks".
- **no comparison**: no month-over-month / period-vs-period ("compare groceries this month vs
  last").
- **no category trend** over time.

## fix - new `services/money_query.py` (pure, testable) + rewire the tool
- `parse_period(text, today) -> (start, end, label)` - this/last month, this/last year, ytd,
  last N days, a named month, with a sensible default (this month).
- `_norm_payee(p)` + `merchant_rollup(txns, top)` - normalized merchant totals.
- `category_breakdown(txns)`; `compare(db, query)` when the text asks to compare two periods.
- `answer(db, query)` - parse period + intent, filter txns, produce a narrative (period spend,
  top categories, top merchants, optional comparison). `_money_query` calls this.

deterministic date math + rollups keep it fully testable without an LLM. verified: this-month
hardcoded, query match date-blind, no merchant/compare.
