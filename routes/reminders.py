import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, Reminder

router = APIRouter(prefix="/api")


def _fmt(r: Reminder) -> dict:
    return {
        "id": r.id,
        "text": r.text,
        "trigger_at": r.trigger_at.isoformat(),
        "type": r.type,
        "session_id": r.session_id,
        "fired": r.fired,
        "created_at": r.created_at.isoformat(),
    }


class ReminderCreate(BaseModel):
    text: str
    trigger_at: str  # ISO datetime string
    type: str = "reminder"  # reminder | message
    session_id: str | None = None


@router.get("/reminders")
def list_reminders(db: DbSession = Depends(get_db)):
    rows = db.query(Reminder).filter_by(fired=False).order_by(Reminder.trigger_at).all()
    return [_fmt(r) for r in rows]


@router.post("/reminders")
def create_reminder(body: ReminderCreate, db: DbSession = Depends(get_db)):
    try:
        trigger_at = datetime.fromisoformat(body.trigger_at)
    except ValueError:
        raise HTTPException(400, "invalid trigger_at — use ISO format")
    r = Reminder(text=body.text, trigger_at=trigger_at, type=body.type, session_id=body.session_id)
    db.add(r)
    db.commit()
    db.refresh(r)
    return _fmt(r)


@router.delete("/reminders/{rid}")
def delete_reminder(rid: str, db: DbSession = Depends(get_db)):
    r = db.get(Reminder, rid)
    if not r:
        raise HTTPException(404, "not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.get("/reminders/due")
def due_reminders(db: DbSession = Depends(get_db)):
    """return reminders that are due and not yet fired; marks them fired"""
    now = datetime.utcnow()
    due = (
        db.query(Reminder)
        .filter(
            Reminder.trigger_at <= now,
            Reminder.fired == False,
            Reminder.type == "reminder",
        )
        .all()
    )
    for r in due:
        r.fired = True
    db.commit()
    return [_fmt(r) for r in due]
