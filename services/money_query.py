"""2a - natural-language spending queries. pure + testable: temporal parsing, merchant rollups,
category breakdowns, period comparison. the money_query agent tool calls answer().
"""

import calendar
import re
from datetime import date, timedelta

MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def _last_day(y, m):
    return date(y, m, calendar.monthrange(y, m)[1])


def parse_period(text, today=None):
    """(start, end, label) for a temporal phrase. defaults to this month."""
    today = today or date.today()
    t = (text or "").lower()
    y, m = today.year, today.month
    if "last year" in t:
        return date(y - 1, 1, 1), date(y - 1, 12, 31), "last year"
    if "this year" in t or "year to date" in t or "ytd" in t:
        return date(y, 1, 1), today, "this year"
    md = re.search(r"last (\d+) days?", t)
    if md:
        n = int(md.group(1))
        return today - timedelta(days=n), today, f"last {n} days"
    # this-month before last-month so "this month vs last month" parses to this month (primary)
    if "this month" in t:
        return date(y, m, 1), today, "this month"
    if "last month" in t:
        pm, py = (m - 1, y) if m > 1 else (12, y - 1)
        return date(py, pm, 1), _last_day(py, pm), "last month"
    for i, name in enumerate(MONTHS, 1):
        if name in t:
            yy = y if i <= m else y - 1  # most recent occurrence
            return date(yy, i, 1), _last_day(yy, i), name
    return date(y, m, 1), today, "this month"


def _prev_period(start, end, label):
    if label == "this month":
        # this month is partial (1st..today) — compare against last month truncated to the same
        # day so it's month-to-date vs month-to-date, not vs a full month (a false "spent less")
        pm, py = (start.month - 1, start.year) if start.month > 1 else (12, start.year - 1)
        last = _last_day(py, pm).day
        return date(py, pm, 1), date(py, pm, min(end.day, last)), "last month"
    if label == "last month":
        pm, py = (start.month - 1, start.year) if start.month > 1 else (12, start.year - 1)
        return date(py, pm, 1), _last_day(py, pm), MONTHS[pm - 1]
    length = (end - start).days
    pend = start - timedelta(days=1)
    return pend - timedelta(days=length), pend, "the prior period"


def _norm_payee(p):
    s = (p or "").lower().strip()
    s = s.split("*")[0]  # amazon.com*A1B2C -> amazon.com
    s = re.sub(r"#.*$", "", s)  # starbucks #1234 -> starbucks
    s = re.sub(r"\s+\d+\s*$", "", s)  # trailing store numbers
    return s.strip()


def merchant_rollup(txns, top=10):
    roll = {}
    for t in txns:
        amt = getattr(t, "amount", 0) or 0
        if amt >= 0:
            continue
        m = _norm_payee(getattr(t, "payee", "") or "")
        if not m:
            continue
        roll[m] = roll.get(m, 0.0) + (-amt)
    return sorted(roll.items(), key=lambda x: -x[1])[:top]


def category_breakdown(txns):
    cb = {}
    for t in txns:
        amt = getattr(t, "amount", 0) or 0
        if amt >= 0:
            continue
        c = getattr(t, "category", "") or "uncategorized"
        cb[c] = cb.get(c, 0.0) + (-amt)
    return sorted(cb.items(), key=lambda x: -x[1])


def _period_txns(db, start, end):
    from core.database import Account, Transaction

    accts = {a.id for a in db.query(Account).filter_by(archived=False).all()}
    if not accts:
        return []
    # half-open date range on the stored ISO string: a same-day timed txn ('...Thh:mm') still
    # counts (matches the old [:10] python filter) without a full-table scan
    lo, hi = start.isoformat(), (end + timedelta(days=1)).isoformat()
    return (
        db.query(Transaction)
        .filter(Transaction.account_id.in_(accts), Transaction.date >= lo, Transaction.date < hi)
        .all()
    )


def answer(db, query, today=None):
    """a narrative answer to a spending question: period total + top categories + merchants,
    with an optional comparison to the preceding period."""
    today = today or date.today()
    start, end, label = parse_period(query, today)
    txns = _period_txns(db, start, end)
    spend = [t for t in txns if (t.amount or 0) < 0]
    spent = sum(-(t.amount or 0.0) for t in spend)
    lines = [f"{label}: spent {spent:.2f} across {len(spend)} transactions"]
    cb = category_breakdown(txns)[:5]
    if cb:
        lines.append("top categories: " + ", ".join(f"{c} {v:.2f}" for c, v in cb))
    mr = merchant_rollup(txns)[:5]
    if mr:
        lines.append("top merchants: " + ", ".join(f"{m} {v:.2f}" for m, v in mr))
    q = (query or "").lower()
    if any(k in q for k in ("compare", " vs ", "vs.", "month-over-month", "month over month")):
        pstart, pend, plabel = _prev_period(start, end, label)
        ptxns = _period_txns(db, pstart, pend)
        pspent = sum(-(t.amount or 0.0) for t in ptxns if (t.amount or 0) < 0)
        delta = spent - pspent
        lines.append(f"vs {plabel}: spent {pspent:.2f} ({'+' if delta >= 0 else ''}{delta:.2f})")
    return "\n".join(lines)
