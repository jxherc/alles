"""
subscription manager — recurring costs with billing cycles, due-date
rollover, monthly/yearly totals, and push reminders before renewals.
"""

import asyncio
import calendar
import functools
import inspect
import logging
import math
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import FinanceLedgerState, SessionLocal, Subscription, get_db
from services import actual_finance, finance_currency


def _subscription_write_authority(endpoint):
    """Keep the legacy-write check and mutation in one worker-thread lock lifetime."""
    signature = inspect.signature(endpoint)

    @functools.wraps(endpoint)
    def guarded(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        db = bound.arguments.get("db")
        if db is None:
            raise RuntimeError("subscription write authority requires its request database session")
        with actual_finance.AUTHORITY_LOCK:
            if actual_finance.is_canonical(db):
                raise HTTPException(
                    409,
                    "subscription schedules and payments are read-only after they move to the canonical Actual ledger",
                )
            return endpoint(*args, **kwargs)

    guarded._alles_authority_same_thread = True
    return guarded


def _subscription_write_preflight(db: DbSession = Depends(get_db)) -> None:
    """Reject canonical-mode writes before request-body validation in one worker."""
    with actual_finance.AUTHORITY_LOCK:
        if actual_finance.is_canonical(db):
            raise HTTPException(
                409,
                "subscription schedules and payments are read-only after they move to the canonical Actual ledger",
            )


def _subscription_rows(db: DbSession):
    with actual_finance.AUTHORITY_LOCK:
        if not actual_finance.is_canonical(db):
            return db.query(Subscription).all()
        legacy = {row.id: row for row in db.query(Subscription).all()}
        try:
            canonical = actual_finance.subscription_schedules(db)
        except actual_finance.ActualFinanceUnavailable as exc:
            raise HTTPException(
                503, f"canonical subscription schedules are unavailable: {exc}"
            ) from exc
        except actual_finance.ActualFinanceError as exc:
            raise HTTPException(409, str(exc)) from exc
    rows = []
    for item in canonical:
        old = legacy.get(item["id"])
        metadata = item["metadata"]
        identity_price = finance_currency.decimal_text(item["price"])
        original_price_text = (
            metadata.get("original_price_text")
            or (old.original_price_text if old else "")
            or identity_price
        )
        original_currency_code = (
            metadata.get("original_currency_code")
            or (old.original_currency_code if old else "")
            or item["currency"]
        )
        base_price_text = (
            metadata.get("base_price_text")
            or (old.base_price_text if old else "")
            or identity_price
        )
        base_currency_code = (
            metadata.get("base_currency_code")
            or (old.base_currency_code if old else "")
            or item["currency"]
        )
        rate_text = metadata.get("rate_text") or (old.fx_rate_text if old else "") or "1"
        rate_date = metadata.get("rate_date") or (old.fx_rate_date if old else "")
        rate_source = metadata.get("source") or (old.fx_source if old else "") or "actual_identity"
        migrated_name = f"Alles subscription: {old.name} [{old.id[:8]}]" if old else ""
        current_name = old.name if old and item["name"] == migrated_name else item["name"]
        rows.append(
            SimpleNamespace(
                id=item["id"],
                trial_end=old.trial_end if old else "",
                name=current_name,
                price=item["price"],
                currency=item["currency"],
                cycle=item["cycle"],
                cycle_days=item["cycle_days"],
                next_due=item["next_due"],
                category=metadata.get("category") or (old.category if old else ""),
                url=metadata.get("url") or (old.url if old else ""),
                cancel_url=metadata.get("cancel_url") or (old.cancel_url if old else ""),
                notes=old.notes if old else "",
                active=item["active"],
                remind_days=old.remind_days if old else 0,
                account_id=item["account_id"],
                created_at=old.created_at if old else datetime.now(UTC),
                original_price_text=str(original_price_text),
                original_currency_code=str(original_currency_code),
                base_price_text=str(base_price_text),
                base_currency_code=str(base_currency_code),
                canonical_base_price_text=identity_price,
                canonical_base_currency_code=str(item["currency"]),
                fx_rate_text=str(rate_text),
                fx_rate_date=str(rate_date),
                fx_source=str(rate_source),
                last_notified_due=old.last_notified_due if old else "",
            )
        )
    return rows


def _subscription_exists(db: DbSession, sid: str) -> bool:
    return any(str(row.id) == str(sid) for row in _subscription_rows(db))


router = APIRouter(prefix="/api")
log = logging.getLogger("aide.subs")

CYCLES = ("weekly", "monthly", "quarterly", "yearly", "custom")

# how many of each cycle fit in a month, for normalized totals
_PER_MONTH = {"weekly": 52 / 12, "monthly": 1.0, "quarterly": 1 / 3, "yearly": 1 / 12}


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _advance(d: date, cycle: str, cycle_days: int) -> date:
    if cycle == "weekly":
        return d + timedelta(days=7)
    if cycle == "monthly":
        return _add_months(d, 1)
    if cycle == "quarterly":
        return _add_months(d, 3)
    if cycle == "yearly":
        return _add_months(d, 12)
    return d + timedelta(days=max(1, cycle_days or 30))


def _parse(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def _parse_maybe(s: str):
    try:
        return _parse(s)
    except ValueError:
        return None


def _roll(sub: Subscription, today: date) -> bool:
    """advance an overdue next_due until it's in the future. returns changed."""
    if not sub.active:
        return False
    d = _parse_maybe(sub.next_due)
    if not d:
        return False
    changed = False
    while d < today:
        d = _advance(d, sub.cycle, sub.cycle_days)
        changed = True
    if changed:
        sub.next_due = d.isoformat()
    return changed


_POST_CAP = 36  # don't flood if the app sat unopened for years


def _reviewed_subscription_charge(sub: Subscription, account) -> dict:
    try:
        original = Decimal(str(sub.original_price_text or sub.price))
        listed = Decimal(finance_currency.decimal_text(sub.price))
        base = Decimal(str(sub.base_price_text or ""))
        rate = Decimal(str(sub.fx_rate_text or ""))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(409, "subscription requires valid reviewed currency evidence") from exc
    if any(not value.is_finite() or value < 0 for value in (original, listed, base)):
        raise HTTPException(409, "subscription requires valid reviewed currency evidence")
    if not rate.is_finite() or rate <= 0:
        raise HTTPException(409, "subscription requires a positive reviewed conversion rate")
    if original != listed:
        raise HTTPException(
            409, "subscription price no longer matches its reviewed currency evidence"
        )

    original_code = finance_currency.currency_code(sub.original_currency_code or sub.currency)
    base_code = finance_currency.currency_code(sub.base_currency_code)
    account_code = finance_currency.currency_code(account.currency_code or account.currency)
    if "XXX" in {original_code, base_code, account_code}:
        raise HTTPException(409, "subscription and account require reviewed currency codes")
    expected_base = (original * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    if base != base.quantize(Decimal("0.01")) or base != expected_base:
        raise HTTPException(409, "subscription base amount does not match its reviewed rate")
    if account_code == original_code:
        native = original
    elif account_code == base_code:
        native = base
    else:
        raise HTTPException(
            409,
            f"subscription currency evidence cannot post to a {account_code} account",
        )
    return {
        "native": native,
        "original": original,
        "original_code": original_code,
        "base": base,
        "base_code": base_code,
        "rate": rate,
    }


def _subscription_transaction(db, sub: Subscription, account, posted_on: str, evidence=None):
    from core.database import Transaction

    evidence = evidence or _reviewed_subscription_charge(sub, account)
    txn = Transaction(
        account_id=sub.account_id,
        date=posted_on,
        amount=-float(evidence["native"]),
        category=(sub.category or "subscriptions"),
        payee=sub.name,
        notes="auto: subscription renewal",
    )
    db.add(txn)
    finance_currency.prepare_transaction(
        db,
        txn,
        source="subscription_reviewed",
        original_amount=-evidence["original"],
        original_currency_code=evidence["original_code"],
        base_amount=-evidence["base"],
        base_currency_code=evidence["base_code"],
        rate=evidence["rate"],
        rate_date=sub.fx_rate_date or "",
    )
    db.flush()
    return txn


def _roll_and_post(sub: Subscription, today: date, db) -> bool:
    """roll an overdue sub forward AND, if it's linked to a money account, drop a
    real transaction for each due date that just passed. idempotent via
    last_posted_due so the same renewal is never double-posted."""
    if actual_finance.is_canonical(db):
        return False
    if not sub.active:
        return False
    from core.database import Account, SubPayment

    d = _parse_maybe(sub.next_due)
    if not d:
        return False
    charges = []
    while d < today:
        charges.append(d)  # this due date rolled over → a charge happened
        d = _advance(d, sub.cycle, sub.cycle_days)
    if not charges:
        return False

    account = db.get(Account, sub.account_id) if (sub.account_id or "") else None
    evidence = _reviewed_subscription_charge(sub, account) if account else None
    sub.next_due = d.isoformat()
    if account:
        last = sub.last_posted_due or ""
        for cd in charges[-_POST_CAP:]:
            iso = cd.isoformat()
            if iso <= last:  # already posted this (or an earlier) renewal
                continue
            txn = _subscription_transaction(db, sub, account, iso, evidence)
            # record the payment too so auto-posted renewals show in history and can be undone
            payment = SubPayment(sub_id=sub.id, date=iso, amount=sub.price or 0.0, txn_id=txn.id)
            finance_currency.prepare_payment(payment, sub)
            db.add(payment)
            sub.last_posted_due = iso
    return True


def _monthly_cost(sub: Subscription) -> float:
    if sub.cycle == "custom":
        return sub.price * 30.44 / max(1, sub.cycle_days or 30)
    return sub.price * _PER_MONTH.get(sub.cycle, 1.0)


def _base_price(sub: Subscription) -> float:
    base_price_text = getattr(sub, "canonical_base_price_text", "") or sub.base_price_text
    if (
        not str(base_price_text or "").strip()
        or not str(
            getattr(sub, "canonical_base_currency_code", "") or sub.base_currency_code or ""
        ).strip()
        or finance_currency.currency_code(
            getattr(sub, "canonical_base_currency_code", "") or sub.base_currency_code
        )
        == "XXX"
    ):
        raise HTTPException(
            409,
            f"subscription {sub.id} requires reviewed conversion evidence before aggregation",
        )
    try:
        value = Decimal(str(base_price_text))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            409, f"subscription {sub.id} has invalid base-currency evidence"
        ) from exc
    if not value.is_finite() or value < 0:
        raise HTTPException(409, f"subscription {sub.id} has invalid base-currency evidence")
    return float(value)


def _base_monthly_cost(sub: Subscription) -> float:
    price = _base_price(sub)
    if sub.cycle == "custom":
        return price * 30.44 / max(1, sub.cycle_days or 30)
    return price * _PER_MONTH.get(sub.cycle, 1.0)


def _aggregate_currency(subscriptions: list[Subscription], db: DbSession) -> str:
    state = db.get(FinanceLedgerState, "primary")
    configured_base = finance_currency.currency_code(state.base_currency_code if state else "CAD")
    if configured_base == "XXX":
        raise HTTPException(409, "subscription totals require a valid ledger base currency")
    if not subscriptions:
        return configured_base
    for sub in subscriptions:
        _base_price(sub)
        evidence_base = finance_currency.currency_code(
            getattr(sub, "canonical_base_currency_code", "") or sub.base_currency_code
        )
        if evidence_base != configured_base:
            raise HTTPException(
                409,
                "subscription totals require reviewed conversion evidence in the configured ledger base currency",
            )
    return configured_base


def _trial_days_left(sub, today: date):
    if not (sub.trial_end or ""):
        return None
    try:
        return (_parse(sub.trial_end) - today).days
    except ValueError:
        return None


def _fmt(
    sub: Subscription,
    today: date,
    *,
    renewal_review_required: bool = False,
) -> dict:
    due = _parse_maybe(sub.next_due)
    days = (due - today).days if due else None
    notification_marker = str(sub.last_notified_due or "")
    if notification_marker.startswith("pending:"):
        notification_state = "pending"
        notification_due = notification_marker.removeprefix("pending:")
    elif notification_marker.startswith("uncertain:"):
        notification_state = "uncertain"
        notification_due = notification_marker.removeprefix("uncertain:")
    elif notification_marker:
        notification_state = "sent"
        notification_due = notification_marker
    else:
        notification_state = "idle"
        notification_due = ""
    return {
        "id": sub.id,
        "trial_end": sub.trial_end or "",
        "trial_days_left": _trial_days_left(sub, today),
        "name": sub.name,
        "price": sub.price,
        "currency": sub.currency,
        "cycle": sub.cycle,
        "cycle_days": sub.cycle_days,
        "next_due": sub.next_due,
        "days_until": days,
        "payable": sub.active and days is not None and days <= 0,
        "renewal_review_required": renewal_review_required,
        "monthly_cost": round(_monthly_cost(sub), 2),
        "category": sub.category,
        "url": sub.url,
        "cancel_url": sub.cancel_url or "",
        "notes": sub.notes,
        "active": sub.active,
        "remind_days": sub.remind_days,
        "account_id": sub.account_id or "",
        "created_at": sub.created_at.isoformat(),
        "original_price_text": sub.original_price_text or finance_currency.decimal_text(sub.price),
        "original_currency_code": sub.original_currency_code
        or finance_currency.currency_code(sub.currency),
        "base_price_text": sub.base_price_text or "",
        "base_currency_code": sub.base_currency_code or "",
        "canonical_base_price_text": getattr(sub, "canonical_base_price_text", "")
        or sub.base_price_text
        or "",
        "canonical_base_currency_code": getattr(sub, "canonical_base_currency_code", "")
        or sub.base_currency_code
        or "",
        "fx_rate_text": sub.fx_rate_text or "",
        "fx_rate_date": sub.fx_rate_date or "",
        "fx_source": sub.fx_source or "",
        "notification_delivery": {"state": notification_state, "due": notification_due},
    }


def _merge_payment_history(legacy: list[dict], canonical: list[dict]) -> list[dict]:
    canonical_sources = {
        str(row.get("source_payment_id") or "") for row in canonical if row.get("source_payment_id")
    }
    canonical_transactions = {
        str(row.get("txn_id") or "") for row in canonical if row.get("txn_id")
    }
    if any(
        not str(row.get("source_payment_id") or "") and not str(row.get("txn_id") or "")
        for row in canonical
    ):
        raise actual_finance.ActualFinanceError(
            "canonical subscription payment is missing its durable identity"
        )
    remaining_legacy = [
        row
        for row in legacy
        if str(row.get("source_payment_id") or "") not in canonical_sources
        and (
            not str(row.get("txn_id") or "")
            or str(row.get("txn_id") or "") not in canonical_transactions
        )
    ]
    return [*remaining_legacy, *canonical]


@router.get("/subscriptions")
def list_subscriptions(advance: bool = True, db: DbSession = Depends(get_db)):
    today = date.today()
    renewal_review_required: set[str] = set()
    # Select the authoritative rows and perform the historical legacy advance
    # under one authority snapshot. A cutover or rollback cannot swap ledgers
    # between the read and its conditional mutation.
    with actual_finance.AUTHORITY_LOCK:
        subs = _subscription_rows(db)
        if advance:
            changed = False
            for sub in subs:
                try:
                    changed = _roll_and_post(sub, today, db) or changed
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    renewal_review_required.add(sub.id)
            if changed:
                db.commit()
    active = [s for s in subs if s.active]
    try:
        aggregate_currency = _aggregate_currency(active, db)
        monthly = sum(_base_monthly_cost(s) for s in active)
        totals_available = True
    except HTTPException:
        aggregate_currency = ""
        monthly = None
        totals_available = False
    items = sorted(
        (
            _fmt(
                s,
                today,
                renewal_review_required=s.id in renewal_review_required,
            )
            for s in subs
        ),
        key=lambda x: (not x["active"], x["days_until"] is None, x["days_until"] or 0),
    )
    from core.database import SubPayment

    legacy_payments: dict[str, list[dict]] = {}
    for payment in db.query(SubPayment).all():
        legacy_payments.setdefault(payment.sub_id, []).append(
            {
                "id": payment.id,
                "txn_id": payment.txn_id or "",
                "source_payment_id": payment.id,
            }
        )
    counts = {sub_id: len(rows) for sub_id, rows in legacy_payments.items()}
    with actual_finance.AUTHORITY_LOCK:
        if actual_finance.is_canonical(db):
            try:
                canonical_payments = actual_finance.subscription_payments(db)
            except actual_finance.ActualFinanceUnavailable as exc:
                raise HTTPException(
                    503, f"canonical subscription payments are unavailable: {exc}"
                ) from exc
            except actual_finance.ActualFinanceError as exc:
                raise HTTPException(409, str(exc)) from exc
            for sub_id in set(legacy_payments) | set(canonical_payments):
                counts[sub_id] = len(
                    _merge_payment_history(
                        legacy_payments.get(sub_id, []), canonical_payments.get(sub_id, [])
                    )
                )
    from core.database import SubPriceChange

    latest_change = {}
    for c in db.query(SubPriceChange).order_by(SubPriceChange.created_at.asc()).all():
        latest_change[c.sub_id] = c  # asc → last write wins = most recent
    for it in items:
        it["paid_count"] = counts.get(it["id"], 0)
        c = latest_change.get(it["id"])
        it["price_increased"] = bool(c and c.new_price > c.old_price)
        it["last_price_change"] = (
            {"old": c.old_price, "new": c.new_price, "date": c.date} if c else None
        )
    return {
        "subscriptions": items,
        "summary": {
            "active": len(active),
            "monthly_total": round(monthly, 2) if monthly is not None else None,
            "yearly_total": round(monthly * 12, 2) if monthly is not None else None,
            "currency": aggregate_currency,
            "totals_available": totals_available,
        },
    }


@router.get("/subscriptions/analytics")
def analytics(db: DbSession = Depends(get_db)):
    """normalized monthly spend, broken down by category and by billing cycle."""
    active = [s for s in _subscription_rows(db) if s.active]
    aggregate_currency = _aggregate_currency(active, db)
    by_cat: dict[str, float] = {}
    by_cycle: dict[str, float] = {}
    for s in active:
        mc = _base_monthly_cost(s)
        cat = (s.category or "").strip() or "uncategorized"
        by_cat[cat] = by_cat.get(cat, 0) + mc
        by_cycle[s.cycle] = by_cycle.get(s.cycle, 0) + mc
    monthly = sum(_base_monthly_cost(s) for s in active)
    return {
        "monthly_total": round(monthly, 2),
        "yearly_total": round(monthly * 12, 2),
        "currency": aggregate_currency,
        "count": len(active),
        "by_category": [
            {"name": k, "monthly": round(v, 2)}
            for k, v in sorted(by_cat.items(), key=lambda x: -x[1])
        ],
        "by_cycle": [
            {"name": k, "monthly": round(v, 2)}
            for k, v in sorted(by_cycle.items(), key=lambda x: -x[1])
        ],
    }


class SubBody(BaseModel):
    name: str
    price: float = 0.0
    currency: str = ""
    cycle: str = "monthly"
    cycle_days: int = 30
    next_due: str
    category: str = ""
    url: str = ""
    cancel_url: str = ""
    notes: str = ""
    remind_days: int = 1
    account_id: str = ""
    trial_end: str = ""


def _validate(body: SubBody):
    if not body.name.strip():
        raise HTTPException(400, "name required")
    if body.cycle not in CYCLES:
        raise HTTPException(400, f"cycle must be one of {', '.join(CYCLES)}")
    if not math.isfinite(body.price) or body.price < 0:
        raise HTTPException(400, "price must be a finite non-negative number")
    try:
        finance_currency.minor_unit_decimal_text(body.price)
    except ValueError as exc:
        raise HTTPException(400, "price must be a supported amount in cents") from exc
    try:
        _parse(body.next_due)
    except ValueError:
        raise HTTPException(400, "next_due must be an ISO date (YYYY-MM-DD)")


@router.get("/subscriptions/trials")
def trials_ending(days: int = 14, db: DbSession = Depends(get_db)):
    """subscriptions whose free trial / cancel-by lands in the next `days` days."""
    today = date.today()
    out = []
    for sub in _subscription_rows(db):
        dl = _trial_days_left(sub, today)
        if dl is not None and 0 <= dl <= days:
            out.append(_fmt(sub, today))
    out.sort(key=lambda s: s["trial_days_left"])
    return out


_CYCLE_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 91, "yearly": 365}


def _cycle_len(sub) -> int:
    return _CYCLE_DAYS.get(sub.cycle, max(1, sub.cycle_days or 30))


@router.get("/subscriptions/unused")
def unused_subscriptions(cycles: int = 2, as_of: str = "", db: DbSession = Depends(get_db)):
    """active subs with no matching money charge (name in payee/notes/category) in the
    last `cycles` cycle-lengths — likely forgotten/unused (4e)."""
    from core.database import Transaction

    try:
        today = _parse(as_of) if as_of else date.today()
    except ValueError:
        today = date.today()
    if actual_finance.is_canonical(db):
        try:
            transaction_rows = [SimpleNamespace(**row) for row in actual_finance.transactions(db)]
        except actual_finance.ActualFinanceUnavailable as exc:
            raise HTTPException(503, f"canonical transactions are unavailable: {exc}") from exc
        except actual_finance.ActualFinanceError as exc:
            raise HTTPException(409, str(exc)) from exc
    else:
        transaction_rows = db.query(Transaction).all()
    charges = [t for t in transaction_rows if (t.amount or 0.0) < 0]
    out = []
    for sub in (row for row in _subscription_rows(db) if row.active):
        name = (sub.name or "").strip().lower()
        if not name:
            continue
        win = _cycle_len(sub) * max(1, cycles)
        cutoff = today - timedelta(days=win)
        matched = False
        for t in charges:
            hay = f"{t.payee or ''} {t.notes or ''} {t.category or ''}".lower()
            if name in hay:
                try:
                    td = _parse(t.date)
                except ValueError:
                    continue
                if cutoff <= td <= today:
                    matched = True
                    break
        if not matched:
            row = _fmt(sub, today)
            row["no_charge_days"] = win
            out.append(row)
    return {"unused": out}


@router.get("/subscriptions/upcoming")
def upcoming_renewals(days: int = 7, db: DbSession = Depends(get_db)):
    """active subs whose next charge lands in the next `days` days, soonest first,
    plus the summed cost — answers 'what's hitting my card this week, and how much'."""
    today = date.today()
    matched = []
    for sub in _subscription_rows(db):
        if not sub.active:
            continue
        due = _parse_maybe(sub.next_due)
        if not due:
            continue
        du = (due - today).days
        if 0 <= du <= days:
            matched.append(sub)
    aggregate_currency = _aggregate_currency(matched, db)
    items = [_fmt(sub, today) for sub in matched]
    items.sort(key=lambda s: s["days_until"])
    total = round(sum(_base_price(sub) for sub in matched), 2)
    return {
        "days": days,
        "count": len(items),
        "total": total,
        "currency": aggregate_currency,
        "items": items,
    }


def _norm_name(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def _host(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    if not m:
        return ""
    h = m.group(1).lower()
    return h[4:] if h.startswith("www.") else h


@router.get("/subscriptions/duplicates")
def duplicates(db: DbSession = Depends(get_db)):
    """flag subs that look like the same service tracked twice — same normalized
    name OR same url host. union-find so a name-match and a host-match chain together."""
    subs = _subscription_rows(db)
    parent = {s.id: s.id for s in subs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    by_name, by_host = defaultdict(list), defaultdict(list)
    for s in subs:
        nn = _norm_name(s.name)
        if nn:
            by_name[nn].append(s.id)
        h = _host(s.url)
        if h:
            by_host[h].append(s.id)
    for ids in list(by_name.values()) + list(by_host.values()):
        for other in ids[1:]:
            union(ids[0], other)

    clusters = defaultdict(list)
    for s in subs:
        clusters[find(s.id)].append(s)
    groups = []
    for grp in clusters.values():
        if len(grp) > 1:
            groups.append(
                {
                    "subs": [
                        {"id": s.id, "name": s.name, "price": s.price, "url": s.url} for s in grp
                    ]
                }
            )
    return {"groups": groups, "count": len(groups)}


@router.get("/subscriptions/overlaps")
def overlaps(db: DbSession = Depends(get_db)):
    """flag paying for 2+ services in the same redundant category (spotify + apple music). 2f"""
    from services import sub_overlap

    groups = sub_overlap.overlaps(_subscription_rows(db))
    return {"groups": groups, "count": len(groups)}


@router.get("/subscriptions/forecast")
def forecast(months: int = 6, db: DbSession = Depends(get_db)):
    """project each active sub's charges across the next `months` calendar months."""
    months = max(1, min(24, months))
    today = date.today()
    active = [s for s in _subscription_rows(db) if s.active]
    aggregate_currency = _aggregate_currency(active, db)
    buckets = []
    y, m = today.year, today.month
    for _ in range(months):
        buckets.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    last_y, last_m = buckets[-1]
    end = date(last_y, last_m, calendar.monthrange(last_y, last_m)[1])
    totals = {bkt: 0.0 for bkt in buckets}
    for s in active:
        d = _parse_maybe(s.next_due)
        if not d:
            continue
        guard = 0
        while d < today and guard < 2000:  # skip charges already in the past
            d = _advance(d, s.cycle, s.cycle_days)
            guard += 1
        while d <= end and guard < 2000:
            key = (d.year, d.month)
            if key in totals:
                totals[key] += _base_price(s)
            d = _advance(d, s.cycle, s.cycle_days)
            guard += 1
    out = [
        {"month": f"{by:04d}-{bm:02d}", "total": round(totals[(by, bm)], 2)} for (by, bm) in buckets
    ]
    return {
        "months": months,
        "currency": aggregate_currency,
        "forecast": out,
        "total": round(sum(x["total"] for x in out), 2),
    }


@router.post("/subscriptions", dependencies=[Depends(_subscription_write_preflight)])
@_subscription_write_authority
def create_subscription(body: SubBody, db: DbSession = Depends(get_db)):
    _validate(body)
    state = db.get(FinanceLedgerState, "primary")
    default_currency = finance_currency.currency_code(state.base_currency_code if state else "CAD")
    resolved_currency = (body.currency or "").strip() or default_currency
    if finance_currency.currency_code(resolved_currency) == "XXX":
        raise HTTPException(400, "currency must be an unambiguous ISO currency code")
    sub = Subscription(
        name=body.name.strip(),
        price=body.price,
        currency=resolved_currency,
        cycle=body.cycle,
        cycle_days=body.cycle_days,
        next_due=str(body.next_due)[:10],
        category=body.category.strip(),
        url=body.url.strip(),
        cancel_url=(body.cancel_url or "").strip(),
        notes=body.notes,
        remind_days=max(0, body.remind_days),
        account_id=(body.account_id or "").strip(),
        trial_end=str(body.trial_end or "")[:10],
    )
    finance_currency.prepare_subscription(sub)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return _fmt(sub, date.today())


class SubPatch(BaseModel):
    name: str | None = None
    price: float | None = None
    currency: str | None = None
    cycle: str | None = None
    cycle_days: int | None = None
    next_due: str | None = None
    category: str | None = None
    url: str | None = None
    cancel_url: str | None = None
    notes: str | None = None
    active: bool | None = None
    remind_days: int | None = None
    account_id: str | None = None
    trial_end: str | None = None


def _replace_subscription_currency_evidence(sub: Subscription, db: DbSession) -> None:
    """Reset evidence only after a real price/currency change."""
    price = finance_currency.minor_unit_decimal_text(sub.price)
    original_code = finance_currency.currency_code(sub.currency)
    state = db.get(FinanceLedgerState, "primary")
    configured_base = finance_currency.currency_code(
        state.base_currency_code if state else sub.base_currency_code
    )
    sub.original_price_text = price
    sub.original_currency_code = original_code
    if original_code != "XXX" and original_code == configured_base:
        sub.base_price_text = price
        sub.base_currency_code = configured_base
        sub.fx_rate_text = "1"
        sub.fx_rate_date = ""
        sub.fx_source = "manual_identity"
        return
    sub.base_price_text = ""
    sub.base_currency_code = configured_base if configured_base != "XXX" else ""
    sub.fx_rate_text = ""
    sub.fx_rate_date = ""
    sub.fx_source = ""


@router.patch("/subscriptions/{sid}", dependencies=[Depends(_subscription_write_preflight)])
@_subscription_write_authority
def update_subscription(sid: str, body: SubPatch, db: DbSession = Depends(get_db)):
    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    if body.cycle is not None and body.cycle not in CYCLES:
        raise HTTPException(400, f"cycle must be one of {', '.join(CYCLES)}")
    if body.price is not None and (not math.isfinite(body.price) or body.price < 0):
        raise HTTPException(400, "price must be a finite non-negative number")
    if body.price is not None:
        try:
            finance_currency.minor_unit_decimal_text(body.price)
        except ValueError as exc:
            raise HTTPException(400, "price must be a supported amount in cents") from exc
    price_changed = body.price is not None and body.price != (sub.price or 0.0)
    reviewed_currency = finance_currency.currency_code(sub.original_currency_code or sub.currency)
    submitted_currency = (
        finance_currency.currency_code(body.currency) if body.currency is not None else ""
    )
    submitted_display = str(body.currency or "").strip()
    existing_display = str(sub.currency or "").strip()
    if (
        body.currency is not None
        and submitted_display != existing_display
        and submitted_currency == "XXX"
    ):
        raise HTTPException(400, "currency must be an unambiguous ISO currency code")
    currency_changed = (
        body.currency is not None
        and submitted_display != existing_display
        and submitted_currency != reviewed_currency
    )
    if price_changed:
        from core.database import SubPriceChange

        db.add(
            SubPriceChange(
                sub_id=sub.id,
                old_price=sub.price or 0.0,
                new_price=body.price,
                date=date.today().isoformat(),
            )
        )
    if body.next_due is not None:
        try:
            _parse(body.next_due)
        except ValueError:
            raise HTTPException(400, "next_due must be an ISO date (YYYY-MM-DD)")
        sub.next_due = str(body.next_due)[:10]
        sub.last_notified_due = ""  # date changed → re-arm the renewal push
    for field in (
        "name",
        "price",
        "currency",
        "cycle",
        "cycle_days",
        "category",
        "url",
        "cancel_url",
        "notes",
        "active",
        "remind_days",
        "account_id",
        "trial_end",
    ):
        v = getattr(body, field)
        if v is not None:
            setattr(sub, field, v)
    if price_changed or currency_changed:
        _replace_subscription_currency_evidence(sub, db)
    db.commit()
    return _fmt(sub, date.today())


@router.post(
    "/subscriptions/{sid}/paid",
    dependencies=[Depends(_subscription_write_preflight)],
)
@_subscription_write_authority
def mark_paid(sid: str, db: DbSession = Depends(get_db)):
    """mark a DUE renewal paid: log the payment, optionally post the money txn, and
    advance to the next upcoming due. refuses if the sub isn't due yet — that's the
    fix for 'click paid forever and push the date into the future'."""
    from core.database import SubPayment

    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    today = date.today()
    paid_for = _parse(sub.next_due)
    if (paid_for - today).days > 0:
        raise HTTPException(400, "not due yet")

    txn_id = ""
    if (sub.account_id or "") and (sub.last_posted_due or "") < paid_for.isoformat():
        from core.database import Account

        account = db.get(Account, sub.account_id)
        if account:
            txn = _subscription_transaction(db, sub, account, paid_for.isoformat())
            txn_id = txn.id
            sub.last_posted_due = paid_for.isoformat()

    payment = SubPayment(
        sub_id=sub.id, date=paid_for.isoformat(), amount=sub.price or 0.0, txn_id=txn_id
    )
    finance_currency.prepare_payment(payment, sub)
    db.add(payment)

    # advance one full cycle; if overdue, keep advancing whole cycles so one click
    # lands on the next upcoming due (cycle-correct, never just "+1 month").
    nxt = _advance(paid_for, sub.cycle, sub.cycle_days)
    guard = 0
    while (
        nxt < today and guard < 600
    ):  # only skip strictly-past cycles; a due-today stays payable (matches _roll)
        nxt = _advance(nxt, sub.cycle, sub.cycle_days)
        guard += 1
    sub.next_due = nxt.isoformat()
    db.commit()
    return _fmt(sub, today)


@router.get("/subscriptions/{sid}/payments")
def list_payments(sid: str, db: DbSession = Depends(get_db)):
    from core.database import SubPayment

    if not _subscription_exists(db, sid):
        raise HTTPException(404)
    rows = (
        db.query(SubPayment)
        .filter(SubPayment.sub_id == sid)
        .order_by(SubPayment.created_at.desc())
        .all()
    )
    payments = [
        {
            "id": p.id,
            "date": p.date,
            "amount": p.amount,
            "txn_id": p.txn_id or "",
            "source_payment_id": p.id,
        }
        for p in rows
    ]
    with actual_finance.AUTHORITY_LOCK:
        if actual_finance.is_canonical(db):
            state = db.get(FinanceLedgerState, "primary")
            base_currency = finance_currency.currency_code(
                state.base_currency_code if state else ""
            )
            payments = [
                {
                    "id": payment.id,
                    "date": payment.date,
                    "amount": float(payment.base_amount_text),
                    "currency": finance_currency.currency_code(
                        payment.base_currency_code or base_currency
                    ),
                    "txn_id": payment.txn_id or "",
                    "original_amount_text": payment.original_amount_text or "",
                    "original_currency_code": payment.original_currency_code or "",
                    "base_amount_text": payment.base_amount_text or "",
                    "base_currency_code": payment.base_currency_code or base_currency,
                    "source_payment_id": payment.id,
                }
                for payment in rows
            ]
            try:
                canonical = actual_finance.subscription_payments(db, subscription_id=sid).get(
                    sid, []
                )
            except actual_finance.ActualFinanceUnavailable as exc:
                raise HTTPException(
                    503, f"canonical subscription payments are unavailable: {exc}"
                ) from exc
            except actual_finance.ActualFinanceError as exc:
                raise HTTPException(409, str(exc)) from exc
            payments = _merge_payment_history(
                payments,
                [{**item, "currency": base_currency} for item in canonical],
            )
    public = [
        {key: value for key, value in payment.items() if key != "source_payment_id"}
        for payment in payments
    ]
    return sorted(public, key=lambda item: (item["date"], item["id"]), reverse=True)


@router.post(
    "/subscriptions/{sid}/payments/undo",
    dependencies=[Depends(_subscription_write_preflight)],
)
@_subscription_write_authority
def undo_payment(sid: str, db: DbSession = Depends(get_db)):
    """undo the most recent payment: drop its money txn (if any) and step next_due
    back to the date that was paid."""
    from core.database import SubPayment, Transaction

    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    last = (
        db.query(SubPayment)
        .filter(SubPayment.sub_id == sid)
        .order_by(SubPayment.created_at.desc())
        .first()
    )
    if not last:
        raise HTTPException(400, "no payment to undo")
    if last.txn_id:
        t = db.get(Transaction, last.txn_id)
        if t:
            db.delete(t)
    sub.next_due = last.date
    paid_date = last.date
    db.delete(last)
    db.flush()
    # restore the idempotency marker to its pre-payment state instead of wiping it to "" (which
    # made the next roll re-post every already-charged renewal). keep it < the undone cycle so a
    # re-pay can re-post exactly that charge.
    prev = (
        db.query(SubPayment)
        .filter(SubPayment.sub_id == sid)
        .order_by(SubPayment.created_at.desc())
        .first()
    )
    if prev:
        sub.last_posted_due = prev.date
    else:
        from datetime import timedelta

        sub.last_posted_due = (_parse(paid_date) - timedelta(days=1)).isoformat()
    db.commit()
    return _fmt(sub, date.today())


@router.get("/subscriptions/{sid}/price-history")
def price_history(sid: str, db: DbSession = Depends(get_db)):
    from core.database import SubPriceChange

    if not _subscription_exists(db, sid):
        raise HTTPException(404)
    rows = (
        db.query(SubPriceChange)
        .filter(SubPriceChange.sub_id == sid)
        .order_by(SubPriceChange.created_at.desc())
        .all()
    )
    return [{"old": r.old_price, "new": r.new_price, "date": r.date} for r in rows]


@router.delete("/subscriptions/{sid}", dependencies=[Depends(_subscription_write_preflight)])
@_subscription_write_authority
def delete_subscription(sid: str, db: DbSession = Depends(get_db)):
    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    db.delete(sub)
    db.commit()
    return {"ok": True}


def _notification_schedule(
    db: DbSession,
    subscription_id: str,
    due_key: str,
    canonical: bool,
):
    if actual_finance.is_canonical(db) != canonical:
        return None
    if canonical:
        schedules = _subscription_rows(db)
        schedule = next((row for row in schedules if row.id == subscription_id), None)
    else:
        schedule = db.get(Subscription, subscription_id)
    if (
        schedule is None
        or not schedule.active
        or schedule.next_due != due_key
        or schedule.remind_days <= 0
    ):
        return None
    return schedule


def _claim_notification(
    db: DbSession,
    subscription_id: str,
    due_key: str,
    canonical: bool,
    today: date,
):
    with actual_finance.AUTHORITY_LOCK:
        db.rollback()
        schedule = _notification_schedule(db, subscription_id, due_key, canonical)
        marker_row = db.get(Subscription, subscription_id)
        if schedule is None or marker_row is None:
            return None
        terminal_markers = {
            due_key,
            f"pending:{due_key}",
            f"uncertain:{due_key}",
        }
        if marker_row.last_notified_due in terminal_markers:
            return None
        try:
            days = (_parse(due_key) - today).days
        except ValueError:
            return None
        if days > schedule.remind_days:
            return None
        marker_row.last_notified_due = f"pending:{due_key}"
        db.commit()
        return schedule


def _finalize_notification(
    db: DbSession,
    subscription_id: str,
    due_key: str,
    canonical: bool,
    marker: str,
) -> bool:
    with actual_finance.AUTHORITY_LOCK:
        db.rollback()
        schedule = _notification_schedule(db, subscription_id, due_key, canonical)
        marker_row = db.get(Subscription, subscription_id)
        if (
            schedule is None
            or marker_row is None
            or marker_row.last_notified_due != f"pending:{due_key}"
        ):
            return False
        marker_row.last_notified_due = marker
        db.commit()
        return True


def _prepare_renewals(today: date) -> tuple[bool, list[tuple[str, str]]]:
    db = SessionLocal()
    try:
        with actual_finance.AUTHORITY_LOCK:
            legacy_subs = db.query(Subscription).all()
            canonical = actual_finance.is_canonical(db)
            changed = False
            for sub in legacy_subs:
                marker = str(sub.last_notified_due or "")
                if marker.startswith("pending:"):
                    sub.last_notified_due = f"uncertain:{marker.removeprefix('pending:')}"
                    changed = True
            if not canonical:
                for sub in legacy_subs:
                    if not sub.active:
                        continue
                    try:
                        changed = _roll_and_post(sub, today, db) or changed
                    except HTTPException as exc:
                        if exc.status_code != 409:
                            raise
            if changed:
                db.commit()
            rows = _subscription_rows(db) if canonical else legacy_subs
            return canonical, [(str(row.id), str(row.next_due)) for row in rows if row.active]
    finally:
        db.close()


def _claim_notification_once(
    subscription_id: str,
    due_key: str,
    canonical: bool,
    today: date,
):
    db = SessionLocal()
    try:
        schedule = _claim_notification(db, subscription_id, due_key, canonical, today)
        if schedule is None:
            return None
        return SimpleNamespace(
            id=str(schedule.id),
            name=str(schedule.name),
            next_due=str(schedule.next_due),
            currency=str(schedule.currency),
            price=float(schedule.price or 0),
        )
    finally:
        db.close()


def _finalize_notification_once(
    subscription_id: str,
    due_key: str,
    canonical: bool,
    marker: str,
) -> bool:
    db = SessionLocal()
    try:
        return _finalize_notification(db, subscription_id, due_key, canonical, marker)
    finally:
        db.close()


async def check_renewals():
    """called from the background loop — push once per billing period when a
    renewal is within the subscription's reminder window."""
    from routes.push import broadcast_result

    today = date.today()
    # Every database and Actual bridge operation stays inside the worker that
    # owns its SQLAlchemy session. Push delivery remains async on the main loop.
    canonical, subscriptions = await asyncio.to_thread(_prepare_renewals, today)
    for subscription_id, due_key in subscriptions:
        claimed = await asyncio.to_thread(
            _claim_notification_once,
            subscription_id,
            due_key,
            canonical,
            today,
        )
        if claimed is None:
            continue
        days = (_parse(claimed.next_due) - today).days
        when = "today" if days <= 0 else ("tomorrow" if days == 1 else f"in {days} days")
        price = f" — {claimed.currency}{claimed.price:g}" if claimed.price else ""
        try:
            result = await broadcast_result(
                {
                    "title": "subscription renewal",
                    "body": f"{claimed.name} renews {when}{price}",
                    "url": "/",
                    "tag": f"sub-{claimed.id}-{claimed.next_due}",
                }
            )
            if result["sent"]:
                marker = due_key
            elif result["uncertain"]:
                marker = f"uncertain:{due_key}"
            else:
                marker = ""
            await asyncio.to_thread(
                _finalize_notification_once,
                subscription_id,
                due_key,
                canonical,
                marker,
            )
        except Exception as e:
            await asyncio.to_thread(
                _finalize_notification_once,
                subscription_id,
                due_key,
                canonical,
                f"uncertain:{due_key}",
            )
            log.warning("renewal push outcome uncertain: %s", type(e).__name__)


@router.get("/subscriptions/detect")
def detect_subscriptions(db: DbSession = Depends(get_db)):
    """propose recurring charges from the money ledger (1f engine) that aren't already
    tracked as subs. 4e turns a candidate into a real subscription."""
    from core.database import Transaction
    from services import txn_ingest

    if actual_finance.is_canonical(db):
        try:
            txns = actual_finance.transactions(db)
        except actual_finance.ActualFinanceUnavailable as exc:
            raise HTTPException(503, f"canonical transactions are unavailable: {exc}") from exc
        except actual_finance.ActualFinanceError as exc:
            raise HTTPException(409, str(exc)) from exc
    else:
        txns = [
            {"date": t.date, "amount": t.amount, "payee": t.payee}
            for t in db.query(Transaction).all()
        ]
    cands = txn_ingest.detect_recurring(txns)
    existing = {(s.name or "").strip().lower() for s in _subscription_rows(db)}
    out = [c for c in cands if (c["payee"] or "").strip().lower() not in existing]
    return {"candidates": out}
