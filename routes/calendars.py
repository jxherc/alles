from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import get_db, SessionLocal, Calendar, CalendarEvent

router = APIRouter(prefix="/api")


def _fmt(c: Calendar) -> dict:
    return {"id": c.id, "name": c.name, "color": c.color, "visible": bool(c.visible),
            "is_default": bool(c.is_default), "sort_order": c.sort_order}


def seed_default_calendar():
    """first boot: make a 'Personal' calendar and adopt any pre-existing events."""
    db = SessionLocal()
    try:
        if db.query(Calendar).count() == 0:
            cal = Calendar(name="Personal", color="accent", is_default=True, sort_order=0)
            db.add(cal); db.commit()
            # adopt orphan events (from before calendars existed)
            db.query(CalendarEvent).filter(
                (CalendarEvent.calendar_id == "") | (CalendarEvent.calendar_id.is_(None))
            ).update({"calendar_id": cal.id})
            db.commit()
    finally:
        db.close()


def _default_id(db) -> str:
    c = db.query(Calendar).filter(Calendar.is_default == True).first() \
        or db.query(Calendar).order_by(Calendar.sort_order).first()
    return c.id if c else ""


@router.get("/calendars")
def list_calendars(db: DbSession = Depends(get_db)):
    cals = db.query(Calendar).order_by(Calendar.sort_order, Calendar.created_at).all()
    if not cals:
        seed_default_calendar()
        cals = db.query(Calendar).order_by(Calendar.sort_order, Calendar.created_at).all()
    return [_fmt(c) for c in cals]


class CalBody(BaseModel):
    name: str = "Calendar"
    color: str = "accent"
    visible: bool = True


@router.post("/calendars")
def create_calendar(body: CalBody, db: DbSession = Depends(get_db)):
    n = db.query(Calendar).count()
    c = Calendar(name=body.name.strip() or "Calendar", color=body.color or "accent",
                 visible=body.visible, sort_order=n)
    db.add(c); db.commit(); db.refresh(c)
    return _fmt(c)


class CalPatch(BaseModel):
    name: str | None = None
    color: str | None = None
    visible: bool | None = None
    sort_order: int | None = None


@router.patch("/calendars/{cid}")
def update_calendar(cid: str, body: CalPatch, db: DbSession = Depends(get_db)):
    c = db.get(Calendar, cid)
    if not c:
        raise HTTPException(404)
    for f in ("name", "color", "visible", "sort_order"):
        v = getattr(body, f)
        if v is not None:
            setattr(c, f, v)
    db.commit()
    return _fmt(c)


@router.delete("/calendars/{cid}")
def delete_calendar(cid: str, db: DbSession = Depends(get_db)):
    c = db.get(Calendar, cid)
    if not c:
        raise HTTPException(404)
    if c.is_default:
        raise HTTPException(400, "can't delete the default calendar")
    # move its events to the default calendar instead of nuking them
    dest = _default_id(db)
    db.query(CalendarEvent).filter(CalendarEvent.calendar_id == cid).update({"calendar_id": dest})
    db.delete(c); db.commit()
    return {"ok": True, "moved_to": dest}
