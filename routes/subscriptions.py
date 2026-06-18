"""
subscription manager — recurring costs with billing cycles, due-date
rollover, monthly/yearly totals, and push reminders before renewals.
"""

import calendar
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import SessionLocal, Subscription, get_db

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


def _roll(sub: Subscription, today: date) -> bool:
    """advance an overdue next_due until it's in the future. returns changed."""
    if not sub.active:
        return False
    d = _parse(sub.next_due)
    changed = False
    while d < today:
        d = _advance(d, sub.cycle, sub.cycle_days)
        changed = True
    if changed:
        sub.next_due = d.isoformat()
    return changed


_POST_CAP = 36  # don't flood if the app sat unopened for years


def _roll_and_post(sub: Subscription, today: date, db) -> bool:
    """roll an overdue sub forward AND, if it's linked to a money account, drop a
    real transaction for each due date that just passed. idempotent via
    last_posted_due so the same renewal is never double-posted."""
    if not sub.active:
        return False
    from core.database import Transaction

    d = _parse(sub.next_due)
    charges = []
    while d < today:
        charges.append(d)  # this due date rolled over → a charge happened
        d = _advance(d, sub.cycle, sub.cycle_days)
    if not charges:
        return False
    from core.database import Account

    sub.next_due = d.isoformat()
    if (sub.account_id or "") and db.get(Account, sub.account_id):
        last = sub.last_posted_due or ""
        for cd in charges[-_POST_CAP:]:
            iso = cd.isoformat()
            if iso <= last:  # already posted this (or an earlier) renewal
                continue
            db.add(
                Transaction(
                    account_id=sub.account_id,
                    date=iso,
                    amount=-abs(sub.price or 0.0),
                    category=(sub.category or "subscriptions"),
                    payee=sub.name,
                    notes="auto: subscription renewal",
                )
            )
            sub.last_posted_due = iso
    return True


def _monthly_cost(sub: Subscription) -> float:
    if sub.cycle == "custom":
        return sub.price * 30.44 / max(1, sub.cycle_days or 30)
    return sub.price * _PER_MONTH.get(sub.cycle, 1.0)


def _trial_days_left(sub, today: date):
    if not (sub.trial_end or ""):
        return None
    try:
        return (_parse(sub.trial_end) - today).days
    except ValueError:
        return None


def _fmt(sub: Subscription, today: date) -> dict:
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
        "days_until": (_parse(sub.next_due) - today).days,
        "payable": sub.active and (_parse(sub.next_due) - today).days <= 0,
        "monthly_cost": round(_monthly_cost(sub), 2),
        "category": sub.category,
        "url": sub.url,
        "notes": sub.notes,
        "active": sub.active,
        "remind_days": sub.remind_days,
        "account_id": sub.account_id or "",
        "created_at": sub.created_at.isoformat(),
    }


@router.get("/subscriptions")
def list_subscriptions(db: DbSession = Depends(get_db)):
    today = date.today()
    subs = db.query(Subscription).all()
    if any(_roll_and_post(s, today, db) for s in subs):
        db.commit()
    active = [s for s in subs if s.active]
    monthly = sum(_monthly_cost(s) for s in active)
    items = sorted((_fmt(s, today) for s in subs), key=lambda x: (not x["active"], x["days_until"]))
    from sqlalchemy import func

    from core.database import SubPayment

    counts = dict(
        db.query(SubPayment.sub_id, func.count(SubPayment.id)).group_by(SubPayment.sub_id).all()
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
            "monthly_total": round(monthly, 2),
            "yearly_total": round(monthly * 12, 2),
            "currency": active[0].currency if active else "$",
        },
    }


