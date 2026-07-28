import calendar as _cal
import functools
import hashlib
import inspect
import math
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DbSession

from core.database import (
    Account,
    Budget,
    BudgetAssignment,
    CategoryRule,
    FinanceLedgerState,
    FundingTarget,
    Goal,
    Holding,
    RecurringTxn,
    TagRule,
    Transaction,
    TxnSplit,
    Watch,
    get_db,
)
from services import actual_finance, finance_currency, fx


def _actual_error(exc: actual_finance.ActualFinanceError):
    status_code = 503 if isinstance(exc, actual_finance.ActualFinanceUnavailable) else 409
    raise HTTPException(status_code, str(exc)) from exc


def _legacy_ledger_mutation(method: str, path: str) -> bool:
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    normalized = path.strip("/")
    if normalized == "api/money":
        normalized = ""
    elif normalized.startswith("api/money/"):
        normalized = normalized.removeprefix("api/money/")
    parts = normalized.split("/") if normalized else []
    return (
        parts[:1] == ["recurring"]
        or parts[:1] == ["envelope"]
        or parts in (["rules", "apply"], ["tag-rules", "apply"])
        or (
            parts[:1] == ["transactions"]
            and not (
                (method == "POST" and parts == ["transactions"])
                or (method in {"PATCH", "DELETE"} and len(parts) == 2)
            )
        )
    )


def _money_authority(path: str, methods: set[str], endpoint):
    """Run the authority snapshot and endpoint inside one worker-thread lock lifetime."""
    signature = inspect.signature(endpoint)

    @functools.wraps(endpoint)
    def guarded(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        db = bound.arguments.get("db")
        if db is None:
            raise RuntimeError("Finance route authority requires its request database session")
        with actual_finance.AUTHORITY_LOCK:
            canonical = actual_finance.is_canonical(db)
            if canonical and any(_legacy_ledger_mutation(method, path) for method in methods):
                raise HTTPException(
                    409,
                    "this legacy Finance action is read-only after Actual cutover",
                )
            return endpoint(*args, **kwargs)

    guarded._alles_authority_same_thread = True
    return guarded


def _money_preflight(request: Request, db: DbSession = Depends(get_db)) -> None:
    """Reject legacy writes before body validation without holding a lock across a yield."""
    with actual_finance.AUTHORITY_LOCK:
        if actual_finance.is_canonical(db) and _legacy_ledger_mutation(
            request.method.upper(), request.url.path
        ):
            raise HTTPException(
                409,
                "this legacy Finance action is read-only after Actual cutover",
            )


class _MoneyAuthorityRoute(APIRoute):
    def __init__(self, path, endpoint, *, methods=None, **kwargs):
        normalized_methods = {str(method).upper() for method in (methods or {"GET"})}
        super().__init__(
            path,
            _money_authority(path, normalized_methods, endpoint),
            methods=methods,
            **kwargs,
        )


def _require_actual_backed_analytics(db: DbSession, feature: str) -> None:
    """Do not present frozen legacy calculations after Actual becomes canonical."""
    if actual_finance.is_canonical(db):
        raise HTTPException(
            409,
            f"{feature} is unavailable after Actual cutover until it is calculated from the canonical ledger",
        )


def _require_legacy_ledger_write(db: DbSession) -> None:
    """Keep retained migration tables immutable once Actual owns the ledger."""
    if actual_finance.is_canonical(db):
        raise HTTPException(409, "this legacy Finance action is read-only after Actual cutover")


router = APIRouter(
    prefix="/api/money",
    dependencies=[Depends(_money_preflight)],
    route_class=_MoneyAuthorityRoute,
)

RECUR_CYCLES = ("weekly", "monthly", "quarterly", "yearly", "custom")


def _like_esc(s: str) -> str:
    """escape LIKE wildcards so a search term with % or _ matches literally, not as a wildcard."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _need_floats(body, *fields):
    """coerce the named body fields to finite floats in place; 400 on junk. the dict PATCH
    routes setattr numeric fields raw, so bad input used to bubble up as an ugly 500."""
    for f in fields:
        if f in body and body[f] is not None:
            try:
                v = float(body[f])
            except (TypeError, ValueError):
                raise HTTPException(400, f"{f} must be a number")
            if not math.isfinite(v):
                raise HTTPException(400, f"{f} must be a finite number")
            body[f] = v


def _prepare_money(action, *, detail="amount is outside the supported range"):
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(400, detail) from exc


def _add_months(d: date, n: int, anchor: int | None = None) -> date:
    # clamp from the ANCHOR day (original day-of-month), not the possibly-already-clamped d.day, so a
    # bill due the 31st goes 31 -> feb 28 -> mar 31 instead of drifting down to the 28th forever
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(anchor or d.day, _cal.monthrange(y, m)[1]))


def _advance(d: date, cycle: str, cycle_days: int, anchor: int | None = None) -> date:
    if cycle == "weekly":
        return d + timedelta(days=7)
    if cycle == "monthly":
        return _add_months(d, 1, anchor)
    if cycle == "quarterly":
        return _add_months(d, 3, anchor)
    if cycle == "yearly":
        return _add_months(d, 12, anchor)
    return d + timedelta(days=max(1, cycle_days or 30))


# ── accounts ────────────────────────────────────────────────────────────────
def _fin(x):
    """non-finite (nan/inf) amounts brick JSON serialization + every money read. coerce to 0 on the
    read path so one poisoned row can't take down the whole section, and reject them on input."""
    return x if isinstance(x, (int, float)) and math.isfinite(x) else 0.0


def _balances(db):
    from sqlalchemy import func

    bal = defaultdict(float)
    rows = (
        db.query(Transaction.account_id, func.sum(Transaction.amount))
        .group_by(Transaction.account_id)
        .all()
    )
    for acct_id, total in rows:
        bal[acct_id] = _fin(total or 0.0)
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
        "low_balance": a.low_balance or 0.0,
        "balance": round(balance, 2),
        "currency_code": a.currency_code or finance_currency.currency_code(a.currency),
        "base_currency_code": a.base_currency_code or "",
        "original_opening_text": a.original_opening_text
        or finance_currency.decimal_text(a.opening),
        "base_opening_text": a.base_opening_text or "",
        "opening_fx_rate_text": a.opening_fx_rate_text or "",
        "opening_fx_rate_date": a.opening_fx_rate_date or "",
        "opening_fx_source": a.opening_fx_source or "",
    }


