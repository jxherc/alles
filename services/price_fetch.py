"""2d - refresh holding prices from an external source + keep a price history.

the network fetch is best-effort and pluggable: `refresh` takes a `fetcher(symbols)->{sym:price}`
so tests pass a deterministic stub and prod uses `_default_fetcher` (keyless Stooq CSV). the default
returns {} on any hiccup, so a flaky/offline source never breaks the call.
"""

from core.database import Holding, PriceHistory


def _held_symbols(db):
    return sorted({(h.symbol or "").upper() for h in db.query(Holding).all() if h.symbol})


def refresh(db, *, fetcher=None, now=None):
    """reprice every held symbol from `fetcher`, record a PriceHistory row per priced symbol."""
    fetcher = fetcher or _default_fetcher
    syms = _held_symbols(db)
    if not syms:
        return {"updated": 0, "prices": {}}
    prices = fetcher(syms) or {}
    prices = {k.upper(): float(v) for k, v in prices.items() if v is not None}
    updated = 0
    for h in db.query(Holding).all():
        p = prices.get((h.symbol or "").upper())
        if p is None:
            continue
        h.price = p
        updated += 1
    for sym, p in prices.items():
        row = PriceHistory(symbol=sym, price=p)
        if now is not None:
            row.ts = now
        db.add(row)
    db.commit()
    return {"updated": updated, "prices": prices}


def history(db, symbol, *, limit=30):
    rows = (
        db.query(PriceHistory)
        .filter_by(symbol=(symbol or "").upper())
        .order_by(PriceHistory.ts.desc())
        .limit(limit)
        .all()
    )
    return [{"price": r.price, "ts": r.ts.isoformat() if r.ts else None} for r in rows]


def return_since_first(db, symbol):
    """pct change from the earliest recorded price to the latest, or None if no history."""
    rows = (
        db.query(PriceHistory)
        .filter_by(symbol=(symbol or "").upper())
        .order_by(PriceHistory.ts.asc())
        .all()
    )
    if not rows:
        return None
    first, last = rows[0].price, rows[-1].price
    if not first:
        return None
    return round((last - first) / first * 100, 2)


def _default_fetcher(symbols):
    # best-effort keyless quote pull (stooq). any failure -> {} so prod never breaks on a flaky source.
    import httpx

    out = {}
    for sym in symbols:
        try:
            r = httpx.get(
                "https://stooq.com/q/l/",
                params={"s": sym.lower(), "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                timeout=6,
            )
            # csv: Symbol,Date,Time,Open,High,Low,Close,Volume
            line = r.text.strip().splitlines()[-1].split(",")
            close = line[6]
            if close and close not in ("N/D", "0"):
                out[sym] = float(close)
        except Exception:
            continue  # skip this symbol, keep going
    return out
