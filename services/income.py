"""2f - income smoothing + quarterly estimated-tax organizing. classify income txns by type,
rolling-average monthly income, and surface the upcoming US estimated-tax quarter with a set-aside
suggestion (income x a user rate). this ORGANIZES - it does not compute actual tax liability.
"""

import datetime

from core.database import Transaction

# payee keyword -> income type (first match wins, checked in order)
_RULES = [
    ("salary", ("payroll", "salary", "paycheck", "direct dep", "adp", "wages")),
    ("freelance", ("upwork", "fiverr", "stripe", "invoice", "freelance", "contract", "gusto")),
    ("investment", ("dividend", "interest", "capital gain", "vanguard", "coupon", "div ")),
    ("refund", ("refund", "rebate", "irs", "tax return")),
]

# label, earning-period (start month/day, end month/day), due (month/day), due in next year?
_QUARTERS = [
    ("Q1", (1, 1), (3, 31), (4, 15), False),
    ("Q2", (4, 1), (5, 31), (6, 15), False),
    ("Q3", (6, 1), (8, 31), (9, 15), False),
    ("Q4", (9, 1), (12, 31), (1, 15), True),
]


def classify(payee):
    p = (payee or "").lower()
    for typ, kws in _RULES:
        if any(k in p for k in kws):
            return typ
    return "other"


def _income_txns(db):
    return [t for t in db.query(Transaction).all() if (t.amount or 0.0) > 0 and not t.transfer_id]


def by_type(db, month):
    """income totals per type for a YYYY-MM month."""
    out = {}
    for t in _income_txns(db):
        if (t.date or "")[:7] != month:
            continue
        typ = classify(t.payee)
        out[typ] = out.get(typ, 0.0) + (t.amount or 0.0)
    return {k: round(v, 2) for k, v in out.items()}


def rolling_income(db, *, months=3, as_of=None):
    """avg monthly income over the last `months` complete months before as_of."""
    from services.forecast import _recent_months

    as_of = as_of or datetime.date.today()
    periods = set(_recent_months(as_of, months))
    total = sum(t.amount or 0.0 for t in _income_txns(db) if (t.date or "")[:7] in periods)
    return round(total / months, 2)


def current_quarter(as_of):
    """the estimated-tax quarter as_of's date falls in (by earning period)."""
    y = as_of.year
    for label, start, end, due, due_next in _QUARTERS:
        s = datetime.date(y, *start)
        e = datetime.date(y, *end)
        if s <= as_of <= e:
            due_date = datetime.date(y + 1 if due_next else y, *due)
            return {
                "label": label,
                "start": s.isoformat(),
                "end": e.isoformat(),
                "due": due_date.isoformat(),
            }
    return None


def quarter_income(db, as_of):
    """income earned in the current quarter, up to as_of."""
    q = current_quarter(as_of)
    if not q:
        return 0.0
    lo, hi = q["start"], min(q["end"], as_of.isoformat())
    total = sum(t.amount or 0.0 for t in _income_txns(db) if lo <= (t.date or "")[:10] <= hi)
    return round(total, 2)


def set_aside(db, as_of, rate=0.25):
    return round(quarter_income(db, as_of) * rate, 2)


def upcoming_due(as_of, window_days=21):
    """the quarter whose DUE date lands within [as_of, as_of+window], with its earning window
    resolved to concrete dates. returns None if no due date is near. used by the reminder signal."""
    for yr in (as_of.year - 1, as_of.year, as_of.year + 1):
        for label, start, end, due, due_next in _QUARTERS:
            due_date = datetime.date(yr + 1 if due_next else yr, *due)
            delta = (due_date - as_of).days
            if 0 <= delta <= window_days:
                s = datetime.date(yr, *start)
                e = datetime.date(yr, *end)
                return {
                    "label": label,
                    "start": s.isoformat(),
                    "end": e.isoformat(),
                    "due": due_date.isoformat(),
                    "days": delta,
                }
    return None


def due_quarter_income(db, q):
    """income earned in a resolved quarter window `q` (from upcoming_due)."""
    total = sum(
        t.amount or 0.0 for t in _income_txns(db) if q["start"] <= (t.date or "")[:10] <= q["end"]
    )
    return round(total, 2)
