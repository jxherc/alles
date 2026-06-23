# stage 2c - spending anomaly alerts + merchant insights - audit findings (2026-06-23)

## current state
`signals._budget` only emits when a category exceeds an explicitly-set `Budget` limit. there is
NO anomaly detection: a category that spikes 3x its usual spend, or a brand-new merchant, goes
unflagged unless the user set a hard budget. (subscription price-hike detection already exists in
the subs engine, so that's out of scope here.)

## the gap
- no statistical anomaly: "groceries are 3x your usual this month" with no budget set.
- no new-merchant surfacing: "first time spending at <merchant> this month".

## fix - new `services/money_stats.py` (pure, reuses 2a/2b) + extend `_budget`
- `category_anomalies(db, *, as_of, months=3, ratio=1.5, min_amount=50)` - this month's spend per
  category vs the historical average (reuses forecast.category_averages); flags categories
  >= ratio x baseline. returns [{category, current, baseline, ratio}].
- `new_merchants(db, *, as_of, months=3, min_amount=20)` - normalized merchants (reuses
  money_query._norm_payee) seen THIS month but not in the prior N months.
- `signals._budget` appends anomaly + new-merchant signals (category "budget", so they flow into
  proactive via the money toggle) alongside the existing budget-over signals.

deterministic stats, fully testable. verified: only hard-limit budget signals today; no anomaly
or new-merchant surfacing.