@router.get("/subscriptions/analytics")
def analytics(db: DbSession = Depends(get_db)):
    """normalized monthly spend, broken down by category and by billing cycle."""
    active = [s for s in db.query(Subscription).all() if s.active]
    by_cat: dict[str, float] = {}
    by_cycle: dict[str, float] = {}
    for s in active:
        mc = _monthly_cost(s)
        cat = (s.category or "").strip() or "uncategorized"
        by_cat[cat] = by_cat.get(cat, 0) + mc
        by_cycle[s.cycle] = by_cycle.get(s.cycle, 0) + mc
    monthly = sum(_monthly_cost(s) for s in active)
    return {
        "monthly_total": round(monthly, 2),
        "yearly_total": round(monthly * 12, 2),
        "currency": active[0].currency if active else "$",
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
    currency: str = "$"
    cycle: str = "monthly"
    cycle_days: int = 30
    next_due: str
    category: str = ""
    url: str = ""
    notes: str = ""
    remind_days: int = 1
    account_id: str = ""
    trial_end: str = ""


def _validate(body: SubBody):
    if not body.name.strip():
        raise HTTPException(400, "name required")
    if body.cycle not in CYCLES:
        raise HTTPException(400, f"cycle must be one of {', '.join(CYCLES)}")
    if body.price < 0:
        raise HTTPException(400, "price can't be negative")
    try:
        _parse(body.next_due)
    except ValueError:
        raise HTTPException(400, "next_due must be an ISO date (YYYY-MM-DD)")


@router.get("/subscriptions/trials")
def trials_ending(days: int = 14, db: DbSession = Depends(get_db)):
    """subscriptions whose free trial / cancel-by lands in the next `days` days."""
    today = date.today()
    out = []
    for sub in db.query(Subscription).all():
        dl = _trial_days_left(sub, today)
        if dl is not None and 0 <= dl <= days:
            out.append(_fmt(sub, today))
    out.sort(key=lambda s: s["trial_days_left"])
    return out


@router.get("/subscriptions/upcoming")
def upcoming_renewals(days: int = 7, db: DbSession = Depends(get_db)):
    """active subs whose next charge lands in the next `days` days, soonest first,
    plus the summed cost — answers 'what's hitting my card this week, and how much'."""
    today = date.today()
    items = []
    for sub in db.query(Subscription).all():
        if not sub.active:
            continue
        du = (_parse(sub.next_due) - today).days
        if 0 <= du <= days:
            items.append(_fmt(sub, today))
    items.sort(key=lambda s: s["days_until"])
    total = round(sum(s["price"] or 0 for s in items), 2)
    return {
        "days": days,
        "count": len(items),
        "total": total,
        "currency": items[0]["currency"] if items else "$",
        "items": items,
    }


@router.get("/subscriptions/forecast")
def forecast(months: int = 6, db: DbSession = Depends(get_db)):
    """project each active sub's charges across the next `months` calendar months."""
    months = max(1, min(24, months))
    today = date.today()
    active = [s for s in db.query(Subscription).all() if s.active]
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
        d = _parse(s.next_due)
        guard = 0
        while d < today and guard < 2000:  # skip charges already in the past
            d = _advance(d, s.cycle, s.cycle_days)
            guard += 1
        while d <= end and guard < 2000:
            key = (d.year, d.month)
            if key in totals:
                totals[key] += s.price or 0.0
            d = _advance(d, s.cycle, s.cycle_days)
            guard += 1
    out = [
        {"month": f"{by:04d}-{bm:02d}", "total": round(totals[(by, bm)], 2)} for (by, bm) in buckets
    ]
    return {
        "months": months,
        "currency": active[0].currency if active else "$",
        "forecast": out,
        "total": round(sum(x["total"] for x in out), 2),
    }


@router.post("/subscriptions")
def create_subscription(body: SubBody, db: DbSession = Depends(get_db)):
    _validate(body)
    sub = Subscription(
        name=body.name.strip(),
        price=body.price,
        currency=body.currency or "$",
        cycle=body.cycle,
        cycle_days=body.cycle_days,
        next_due=str(body.next_due)[:10],
        category=body.category.strip(),
        url=body.url.strip(),
        notes=body.notes,
        remind_days=max(0, body.remind_days),
        account_id=(body.account_id or "").strip(),
        trial_end=str(body.trial_end or "")[:10],
    )
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
    notes: str | None = None
    active: bool | None = None
    remind_days: int | None = None
    account_id: str | None = None
    trial_end: str | None = None


@router.patch("/subscriptions/{sid}")
def update_subscription(sid: str, body: SubPatch, db: DbSession = Depends(get_db)):
    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    if body.cycle is not None and body.cycle not in CYCLES:
        raise HTTPException(400, f"cycle must be one of {', '.join(CYCLES)}")
    if body.price is not None and body.price != (sub.price or 0.0):
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
        "notes",
        "active",
        "remind_days",
        "account_id",
        "trial_end",
    ):
        v = getattr(body, field)
        if v is not None:
            setattr(sub, field, v)
    db.commit()
    return _fmt(sub, date.today())


