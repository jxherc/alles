"""Shared rules for creating owner-managed calendar events."""

import json
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.database import Calendar, CalendarEvent, SessionLocal
from core.settings import load_settings


def json_list(value: str) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def event_dict(event: CalendarEvent) -> dict:
    """The saved Calendar event shape shared by reads and exports."""
    return {
        "id": event.id,
        "calendar_id": event.calendar_id or "",
        "title": event.title,
        "description": event.description,
        "location": event.location or "",
        "guests": event.guests or "",
        "start_dt": event.start_dt,
        "end_dt": event.end_dt,
        "all_day": event.all_day,
        "color": event.color,
        "reminders": json_list(event.reminders),
        "recurrence": event.recurrence or "",
        "recur_interval": event.recur_interval or 1,
        "recur_byday": event.recur_byday or "",
        "recur_count": event.recur_count,
        "recur_until": event.recur_until,
        "recur_except": json_list(event.recur_except),
        "meeting_url": event.meeting_url or "",
        "created_at": event.created_at.isoformat(),
    }


def seed_default_calendar():
    """First boot: make a Personal calendar and adopt pre-existing orphan events."""
    db = SessionLocal()
    try:
        if db.query(Calendar).count() == 0:
            cal = Calendar(name="Personal", color="accent", is_default=True, sort_order=0)
            db.add(cal)
            db.commit()
            db.query(CalendarEvent).filter(
                (CalendarEvent.calendar_id == "") | (CalendarEvent.calendar_id.is_(None))
            ).update({"calendar_id": cal.id})
            db.commit()
    finally:
        db.close()


def default_calendar_id(db: Session) -> str:
    cal = (
        db.query(Calendar).filter(Calendar.is_default == True).first()
        or db.query(Calendar).order_by(Calendar.sort_order).first()
    )
    if not cal:
        seed_default_calendar()
        cal = db.query(Calendar).filter(Calendar.is_default == True).first()
    return cal.id if cal else ""


def default_duration() -> int:
    """Minutes to use when a timed event has a start but no end."""
    try:
        value = int(load_settings().get("cal_default_duration_min") or 60)
        return value if value > 0 else 60
    except (ValueError, TypeError):
        return 60


def plus_minutes(iso: str, minutes: int):
    try:
        return (datetime.fromisoformat(iso) + timedelta(minutes=minutes)).isoformat()
    except (ValueError, TypeError):
        return None


def validate_event(data):
    if not str(data.get("title") or "").strip():
        raise HTTPException(400, "An event title is required.")
    try:
        start = datetime.fromisoformat(data.get("start_dt") or "")
        end = datetime.fromisoformat(data["end_dt"]) if data.get("end_dt") else None
        if end and (end.date() < start.date() if data.get("all_day") else end <= start):
            raise HTTPException(400, "The end must be after the start.")
    except (ValueError, TypeError):
        raise HTTPException(400, "Use valid start and end dates with matching timezones.") from None


def event_columns(data):
    return {
        **data,
        "reminders": json.dumps(data.get("reminders") or []),
        "recur_except": json.dumps(data.get("recur_except") or []),
    }


def create_event(db: Session, data: dict) -> CalendarEvent:
    data = dict(data)
    data["calendar_id"] = data.get("calendar_id") or default_calendar_id(db)
    if not data.get("all_day") and not data.get("end_dt") and data.get("start_dt"):
        data["end_dt"] = plus_minutes(data["start_dt"], default_duration()) or data.get("end_dt")
    validate_event(data)
    event = CalendarEvent(**event_columns(data))
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
