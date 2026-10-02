from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Reminder, ReminderCreateReceipt, Session, get_db
from services.model_resolver import ModelResolutionError, resolve_session_model

router = APIRouter(prefix="/api")


def _fmt(r: Reminder) -> dict:
    return {
        "id": r.id,
        "text": r.text,
        "trigger_at": r.trigger_at.isoformat(),
        "type": r.type,
        "session_id": r.session_id,
        "fired": r.fired,
        "delivery_started": r.type == "message" and bool(r.notified) and not r.fired,
        "created_at": r.created_at.isoformat(),
    }


class ReminderCreate(BaseModel):
    text: str
    trigger_at: str  # ISO datetime string
    type: str = "reminder"  # reminder | message
    session_id: str | None = None
    request_id: str = ""


@contextmanager
def _reminder_write(db, rid=""):
    # Release even read-only replay reservations before the response is serialized;
    # a scheduled job must not wait on a request's dependency cleanup.
    try:
        db.query(Reminder).filter_by(id=rid).update(
            {Reminder.id: Reminder.id}, synchronize_session=False
        )
        db.expire_all()
        yield
    finally:
        db.rollback()


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
    if trigger_at.tzinfo is not None:
        trigger_at = trigger_at.astimezone(UTC).replace(tzinfo=None)
    if not body.text.strip():
        raise HTTPException(400, "enter reminder text")
    if body.type not in {"reminder", "message"}:
        raise HTTPException(400, "type must be reminder or message")
    identity = None
    if body.request_id:
        try:
            identity = str(UUID(body.request_id))
            if body.request_id.lower() != identity:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "request_id must be a canonical UUID") from None
    with _reminder_write(db):
        receipt = db.get(ReminderCreateReceipt, identity) if identity else None
        if receipt is not None:
            saved = db.get(Reminder, receipt.reminder_id) if receipt.reminder_id else None
            if saved is None:
                raise HTTPException(
                    410, "this reminder was cancelled; discard the retry to start another"
                )
            if (saved.text, saved.trigger_at, saved.type, saved.session_id) != (
                body.text,
                trigger_at,
                body.type,
                body.session_id,
            ):
                raise HTTPException(409, "this request_id was already used for another reminder")
            return _fmt(saved)
        if body.type == "message":
            session = db.get(Session, body.session_id) if body.session_id else None
            if not session:
                raise HTTPException(400, "open a conversation in aide before scheduling a message")
            try:
                resolve_session_model(db, session)
            except ModelResolutionError as exc:
                raise HTTPException(400, f"choose an available model in aide: {exc}") from exc
        if identity:
            receipt = ReminderCreateReceipt(id=identity)
            db.add(receipt)
            db.flush()
        r = Reminder(
            text=body.text, trigger_at=trigger_at, type=body.type, session_id=body.session_id
        )
        db.add(r)
        if receipt is not None:
            db.flush()
            receipt.reminder_id = r.id
        db.commit()
        db.refresh(r)
        return _fmt(r)


@router.delete("/reminders/{rid}")
def delete_reminder(rid: str, db: DbSession = Depends(get_db)):
    with _reminder_write(db, rid):
        r = db.get(Reminder, rid)
        if not r:
            raise HTTPException(404, "not found")
        if r.type == "message" and r.notified and not r.fired:
            raise HTTPException(
                409, "this message has already started; check its conversation for a reply"
            )
        db.query(ReminderCreateReceipt).filter_by(reminder_id=rid).update(
            {ReminderCreateReceipt.reminder_id: None}, synchronize_session=False
        )
        db.delete(r)
        db.commit()
        return {"ok": True}


@router.get("/reminders/due")
def due_reminders(db: DbSession = Depends(get_db)):
    """Return pending due reminders without consuming them."""
    now = datetime.now(UTC).replace(tzinfo=None)
    due = (
        db.query(Reminder)
        .filter(
            Reminder.trigger_at <= now,
            Reminder.fired == False,
            Reminder.type == "reminder",
        )
        .all()
    )
    return [_fmt(r) for r in due]


@router.post("/reminders/{rid}/ack")
def acknowledge_reminder(rid: str, db: DbSession = Depends(get_db)):
    """Mark a plain reminder fired after the browser displays it."""
    with _reminder_write(db, rid):
        r = db.get(Reminder, rid)
        if not r:
            raise HTTPException(404, "not found")
        if r.type != "reminder" or r.trigger_at > datetime.now(UTC).replace(tzinfo=None):
            raise HTTPException(409, "reminder is not due")
        r.fired = True
        db.commit()
        return _fmt(r)