@router.post("/subscriptions/{sid}/paid")
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
        from core.database import Account, Transaction

        if db.get(Account, sub.account_id):
            txn = Transaction(
                account_id=sub.account_id,
                date=paid_for.isoformat(),
                amount=-abs(sub.price or 0.0),
                category=(sub.category or "subscriptions"),
                payee=sub.name,
                notes="auto: subscription renewal",
            )
            db.add(txn)
            db.flush()
            txn_id = txn.id
            sub.last_posted_due = paid_for.isoformat()

    db.add(
        SubPayment(sub_id=sub.id, date=paid_for.isoformat(), amount=sub.price or 0.0, txn_id=txn_id)
    )

    # advance one full cycle; if overdue, keep advancing whole cycles so one click
    # lands on the next upcoming due (cycle-correct, never just "+1 month").
    nxt = _advance(paid_for, sub.cycle, sub.cycle_days)
    guard = 0
    while nxt <= today and guard < 600:
        nxt = _advance(nxt, sub.cycle, sub.cycle_days)
        guard += 1
    sub.next_due = nxt.isoformat()
    db.commit()
    return _fmt(sub, today)


@router.get("/subscriptions/{sid}/payments")
def list_payments(sid: str, db: DbSession = Depends(get_db)):
    from core.database import SubPayment

    if not db.get(Subscription, sid):
        raise HTTPException(404)
    rows = (
        db.query(SubPayment)
        .filter(SubPayment.sub_id == sid)
        .order_by(SubPayment.created_at.desc())
        .all()
    )
    return [
        {"id": p.id, "date": p.date, "amount": p.amount, "txn_id": p.txn_id or ""} for p in rows
    ]


@router.post("/subscriptions/{sid}/payments/undo")
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
    sub.last_posted_due = ""  # let a re-pay re-post the charge
    db.delete(last)
    db.commit()
    return _fmt(sub, date.today())


@router.get("/subscriptions/{sid}/price-history")
def price_history(sid: str, db: DbSession = Depends(get_db)):
    from core.database import SubPriceChange

    if not db.get(Subscription, sid):
        raise HTTPException(404)
    rows = (
        db.query(SubPriceChange)
        .filter(SubPriceChange.sub_id == sid)
        .order_by(SubPriceChange.created_at.desc())
        .all()
    )
    return [{"old": r.old_price, "new": r.new_price, "date": r.date} for r in rows]


@router.delete("/subscriptions/{sid}")
def delete_subscription(sid: str, db: DbSession = Depends(get_db)):
    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    db.delete(sub)
    db.commit()
    return {"ok": True}


async def check_renewals():
    """called from the background loop — push once per billing period when a
    renewal is within the subscription's reminder window."""
    from routes.push import broadcast

    today = date.today()
    db = SessionLocal()
    try:
        subs = db.query(Subscription).filter(Subscription.active == True).all()
        if any(_roll_and_post(s, today, db) for s in subs):
            db.commit()
        for s in subs:
            if s.remind_days <= 0 or s.last_notified_due == s.next_due:
                continue
            days = (_parse(s.next_due) - today).days
            if days > s.remind_days:
                continue
            s.last_notified_due = s.next_due
            db.commit()
            when = "today" if days <= 0 else ("tomorrow" if days == 1 else f"in {days} days")
            price = f" — {s.currency}{s.price:g}" if s.price else ""
            try:
                await broadcast(
                    {
                        "title": "subscription renewal",
                        "body": f"{s.name} renews {when}{price}",
                        "url": "/",
                        "tag": f"sub-{s.id}-{s.next_due}",
                    }
                )
            except Exception as e:
                log.warning(f"renewal push failed: {e}")
    finally:
        db.close()
