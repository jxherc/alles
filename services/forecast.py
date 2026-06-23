"""2b - spending forecast helpers: per-category projection from history + what-if scenarios.
pure + testable; routes/money.py:/forecast uses these.
"""

from datetime import date


def _recent_months(as_of, n):
    """the n complete months BEFORE as_of's month, as 'YYYY-MM' strings."""
    y, m = as_of.year, as_of.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def category_averages(db, *, months=3, as_of=None):
    """avg monthly SPEND per category over the last `months` complete months (income excluded,
    non-archived accounts only)."""
    from core.database import Account, Transaction

    as_of = as_of or date.today()
    periods = set(_recent_months(as_of, months))
    accts = {a.id for a in db.query(Account).filter_by(archived=False).all()}
    totals = {}
    for t in db.query(Transaction).all():
        if t.account_id not in accts or (t.amount or 0) >= 0:
            continue
        if (t.date or "")[:7] in periods:
            c = t.category or "uncategorized"
            totals[c] = totals.get(c, 0.0) + (-(t.amount or 0.0))
    return {c: round(v / months, 2) for c, v in totals.items()}


def apply_scenario(occ, *, skip_payees=(), income_delta=0.0, at=None):
    """what-if over the recurring occurrence list: drop occurrences whose payee matches a skip
    term (case-insensitive substring); append an income-adjustment occurrence for income_delta."""
    skips = [s.lower() for s in skip_payees if s]
    out = [o for o in occ if not any(s in (o.get("payee", "") or "").lower() for s in skips)]
    if income_delta:
        when = at or (out[-1]["date"] if out else (occ[-1]["date"] if occ else ""))
        out = out + [{"date": when, "amount": float(income_delta), "payee": "income adjustment"}]
    return out
