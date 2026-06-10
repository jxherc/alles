"""
days — event countdowns and "days since" counters. one-shot dates count
down then flip to counting up; yearly/monthly repeats roll to the next
occurrence and track which anniversary it is. push notifications fire
inside each event's reminder window.
"""
import calendar
import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, SessionLocal, DayEvent

router = APIRouter(prefix="/api")
log = logging.getLogger("aide.days")

REPEATS = ("none", "yearly", "monthly")


def _parse(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def _clamp(y: int, m: int, d: int) -> date:
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def _occurrence(orig: date, today: date, repeat: str) -> tuple[date, int]:
    """next occurrence on/after today, and which anniversary it is (1-based).
    handles feb 29 birthdays and 31st-of-month repeats by clamping."""
    if repeat == "yearly":
        occ = _clamp(today.year, orig.month, orig.day)
        if occ < today:
            occ = _clamp(today.year + 1, orig.month, orig.day)
        return occ, occ.year - orig.year
    if repeat == "monthly":
        occ = _clamp(today.year, today.month, orig.day)
        if occ < today:
            y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            occ = _clamp(y, m, orig.day)
        return occ, (occ.year - orig.year) * 12 + (occ.month - orig.month)
    return orig, 0


def _prev_occurrence(orig: date, occ: date, repeat: str) -> date:
    if repeat == "yearly":
        return _clamp(occ.year - 1, orig.month, orig.day)
    if repeat == "monthly":
        y, m = (occ.year - 1, 12) if occ.month == 1 else (occ.year, occ.month - 1)
        return _clamp(y, m, orig.day)
    return orig


def _ymd_between(a: date, b: date) -> str:
    """human breakdown of the span a→b, e.g. '2 years 3 months 12 days'"""
    if a > b:
        a, b = b, a
    y = b.year - a.year
    m = b.month - a.month
    d = b.day - a.day
    if d < 0:
        m -= 1
        pm_y, pm_m = (b.year - 1, 12) if b.month == 1 else (b.year, b.month - 1)
        d += calendar.monthrange(pm_y, pm_m)[1]
    if m < 0:
        y -= 1
        m += 12
    parts = []
    if y: parts.append(f"{y} year{'s' if y != 1 else ''}")
    if m: parts.append(f"{m} month{'s' if m != 1 else ''}")
    if d or not parts: parts.append(f"{d} day{'s' if d != 1 else ''}")
    return " ".join(parts)


def _fmt(ev: DayEvent, today: date) -> dict:
    orig = _parse(ev.date)
    if ev.repeat in ("yearly", "monthly"):
        target, nth = _occurrence(orig, today, ev.repeat)
        days = (target - today).days
        mode = "today" if days == 0 else "countdown"
        # progress through the current cycle
        prev = _prev_occurrence(orig, target, ev.repeat)
        span = (target - prev).days or 1
        progress = round(min(1.0, max(0.0, (today - prev).days / span)), 3)
        breakdown = _ymd_between(today, target) if days else ""
    else:
        target, nth = orig, 0
        days = (target - today).days
        mode = "today" if days == 0 else ("countdown" if days > 0 else "since")
        progress = None
        if days > 0:
            start = ev.created_at.date() if ev.created_at else today
            span = (target - start).days
            if span > 0:
                progress = round(min(1.0, max(0.0, (today - start).days / span)), 3)
        breakdown = _ymd_between(today, target) if days else ""
    return {
        "id": ev.id, "name": ev.name, "date": ev.date,
        "repeat": ev.repeat, "category": ev.category, "notes": ev.notes,
        "pinned": ev.pinned, "notify_days": ev.notify_days,
        "target": target.isoformat(), "days": days, "count": abs(days),
        "mode": mode, "nth": nth, "breakdown": breakdown, "progress": progress,
        "created_at": ev.created_at.isoformat(),
    }


@router.get("/days")
def list_days(db: DbSession = Depends(get_db)):
    today = date.today()
    items = [_fmt(e, today) for e in db.query(DayEvent).all()]
    items.sort(key=lambda x: (x["mode"] != "today", not x["pinned"],
                              x["mode"] == "since", x["count"]))
    return {
        "events": items,
        "summary": {
            "today": sum(1 for x in items if x["mode"] == "today"),
            "upcoming": sum(1 for x in items if x["mode"] == "countdown"),
            "since": sum(1 for x in items if x["mode"] == "since"),
        },
    }


class DayBody(BaseModel):
    name: str
    date: str
    repeat: str = "none"
    category: str = ""
    notes: str = ""
    pinned: bool = False
    notify_days: int = 1


def _validate(name: str, dt: str, repeat: str):
    if not name.strip():
        raise HTTPException(400, "name required")
    if repeat not in REPEATS:
        raise HTTPException(400, f"repeat must be one of {', '.join(REPEATS)}")
    try:
        _parse(dt)
    except ValueError:
        raise HTTPException(400, "date must be an ISO date (YYYY-MM-DD)")


@router.post("/days")
def create_day(body: DayBody, db: DbSession = Depends(get_db)):
    _validate(body.name, body.date, body.repeat)
    ev = DayEvent(name=body.name.strip(), date=str(body.date)[:10], repeat=body.repeat,
                  category=body.category.strip(), notes=body.notes,
                  pinned=body.pinned, notify_days=body.notify_days)
    db.add(ev); db.commit(); db.refresh(ev)
    return _fmt(ev, date.today())


class DayPatch(BaseModel):
    name: str | None = None
    date: str | None = None
    repeat: str | None = None
    category: str | None = None
    notes: str | None = None
    pinned: bool | None = None
    notify_days: int | None = None


@router.patch("/days/{eid}")
def update_day(eid: str, body: DayPatch, db: DbSession = Depends(get_db)):
    ev = db.get(DayEvent, eid)
    if not ev:
        raise HTTPException(404)
    if body.repeat is not None and body.repeat not in REPEATS:
        raise HTTPException(400, f"repeat must be one of {', '.join(REPEATS)}")
    if body.date is not None:
        try:
            _parse(body.date)
        except ValueError:
            raise HTTPException(400, "date must be an ISO date (YYYY-MM-DD)")
        ev.date = str(body.date)[:10]
        ev.last_notified = ""    # date changed → re-arm the push
    for field in ("name", "repeat", "category", "notes", "pinned", "notify_days"):
        v = getattr(body, field)
        if v is not None:
            setattr(ev, field, v)
    db.commit()
    return _fmt(ev, date.today())


@router.delete("/days/{eid}")
def delete_day(eid: str, db: DbSession = Depends(get_db)):
    ev = db.get(DayEvent, eid)
    if not ev:
        raise HTTPException(404)
    db.delete(ev); db.commit()
    return {"ok": True}


async def check_day_events():
    """called from the background loop — push when an event enters its
    reminder window, once per occurrence."""
    from routes.push import broadcast
    today = date.today()
    db = SessionLocal()
    try:
        for ev in db.query(DayEvent).filter(DayEvent.notify_days >= 0).all():
            orig = _parse(ev.date)
            if ev.repeat in ("yearly", "monthly"):
                target, nth = _occurrence(orig, today, ev.repeat)
            else:
                target, nth = orig, 0
                if target < today:
                    continue    # already counting up — nothing to announce
            days = (target - today).days
            if days > ev.notify_days or ev.last_notified == target.isoformat():
                continue
            ev.last_notified = target.isoformat()
            db.commit()
            nth_part = f" ({nth}{_ordinal(nth)} time)" if nth > 1 else ""
            when = "is today" if days == 0 else ("is tomorrow" if days == 1 else f"in {days} days")
            try:
                await broadcast({"title": "days", "body": f"{ev.name} {when}{nth_part}",
                                 "url": "/", "tag": f"day-{ev.id}-{target.isoformat()}"})
            except Exception as e:
                log.warning(f"day event push failed: {e}")
    finally:
        db.close()


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
