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
from core.database import get_db, SessionLocal, Subscription

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
    if cycle == "weekly":    return d + timedelta(days=7)
    if cycle == "monthly":   return _add_months(d, 1)
    if cycle == "quarterly": return _add_months(d, 3)
    if cycle == "yearly":    return _add_months(d, 12)
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


def _monthly_cost(sub: Subscription) -> float:
    if sub.cycle == "custom":
        return sub.price * 30.44 / max(1, sub.cycle_days or 30)
    return sub.price * _PER_MONTH.get(sub.cycle, 1.0)


def _fmt(sub: Subscription, today: date) -> dict:
    return {
        "id": sub.id, "name": sub.name,
        "price": sub.price, "currency": sub.currency,
        "cycle": sub.cycle, "cycle_days": sub.cycle_days,
        "next_due": sub.next_due,
        "days_until": (_parse(sub.next_due) - today).days,
        "monthly_cost": round(_monthly_cost(sub), 2),
        "category": sub.category, "url": sub.url, "notes": sub.notes,
        "active": sub.active, "remind_days": sub.remind_days,
        "created_at": sub.created_at.isoformat(),
    }


@router.get("/subscriptions")
def list_subscriptions(db: DbSession = Depends(get_db)):
    today = date.today()
    subs = db.query(Subscription).all()
    if any(_roll(s, today) for s in subs):
        db.commit()
    active = [s for s in subs if s.active]
    monthly = sum(_monthly_cost(s) for s in active)
    items = sorted((_fmt(s, today) for s in subs),
                   key=lambda x: (not x["active"], x["days_until"]))
    return {
        "subscriptions": items,
        "summary": {
            "active": len(active),
            "monthly_total": round(monthly, 2),
            "yearly_total": round(monthly * 12, 2),
            "currency": active[0].currency if active else "$",
        },
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


@router.post("/subscriptions")
def create_subscription(body: SubBody, db: DbSession = Depends(get_db)):
    _validate(body)
    sub = Subscription(
        name=body.name.strip(), price=body.price, currency=body.currency or "$",
        cycle=body.cycle, cycle_days=body.cycle_days,
        next_due=str(body.next_due)[:10], category=body.category.strip(),
        url=body.url.strip(), notes=body.notes, remind_days=max(0, body.remind_days),
    )
    db.add(sub); db.commit(); db.refresh(sub)
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


@router.patch("/subscriptions/{sid}")
def update_subscription(sid: str, body: SubPatch, db: DbSession = Depends(get_db)):
    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    if body.cycle is not None and body.cycle not in CYCLES:
        raise HTTPException(400, f"cycle must be one of {', '.join(CYCLES)}")
    if body.next_due is not None:
        try:
            _parse(body.next_due)
        except ValueError:
            raise HTTPException(400, "next_due must be an ISO date (YYYY-MM-DD)")
        sub.next_due = str(body.next_due)[:10]
        sub.last_notified_due = ""    # date changed → re-arm the renewal push
    for field in ("name", "price", "currency", "cycle", "cycle_days",
                  "category", "url", "notes", "active", "remind_days"):
        v = getattr(body, field)
        if v is not None:
            setattr(sub, field, v)
    db.commit()
    return _fmt(sub, date.today())


@router.post("/subscriptions/{sid}/paid")
def mark_paid(sid: str, db: DbSession = Depends(get_db)):
    """advance one billing cycle (e.g. after paying early or fixing the date)"""
    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    sub.next_due = _advance(_parse(sub.next_due), sub.cycle, sub.cycle_days).isoformat()
    db.commit()
    return _fmt(sub, date.today())


@router.delete("/subscriptions/{sid}")
def delete_subscription(sid: str, db: DbSession = Depends(get_db)):
    sub = db.get(Subscription, sid)
    if not sub:
        raise HTTPException(404)
    db.delete(sub); db.commit()
    return {"ok": True}


async def check_renewals():
    """called from the background loop — push once per billing period when a
    renewal is within the subscription's reminder window."""
    from routes.push import broadcast
    today = date.today()
    db = SessionLocal()
    try:
        subs = db.query(Subscription).filter(Subscription.active == True).all()
        if any(_roll(s, today) for s in subs):
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
                await broadcast({"title": "subscription renewal",
                                 "body": f"{s.name} renews {when}{price}",
                                 "url": "/", "tag": f"sub-{s.id}-{s.next_due}"})
            except Exception as e:
                log.warning(f"renewal push failed: {e}")
    finally:
        db.close()
