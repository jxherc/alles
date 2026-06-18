from collections import defaultdict
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, Account, Transaction, Budget

router = APIRouter(prefix="/api/money")


# ── accounts ────────────────────────────────────────────────────────────────
def _balances(db):
    bal = defaultdict(float)
    for t in db.query(Transaction).all():
        bal[t.account_id] += t.amount or 0.0
    return bal


def _acct(a, balance):
    return {
        "id": a.id,
        "name": a.name,
        "kind": a.kind,
        "currency": a.currency,
        "opening": a.opening,
        "color": a.color,
        "archived": bool(a.archived),
        "balance": round(balance, 2),
    }


@router.get("/accounts")
def list_accounts(db: DbSession = Depends(get_db)):
    bal = _balances(db)
    rows = db.query(Account).order_by(Account.created_at.asc()).all()
    return [_acct(a, (a.opening or 0.0) + bal.get(a.id, 0.0)) for a in rows]


class AccountBody(BaseModel):
    name: str
    kind: str = "checking"
    currency: str = "$"
    opening: float = 0.0
    color: str = "accent"


@router.post("/accounts")
def create_account(body: AccountBody, db: DbSession = Depends(get_db)):
    a = Account(
        name=(body.name or "account").strip() or "account",
        kind=body.kind,
        currency=body.currency or "$",
        opening=body.opening or 0.0,
        color=body.color or "accent",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return _acct(a, a.opening or 0.0)


@router.patch("/accounts/{aid}")
def update_account(aid: str, body: dict, db: DbSession = Depends(get_db)):
    a = db.get(Account, aid)
    if not a:
        raise HTTPException(404)
    for k in ("name", "kind", "currency", "opening", "color", "archived"):
        if k in body:
            setattr(a, k, body[k])
    db.commit()
    bal = _balances(db)
    return _acct(a, (a.opening or 0.0) + bal.get(a.id, 0.0))


@router.delete("/accounts/{aid}")
def delete_account(aid: str, db: DbSession = Depends(get_db)):
    a = db.get(Account, aid)
    if not a:
        raise HTTPException(404)
    db.query(Transaction).filter(Transaction.account_id == aid).delete()
    db.delete(a)
    db.commit()
    return {"ok": True}


# ── transactions ──────────────────────────────────────────────────────────────
def _txn(t):
    return {
        "id": t.id,
        "account_id": t.account_id,
        "date": t.date,
        "amount": t.amount,
        "category": t.category,
        "payee": t.payee,
        "notes": t.notes,
    }


@router.get("/transactions")
def list_txns(
    account: str = "",
    month: str = "",
    category: str = "",
    limit: int = 500,
    db: DbSession = Depends(get_db),
):
    q = db.query(Transaction)
    if account:
        q = q.filter(Transaction.account_id == account)
    if category:
        q = q.filter(Transaction.category == category)
    if month:  # month = "YYYY-MM"
        q = q.filter(Transaction.date.like(f"{month}%"))
    rows = q.order_by(Transaction.date.desc(), Transaction.created_at.desc()).limit(limit).all()
    return [_txn(t) for t in rows]


class TxnBody(BaseModel):
    account_id: str
    date: str
    amount: float
    category: str = ""
    payee: str = ""
    notes: str = ""


@router.post("/transactions")
def create_txn(body: TxnBody, db: DbSession = Depends(get_db)):
    if not db.get(Account, body.account_id):
        raise HTTPException(400, "unknown account")
    t = Transaction(
        account_id=body.account_id,
        date=body.date,
        amount=body.amount,
        category=(body.category or "").strip(),
        payee=(body.payee or "").strip(),
        notes=(body.notes or "").strip(),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _txn(t)


@router.patch("/transactions/{tid}")
def update_txn(tid: str, body: dict, db: DbSession = Depends(get_db)):
    t = db.get(Transaction, tid)
    if not t:
        raise HTTPException(404)
    for k in ("account_id", "date", "amount", "category", "payee", "notes"):
        if k in body:
            setattr(t, k, body[k])
    db.commit()
    return _txn(t)


@router.delete("/transactions/{tid}")
def delete_txn(tid: str, db: DbSession = Depends(get_db)):
    t = db.get(Transaction, tid)
    if not t:
        raise HTTPException(404)
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.get("/transactions/export.csv")
def export_txns_csv(db: DbSession = Depends(get_db)):
    """download all transactions as CSV (open in a spreadsheet)."""
    import csv, io
    from fastapi.responses import Response

    def _safe(v):
        # neutralize spreadsheet formula injection: a cell starting with =,+,-,@
        # (or a leading tab/CR) is run as a formula by Excel/Sheets/LibreOffice.
        s = "" if v is None else str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "amount", "category", "payee", "notes", "account_id"])
    for t in db.query(Transaction).order_by(Transaction.date).all():
        w.writerow(
            [
                t.date,
                t.amount,
                _safe(t.category or ""),
                _safe(t.payee or ""),
                _safe(t.notes or ""),
                t.account_id,
            ]
        )
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"content-disposition": 'attachment; filename="transactions.csv"'},
    )