@router.get("/accounts")
def list_accounts(db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            return actual_finance.accounts(db)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    bal = _balances(db)
    rows = db.query(Account).order_by(Account.created_at.asc()).all()
    return [_acct(a, (a.opening or 0.0) + bal.get(a.id, 0.0)) for a in rows]


class AccountBody(BaseModel):
    name: str
    kind: str = "checking"
    currency: str = "$"
    opening: float = 0.0
    color: str = "accent"
    low_balance: float = 0.0
    request_id: str = ""


@router.post("/accounts")
def create_account(body: AccountBody, db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            values = body.model_dump()
            if "currency" not in body.model_fields_set:
                values.pop("currency", None)
            request_id = values.pop("request_id", "")
            return actual_finance.create_account(db, values, request_id=request_id)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    a = Account(
        name=(body.name or "account").strip() or "account",
        kind=body.kind,
        currency=body.currency or "$",
        opening=body.opening or 0.0,
        color=body.color or "accent",
        low_balance=body.low_balance or 0.0,
    )
    _prepare_money(lambda: finance_currency.prepare_account(a), detail="opening balance is invalid")
    db.add(a)
    db.commit()
    db.refresh(a)
    return _acct(a, a.opening or 0.0)


@router.patch("/accounts/{aid}")
def update_account(aid: str, body: dict, db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            return actual_finance.update_account(db, aid, body)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    a = db.get(Account, aid)
    if not a:
        raise HTTPException(404)
    _need_floats(body, "opening", "low_balance")
    for k in ("name", "kind", "currency", "opening", "color", "archived", "low_balance"):
        if k in body:
            setattr(a, k, body[k])
    if "currency" in body:
        _prepare_money(
            lambda: finance_currency.prepare_account(a), detail="opening balance is invalid"
        )
    elif "opening" in body:
        _prepare_money(
            lambda: finance_currency.refresh_account_opening(a),
            detail="opening balance is invalid",
        )
    db.commit()
    bal = _balances(db)
    return _acct(a, (a.opening or 0.0) + bal.get(a.id, 0.0))


@router.delete("/accounts/{aid}")
def delete_account(aid: str, db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            return actual_finance.close_account(db, aid)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    a = db.get(Account, aid)
    if not a:
        raise HTTPException(404)
    # transfer legs share a string transfer_id (no FK), so unlink the partner legs in
    # other accounts before we nuke this account's txns — keeps the moved money as plain txns
    xfer_ids = [
        x[0]
        for x in db.query(Transaction.transfer_id)
        .filter(Transaction.account_id == aid, Transaction.transfer_id != "")
        .all()
    ]
    if xfer_ids:
        db.query(Transaction).filter(
            Transaction.transfer_id.in_(xfer_ids), Transaction.account_id != aid
        ).update({Transaction.transfer_id: ""}, synchronize_session=False)
    db.query(Transaction).filter(Transaction.account_id == aid).delete()
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/accounts/{aid}/reconcile")
def reconcile(aid: str, statement: float = 0.0, db: DbSession = Depends(get_db)):
    """compare the cleared balance (opening + cleared txns) against a statement balance (4a)."""
    if actual_finance.is_canonical(db):
        try:
            actual = actual_finance.inspect(db)
            rows = actual_finance.transactions(db, actual=actual)
            account = next(
                (row for row in actual_finance.accounts(db, actual=actual) if row["id"] == aid),
                None,
            )
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
        if not account:
            raise HTTPException(404, "unknown account")
        uncleared = sum(
            row["amount"] for row in rows if row["account_id"] == aid and not row["cleared"]
        )
        cleared_balance = round(account["balance"] - uncleared, 2)
        diff = round(statement - cleared_balance, 2)
        return {
            "account_id": aid,
            "cleared_balance": cleared_balance,
            "statement": round(statement, 2),
            "difference": diff,
            "reconciled": abs(diff) < 0.005,
        }
    a = db.get(Account, aid)
    if not a:
        raise HTTPException(404, "unknown account")
    cleared = sum(
        t.amount or 0.0
        for t in db.query(Transaction)
        .filter(Transaction.account_id == aid, Transaction.cleared == True)  # noqa: E712
        .all()
    )
    cleared_balance = round((a.opening or 0.0) + cleared, 2)
    diff = round(statement - cleared_balance, 2)
    return {
        "account_id": aid,
        "cleared_balance": cleared_balance,
        "statement": round(statement, 2),
        "difference": diff,
        "reconciled": abs(diff) < 0.005,
    }


# ── auto-categorization rules (payee substring → category) ────────────────────
def _categorize(payee: str, rules) -> str:
    """first rule whose match is a (case-insensitive) substring of the payee wins."""
    p = (payee or "").lower()
    if not p:
        return ""
    for r in rules:
        m = (r.match or "").lower()
        if m and m in p:
            return r.category or ""
    return ""


def _rules(db):
    return db.query(CategoryRule).order_by(CategoryRule.created_at.asc()).all()


def _tag_rules(db):
    return db.query(TagRule).order_by(TagRule.created_at.asc()).all()


def _distribute(t, splits_by_txn, by):
    """add one expense txn's magnitude into `by` (cat→spent), honoring splits."""
    amt = t.amount or 0.0
    sp = splits_by_txn.get(t.id)
    if sp:
        covered = 0.0
        for s in sp:
            by[s.category or "uncategorized"] += s.amount or 0.0
            covered += s.amount or 0.0
        rem = round(-amt - covered, 2)
        if rem > 0:
            by[(t.category or "uncategorized")] += rem
    else:
        by[(t.category or "uncategorized")] += -amt


def _spending_by_cat(db, month, upto=False, txns=None, splits_by_txn=None):
    """expense per category for a month (or cumulatively through it, `upto=True`),
    honoring splits + excluding transfers. shared by summary + the envelope view (4b)."""
    if splits_by_txn is None:
        splits_by_txn = defaultdict(list)
        for s in db.query(TxnSplit).all():
            splits_by_txn[s.txn_id].append(s)
    by = defaultdict(float)
    _txns = txns if txns is not None else db.query(Transaction).all()
    for t in _txns:
        if t.transfer_id or (t.amount or 0.0) >= 0:
            continue
        mo = (t.date or "")[:7]
        if (mo > month) if upto else (mo != month):
            continue
        _distribute(t, splits_by_txn, by)
    return by


# ── transactions ──────────────────────────────────────────────────────────────
def _norm_tags(s):
    """csv tags → lowercased, trimmed, de-duped, order-preserving."""
    seen, out = set(), []
    for t in (s or "").split(","):
        t = t.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out)


def _txn(t):
    return {
        "id": t.id,
        "account_id": t.account_id,
        "date": t.date,
        "amount": _fin(t.amount),
        "category": t.category,
        "payee": t.payee,
        "notes": t.notes,
        "transfer_id": t.transfer_id or "",
        "tags": t.tags or "",
        "receipt_id": t.receipt_id or "",
        "cleared": bool(t.cleared),
        "original_amount_text": t.original_amount_text
        or finance_currency.decimal_text(_fin(t.amount)),
        "original_currency_code": t.original_currency_code or "",
        "base_amount_text": t.base_amount_text or "",
        "base_currency_code": t.base_currency_code or "",
        "import_identity": t.import_identity or "",
        "import_batch_id": t.import_batch_id or "",
        "import_source": t.import_source or "",
    }


@router.get("/transactions")
def list_txns(
    account: str = "",
    month: str = "",
    category: str = "",
    tag: str = "",
    limit: int = 500,
    db: DbSession = Depends(get_db),
):
    if actual_finance.is_canonical(db):
        try:
            rows = actual_finance.transactions(db)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
        if account:
            rows = [row for row in rows if row["account_id"] == account]
        if category:
            rows = [row for row in rows if row["category"] == category]
        if tag:
            wanted = tag.strip().lower()
            rows = [
                row
                for row in rows
                if wanted
                in {item.strip().lower() for item in row["tags"].split(",") if item.strip()}
            ]
        if month:
            rows = [row for row in rows if row["date"].startswith(month)]
        limit = max(1, min(int(limit), 10000))
        return sorted(rows, key=lambda row: (row["date"], row["id"]), reverse=True)[:limit]
    _post_due_recurring(db)
    limit = max(1, min(int(limit), 10000))  # clamp: a huge value overflows sqlite's INTEGER -> 500
    q = db.query(Transaction)
    if account:
        q = q.filter(Transaction.account_id == account)
    if category:
        q = q.filter(Transaction.category == category)
    if tag:  # tags are stored csv-normalized → substring match on a single tag
        q = q.filter(Transaction.tags.like(f"%{_like_esc(tag.strip().lower())}%", escape="\\"))
    if month:  # month = "YYYY-MM"
        q = q.filter(Transaction.date.like(f"{month}%"))
    rows = q.order_by(Transaction.date.desc(), Transaction.created_at.desc()).limit(limit).all()
    # only check splits for the rows we're returning, not the whole splits table
    ids = [t.id for t in rows]
    split_ids = (
        {r[0] for r in db.query(TxnSplit.txn_id).filter(TxnSplit.txn_id.in_(ids)).distinct().all()}
        if ids
        else set()
    )
    out = []
    for t in rows:
        d = _txn(t)
        d["split"] = t.id in split_ids
        out.append(d)
    return out


@router.get("/transactions/search")
def search_txns(
    q: str = "",
    min_amt: float = None,
    max_amt: float = None,
    account: str = "",
    month: str = "",
    limit: int = 500,
    db: DbSession = Depends(get_db),
):
    """text search across payee/category/notes + filter by |amount| range, account,
    month. date-desc. answers 'what did I spend at X' / 'charges over $100'."""
    if actual_finance.is_canonical(db):
        try:
            rows = actual_finance.transactions(db)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
        if account:
            rows = [row for row in rows if row["account_id"] == account]
        if month:
            rows = [row for row in rows if row["date"].startswith(month)]
        needle = (q or "").strip().casefold()
        if needle:
            rows = [
                row
                for row in rows
                if needle in " ".join((row["payee"], row["category"], row["notes"])).casefold()
            ]
        if min_amt is not None:
            rows = [row for row in rows if abs(row["amount"]) >= min_amt]
        if max_amt is not None:
            rows = [row for row in rows if abs(row["amount"]) <= max_amt]
        return sorted(rows, key=lambda row: (row["date"], row["id"]), reverse=True)[
            : max(1, min(int(limit), 10000))
        ]
    query = db.query(Transaction)
    if account:
        query = query.filter(Transaction.account_id == account)
    if month:
        query = query.filter(Transaction.date.like(f"{month}%"))
    ql = (q or "").strip().lower()
    if ql:  # push the text match into sql instead of scanning every row in python
        like = f"%{_like_esc(ql)}%"
        query = query.filter(
            or_(
                func.lower(Transaction.payee).like(like, escape="\\"),
                func.lower(Transaction.category).like(like, escape="\\"),
                func.lower(Transaction.notes).like(like, escape="\\"),
            )
        )
    if min_amt is not None:
        query = query.filter(func.abs(Transaction.amount) >= min_amt)
    if max_amt is not None:
        query = query.filter(func.abs(Transaction.amount) <= max_amt)
    rows = (
        query.order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .limit(max(1, limit))
        .all()
    )
    return [_txn(t) for t in rows]


class TxnBody(BaseModel):
    account_id: str
    date: str
    amount: float
    category: str = ""
    payee: str = ""
    notes: str = ""
    tags: str = ""
    receipt_id: str = ""
    cleared: bool = False
    request_id: str = ""


@router.post("/transactions")
def create_txn(body: TxnBody, db: DbSession = Depends(get_db)):
    if not math.isfinite(body.amount):
        raise HTTPException(400, "amount must be a finite number")
    values = {
        **body.model_dump(),
        "category": (body.category or "").strip(),
        "payee": (body.payee or "").strip(),
        "notes": (body.notes or "").strip(),
        "tags": _norm_tags(body.tags),
        "receipt_id": (body.receipt_id or "").strip(),
    }
    if actual_finance.is_canonical(db):
        try:
            request_id = values.pop("request_id", "")
            return actual_finance.create_transaction(db, values, request_id=request_id)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    if not values["category"]:  # legacy-only rules freeze at Actual cutover
        values["category"] = _categorize(body.payee, _rules(db))
    from services import tag_rules

    values["tags"] = tag_rules.apply_rules(body.payee, _tag_rules(db), existing=values["tags"])
    if not db.get(Account, body.account_id):
        raise HTTPException(400, "unknown account")
    t = Transaction(
        account_id=values["account_id"],
        date=values["date"],
        amount=values["amount"],
        category=values["category"],
        payee=values["payee"],
        notes=values["notes"],
        tags=values["tags"],
        receipt_id=values["receipt_id"],
        cleared=bool(values["cleared"]),
    )
    db.add(t)
    _prepare_money(lambda: finance_currency.prepare_transaction(db, t, source="manual_identity"))
    db.commit()
    db.refresh(t)
    return _txn(t)


@router.patch("/transactions/{tid}")
def update_txn(tid: str, body: dict, db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            return actual_finance.update_transaction(db, tid, body)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    t = db.get(Transaction, tid)
    if not t:
        raise HTTPException(404)
    # validate like create_txn does, or a bad PATCH silently corrupts a real money value
    if "amount" in body:
        try:
            body["amount"] = float(body["amount"])
        except (TypeError, ValueError):
            raise HTTPException(400, "amount must be a number")
        if not math.isfinite(body["amount"]):
            raise HTTPException(400, "amount must be a finite number")
    if "account_id" in body and not db.get(Account, body["account_id"]):
        raise HTTPException(400, "unknown account")
    for k in ("account_id", "date", "amount", "category", "payee", "notes", "receipt_id"):
        if k in body:
            setattr(t, k, body[k])
    if "tags" in body:
        t.tags = _norm_tags(body["tags"])
    if "cleared" in body:
        t.cleared = bool(body["cleared"])
    if "amount" in body or "account_id" in body:
        _prepare_money(
            lambda: finance_currency.prepare_transaction(db, t, source="manual_update_identity")
        )
    db.commit()
    return _txn(t)


@router.delete("/transactions/{tid}")
def delete_txn(tid: str, db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            return actual_finance.delete_transaction(db, tid)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    t = db.get(Transaction, tid)
    if not t:
        raise HTTPException(404)
    db.query(TxnSplit).filter(
        TxnSplit.txn_id == tid
    ).delete()  # FK cascade isn't enforced on sqlite
    db.delete(t)
    db.commit()
    return {"ok": True}


# ── splits (one charge across categories, 4a) ─────────────────────────────────
class SplitItem(BaseModel):
    category: str = ""
    amount: float = 0.0


class SplitsBody(BaseModel):
    splits: list[SplitItem] = []


@router.get("/transactions/{tid}/splits")
def get_splits(tid: str, db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        raise HTTPException(409, "transaction splits are managed in Actual after cutover")
    if not db.get(Transaction, tid):
        raise HTTPException(404)
    rows = (
        db.query(TxnSplit).filter(TxnSplit.txn_id == tid).order_by(TxnSplit.created_at.asc()).all()
    )
    return {"splits": [{"category": s.category, "amount": s.amount} for s in rows]}


@router.put("/transactions/{tid}/splits")
def put_splits(tid: str, body: SplitsBody, db: DbSession = Depends(get_db)):
    _require_legacy_ledger_write(db)
    t = db.get(Transaction, tid)
    if not t:
        raise HTTPException(404)
    # splits model how an expense divides across categories — _spending_by_cat skips
    # income (amount >= 0) and transfers, so splits on those would never show up.
    if t.transfer_id or (t.amount or 0.0) >= 0:
        raise HTTPException(400, "only an expense transaction can be split")
    items = [s for s in body.splits if (s.category or "").strip() and (s.amount or 0) > 0]
    total = round(sum(s.amount for s in items), 2)
    if total > round(abs(t.amount or 0.0), 2) + 0.005:
        raise HTTPException(400, "splits exceed the transaction amount")
    db.query(TxnSplit).filter(TxnSplit.txn_id == tid).delete()
    for s in items:
        db.add(TxnSplit(txn_id=tid, category=s.category.strip(), amount=round(s.amount, 2)))
    db.commit()
    return {
        "ok": True,
        "splits": [{"category": s.category.strip(), "amount": round(s.amount, 2)} for s in items],
    }


@router.get("/transactions/export.csv")
def export_txns_csv(db: DbSession = Depends(get_db)):
    """download all transactions as CSV (open in a spreadsheet)."""
    import csv
    import io

    from fastapi.responses import Response

    def _safe(v):
        # neutralize spreadsheet formula injection: a cell starting with =,+,-,@
        # (or a leading tab/CR) is run as a formula by Excel/Sheets/LibreOffice.
        s = "" if v is None else str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    buf = io.StringIO()
    w = csv.writer(buf)
    # include tags — import already reads a tags column, so without it an export→re-import
    # round-trip silently drops every transaction's tags
    w.writerow(["date", "amount", "category", "payee", "notes", "tags", "account_id"])
    if actual_finance.is_canonical(db):
        try:
            source_rows = sorted(actual_finance.transactions(db), key=lambda row: row["date"])
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    else:
        source_rows = db.query(Transaction).order_by(Transaction.date).all()
    for t in source_rows:
        value = t if isinstance(t, dict) else _txn(t)
        w.writerow(
            [
                value["date"],
                value["amount"],
                _safe(value["category"] or ""),
                _safe(value["payee"] or ""),
                _safe(value["notes"] or ""),
                _safe(value["tags"] or ""),
                value["account_id"],
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
    _require_legacy_ledger_write(db)
    import csv
    import io

    if not db.get(Account, body.account_id):
        raise HTTPException(400, "unknown account")
    # existing fingerprints for this account + dups within the file itself
    seen = {
        (t.date, round(t.amount or 0.0, 2), (t.payee or "").strip().lower())
        for t in db.query(Transaction).filter(Transaction.account_id == body.account_id).all()
    }
    seen_identities = {
        str(value)
        for (value,) in db.query(Transaction.import_identity)
        .filter(
            Transaction.account_id == body.account_id,
            Transaction.import_identity != "",
        )
        .all()
    }
    rules = _rules(db)  # auto-categorize rows that arrive without a category
    from services import tag_rules

    trules = _tag_rules(db)
    source_identity = hashlib.sha256(body.csv.encode()).hexdigest()
    n = skipped = 0
    for row_number, row in enumerate(csv.DictReader(io.StringIO(body.csv)), start=2):
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        date = (row.get("date") or "").strip()
        try:
            amt = float(str(row.get("amount") or "").replace(",", "").replace("$", "").strip())
        except ValueError:
            continue
        if not date or not math.isfinite(amt):  # 'inf'/'nan' parse fine but poison the section
            skipped += 1
            continue
        import_identity = finance_currency.stable_import_identity(
            "legacy-csv",
            body.account_id,
            occurrence_identity=f"{source_identity}:{row_number}",
        )
        if import_identity in seen_identities:
            skipped += 1
            continue
        payee = (row.get("payee") or row.get("description") or "").strip()
        key = (date[:10], round(amt, 2), payee.lower())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        cat = (row.get("category") or "").strip() or _categorize(payee, rules)
        transaction = Transaction(
            account_id=body.account_id,
            date=date[:10],
            amount=amt,
            category=cat,
            payee=payee,
            notes=(row.get("notes") or "").strip(),
            tags=tag_rules.apply_rules(payee, trules, existing=_norm_tags(row.get("tags") or "")),
        )
        transaction.import_identity = import_identity
        transaction.import_source = "legacy-csv"
        db.add(transaction)
        try:
            finance_currency.prepare_transaction(db, transaction, source="legacy-csv")
        except ValueError:
            db.expunge(transaction)
            skipped += 1
            continue
        seen_identities.add(import_identity)
        n += 1
    db.commit()
    return {"imported": n, "skipped": skipped}


class OfxImport(BaseModel):
    account_id: str
    ofx: str


@router.post("/transactions/import-ofx")
def import_txns_ofx(body: OfxImport, db: DbSession = Depends(get_db)):
    """import an OFX/QFX bank export (1f). same date+amount+payee dedup as CSV."""
    _require_legacy_ledger_write(db)
    from services import txn_ingest

    if not db.get(Account, body.account_id):
        raise HTTPException(400, "unknown account")
    seen = {
        (t.date, round(t.amount or 0.0, 2), (t.payee or "").strip().lower())
        for t in db.query(Transaction).filter(Transaction.account_id == body.account_id).all()
    }
    seen_identities = {
        str(value)
        for (value,) in db.query(Transaction.import_identity)
        .filter(
            Transaction.account_id == body.account_id,
            Transaction.import_identity != "",
        )
        .all()
    }
    rules = _rules(db)
    from services import tag_rules

    trules = _tag_rules(db)
    source_identity = hashlib.sha256(body.ofx.encode()).hexdigest()
    n = skipped = 0
    for row_number, row in enumerate(txn_ingest.parse_ofx(body.ofx), start=1):
        payee = (row.get("payee") or "").strip()
        if not math.isfinite(row.get("amount") or 0.0):
            skipped += 1
            continue
        import_identity = finance_currency.stable_import_identity(
            "legacy-ofx",
            body.account_id,
            external_id=str(row.get("fitid") or ""),
            occurrence_identity=f"{source_identity}:{row_number}",
        )
        if import_identity in seen_identities:
            skipped += 1
            continue
        key = (row["date"][:10], round(row["amount"], 2), payee.lower())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        transaction = Transaction(
            account_id=body.account_id,
            date=row["date"][:10],
            amount=row["amount"],
            category=_categorize(payee, rules),
            payee=payee,
            notes=(row.get("memo") or "").strip(),
            tags=tag_rules.apply_rules(payee, trules),
        )
        transaction.import_identity = import_identity
        transaction.import_source = "legacy-ofx"
        db.add(transaction)
        try:
            finance_currency.prepare_transaction(db, transaction, source="legacy-ofx")
        except ValueError:
            db.expunge(transaction)
            skipped += 1
            continue
        seen_identities.add(import_identity)
        n += 1
    db.commit()
    return {"imported": n, "skipped": skipped}


@router.get("/transactions/recurring-detect")
def recurring_detect(account_id: str = "", db: DbSession = Depends(get_db)):
    """surface likely recurring charges (1f) — the engine money bills + subs auto-detect reuse."""
    from services import txn_ingest

    if actual_finance.is_canonical(db):
        from services import txn_ingest

        try:
            rows = actual_finance.transactions(db)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
        if account_id:
            rows = [row for row in rows if row["account_id"] == account_id]
        return {
            "candidates": txn_ingest.detect_recurring(
                [
                    {"date": row["date"], "amount": row["amount"], "payee": row["payee"]}
                    for row in rows
                ]
            )
        }
    q = db.query(Transaction)
    if account_id:
        q = q.filter(Transaction.account_id == account_id)
    txns = [{"date": t.date, "amount": t.amount, "payee": t.payee} for t in q.all()]
    return {"candidates": txn_ingest.detect_recurring(txns)}


# ── transfers (move money between your own accounts) ──────────────────────────
class TransferBody(BaseModel):
    from_account: str
    to_account: str
    amount: float
    date: str
    notes: str = ""
    request_id: str = ""


@router.post("/transfer")
def create_transfer(body: TransferBody, db: DbSession = Depends(get_db)):
    """one move, two linked legs (−amount out of `from`, +amount into `to`), both
    tagged category 'transfer' + a shared transfer_id so the summary can leave them
    out of income/spending while balances still shift correctly."""
    if body.from_account == body.to_account:
        raise HTTPException(400, "pick two different accounts")
    if not math.isfinite(body.amount) or (body.amount or 0) <= 0:
        raise HTTPException(400, "amount must be positive")
    _prepare_money(lambda: finance_currency.decimal_text(body.amount))
    if actual_finance.is_canonical(db):
        try:
            values = body.model_dump()
            request_id = values.pop("request_id", "")
            return actual_finance.create_transfer(db, values, request_id=request_id)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    src = db.get(Account, body.from_account)
    dst = db.get(Account, body.to_account)
    if not src or not dst:
        raise HTTPException(400, "unknown account")
    import uuid

    tid = uuid.uuid4().hex
    d = (body.date or "")[:10]
    out = Transaction(
        account_id=src.id,
        date=d,
        amount=-abs(body.amount),
        category="transfer",
        payee=f"→ {dst.name}",
        notes=(body.notes or "").strip(),
        transfer_id=tid,
    )
    inc = Transaction(
        account_id=dst.id,
        date=d,
        amount=abs(body.amount),
        category="transfer",
        payee=f"← {src.name}",
        notes=(body.notes or "").strip(),
        transfer_id=tid,
    )
    db.add_all([out, inc])
    finance_currency.prepare_transaction(db, out, source="transfer_identity")
    finance_currency.prepare_transaction(db, inc, source="transfer_identity")
    db.commit()
    db.refresh(out)
    db.refresh(inc)
    return {"transfer_id": tid, "from": _txn(out), "to": _txn(inc)}


@router.delete("/transfer/{tid}")
def delete_transfer(tid: str, db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            return actual_finance.delete_transfer(db, tid)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    legs = db.query(Transaction).filter(Transaction.transfer_id == tid).all()
    if not legs:
        raise HTTPException(404)
    for t in legs:
        db.delete(t)
    db.commit()
    return {"ok": True, "removed": len(legs)}


# ── recurring transactions (rent, salary, loans — auto-posted each cycle) ─────
_RECUR_CAP = 60  # don't flood the ledger if the app sat unopened for years


def _post_due_recurring(db, today: date = None) -> bool:
    """post a real txn for every occurrence of every active rule that's due up to
    today, advancing next_date past today. idempotent: re-running posts nothing new
    because next_date has already moved forward."""
    if actual_finance.is_canonical(db):
        return False
    today = today or date.today()
    changed = False
    for r in db.query(RecurringTxn).filter(RecurringTxn.active == True).all():
        if not r.next_date:
            continue
        try:
            nd = date.fromisoformat(r.next_date[:10])
        except ValueError:
            continue
        anchor = (
            r.anchor_day or nd.day
        )  # clamp every occurrence from here, not the last clamped date
        guard = 0
        while nd <= today and guard < _RECUR_CAP:
            transaction = Transaction(
                account_id=r.account_id,
                date=nd.isoformat(),
                amount=r.amount or 0.0,
                category=r.category or "",
                payee=r.payee or "",
                notes=r.notes or "",
            )
            db.add(transaction)
            finance_currency.prepare_transaction(db, transaction, source="recurring_identity")
            r.last_posted = nd.isoformat()
            nd = _advance(nd, r.cycle, r.cycle_days, anchor)
            guard += 1
            changed = True
        r.next_date = nd.isoformat()
    if changed:
        db.commit()
    return changed


def _rec(r):
    return {
        "id": r.id,
        "account_id": r.account_id,
        "amount": r.amount,
        "category": r.category,
        "payee": r.payee,
        "notes": r.notes,
        "cycle": r.cycle,
        "cycle_days": r.cycle_days,
        "next_date": r.next_date,
        "active": bool(r.active),
        "last_posted": r.last_posted or "",
    }


@router.get("/recurring")
def list_recurring(db: DbSession = Depends(get_db)):
    _require_actual_backed_analytics(db, "recurring schedules")
    _post_due_recurring(db)
    rows = db.query(RecurringTxn).order_by(RecurringTxn.next_date.asc()).all()
    return [_rec(r) for r in rows]


class RecurringBody(BaseModel):
    account_id: str
    amount: float = 0.0
    category: str = ""
    payee: str = ""
    notes: str = ""
    cycle: str = "monthly"
    cycle_days: int = 30
    next_date: str
    active: bool = True


@router.post("/recurring")
def create_recurring(body: RecurringBody, db: DbSession = Depends(get_db)):
    _require_legacy_ledger_write(db)
    if not db.get(Account, body.account_id):
        raise HTTPException(400, "unknown account")
    if body.cycle not in RECUR_CYCLES:
        raise HTTPException(400, f"cycle must be one of {', '.join(RECUR_CYCLES)}")
    try:
        date.fromisoformat(body.next_date[:10])
    except ValueError:
        raise HTTPException(400, "next_date must be an ISO date (YYYY-MM-DD)")
    _prepare_money(lambda: finance_currency.decimal_text(body.amount))
    r = RecurringTxn(
        account_id=body.account_id,
        amount=body.amount or 0.0,
        category=(body.category or "").strip(),
        payee=(body.payee or "").strip(),
        notes=(body.notes or "").strip(),
        cycle=body.cycle,
        cycle_days=body.cycle_days or 30,
        next_date=body.next_date[:10],
        anchor_day=date.fromisoformat(body.next_date[:10]).day,
        active=body.active,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return _rec(r)


@router.patch("/recurring/{rid}")
def update_recurring(rid: str, body: dict, db: DbSession = Depends(get_db)):
    _require_legacy_ledger_write(db)
    r = db.get(RecurringTxn, rid)
    if not r:
        raise HTTPException(404)
    if "cycle" in body and body["cycle"] not in RECUR_CYCLES:
        raise HTTPException(400, f"cycle must be one of {', '.join(RECUR_CYCLES)}")
    if "account_id" in body and not db.get(Account, body["account_id"]):
        raise HTTPException(400, "unknown account")
    _need_floats(body, "amount")
    if body.get("amount") is not None:
        _prepare_money(lambda: finance_currency.decimal_text(body["amount"]))
    if body.get("cycle_days") is not None:
        try:
            body["cycle_days"] = int(body["cycle_days"])
        except (TypeError, ValueError):
            raise HTTPException(400, "cycle_days must be an integer")
    if "next_date" in body:  # validate + normalize to a clean ISO string (accepts int or str)
        try:
            _nd = date.fromisoformat(str(body["next_date"])[:10])
        except ValueError:
            raise HTTPException(400, "next_date must be an ISO date (YYYY-MM-DD)")
        body["next_date"] = _nd.isoformat()  # store dashed str so anchor calc can't choke on an int
    for k in (
        "account_id",
        "amount",
        "category",
        "payee",
        "notes",
        "cycle",
        "cycle_days",
        "next_date",
        "active",
    ):
        if k in body:
            setattr(r, k, body[k])
    if "next_date" in body:
        r.anchor_day = date.fromisoformat(r.next_date[:10]).day  # keep the drift anchor in sync
    db.commit()
    return _rec(r)


@router.delete("/recurring/{rid}")
def delete_recurring(rid: str, db: DbSession = Depends(get_db)):
    _require_legacy_ledger_write(db)
    r = db.get(RecurringTxn, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


# ── category rules CRUD + bulk apply ──────────────────────────────────────────
@router.get("/rules")
def list_rules(db: DbSession = Depends(get_db)):
    return [{"id": r.id, "match": r.match, "category": r.category} for r in _rules(db)]


class RuleBody(BaseModel):
    match: str
    category: str = ""


@router.post("/rules")
def create_rule(body: RuleBody, db: DbSession = Depends(get_db)):
    m = (body.match or "").strip()
    if not m:
        raise HTTPException(400, "match required")
    r = CategoryRule(match=m, category=(body.category or "").strip())
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id, "match": r.match, "category": r.category}


@router.delete("/rules/{rid}")
def delete_rule(rid: str, db: DbSession = Depends(get_db)):
    r = db.get(CategoryRule, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/rules/apply")
def apply_rules(db: DbSession = Depends(get_db)):
    """back-fill categories on existing uncategorized txns using the current rules."""
    _require_legacy_ledger_write(db)
    rules = _rules(db)
    n = 0
    for t in db.query(Transaction).all():
        if t.transfer_id or (t.category or "").strip():
            continue
        c = _categorize(t.payee, rules)
        if c:
            t.category = c
            n += 1
    db.commit()
    return {"updated": n}


# ── tag rules CRUD + bulk apply (2e) ──────────────────────────────────────────
@router.get("/tag-rules")
def list_tag_rules(db: DbSession = Depends(get_db)):
    return [{"id": r.id, "match": r.match, "tags": r.tags} for r in _tag_rules(db)]


class TagRuleBody(BaseModel):
    match: str
    tags: str = ""


@router.post("/tag-rules")
def create_tag_rule(body: TagRuleBody, db: DbSession = Depends(get_db)):
    m = (body.match or "").strip()
    if not m:
        raise HTTPException(400, "match required")
    r = TagRule(match=m, tags=_norm_tags(body.tags))
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id, "match": r.match, "tags": r.tags}


@router.delete("/tag-rules/{rid}")
def delete_tag_rule(rid: str, db: DbSession = Depends(get_db)):
    r = db.get(TagRule, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/tag-rules/apply")
def apply_tag_rules(db: DbSession = Depends(get_db)):
    """back-fill tags on existing txns from the current tag rules (merges, never drops)."""
    _require_legacy_ledger_write(db)
    from services import tag_rules

    rules = _tag_rules(db)
    n = 0
    for t in db.query(Transaction).all():
        if t.transfer_id:
            continue
        new = tag_rules.apply_rules(t.payee, rules, existing=t.tags or "")
        if new != (t.tags or ""):
            t.tags = new
            n += 1
    db.commit()
    return {"updated": n}


# ── budgets (monthly spending caps per category) ──────────────────────────────
@router.get("/budgets")
def list_budgets(db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            return actual_finance.budgets(db, date.today().strftime("%Y-%m"))
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    return [
        {"id": b.id, "category": b.category, "tag": b.tag or "", "limit_amt": b.limit_amt}
        for b in db.query(Budget).order_by(Budget.category.asc()).all()
    ]


class BudgetBody(BaseModel):
    category: str = ""
    tag: str = ""  # 2e - set this (with category empty) for a tag budget
    limit_amt: float = 0.0


@router.post("/budgets")
def upsert_budget(body: BudgetBody, db: DbSession = Depends(get_db)):
    cat = (body.category or "").strip()
    tag = (body.tag or "").strip().lower()
    if not cat and not tag:
        raise HTTPException(400, "category or tag required")
    if actual_finance.is_canonical(db):
        try:
            if tag:
                return actual_finance.set_tag_budget(db, tag, body.limit_amt)
            return actual_finance.set_budget(
                db,
                date.today().strftime("%Y-%m"),
                cat,
                body.limit_amt,
            )
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    if tag:
        b = db.query(Budget).filter(Budget.tag == tag).first()
        if not b:
            b = Budget(category="", tag=tag)
            db.add(b)
    else:
        b = (
            db.query(Budget)
            .filter(Budget.category == cat, (Budget.tag == "") | (Budget.tag.is_(None)))
            .first()
        )
        if not b:
            b = Budget(category=cat)
            db.add(b)
    b.limit_amt = body.limit_amt
    db.commit()
    db.refresh(b)
    return {"id": b.id, "category": b.category, "tag": b.tag or "", "limit_amt": b.limit_amt}


@router.delete("/budgets/{bid}")
def delete_budget(bid: str, db: DbSession = Depends(get_db)):
    if actual_finance.is_canonical(db):
        try:
            return actual_finance.clear_budget(db, bid)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
    b = db.get(Budget, bid)
    if not b:
        raise HTTPException(404)
    db.delete(b)
    db.commit()
    return {"ok": True}


# ── envelope budgeting (YNAB), 4b ─────────────────────────────────────────────
class AssignBody(BaseModel):
    category: str
    amount: float = 0.0
    month: str = ""


@router.put("/envelope/assign")
def assign_envelope(body: AssignBody, db: DbSession = Depends(get_db)):
    _require_legacy_ledger_write(db)
    cat = (body.category or "").strip()
    if not cat:
        raise HTTPException(400, "category required")
    month = (body.month or "").strip() or date.today().strftime("%Y-%m")
    row = db.query(BudgetAssignment).filter_by(
        category=cat, month=month
    ).first() or BudgetAssignment(category=cat, month=month)
    row.assigned = round(body.amount or 0.0, 2)
    db.add(row)
    db.commit()
    return {"category": cat, "month": month, "assigned": row.assigned}


class TargetBody(BaseModel):
    category: str
    amount: float = 0.0
    target_date: str = ""


@router.put("/envelope/target")
def set_target(body: TargetBody, db: DbSession = Depends(get_db)):
    _require_legacy_ledger_write(db)
    cat = (body.category or "").strip()
    if not cat:
        raise HTTPException(400, "category required")
    row = db.query(FundingTarget).filter_by(category=cat).first()
    if (body.amount or 0.0) <= 0:  # zero / negative clears the target
        if row:
            db.delete(row)
            db.commit()
        return {"category": cat, "target": None}
    row = row or FundingTarget(category=cat)
    row.amount = round(body.amount, 2)
    row.target_date = (body.target_date or "").strip()
    db.add(row)
    db.commit()
    return {"category": cat, "target": {"amount": row.amount, "date": row.target_date}}


@router.get("/envelope")
def envelope(month: str = "", db: DbSession = Depends(get_db)):
    _require_actual_backed_analytics(db, "envelope budgeting")
    if not month:
        month = date.today().strftime("%Y-%m")
    # fetch txns + splits once and reuse — both _spending_by_cat calls and the income sum below
    # otherwise each call re-scanned the whole Transaction + TxnSplit tables (4b perf)
    all_txns = db.query(Transaction).all()
    splits_by_txn = defaultdict(list)
    for s in db.query(TxnSplit).all():
        splits_by_txn[s.txn_id].append(s)
    spent_now = _spending_by_cat(db, month, txns=all_txns, splits_by_txn=splits_by_txn)
    spent_upto = _spending_by_cat(db, month, upto=True, txns=all_txns, splits_by_txn=splits_by_txn)
    assigns = db.query(BudgetAssignment).all()
    assigned_now = {a.category: a.assigned for a in assigns if a.month == month}
    assigned_upto = defaultdict(float)
    for a in assigns:
        if a.month <= month:
            assigned_upto[a.category] += a.assigned or 0.0
    targets = {t.category: t for t in db.query(FundingTarget).all()}

    cats = set(spent_now) | set(assigned_now) | set(assigned_upto) | set(spent_upto) | set(targets)
    out = []
    for c in sorted(cats):
        avail = round(assigned_upto.get(c, 0.0) - spent_upto.get(c, 0.0), 2)
        tgt = None
        if c in targets and targets[c].amount > 0:
            amt = targets[c].amount
            tgt = {
                "amount": amt,
                "date": targets[c].target_date or "",
                "funded": round(max(0.0, avail) / amt, 4) if amt else 0.0,
            }
        out.append(
            {
                "category": c,
                "assigned": round(assigned_now.get(c, 0.0), 2),
                "spent": round(spent_now.get(c, 0.0), 2),
                "available": avail,
                "target": tgt,
            }
        )

    income = sum(
        t.amount or 0.0
        for t in all_txns
        if (t.date or "")[:7] == month and not t.transfer_id and (t.amount or 0.0) > 0
    )
    assigned_total = round(sum(assigned_now.values()), 2)
    return {
        "month": month,
        "income": round(income, 2),
        "assigned_total": assigned_total,
        "to_be_budgeted": round(income - assigned_total, 2),
        "categories": out,
    }


@router.get("/age-of-money")
def age_of_money(db: DbSession = Depends(get_db)):
    """FIFO-match income to spending; amount-weighted average age (days) of recent spending."""
    _require_actual_backed_analytics(db, "age of money")

    def _d(s):
        try:
            return date.fromisoformat(str(s)[:10])
        except (TypeError, ValueError):
            return None

    # skip txns with a junk date so one bad import row can't 500 the whole endpoint
    txns = [t for t in db.query(Transaction).all() if not t.transfer_id and _d(t.date)]
    incomes = sorted(
        ([t.date, t.amount] for t in txns if (t.amount or 0.0) > 0), key=lambda x: x[0]
    )
    expenses = sorted(
        ([t.date, -(t.amount or 0.0)] for t in txns if (t.amount or 0.0) < 0), key=lambda x: x[0]
    )
    queue = [list(i) for i in incomes]  # [date, remaining]
    batches = []  # (expense_date, age_days, amount)
    qi = 0
    for ed, need in expenses:
        ed_d = _d(ed)
        while need > 0.005 and qi < len(queue):
            idate, iremain = queue[qi]
            # you can't spend money you haven't received yet. the queue is date-sorted, so if the
            # oldest unspent income is dated after this expense, no earlier income funds it — the
            # spend is "unfunded", skip it (don't emit a negative-age batch). a later expense can
            # still draw on this lot, so leave qi where it is.
            if _d(idate) > ed_d:
                break
            take = min(need, iremain)
            age = (ed_d - _d(idate)).days
            batches.append((ed, age, take))
            need -= take
            queue[qi][1] -= take
            if queue[qi][1] <= 0.005:
                qi += 1
    if not batches:
        return {"age": None, "sample": 0}
    recent = batches[-30:]  # weight toward recent spending
    tot = sum(b[2] for b in recent)
    age = round(sum(b[1] * b[2] for b in recent) / tot) if tot else None
    return {"age": age, "sample": len(batches)}


# ── forecast, net-worth history, holdings, watches, alerts (Simplifi), 4c ─────
def _ym(month):
    # parse 'YYYY-MM' (or longer) -> (year, month). bad/short input falls back to the current
    # month instead of blowing up with a 500 (int("") on a stray ?month=2026 etc)
    try:
        y, m = int(month[:4]), int(month[5:7])
        if not (1 <= m <= 12):
            raise ValueError
        return y, m
    except (ValueError, IndexError):
        t = date.today()
        return t.year, t.month


def _last_day(month):
    y, m = _ym(month)
    return date(y, m, _cal.monthrange(y, m)[1])


def _net_worth_at(db, accounts, date_str, txns=None):
    """opening balances + every txn dated on/before date_str (running net worth)."""
    aset = {a.id for a in accounts if not a.archived}
    nw = sum((a.opening or 0.0) for a in accounts if not a.archived)
    if txns is None:
        txns = db.query(Transaction).all()
    for t in txns:
        if t.account_id in aset and (t.date or "") <= date_str:
            nw += t.amount or 0.0
    return round(nw, 2)


@router.get("/forecast")
def forecast(
    month: str = "",
    as_of: str = "",
    skip: str = "",
    income_delta: float = 0.0,
    db: DbSession = Depends(get_db),
):
    """project the end-of-month balance from today's balance + remaining recurring txns. 2b adds
    a per-category projection (`categories`) + what-if (`skip` comma payees, `income_delta`)."""
    _require_actual_backed_analytics(db, "forecast")
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        as_of_d = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        as_of_d = date.today()
    end = _last_day(month)
    accounts = db.query(Account).all()
    start = _net_worth_at(db, accounts, as_of_d.isoformat())
    occ = []
    for r in db.query(RecurringTxn).filter(RecurringTxn.active == True).all():  # noqa: E712
        if not r.next_date:
            continue
        try:
            d = date.fromisoformat(r.next_date)
        except ValueError:
            continue
        anchor = r.anchor_day or d.day
        guard = 0
        while d <= as_of_d and guard < 600:
            d = _advance(d, r.cycle, r.cycle_days or 30, anchor)
            guard += 1
        while d <= end and guard < 600:
            occ.append(
                {
                    "date": d.isoformat(),
                    "amount": r.amount or 0.0,
                    "payee": r.payee or r.category or "recurring",
                }
            )
            d = _advance(d, r.cycle, r.cycle_days or 30, anchor)
            guard += 1
    occ.sort(key=lambda x: x["date"])
    from services import forecast as forecast_svc

    skip_payees = [s.strip() for s in skip.split(",") if s.strip()]
    occ = forecast_svc.apply_scenario(
        occ, skip_payees=skip_payees, income_delta=income_delta, at=end.isoformat()
    )
    occ.sort(key=lambda x: x["date"])
    bal = start
    line = [{"date": as_of_d.isoformat(), "balance": round(bal, 2)}]
    for o in occ:
        bal += o["amount"]
        line.append({"date": o["date"], "balance": round(bal, 2)})
    line.append({"date": end.isoformat(), "balance": round(bal, 2)})
    return {
        "month": month,
        "start_balance": start,
        "projected": round(bal, 2),
        "recurring": occ,
        "line": line,
        "categories": forecast_svc.category_averages(db, as_of=as_of_d),
    }


@router.get("/networth-history")
def networth_history(months: int = 6, as_of: str = "", db: DbSession = Depends(get_db)):
    _require_actual_backed_analytics(db, "net worth history")
    end_month = as_of[:7] if as_of else date.today().strftime("%Y-%m")
    accounts = db.query(Account).all()
    aset = {a.id for a in accounts if not a.archived}
    base = sum((a.opening or 0.0) for a in accounts if not a.archived)
    # sort our txns once, then sweep cumulatively across month boundaries instead of
    # re-scanning the whole txn list per month (was O(months * txns))
    txns = sorted(
        (t for t in db.query(Transaction).all() if t.account_id in aset),
        key=lambda t: t.date or "",
    )
    y, m = _ym(end_month)
    seq = []
    for _ in range(max(1, months)):
        seq.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    out = []
    nw, i = base, 0
    for mo in reversed(seq):  # oldest -> newest so the running total only moves forward
        cutoff = _last_day(mo).isoformat()
        while i < len(txns) and (txns[i].date or "") <= cutoff:
            nw += txns[i].amount or 0.0
            i += 1
        out.append({"month": mo, "net_worth": round(nw, 2)})
    return out


def _holding(h):
    value = round((h.qty or 0.0) * (h.price or 0.0), 2)
    cost = round((h.qty or 0.0) * (h.cost_basis or 0.0), 2)
    gain = round(value - cost, 2)
    return {
        "id": h.id,
        "symbol": h.symbol,
        "name": h.name or "",
        "qty": h.qty,
        "cost_basis": h.cost_basis,
        "price": h.price,
        "value": value,
        "cost": cost,
        "gain": gain,
        "gain_pct": round(gain / cost * 100, 2) if cost else 0.0,
    }


class HoldingBody(BaseModel):
    symbol: str
    name: str = ""
    qty: float = 0.0
    cost_basis: float = 0.0
    price: float = 0.0


@router.get("/holdings")
def list_holdings(db: DbSession = Depends(get_db)):
    rows = [_holding(h) for h in db.query(Holding).order_by(Holding.created_at.asc()).all()]
    totals = {
        "value": round(sum(r["value"] for r in rows), 2),
        "cost": round(sum(r["cost"] for r in rows), 2),
        "gain": round(sum(r["gain"] for r in rows), 2),
    }
    return {"holdings": rows, "totals": totals}


@router.post("/holdings")
def add_holding(body: HoldingBody, db: DbSession = Depends(get_db)):
    h = Holding(
        symbol=(body.symbol or "?").strip().upper() or "?",
        name=(body.name or "").strip(),
        qty=body.qty or 0.0,
        cost_basis=body.cost_basis or 0.0,
        price=body.price or 0.0,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return _holding(h)


@router.patch("/holdings/{hid}")
def update_holding(hid: str, body: dict, db: DbSession = Depends(get_db)):
    h = db.get(Holding, hid)
    if not h:
        raise HTTPException(404)
    _need_floats(body, "qty", "cost_basis", "price")
    for k in ("symbol", "name", "qty", "cost_basis", "price"):
        if k in body:
            setattr(h, k, body[k])
    db.commit()
    return _holding(h)


@router.delete("/holdings/{hid}")
def delete_holding(hid: str, db: DbSession = Depends(get_db)):
    h = db.get(Holding, hid)
    if not h:
        raise HTTPException(404)
    db.delete(h)
    db.commit()
    return {"ok": True}


@router.post("/holdings/refresh")
def refresh_holdings(db: DbSession = Depends(get_db)):
    # 2d - reprice from the external source (best-effort; returns {updated, prices})
    from services import price_fetch

    return price_fetch.refresh(db)


@router.get("/holdings/{sym}/history")
def holding_history(sym: str, db: DbSession = Depends(get_db)):
    from services import price_fetch

    return {
        "history": price_fetch.history(db, sym),
        "return_pct": price_fetch.return_since_first(db, sym),
    }


@router.get("/income/summary")
def income_summary(month: str = "", db: DbSession = Depends(get_db)):
    """2f - income by type for a month + rolling average + the current tax-quarter set-aside."""
    _require_actual_backed_analytics(db, "income summary")
    from services import income

    today = date.today()
    mo = (month or today.strftime("%Y-%m")).strip()
    from core.settings import load_settings

    rate = load_settings().get("tax_setaside_rate", 0.25) or 0.25
    return {
        "month": mo,
        "by_type": income.by_type(db, mo),
        "rolling_avg": income.rolling_income(db, months=3, as_of=today),
        "quarter": income.current_quarter(today),
        "quarter_income": income.quarter_income(db, today),
        "set_aside": income.set_aside(db, today, rate=rate),
        "rate": rate,
    }


class WatchBody(BaseModel):
    kind: str = "category"
    value: str


@router.get("/watches")
def list_watches(db: DbSession = Depends(get_db)):
    return {
        "watches": [
            {"id": w.id, "kind": w.kind, "value": w.value}
            for w in db.query(Watch).order_by(Watch.created_at.asc()).all()
        ]
    }


@router.post("/watches")
def add_watch(body: WatchBody, db: DbSession = Depends(get_db)):
    val = (body.value or "").strip()
    if not val:
        raise HTTPException(400, "value required")
    w = Watch(kind=body.kind if body.kind in ("payee", "category") else "category", value=val)
    db.add(w)
    db.commit()
    db.refresh(w)
    return {"id": w.id, "kind": w.kind, "value": w.value}


@router.delete("/watches/{wid}")
def delete_watch(wid: str, db: DbSession = Depends(get_db)):
    w = db.get(Watch, wid)
    if not w:
        raise HTTPException(404)
    db.delete(w)
    db.commit()
    return {"ok": True}


@router.get("/alerts")
def alerts(month: str = "", big: float = 200.0, as_of: str = "", db: DbSession = Depends(get_db)):
    _require_actual_backed_analytics(db, "Finance alerts")
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        as_of_d = date.fromisoformat(as_of) if as_of else date.today()
    except ValueError:
        as_of_d = date.today()
    watches = db.query(Watch).all()
    large, watch_hits = [], []
    for t in db.query(Transaction).filter(Transaction.date.like(f"{month}%")).all():
        if t.transfer_id:
            continue
        amt = t.amount or 0.0
        if amt < 0 and abs(amt) >= big:
            large.append(
                {
                    "id": t.id,
                    "payee": t.payee,
                    "amount": amt,
                    "date": t.date,
                    "category": t.category,
                }
            )
        for w in watches:
            hay = (t.category if w.kind == "category" else t.payee) or ""
            if w.value and w.value.lower() in hay.lower():
                watch_hits.append(
                    {"id": t.id, "payee": t.payee, "amount": amt, "date": t.date, "watch": w.value}
                )
                break
    upcoming = []
    for r in db.query(RecurringTxn).filter(RecurringTxn.active == True).all():  # noqa: E712
        try:
            d = date.fromisoformat(r.next_date)
        except (ValueError, TypeError):
            continue
        days = (d - as_of_d).days
        if 0 <= days <= 7:
            upcoming.append(
                {
                    "id": r.id,
                    "payee": r.payee or r.category or "bill",
                    "amount": r.amount,
                    "date": r.next_date,
                    "days": days,
                }
            )
    low_balance = []
    bal = _balances(db)
    for a in db.query(Account).all():
        if a.archived or not (a.low_balance and a.low_balance > 0):
            continue
        cur = round((a.opening or 0.0) + bal.get(a.id, 0.0), 2)
        if cur < a.low_balance:
            low_balance.append(
                {"id": a.id, "name": a.name, "balance": cur, "threshold": a.low_balance}
            )
    return {
        "large_purchases": large,
        "upcoming_bills": upcoming,
        "watch_hits": watch_hits,
        "low_balance": low_balance,
    }


# ── goals, reports, multi-currency (4d) ───────────────────────────────────────
def _goal(g):
    target = g.target or 0.0
    current = g.current or 0.0
    if g.kind == "debt":
        remaining = max(0.0, current)
        progress = (target - current) / target if target else 0.0
    else:
        remaining = max(0.0, target - current)
        progress = current / target if target else 0.0
    monthly = g.monthly or 0.0
    if remaining <= 0:
        eta = 0
    elif monthly > 0:
        eta = math.ceil(remaining / monthly)
    else:
        eta = None
    return {
        "id": g.id,
        "name": g.name,
        "kind": g.kind,
        "target": target,
        "current": current,
        "monthly": monthly,
        "remaining": round(remaining, 2),
        "progress": round(max(0.0, min(1.0, progress)), 4),
        "eta_months": eta,
    }


class GoalBody(BaseModel):
    name: str
    kind: str = "savings"
    target: float = 0.0
    current: float = 0.0
    monthly: float = 0.0


@router.get("/goals")
def list_goals(db: DbSession = Depends(get_db)):
    return {"goals": [_goal(g) for g in db.query(Goal).order_by(Goal.created_at.asc()).all()]}


@router.post("/goals")
def add_goal(body: GoalBody, db: DbSession = Depends(get_db)):
    g = Goal(
        name=(body.name or "goal").strip() or "goal",
        kind=body.kind if body.kind in ("savings", "debt") else "savings",
        target=body.target or 0.0,
        current=body.current or 0.0,
        monthly=body.monthly or 0.0,
    )
    db.add(g)
    db.commit()
    db.refresh(g)
    return _goal(g)


@router.patch("/goals/{gid}")
def update_goal(gid: str, body: dict, db: DbSession = Depends(get_db)):
    g = db.get(Goal, gid)
    if not g:
        raise HTTPException(404)
    _need_floats(body, "target", "current", "monthly")
    for k in ("name", "kind", "target", "current", "monthly"):
        if k in body:
            setattr(g, k, body[k])
    db.commit()
    return _goal(g)


@router.delete("/goals/{gid}")
def delete_goal(gid: str, db: DbSession = Depends(get_db)):
    g = db.get(Goal, gid)
    if not g:
        raise HTTPException(404)
    db.delete(g)
    db.commit()
    return {"ok": True}


def _report_data(db, start, end):
    if actual_finance.is_canonical(db):
        rows = []
        income = expense = 0.0
        by = defaultdict(float)
        try:
            canonical_rows = actual_finance.transactions(db)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
        for row in canonical_rows:
            if row["transfer_id"]:
                continue
            if (start and row["date"] < start) or (end and row["date"] > end):
                continue
            rows.append(row)
            if row["amount"] >= 0:
                income += row["amount"]
            else:
                expense += -row["amount"]
                by[row["category"] or "uncategorized"] += -row["amount"]
        cats = sorted(
            ([category, round(value, 2)] for category, value in by.items()),
            key=lambda item: -item[1],
        )
        return income, expense, cats, rows
    splits_by_txn = defaultdict(list)
    for s in db.query(TxnSplit).all():
        splits_by_txn[s.txn_id].append(s)
    income = expense = 0.0
    by = defaultdict(float)
    rows = []
    for t in db.query(Transaction).order_by(Transaction.date.asc()).all():
        if t.transfer_id:
            continue
        d = t.date or ""
        if (start and d < start) or (end and d > end):
            continue
        rows.append(t)
        amt = t.amount or 0.0
        if amt >= 0:
            income += amt
        else:
            expense += -amt
            _distribute(t, splits_by_txn, by)
    cats = sorted(([c, round(v, 2)] for c, v in by.items()), key=lambda x: -x[1])
    return income, expense, cats, rows


@router.get("/report")
def report(start: str = "", end: str = "", db: DbSession = Depends(get_db)):
    income, expense, cats, _ = _report_data(db, start, end)
    return {
        "start": start,
        "end": end,
        "income": round(income, 2),
        "expense": round(expense, 2),
        "net": round(income - expense, 2),
        "by_category": cats,
    }


@router.get("/report/export.csv")
def report_csv(start: str = "", end: str = "", db: DbSession = Depends(get_db)):
    import csv
    import io

    from fastapi.responses import Response

    def _safe(v):
        s = "" if v is None else str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    _, _, _, rows = _report_data(db, start, end)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "amount", "category", "payee", "notes"])
    for t in rows:
        value = t if isinstance(t, dict) else _txn(t)
        w.writerow(
            [
                _safe(value["date"]),
                value["amount"],
                _safe(value["category"]),
                _safe(value["payee"]),
                _safe(value["notes"]),
            ]
        )
    fname = f"report_{start or 'all'}_{end or 'all'}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/networth-base")
def networth_base(base: str | None = None, db: DbSession = Depends(get_db)):
    """net worth with every account converted to a single base currency (4d)."""
    if actual_finance.is_canonical(db):
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            raise HTTPException(409, "canonical ledger state is unavailable")
        reviewed_base = fx.code(state.base_currency_code)
        if reviewed_base == "XXX":
            raise HTTPException(409, "canonical ledger base currency is invalid")
        requested_base = reviewed_base if not base else fx.code(base)
        if requested_base != reviewed_base:
            raise HTTPException(
                409, "Actual totals are available only in the reviewed base currency"
            )
        try:
            canonical_accounts = actual_finance.accounts(db)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
        rows = [
            {
                "id": row["id"],
                "name": row["name"],
                "currency": state.base_currency_code,
                "native": row["balance"],
                "converted": row["balance"],
            }
            for row in canonical_accounts
            if not row["archived"]
        ]
        return {
            "base": state.base_currency_code,
            "net_worth": round(sum(row["converted"] for row in rows), 2),
            "accounts": rows,
        }
    base = base or "USD"
    rates = fx.get_rates()
    bal = _balances(db)
    rows = []
    total = 0.0
    for a in db.query(Account).all():
        if a.archived:
            continue
        native = (a.opening or 0.0) + bal.get(a.id, 0.0)
        conv = fx.convert(native, a.currency, base, rates)
        total += conv
        rows.append(
            {
                "id": a.id,
                "name": a.name,
                "currency": fx.code(a.currency),
                "native": round(native, 2),
                "converted": conv,
            }
        )
    return {"base": fx.code(base), "net_worth": round(total, 2), "accounts": rows}


# ── summary — powers the cards + charts ───────────────────────────────────────
def _recent_months(month: str, n: int = 6):
    y, m = _ym(month)  # safe parse — a bad/empty month falls back to today instead of a 500
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
        month = date.today().strftime("%Y-%m")
    if actual_finance.is_canonical(db):
        state = db.get(FinanceLedgerState, "primary")
        if state is None:
            raise HTTPException(409, "canonical ledger state is unavailable")
        base = fx.code(state.base_currency_code)
        if base == "XXX":
            raise HTTPException(409, "canonical ledger base currency is invalid")
        try:
            actual = actual_finance.inspect(db)
            accounts = actual_finance.accounts(db, actual=actual)
            all_txns = actual_finance.transactions(db, actual=actual)
            budget_rows = actual_finance.budgets(db, month, actual=actual)
        except actual_finance.ActualFinanceError as exc:
            _actual_error(exc)
        net_worth = sum(row["balance"] for row in accounts if not row["archived"])
        income = expense = 0.0
        by_cat = defaultdict(float)
        for row in all_txns:
            if row["transfer_id"] or not row["date"].startswith(month):
                continue
            if row["amount"] >= 0:
                income += row["amount"]
            else:
                expense += -row["amount"]
                by_cat[row["category"] or "uncategorized"] += -row["amount"]
        cats = sorted(
            ([category, round(value, 2)] for category, value in by_cat.items()),
            key=lambda item: -item[1],
        )
        tag_spend: dict[str, float] = {}
        tag_budget_rows = [row for row in budget_rows if str(row.get("tag") or "").strip()]
        if tag_budget_rows:
            for row in all_txns:
                if row["transfer_id"] or row["amount"] >= 0 or not row["date"].startswith(month):
                    continue
                transaction_tags = set(_norm_tags(row.get("tags") or "").split(","))
                for budget_row in tag_budget_rows:
                    budget_tag = str(budget_row.get("tag") or "").strip().lower()
                    if budget_tag in transaction_tags:
                        tag_spend[budget_tag] = tag_spend.get(budget_tag, 0.0) - row["amount"]
        budgets = [
            {
                "category": row["tag"] if row.get("tag") else row["category"],
                "tag": row.get("tag") or "",
                "limit": row["limit_amt"],
                "spent": round(
                    tag_spend.get(row.get("tag") or "", 0.0)
                    if row.get("tag")
                    else by_cat.get(row["category"], 0.0),
                    2,
                ),
            }
            for row in budget_rows
        ]
        months = _recent_months(month, 6)
        totals = {value: [0.0, 0.0] for value in months}
        for row in all_txns:
            value = row["date"][:7]
            if row["transfer_id"] or value not in totals:
                continue
            totals[value][0 if row["amount"] >= 0 else 1] += abs(row["amount"])
        trend = [
            {
                "month": value,
                "income": round(totals[value][0], 2),
                "expense": round(totals[value][1], 2),
            }
            for value in months
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
            "currency": base,
        }
    accounts = db.query(Account).all()
    bal = _balances(db)
    net_worth = sum((a.opening or 0.0) + bal.get(a.id, 0.0) for a in accounts if not a.archived)

    # fetch all transactions and splits once to avoid N+1 scans
    all_txns = db.query(Transaction).all()
    splits_by_txn = defaultdict(list)
    for s in db.query(TxnSplit).all():
        splits_by_txn[s.txn_id].append(s)

    income = expense = 0.0
    for t in all_txns:
        if (t.date or "")[:7] != month:
            continue
        if t.transfer_id:  # inter-account move, not real income/spending
            continue
        amt = t.amount or 0.0
        if amt >= 0:
            income += amt
        else:
            expense += -amt

    by_cat = _spending_by_cat(db, month, txns=all_txns, splits_by_txn=splits_by_txn)
    cats = sorted(([c, round(v, 2)] for c, v in by_cat.items()), key=lambda x: -x[1])

    budget_rows = db.query(Budget).order_by(Budget.category.asc()).all()
    # tag budgets store category="" so by_cat can't see them - sum this month's tagged expenses
    tag_budgets = [b for b in budget_rows if (b.tag or "").strip()]
    tag_spend: dict[str, float] = {}
    if tag_budgets:
        for t in all_txns:
            if t.transfer_id or (t.amount or 0.0) >= 0 or (t.date or "")[:7] != month:
                continue
            tags = set(_norm_tags(t.tags or "").split(","))
            for b in tag_budgets:
                if b.tag in tags:
                    tag_spend[b.id] = tag_spend.get(b.id, 0.0) + abs(t.amount or 0.0)
    budgets = []
    for b in budget_rows:
        is_tag = bool((b.tag or "").strip())
        budgets.append(
            {
                "category": b.tag if is_tag else b.category,  # show the tag name, not a blank
                "tag": b.tag or "",
                "limit": b.limit_amt,
                "spent": round(
                    tag_spend.get(b.id, 0.0) if is_tag else by_cat.get(b.category, 0.0), 2
                ),
            }
        )

    months = _recent_months(month, 6)
    monthset = set(months)
    tot = {mo: [0.0, 0.0] for mo in months}  # [income, expense]
    for t in all_txns:
        if t.transfer_id:  # transfers aren't income or spending
            continue
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
