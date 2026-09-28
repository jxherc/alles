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
    from sqlalchemy import or_

    from core.database import Account, Transaction

    as_of = as_of or date.today()
    accounts = [
        {"id": row.id, "archived": row.archived}
        for row in db.query(Account).filter_by(archived=False).all()
    ]
    accts = {row["id"] for row in accounts}
    if not accts:
        return {}
    # Historical averages exclude archived accounts, unlike current spending totals.
    # Apply the narrower predicates in SQL before scanning transaction history.
    rows = (
        db.query(Transaction)
        .filter(
            Transaction.account_id.in_(accts),
            Transaction.amount < 0,
            or_(Transaction.transfer_id.is_(None), Transaction.transfer_id == ""),
        )
        .all()
    )
    transactions = [
        {
            "account_id": row.account_id,
            "date": row.date,
            "amount": row.amount,
            "category": row.category,
            "transfer_id": row.transfer_id,
        }
        for row in rows
    ]
    return category_averages_from_rows(accounts, transactions, months=months, as_of=as_of)


def category_averages_from_rows(accounts, transactions, *, months=3, as_of=None):
    """Same category projection for either mapped Finance ledger."""
    as_of = as_of or date.today()
    periods = set(_recent_months(as_of, months))
    accts = {row["id"] for row in accounts if not row["archived"]}
    totals = {}
    for row in transactions:
        amount = row["amount"] or 0.0
        if (
            row["account_id"] not in accts
            or amount >= 0
            or row.get("transfer_id")
            or (row["date"] or "")[:7] not in periods
        ):
            continue
        category = row.get("category") or "uncategorized"
        totals[category] = totals.get(category, 0.0) - amount
    return {category: round(total / months, 2) for category, total in totals.items()}


def apply_scenario(occ, *, skip_payees=(), income_delta=0.0, at=None):
    """what-if over the recurring occurrence list: drop occurrences whose payee matches a skip
    term (case-insensitive substring); append an income-adjustment occurrence for income_delta."""
    skips = [s.lower() for s in skip_payees if s]
    out = [o for o in occ if not any(s in (o.get("payee", "") or "").lower() for s in skips)]
    if income_delta:
        when = at or (out[-1]["date"] if out else (occ[-1]["date"] if occ else ""))
        out = out + [{"date": when, "amount": float(income_delta), "payee": "income adjustment"}]
    return out
