"""Finance spending totals, category anomalies, and merchant insights."""

import calendar
import math
from collections import defaultdict

from sqlalchemy import func

from core.database import Transaction, TxnSplit
from services.forecast import _recent_months, category_averages
from services.money_query import _norm_payee


def finite_amount(value):
    """Keep a corrupt numeric row from breaking Finance read responses."""
    return value if isinstance(value, (int, float)) and math.isfinite(value) else 0.0


def balance_deltas(db):
    by_account = defaultdict(float)
    rows = (
        db.query(Transaction.account_id, func.sum(Transaction.amount))
        .group_by(Transaction.account_id)
        .all()
    )
    for account_id, total in rows:
        by_account[account_id] = finite_amount(total or 0.0)
    return by_account


def networth_history(accounts, transactions, *, end_month, months):
    """Month-end net worth from one ledger's opening balances and dated transactions."""
    open_accounts = {row["id"] for row in accounts if not row["archived"]}
    balance = sum((row["opening"] or 0.0) for row in accounts if not row["archived"])
    rows = sorted(
        (row for row in transactions if row["account_id"] in open_accounts),
        key=lambda row: row["date"] or "",
    )
    year, month = (int(part) for part in end_month.split("-"))
    sequence = []
    for _ in range(max(1, months)):
        sequence.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    result = []
    index = 0
    for period in reversed(sequence):
        period_year, period_month = int(period[:4]), int(period[5:7])
        cutoff = f"{period}-{calendar.monthrange(period_year, period_month)[1]:02d}"
        while index < len(rows) and (rows[index]["date"] or "") <= cutoff:
            balance += rows[index]["amount"] or 0.0
            index += 1
        result.append({"month": period, "net_worth": round(balance, 2)})
    return result


def net_worth_at(accounts, transactions, on_date):
    """Balance of open accounts from openings and transactions through one date."""
    open_accounts = {row["id"] for row in accounts if not row["archived"]}
    total = sum((row["opening"] or 0.0) for row in accounts if not row["archived"])
    for row in transactions:
        if row["account_id"] in open_accounts and (row["date"] or "") <= on_date:
            total += row["amount"] or 0.0
    return round(total, 2)


def distribute_expense(txn, splits_by_txn, by):
    """Add one expense transaction to category totals, honoring split remainders."""
    amt = txn.amount or 0.0
    splits = splits_by_txn.get(txn.id)
    if splits:
        covered = 0.0
        for split in splits:
            by[split.category or "uncategorized"] += split.amount or 0.0
            covered += split.amount or 0.0
        remainder = round(-amt - covered, 2)
        if remainder > 0:
            by[txn.category or "uncategorized"] += remainder
    else:
        by[txn.category or "uncategorized"] += -amt


def spending_by_category(db, month, upto=False, txns=None, splits_by_txn=None):
    """Expense totals for one month, or cumulatively through it with ``upto=True``."""
    if splits_by_txn is None:
        splits_by_txn = defaultdict(list)
        for split in db.query(TxnSplit).all():
            splits_by_txn[split.txn_id].append(split)
    by = defaultdict(float)
    rows = txns if txns is not None else db.query(Transaction).all()
    for txn in rows:
        if txn.transfer_id or (txn.amount or 0.0) >= 0:
            continue
        txn_month = (txn.date or "")[:7]
        if (txn_month > month) if upto else (txn_month != month):
            continue
        distribute_expense(txn, splits_by_txn, by)
    return by


def category_anomalies(db, *, as_of, months=3, ratio=1.5, min_amount=50.0, cur=None):
    """categories whose THIS-month spend is >= ratio x the historical monthly average.
    pass `cur` (this month's spend-by-category) to reuse an already-computed dict and
    skip a redundant full transaction scan."""
    avg = category_averages(db, months=months, as_of=as_of)
    if cur is None:
        cur = spending_by_category(db, as_of.strftime("%Y-%m"))
    out = []
    for cat, spent in cur.items():
        base = avg.get(cat, 0.0)
        if spent >= min_amount and base > 0 and spent >= base * ratio:
            out.append(
                {
                    "category": cat,
                    "current": round(spent, 2),
                    "baseline": round(base, 2),
                    "ratio": round(spent / base, 2),
                }
            )
    return sorted(out, key=lambda x: -x["ratio"])


def new_merchants(db, *, as_of, months=3, min_amount=20.0):
    """normalized merchants seen THIS month but not in the prior `months`."""
    from sqlalchemy import or_

    from core.database import Account, Transaction

    cur_month = as_of.strftime("%Y-%m")
    prior = set(_recent_months(as_of, months))
    accts = {a.id for a in db.query(Account).filter_by(archived=False).all()}
    cur_m, prior_m = {}, set()
    # Merchant insights exclude archived accounts; current spending totals include them.
    # Apply the narrower predicates in SQL before inspecting merchant names.
    rows = (
        db.query(Transaction)
        .filter(
            Transaction.account_id.in_(accts),
            Transaction.amount < 0,
            or_(Transaction.transfer_id.is_(None), Transaction.transfer_id == ""),
        )
        .all()
        if accts
        else []
    )
    for t in rows:
        m = _norm_payee(t.payee or "")
        if not m:
            continue
        mo = (t.date or "")[:7]
        if mo == cur_month:
            cur_m[m] = cur_m.get(m, 0.0) + (-(t.amount or 0.0))
        elif mo in prior:
            prior_m.add(m)
    return [
        {"merchant": m, "amount": round(v, 2)}
        for m, v in sorted(cur_m.items(), key=lambda x: -x[1])
        if m not in prior_m and v >= min_amount
    ]
