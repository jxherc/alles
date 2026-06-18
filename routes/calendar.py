import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import Calendar, CalendarEvent, get_db

router = APIRouter(prefix="/api")


def _jl(s):
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _fmt(e: CalendarEvent) -> dict:
    return {
        "id": e.id,
        "calendar_id": e.calendar_id or "",
        "title": e.title,
        "description": e.description,
        "location": e.location or "",
        "guests": e.guests or "",
        "start_dt": e.start_dt,
        "end_dt": e.end_dt,
        "all_day": e.all_day,
        "color": e.color,
        "reminders": _jl(e.reminders),
        "recurrence": e.recurrence or "",
        "recur_interval": e.recur_interval or 1,
        "recur_byday": e.recur_byday or "",
        "recur_count": e.recur_count,
        "recur_until": e.recur_until,
        "recur_except": _jl(e.recur_except),
        "created_at": e.created_at.isoformat(),
    }


def _default_cal(db) -> str:
    c = (
        db.query(Calendar).filter(Calendar.is_default == True).first()
        or db.query(Calendar).order_by(Calendar.sort_order).first()
    )
    if not c:
        from routes.calendars import seed_default_calendar

        seed_default_calendar()
        c = db.query(Calendar).filter(Calendar.is_default == True).first()
    return c.id if c else ""


@router.get("/calendar")
def list_events(db: DbSession = Depends(get_db)):
    rows = db.query(CalendarEvent).order_by(CalendarEvent.start_dt.asc()).all()
    return [_fmt(e) for e in rows]


@router.get("/calendar/tasks")
def calendar_tasks(start: str = "", end: str = "", db: DbSession = Depends(get_db)):
    """tasks that have a due date, as calendar items (overlay, Google Tasks style)."""
    from core.database import Task

    q = db.query(Task).filter(Task.due_date != None, Task.due_date != "")  # noqa: E711
    if start:
        q = q.filter(Task.due_date >= start)
    if end:
        q = q.filter(Task.due_date <= end)
    rows = q.order_by(Task.due_date.asc()).all()
    return [{"id": t.id, "title": t.title, "date": t.due_date, "done": t.done} for t in rows]


@router.get("/calendar/agenda")
def agenda(days: int = 30, db: DbSession = Depends(get_db)):
    """upcoming events grouped by day — a flat agenda list for the next N days."""
    from datetime import date, timedelta

    today = date.today().isoformat()
    until = (date.today() + timedelta(days=days)).isoformat()
    rows = (
        db.query(CalendarEvent)
        .filter(CalendarEvent.start_dt >= today, CalendarEvent.start_dt <= until + "T99")
        .order_by(CalendarEvent.start_dt.asc())
        .all()
    )
    groups: dict[str, list] = {}
    for e in rows:
        groups.setdefault(e.start_dt[:10], []).append(_fmt(e))
    return {"days": [{"date": d, "events": groups[d]} for d in sorted(groups)]}


class QuickEvent(BaseModel):
    text: str


