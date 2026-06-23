# stage 2d - holdings price-fetch + portfolio - audit findings (2026-06-23)

## current state
`Holding` (core/database.py) stores a MANUAL `price` (defaults 0.0). `_holding` (routes/money.py:1067)
computes value/cost/gain/gain_pct from that frozen price. nothing ever updates `price` unless the
user PATCHes it by hand. there is:
- NO auto price fetch (the holding price goes stale the moment it's entered).
- NO price history (can't show a holding's trend or compute return over time).
- NO refresh job + no refresh endpoint.

so the "portfolio" is a static snapshot the user has to hand-maintain. exercised: added a holding via
POST /holdings, confirmed price stays whatever was typed; no mechanism re-prices it.

## the gap
- a way to refresh holding prices from an external source (pluggable, best-effort, no hard dep).
- a price-history table so each refresh is recorded -> per-holding trend + return since first seen.
- a refresh endpoint (manual button) + a periodic job (best-effort, off by default cost-wise it's free
  but network so run sparingly).

## fix - new `services/price_fetch.py` (pure core, stub-seam fetcher) + `PriceHistory` model
- `PriceHistory(symbol, price, ts)` - one row per symbol per refresh. new TABLE so create_all picks it
  up on existing DBs (no migration needed; create_all only adds missing tables).
- `refresh(db, *, fetcher=None, now=None)` - collect held symbols, call `fetcher(symbols)->{sym:price}`,
  update each Holding.price + append a PriceHistory row. returns {updated, prices}. fetcher defaults to
  `_default_fetcher` (best-effort Stooq CSV, keyless; returns {} on any failure so prod never breaks).
  the fetcher arg is the TEST SEAM - tests pass a deterministic dict-returning stub, never the network.
- `history(db, symbol, *, limit)` - recent PriceHistory rows for a symbol (trend).
- `return_since_first(db, symbol)` - pct change from the earliest recorded price to the latest.
- routes/money.py: POST /holdings/refresh (manual trigger) + /holdings/{sym}/history. `_holding` gains
  a `price_history` count is overkill; keep serializer as-is, add return via the history endpoint.
- app.py: register a `holdings_price` job (best-effort, every 6h, run_at_start=False).

deterministic core fully tested via the stub fetcher; the network default is thin + try/excepted.
