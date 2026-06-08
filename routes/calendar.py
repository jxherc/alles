from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, CalendarEvent

router = APIRouter(prefix="/api")

def _fmt(e: CalendarEvent) -> dict:
    return {
        "id": e.id, "title": e.title, "description": e.description,
        "start_dt": e.start_dt, "end_dt": e.end_dt,
        "all_day": e.all_day, "color": e.color,
        "recurrence": e.recurrence or "", "recur_until": e.recur_until,
        "created_at": e.created_at.isoformat(),
    }

@router.get("/calendar")
def list_events(db: DbSession = Depends(get_db)):
    rows = db.query(CalendarEvent).order_by(CalendarEvent.start_dt.asc()).all()
    return [_fmt(e) for e in rows]

class EventBody(BaseModel):
    title: str
    description: str = ""
    start_dt: str
    end_dt: Optional[str] = None
    all_day: bool = False
    color: str = ""
    recurrence: str = ""
    recur_until: Optional[str] = None

@router.post("/calendar")
def create_event(body: EventBody, db: DbSession = Depends(get_db)):
    e = CalendarEvent(**body.model_dump())
    db.add(e); db.commit(); db.refresh(e)
    return _fmt(e)

@router.patch("/calendar/{eid}")
def update_event(eid: str, body: EventBody, db: DbSession = Depends(get_db)):
    e = db.get(CalendarEvent, eid)
    if not e: raise HTTPException(404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(e, k, v)
    db.commit(); return _fmt(e)

@router.delete("/calendar/{eid}")
def delete_event(eid: str, db: DbSession = Depends(get_db)):
    e = db.get(CalendarEvent, eid)
    if not e: raise HTTPException(404)
    db.delete(e); db.commit()
    return {"ok": True}