@router.post("/calendar/quick")
def quick_event(body: QuickEvent, db: DbSession = Depends(get_db)):
    """natural-language event: 'lunch with sam friday 1pm', 'dentist june 20 9am'."""
    from services.event_nl import parse_event

    if not body.text.strip():
        raise HTTPException(400, "empty")
    p = parse_event(body.text)
    e = CalendarEvent(
        title=p["title"],
        start_dt=p["start_dt"],
        end_dt=p["end_dt"],
        all_day=p["all_day"],
        recurrence=p.get("recurrence", ""),
        recur_until=p.get("recur_until"),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return _fmt(e)


class EventBody(BaseModel):
    title: str
    calendar_id: str = ""
    description: str = ""
    location: str = ""
    guests: str = ""
    start_dt: str
    end_dt: Optional[str] = None
    all_day: bool = False
    color: str = ""
    reminders: list[int] = []
    recurrence: str = ""
    recur_interval: int = 1
    recur_byday: str = ""
    recur_count: Optional[int] = None
    recur_until: Optional[str] = None
    recur_except: list[str] = []


@router.post("/calendar")
def create_event(body: EventBody, db: DbSession = Depends(get_db)):
    data = body.model_dump()
    data["calendar_id"] = data.get("calendar_id") or _default_cal(db)
    data["reminders"] = json.dumps(data.get("reminders") or [])
    data["recur_except"] = json.dumps(data.get("recur_except") or [])
    e = CalendarEvent(**data)
    db.add(e)
    db.commit()
    db.refresh(e)
    return _fmt(e)


class EventPatch(BaseModel):
    title: Optional[str] = None
    calendar_id: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    guests: Optional[str] = None
    start_dt: Optional[str] = None
    end_dt: Optional[str] = None
    all_day: Optional[bool] = None
    color: Optional[str] = None
    reminders: Optional[list[int]] = None
    recurrence: Optional[str] = None
    recur_interval: Optional[int] = None
    recur_byday: Optional[str] = None
    recur_count: Optional[int] = None
    recur_until: Optional[str] = None
    recur_except: Optional[list[str]] = None


@router.patch("/calendar/{eid}")
def update_event(eid: str, body: EventPatch, db: DbSession = Depends(get_db)):
    e = db.get(CalendarEvent, eid)
    if not e:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    if "reminders" in data:
        data["reminders"] = json.dumps(data["reminders"] or [])
    if "recur_except" in data:
        data["recur_except"] = json.dumps(data["recur_except"] or [])
    for k, v in data.items():
        setattr(e, k, v)
    db.commit()
    return _fmt(e)


@router.delete("/calendar/{eid}")
def delete_event(eid: str, scope: str = "all", occ: str = "", db: DbSession = Depends(get_db)):
    """scope='all' deletes the event/series; 'this' excludes one occurrence (occ
    date); 'following' ends the series the day before occ."""
    from datetime import date, timedelta

    e = db.get(CalendarEvent, eid)
    if not e:
        raise HTTPException(404)
    if scope == "this" and occ and e.recurrence:
        ex = _jl(e.recur_except)
        if occ[:10] not in ex:
            ex.append(occ[:10])
        e.recur_except = json.dumps(ex)
        db.commit()
        return {"ok": True, "scope": "this"}
    if scope == "following" and occ and e.recurrence:
        try:
            e.recur_until = (date.fromisoformat(occ[:10]) - timedelta(days=1)).isoformat()
            e.recur_count = None
            db.commit()
            return {"ok": True, "scope": "following"}
        except ValueError:
            pass
    db.delete(e)
    db.commit()
    return {"ok": True}


@router.get("/calendar/export.ics")
def export_ics(db: DbSession = Depends(get_db)):
    """download every event as a .ics — import into Apple/Google/Outlook calendar."""
    from fastapi.responses import Response

    from services.ics import to_ics

    rows = db.query(CalendarEvent).order_by(CalendarEvent.start_dt.asc()).all()
    body = to_ics([_fmt(e) for e in rows])
    return Response(
        body,
        media_type="text/calendar",
        headers={"content-disposition": 'attachment; filename="alles-calendar.ics"'},
    )


class IcsImport(BaseModel):
    ics: str


@router.post("/calendar/import")
def import_ics(body: IcsImport, db: DbSession = Depends(get_db)):
    """import events from a pasted/uploaded .ics."""
    from services.ics import parse_ics

    n = 0
    for ev in parse_ics(body.ics):
        db.add(
            CalendarEvent(
                title=ev["title"] or "(untitled)",
                start_dt=ev["start_dt"],
                end_dt=ev.get("end_dt"),
                all_day=ev.get("all_day", False),
                description=ev.get("description", ""),
            )
        )
        n += 1
    db.commit()
    return {"imported": n}
