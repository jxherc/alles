"""Shared rules for creating owner-managed calendar events."""

import json
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.database import BookingPage, Calendar, CalendarEvent, EventAttendee, SessionLocal
from core.settings import load_settings
from services.commitment_requests import create_request
from services.commitment_sources import source_dict, source_json


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
        "source": source_dict(event.source_json),
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
        cal = Calendar(name="Personal", color="accent", is_default=True, sort_order=0)
        db.add(cal)
        db.flush()
        db.query(CalendarEvent).filter(
            (CalendarEvent.calendar_id == "") | (CalendarEvent.calendar_id.is_(None))
        ).update({"calendar_id": cal.id})
    return cal.id


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
    data = dict(data)
    if "source" in data:
        data["source_json"] = source_json(data.pop("source"))
    return {
        **data,
        "reminders": json.dumps(data.get("reminders") or []),
        "recur_except": json.dumps(data.get("recur_except") or []),
    }


def prepare_event(data: dict) -> dict:
    """Validate a proposal and resolve its duration without creating any records."""
    data = dict(data)
    if not data.get("all_day") and not data.get("end_dt") and data.get("start_dt"):
        data["end_dt"] = plus_minutes(data["start_dt"], default_duration()) or data.get("end_dt")
    validate_event(data)
    return data


def create_event(db: Session, data: dict) -> CalendarEvent:
    data = dict(data)
    request_id = data.pop("request_id", "")
    with create_request(db, "event", request_id, data) as (receipt, existing):
        if existing is not None:
            return existing
        data = prepare_event(data)
        data["calendar_id"] = data.get("calendar_id") or default_calendar_id(db)
        event = CalendarEvent(**event_columns(data))
        db.add(event)
        if receipt is not None:
            db.flush()
            receipt.resource_id = event.id
        db.commit()
        db.refresh(event)
        return event


def delete_event(db: Session, event: CalendarEvent) -> None:
    # Invitees have no FK cascade; their RSVP tokens must retire with the event.
    db.query(EventAttendee).filter(EventAttendee.event_id == event.id).delete()
    db.delete(event)
    db.commit()


def compute_booking_slots(db, page: BookingPage, date_str: str) -> list[dict]:
    """discrete bookable start times on a date for a booking page (steps the free
    windows by the page's duration). returns [{start,end}] ISO (minute precision)."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from services.recur import expand, free_slots

    try:
        day = _date.fromisoformat(date_str)
    except ValueError:
        return []
    rs = _dt.combine(day, _dt.min.time())
    re_ = rs + _td(days=1)
    busy = []
    for e in db.query(CalendarEvent).all():
        if e.all_day:
            continue
        try:
            base_s = _dt.fromisoformat(e.start_dt)
            base_e = _dt.fromisoformat(e.end_dt) if e.end_dt else base_s + _td(hours=1)
            dur = base_e - base_s
        except (ValueError, TypeError):
            continue
        if e.recurrence:
            for occ in expand(event_dict(e), rs, re_):
                busy.append((occ, occ + dur))
        elif rs <= base_s < re_:
            busy.append((base_s, base_e))
    windows = free_slots(busy, day, page.duration_min, page.work_start, page.work_end)
    step = _td(minutes=page.duration_min)
    out = []
    for w in windows:
        cur = _dt.fromisoformat(w["start"])
        wend = _dt.fromisoformat(w["end"])
        while cur + step <= wend:
            out.append(
                {
                    "start": cur.isoformat(timespec="minutes"),
                    "end": (cur + step).isoformat(timespec="minutes"),
                }
            )
            cur += step
    return out