class CsvImport(BaseModel):
    csv: str
    account_id: str


@router.post("/transactions/import.csv")
def import_txns_csv(body: CsvImport, db: DbSession = Depends(get_db)):
    """import transactions from a CSV (e.g. a bank export). needs date + amount
    columns. skips rows that duplicate an existing txn (same date+amount+payee in
    this account) so re-importing an overlapping statement doesn't double-count."""
    import csv, io

    if not db.get(Account, body.account_id):
        raise HTTPException(400, "unknown account")
    # existing fingerprints for this account + dups within the file itself
    seen = {
        (t.date, round(t.amount or 0.0, 2), (t.payee or "").strip().lower())
        for t in db.query(Transaction).filter(Transaction.account_id == body.account_id).all()
    }
    n = skipped = 0
    for row in csv.DictReader(io.StringIO(body.csv)):
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        date = (row.get("date") or "").strip()
        try:
            amt = float(str(row.get("amount") or "").replace(",", "").replace("$", "").strip())
        except ValueError:
            continue
        if not date:
            continue
        payee = (row.get("payee") or row.get("description") or "").strip()
        key = (date[:10], round(amt, 2), payee.lower())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        db.add(
            Transaction(
                account_id=body.account_id,
                date=date[:10],
                amount=amt,
                category=(row.get("category") or "").strip(),
                payee=payee,
                notes=(row.get("notes") or "").strip(),
            )
        )
        n += 1
    db.commit()
    return {"imported": n, "skipped": skipped}


# ── budgets (monthly spending caps per category) ──────────────────────────────
@router.get("/budgets")
def list_budgets(db: DbSession = Depends(get_db)):
    return [
        {"id": b.id, "category": b.category, "limit_amt": b.limit_amt}
        for b in db.query(Budget).order_by(Budget.category.asc()).all()
    ]


class BudgetBody(BaseModel):
    category: str
    limit_amt: float = 0.0


@router.post("/budgets")
def upsert_budget(body: BudgetBody, db: DbSession = Depends(get_db)):
    cat = (body.category or "").strip()
    if not cat:
        raise HTTPException(400, "category required")
    b = db.query(Budget).filter(Budget.category == cat).first()
    if b:
        b.limit_amt = body.limit_amt
    else:
        b = Budget(category=cat, limit_amt=body.limit_amt)
        db.add(b)
    db.commit()
    db.refresh(b)
    return {"id": b.id, "category": b.category, "limit_amt": b.limit_amt}


@router.delete("/budgets/{bid}")
def delete_budget(bid: str, db: DbSession = Depends(get_db)):
    b = db.get(Budget, bid)
    if not b:
        raise HTTPException(404)
    db.delete(b)
    db.commit()
    return {"ok": True}


# ── summary — powers the cards + charts ───────────────────────────────────────
def _recent_months(month: str, n: int = 6):
    base = datetime.strptime(month + "-01", "%Y-%m-%d")
    y, m = base.year, base.month
    out = []
    for i in range(n - 1, -1, -1):
        mm, yy = m - i, y
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


@router.get("/summary")
def summary(month: str = "", db: DbSession = Depends(get_db)):
    if not month:
        month = datetime.utcnow().strftime("%Y-%m")
    accounts = db.query(Account).all()
    bal = _balances(db)
    net_worth = sum((a.opening or 0.0) + bal.get(a.id, 0.0) for a in accounts if not a.archived)

    income = expense = 0.0
    by_cat = defaultdict(float)
    for t in db.query(Transaction).filter(Transaction.date.like(f"{month}%")).all():
        amt = t.amount or 0.0
        if amt >= 0:
            income += amt
        else:
            expense += -amt
            by_cat[(t.category or "uncategorized")] += -amt
    cats = sorted(([c, round(v, 2)] for c, v in by_cat.items()), key=lambda x: -x[1])

    budgets = []
    for b in db.query(Budget).order_by(Budget.category.asc()).all():
        budgets.append(
            {
                "category": b.category,
                "limit": b.limit_amt,
                "spent": round(by_cat.get(b.category, 0.0), 2),
            }
        )

    months = _recent_months(month, 6)
    monthset = set(months)
    tot = {mo: [0.0, 0.0] for mo in months}  # [income, expense]
    for t in db.query(Transaction).all():
        mo = (t.date or "")[:7]
        if mo in monthset:
            amt = t.amount or 0.0
            if amt >= 0:
                tot[mo][0] += amt
            else:
                tot[mo][1] += -amt
    trend = [
        {"month": mo, "income": round(tot[mo][0], 2), "expense": round(tot[mo][1], 2)}
        for mo in months
    ]

    return {
        "month": month,
        "net_worth": round(net_worth, 2),
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "by_category": cats,
        "budgets": budgets,
        "trend": trend,
        "currency": accounts[0].currency if accounts else "$",
    }
