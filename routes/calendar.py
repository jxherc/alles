import json
import re
from datetime import UTC
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session as DbSession

from core.database import (
    BookingPage,
    Calendar,
    CalendarEvent,
    CalendarSubscription,
    EventAttendee,
    get_db,
)
from core.settings import load_settings
from services import calendar_events
from services.commitment_sources import CommitmentSource

router = APIRouter(prefix="/api")


def _ready(payload) -> JSONResponse:
    """a big read (thousands of events, months of repeats) turned into json here, in the
    threadpool running the route. handed back as plain data, fastapi encodes it on the event
    loop, which stalled every other request (/health too) for up to a second. the payloads are
    already plain json types"""
    return JSONResponse(payload)


def _zone_name(time_zone: str = "", x_alles_time_zone: str = Header(default="")) -> str:
    """the browser's zone for this request (a time_zone param or the x-alles-time-zone header
    the calendar sends on every request). it's also kept for background work while the owner
    hasn't set a timezone."""
    name = (time_zone or x_alles_time_zone or "").strip()
    calendar_events.remember_zone(name)
    return name


def _read_zone(name: str = Depends(_zone_name)):
    """the zone a reader converts stored times in: the request's, else the owner's"""
    return calendar_events.owner_zone(name)


@router.get("/calendar")
def list_events(db: DbSession = Depends(get_db), _zone=Depends(_zone_name)):
    # the raw rows: the calendar page reads a kept offset in the browser's own zone
    rows = db.query(CalendarEvent).order_by(CalendarEvent.start_dt.asc()).all()
    return _ready([calendar_events.event_dict(e) for e in rows])


@router.get("/calendar/conflicts")
def calendar_conflicts(db: DbSession = Depends(get_db), zone=Depends(_read_zone)):
    """4a - overlapping timed events (scheduling advisor)."""
    from services import cal_conflict

    rows = [calendar_events.wall_event(e, zone) for e in db.query(CalendarEvent).all()]
    return _ready({"conflicts": cal_conflict.conflicts(rows)})


@router.get("/calendar/free-slots")
def calendar_free_slots(
    day: str,
    day_start: str = "09:00",
    day_end: str = "17:00",
    duration_min: int = 30,
    db: DbSession = Depends(get_db),
    zone=Depends(_read_zone),
):
    """4a - open slots on `day` that fit a `duration_min` meeting."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from services import cal_conflict

    try:
        d = _date.fromisoformat(day)
    except ValueError:
        return {"day": day, "slots": []}  # bad day -> no slots rather than a 500
    if duration_min < 1:
        raise HTTPException(400, "a free time needs to be at least a minute long")
    rs = _dt.combine(d, _dt.min.time())
    re_ = rs + _td(days=1)
    # expand recurring events onto `day` first, or a weekly/daily meeting whose master
    # start is on another date is invisible to free_slots and we'd offer a busy slot.
    rows = []
    for e in db.query(CalendarEvent).all():
        base = calendar_events.wall_event(e, zone)
        if e.recurrence:
            try:
                bs = _dt.fromisoformat((base["start_dt"] or "")[:16])
                be = (
                    _dt.fromisoformat((base["end_dt"] or "")[:16])
                    if base["end_dt"]
                    else bs + _td(minutes=30)
                )
                dur = be - bs
            except (ValueError, TypeError):
                dur = _td(minutes=30)
            # from the day before: last night's late repeat can still run into this morning
            raw = calendar_events.event_dict(e)
            for occ in calendar_events.occurrence_starts(raw, rs - _td(days=1), re_, zone):
                if occ + dur > rs:
                    rows.append(
                        dict(base, start_dt=occ.isoformat(), end_dt=(occ + dur).isoformat())
                    )
        else:
            rows.append(base)
    slots = cal_conflict.free_slots(
        rows, day, day_start=day_start, day_end=day_end, duration_min=duration_min
    )
    return _ready({"day": day, "slots": slots})


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


@router.get("/calendar/birthdays")
def calendar_birthdays(db: DbSession = Depends(get_db)):
    """4a - contact birthdays as an annual all-day overlay. returns month/day (year-agnostic) so
    the frontend can drop them on whatever year it's showing."""
    from core.database import Contact

    out = []
    for c in db.query(Contact).filter(Contact.birthday != None, Contact.birthday != "").all():  # noqa: E711
        parts = (c.birthday or "").strip().split("-")
        try:
            mo, da = (
                (int(parts[1]), int(parts[2]))
                if len(parts) == 3
                else (int(parts[0]), int(parts[1]))
            )
        except (ValueError, IndexError):
            continue  # unparseable birthday, skip it rather than 500
        if 1 <= mo <= 12 and 1 <= da <= 31:
            out.append({"id": c.id, "name": c.name, "month": mo, "day": da})
    return out


@router.post("/calendar/{eid}/duplicate")
def duplicate_event(eid: str, db: DbSession = Depends(get_db), name=Depends(_zone_name)):
    """clone an event (new id), same fields — Google Calendar 'duplicate'."""
    e = db.get(CalendarEvent, eid)
    if not e:
        raise HTTPException(404)
    # drop subscription_id too: a clone tagged with the feed id gets wiped on the next feed
    # refresh (which deletes all events for that subscription). a duplicate is a local event.
    cols = {c.name for c in CalendarEvent.__table__.columns} - {
        "id",
        "created_at",
        "caldav_uid",
        "subscription_id",
    }
    # an exact copy: a kept offset stays kept, so the copy repeats at the same moments
    data = {c: getattr(e, c) for c in cols}
    clone = CalendarEvent(**data)
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return calendar_events.event_dict(clone)


@router.get("/calendar/free")
def free_time(
    date: str,
    minutes: int = 60,
    work_start: int = 9,
    work_end: int = 18,
    db: DbSession = Depends(get_db),
    zone=Depends(_read_zone),
):
    """open slots on a given date that fit `minutes`, avoiding existing timed events."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from services.recur import free_slots

    try:
        day = _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(400, "bad date")
    _check_hours(work_start, work_end)
    if minutes < 1:
        raise HTTPException(400, "a free time needs to be at least a minute long")
    rs = _dt.combine(day, _dt.min.time())
    re_ = rs + _td(days=1)
    busy = []
    for e in db.query(CalendarEvent).all():
        if e.all_day:
            continue
        try:
            # an old import or an api write can still hold an offset
            base_s = _dt.fromisoformat(calendar_events.wall_time(e.start_dt, zone))
            base_e = (
                _dt.fromisoformat(calendar_events.wall_time(e.end_dt, zone)) if e.end_dt else None
            )
            base_e = base_e or base_s + _td(hours=1)
            dur = base_e - base_s
        except (ValueError, TypeError):
            continue
        # anything overlapping the day counts: last night's 22:00-02:00 too, repeats included
        if e.recurrence:
            raw = calendar_events.event_dict(e)
            for occ in calendar_events.occurrence_starts(raw, rs - _td(days=1), re_, zone):
                if occ + dur > rs:
                    busy.append((occ, occ + dur))
        elif base_s < re_ and base_e > rs:
            busy.append((base_s, base_e))
    return _ready({"date": date, "slots": free_slots(busy, day, minutes, work_start, work_end)})


@router.get("/calendar/agenda")
def agenda(days: int = 30, db: DbSession = Depends(get_db), zone=Depends(_read_zone)):
    """upcoming events grouped by day — a flat agenda list for the next N days. recurring events
    are expanded into their occurrences (a weekly event whose master start is in the past still
    has upcoming instances), matching the month/week views."""
    from datetime import date, datetime, timedelta

    # "today" is the owner's day, not the server's (a utc container is a day ahead every evening)
    today = calendar_events.owner_now(zone).date()
    until = today + timedelta(days=days)
    rs = datetime.combine(today, datetime.min.time())
    re_ = datetime.combine(until, datetime.max.time())
    groups: dict[str, list] = {}
    for e in db.query(CalendarEvent).all():
        base = calendar_events.wall_event(e, zone)
        start_dt, end_dt = base["start_dt"], base["end_dt"]
        if e.recurrence:
            try:
                start0 = datetime.fromisoformat(start_dt)
                dur = (datetime.fromisoformat(end_dt) - start0) if end_dt else timedelta(hours=1)
            except (ValueError, TypeError):
                continue
            for occ in calendar_events.occurrence_starts(
                calendar_events.event_dict(e), rs, re_, zone
            ):
                ev = dict(
                    base, start_dt=occ.isoformat(), end_dt=(occ + dur).isoformat(), recurring=True
                )
                groups.setdefault(occ.date().isoformat(), []).append(ev)
        else:
            # a multi-day event (a camping trip, a conference) shows on every day it covers,
            # not just the first; a timed one ending at midnight doesn't spill into the next day
            try:
                first = date.fromisoformat((start_dt or "")[:10])
                last = date.fromisoformat((end_dt or start_dt or "")[:10])
            except ValueError:
                continue
            if end_dt and not e.all_day and (end_dt[11:16] in ("", "00:00")) and last > first:
                last -= timedelta(days=1)
            day = max(first, today)
            while day <= min(last, until):
                groups.setdefault(day.isoformat(), []).append(
                    dict(base, continued=True) if day > first else base
                )
                day += timedelta(days=1)
    for evs in groups.values():
        evs.sort(key=lambda x: x["start_dt"])
    return _ready({"days": [{"date": d, "events": groups[d]} for d in sorted(groups)]})


class QuickEvent(BaseModel):
    text: str


@router.post("/calendar/quick")
def quick_event(
    body: QuickEvent,
    response: Response,
    db: DbSession = Depends(get_db),
    zone=Depends(_read_zone),
):
    """natural-language event: 'lunch with sam friday 1pm', 'dentist june 20 9am'."""
    from services.event_nl import NotADate, parse_event

    if not body.text.strip():
        raise HTTPException(400, "empty")
    try:
        p = parse_event(
            body.text,
            today=calendar_events.owner_now(zone).date(),
            language=load_settings().get("language", "en"),
        )
    except NotADate as error:
        raise HTTPException(400, str(error)) from None
    end = p["end_dt"]
    if not p["all_day"] and not end and p["start_dt"]:
        end = calendar_events.plus_minutes(p["start_dt"], calendar_events.default_duration()) or end
    e = CalendarEvent(
        title=p["title"],
        start_dt=p["start_dt"],
        end_dt=end,
        all_day=p["all_day"],
        calendar_id=calendar_events.default_calendar_id(db),
        recurrence=p.get("recurrence", ""),
        recur_until=p.get("recur_until"),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    if p["no_date"]:
        # a header, not a field: the undo sends this exact record back to compare
        response.headers["X-Alles-No-Date"] = "1"
    return calendar_events.event_dict(e)


# an event colour is a palette name or a real hex; the page puts it inside style="…"
_COLOR = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-z]{1,20})?$")


def _check_color(value):
    if value is not None and not _COLOR.match(value):
        raise ValueError("color must be a palette name or a hex like #5b8def")
    return value


class EventBody(BaseModel):
    title: str
    request_id: str = ""
    source: CommitmentSource | None = None
    calendar_id: str = ""
    description: str = ""
    location: str = ""
    guests: str = ""
    start_dt: str
    end_dt: Optional[str] = None
    all_day: bool = False
    color: str = ""
    reminders: list[int] = []

    _color = field_validator("color")(_check_color)
    recurrence: str = ""
    recur_interval: int = 1
    recur_byday: str = ""
    recur_count: Optional[int] = None
    recur_until: Optional[str] = None
    recur_except: list[str] = []
    meeting_url: str = ""


def _occurrence_index(event, occ, time_zone):
    """Validate the selected local day and count positions, including exclusions."""
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        day = date.fromisoformat(occ)
        zone = ZoneInfo(time_zone)
        start = datetime.fromisoformat(event["start_dt"])
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise HTTPException(400, "use a real occurrence date and time zone") from None
    if start.tzinfo is not None and not event.get("all_day"):
        start = start.astimezone(zone)
    start = start.replace(tzinfo=None)
    # a kept offset repeats in its own frame; occurrence_starts reads each start here
    dates = calendar_events.occurrence_starts(
        {**event, "recur_except": []},
        start.replace(second=0, microsecond=0),
        datetime.combine(day + timedelta(days=1), datetime.min.time()),
        zone,
        cap=8000,
    )
    matches = [i for i, value in enumerate(dates) if value.date() == day]
    skipped = calendar_events.frame_day(event, occ, zone) in event.get("recur_except", [])
    if not matches or skipped:
        raise HTTPException(409, "this occurrence is no longer in the series. reload the calendar")
    return matches[0], day


def _occurrence_dates(event, day, time_zone):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    found = calendar_events.frame_occurrence(event, day, ZoneInfo(time_zone))
    if found:
        # a kept offset: the occurrence at its own moments, in the series' frame
        start, end = found
        return {
            "start_dt": start.isoformat(),
            "end_dt": end.isoformat() if end else event.get("end_dt"),
        }
    start = datetime.fromisoformat(event["start_dt"])
    delta = day - start.date()
    result = {}
    for key in ("start_dt", "end_dt"):
        raw = event.get(key)
        if not raw or not delta.days:
            result[key] = raw
            continue
        value = datetime.fromisoformat(raw) + delta
        result[key] = value.date().isoformat() if len(raw) == 10 else value.isoformat()
    return result


@router.post("/calendar")
def create_event(
    body: EventBody,
    time_zone: str = "",
    x_alles_time_zone: str = Header(default=""),
    db: DbSession = Depends(get_db),
):
    zone_name = _zone_name(time_zone, x_alles_time_zone)
    event = calendar_events.create_event(db, body.model_dump(), time_zone=zone_name)
    return calendar_events.event_dict(event)


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

    _color = field_validator("color")(_check_color)
    recurrence: Optional[str] = None
    recur_interval: Optional[int] = None
    recur_byday: Optional[str] = None
    recur_count: Optional[int] = None
    recur_until: Optional[str] = None
    recur_except: Optional[list[str]] = None
    meeting_url: Optional[str] = None


@router.patch("/calendar/{eid}")
def update_event(
    eid: str,
    body: EventPatch,
    scope: str = "all",
    occ: str = "",
    time_zone: str = "",
    x_alles_time_zone: str = Header(default=""),
    db: DbSession = Depends(get_db),
):
    """Scoped edits create the replacement and update the master in one transaction."""
    from datetime import timedelta

    e = db.get(CalendarEvent, eid)
    if not e:
        raise HTTPException(404)
    if scope not in {"all", "this", "following"}:
        raise HTTPException(400, "unknown edit scope")
    old = calendar_events.event_dict(e)
    old.pop("id")
    old.pop("created_at")
    patch = body.model_dump(exclude_unset=True)
    time_zone = _zone_name(time_zone, x_alles_time_zone)
    zone = calendar_events.write_zone(time_zone)
    data = calendar_events.day_only({**old, **patch})
    if scope == "all":
        _settle(data, patch, old, zone)
    calendar_events.validate_event(data)
    result = e
    try:
        if scope == "all":
            for k, v in calendar_events.event_columns(data).items():
                setattr(e, k, v)
        else:
            if not e.recurrence:
                raise HTTPException(409, "this event no longer repeats. reload the calendar")
            from datetime import date
            from zoneinfo import ZoneInfo

            index, day = _occurrence_index(old, occ, time_zone or "UTC")
            dates = _occurrence_dates(old, day, time_zone or "UTC")
            for key, value in dates.items():
                if key not in patch:
                    data[key] = value
            # the picked day in the series' own frame: a kept offset skips and ends on its days
            framed = calendar_events.frame_day(old, occ, ZoneInfo(time_zone or "UTC"))
            if scope == "following" and "recur_except" not in patch:
                data["recur_except"] = [v for v in old["recur_except"] if v >= framed]
            _settle(data, patch, {**old, **dates}, zone)
            calendar_events.validate_event(data)
            if scope == "this":
                data.update(
                    recurrence="",
                    recur_interval=1,
                    recur_byday="",
                    recur_count=None,
                    recur_until=None,
                    recur_except=[],
                )
                e.recur_except = json.dumps([*old["recur_except"], framed])
            else:
                if data.get("recur_count") == old.get("recur_count") and old.get("recur_count"):
                    data["recur_count"] = old["recur_count"] - index
                e.recur_until = (date.fromisoformat(framed) - timedelta(days=1)).isoformat()
            result = CalendarEvent(**calendar_events.event_columns(data))
            db.add(result)
        db.commit()
        db.refresh(result)
    except Exception:
        db.rollback()
        raise
    return calendar_events.event_dict(result)


_RULES = ("recurrence", "recur_interval", "recur_byday", "recur_count", "recur_until")


def _settle(data, patch, base, zone):
    """a time or a repeat rule picked in a zone the owner chose becomes wall time there. an edit
    that leaves them alone (a title, a note) leaves a kept offset alone too"""
    picked = {k for k in (*_RULES, "recur_except") if k in patch and patch[k] != base.get(k)}
    if not zone or not (picked or calendar_events.times_moved(patch, base)):
        return
    calendar_events.to_wall_series(data, zone, base.get("start_dt"), picked)


@router.delete("/calendar/{eid}")
def delete_event(
    eid: str,
    scope: str = "all",
    occ: str = "",
    db: DbSession = Depends(get_db),
    expected: dict | None = None,
    name: str = Depends(_zone_name),
):
    """scope='all' deletes the event/series; 'this' excludes one occurrence (occ
    date); 'following' ends the series the day before occ."""
    from datetime import date, timedelta

    if expected is not None:
        if scope != "all" or occ:
            raise HTTPException(422, "quick-add undo must delete the whole event")
        if expected.get("id") != eid:
            raise HTTPException(409, "this event doesn't match the saved quick-add receipt")
    e = db.get(CalendarEvent, eid)
    if not e:
        raise HTTPException(404)
    # the day the browser picked, in the series' own frame: a kept offset's days are its own
    zone = calendar_events.owner_zone(name)
    if scope == "this" and occ and e.recurrence:
        ex = calendar_events.json_list(e.recur_except)
        day = calendar_events.frame_day(calendar_events.event_dict(e), occ[:10], zone)
        if day not in ex:
            ex.append(day)
        e.recur_except = json.dumps(ex)
        db.commit()
        return {"ok": True, "scope": "this"}
    if scope == "following" and occ and e.recurrence:
        try:
            date.fromisoformat(occ[:10])
            day = calendar_events.frame_day(calendar_events.event_dict(e), occ[:10], zone)
            e.recur_until = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
            e.recur_count = None
            db.commit()
            return {"ok": True, "scope": "following"}
        except ValueError:
            pass
    calendar_events.delete_event(db, e, expected=expected)
    return {"ok": True}


@router.get("/calendar/export.ics")
def export_ics(db: DbSession = Depends(get_db)):
    """download every event as a .ics — import into Apple/Google/Outlook calendar."""
    from fastapi.responses import Response

    from services.ics import to_ics

    rows = db.query(CalendarEvent).order_by(CalendarEvent.start_dt.asc()).all()
    body = to_ics([calendar_events.event_dict(e) for e in rows])
    return Response(
        body,
        media_type="text/calendar",
        headers={"content-disposition": 'attachment; filename="alles-calendar.ics"'},
    )


class IcsImport(BaseModel):
    ics: str


@router.post("/calendar/import")
def import_ics(body: IcsImport, db: DbSession = Depends(get_db), name=Depends(_zone_name)):
    """import events from a pasted/uploaded .ics."""
    from services.ics import parse_ics

    content = body.ics.lstrip("\ufeff").strip()
    lines = content.splitlines()
    if not lines or lines[0] != "BEGIN:VCALENDAR" or lines[-1] != "END:VCALENDAR":
        raise HTTPException(400, "choose a complete .ics calendar file")
    events = parse_ics(content, zone=calendar_events.write_zone(name))
    end_fields = sum(line.split(":", 1)[0].split(";")[0].upper() == "DTEND" for line in lines)
    if (
        lines.count("BEGIN:VEVENT") != len(events)
        or lines.count("END:VEVENT") != len(events)
        or end_fields != sum(bool(event.get("end_dt")) for event in events)
    ):
        raise HTTPException(
            400,
            "an event in this file is incomplete or has a date that doesn't exist. nothing was imported",
        )
    # Validate the entire file before adding any rows; retries must not duplicate a partial import.
    for ev in events:
        ev["title"] = ev["title"] or "(untitled)"
        calendar_events.validate_event(ev)
    n = 0
    cid = calendar_events.default_calendar_id(db)
    for ev in events:
        db.add(
            CalendarEvent(
                title=ev["title"] or "(untitled)",
                start_dt=ev["start_dt"],
                end_dt=ev.get("end_dt"),
                all_day=ev.get("all_day", False),
                description=ev.get("description", ""),
                calendar_id=cid,
            )
        )
        n += 1
    db.commit()
    return {"imported": n}


# ── ICS URL subscriptions (8a) ────────────────────────────────────────────────
def fetch_ics(url: str) -> str:
    """fetch a remote .ics. isolated so tests can patch it (no network)."""
    # webcal:// is just http(s) for an ICS feed
    u = url.strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[len("webcal://") :]
    from services.net_guard import safe_get

    # SSRF guard re-checked on every redirect hop (a feed url could 302 to an internal address)
    r = safe_get(u, timeout=20)
    r.raise_for_status()
    return r.text


def refresh_subscription(db, sub: CalendarSubscription, ics_text: str) -> int:
    """full-replace this subscription's events from the given ICS text."""
    from datetime import datetime

    from services.ics import parse_ics

    db.query(CalendarEvent).filter(CalendarEvent.subscription_id == sub.id).delete()
    n = 0
    for ev in parse_ics(ics_text or ""):
        db.add(
            CalendarEvent(
                title=ev["title"] or "(untitled)",
                start_dt=ev["start_dt"],
                end_dt=ev.get("end_dt"),
                all_day=ev.get("all_day", False),
                description=ev.get("description", ""),
                calendar_id=sub.calendar_id,
                subscription_id=sub.id,
            )
        )
        n += 1
    sub.last_synced = datetime.now(UTC).replace(tzinfo=None).isoformat()
    sub.last_status = "ok"
    db.commit()
    return n


def _sub_out(db, s: CalendarSubscription, cnt: int | None = None) -> dict:
    if cnt is None:
        cnt = db.query(CalendarEvent).filter(CalendarEvent.subscription_id == s.id).count()
    return {
        "id": s.id,
        "name": s.name,
        "url": s.url,
        "calendar_id": s.calendar_id,
        "last_synced": s.last_synced or "",
        "last_status": s.last_status or "",
        "event_count": cnt,
    }


class SubBody(BaseModel):
    name: str
    url: str
    calendar_id: str = ""


@router.get("/calendar/subscriptions")
def list_subscriptions(db: DbSession = Depends(get_db)):
    from sqlalchemy import func

    subs = db.query(CalendarSubscription).all()
    # one grouped count instead of a count() per subscription (was N+1)
    counts = dict(
        db.query(CalendarEvent.subscription_id, func.count(CalendarEvent.id))
        .filter(CalendarEvent.subscription_id != None)  # noqa: E711
        .group_by(CalendarEvent.subscription_id)
        .all()
    )
    return [_sub_out(db, s, counts.get(s.id, 0)) for s in subs]


@router.post("/calendar/subscriptions")
def create_subscription(body: SubBody, db: DbSession = Depends(get_db)):
    if not body.url.strip():
        raise HTTPException(400, "url required")
    cid = body.calendar_id or ""
    if not cid:  # give the feed its own calendar layer
        c = Calendar(name=body.name or "Subscription", color="accent")
        db.add(c)
        db.commit()
        db.refresh(c)
        cid = c.id
    sub = CalendarSubscription(
        name=body.name or "Subscription", url=body.url.strip(), calendar_id=cid
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    # best-effort initial sync (never fail the create on a bad feed)
    try:
        refresh_subscription(db, sub, fetch_ics(sub.url))
    except Exception as e:
        sub.last_status = f"error: {e}"
        db.commit()
    return _sub_out(db, sub)


@router.post("/calendar/subscriptions/{sid}/refresh")
def refresh_subscription_endpoint(sid: str, db: DbSession = Depends(get_db)):
    sub = db.get(CalendarSubscription, sid)
    if not sub:
        raise HTTPException(404)
    try:
        refresh_subscription(db, sub, fetch_ics(sub.url))
    except Exception as e:
        from datetime import datetime

        sub.last_synced = datetime.now(UTC).replace(tzinfo=None).isoformat()
        sub.last_status = f"error: {e}"
        db.commit()
    return _sub_out(db, sub)


@router.delete("/calendar/subscriptions/{sid}")
def delete_subscription(sid: str, db: DbSession = Depends(get_db)):
    sub = db.get(CalendarSubscription, sid)
    if not sub:
        raise HTTPException(404)
    cid = sub.calendar_id
    db.query(CalendarEvent).filter(CalendarEvent.subscription_id == sid).delete()
    db.delete(sub)
    db.commit()
    # clean up the dedicated calendar layer create_subscription auto-made, if it's now empty and
    # unreferenced, instead of leaving an orphan layer in the sidebar after every add/remove cycle
    if cid:
        cal = db.get(Calendar, cid)
        if cal and not getattr(cal, "is_default", False):
            has_events = db.query(CalendarEvent).filter(CalendarEvent.calendar_id == cid).count()
            has_subs = (
                db.query(CalendarSubscription)
                .filter(CalendarSubscription.calendar_id == cid)
                .count()
            )
            if not has_events and not has_subs:
                db.delete(cal)
                db.commit()
    return {"ok": True}


async def refresh_all_subscriptions():
    """hourly job — re-pull every configured ICS feed."""
    from core.database import SessionLocal

    db = SessionLocal()
    try:
        for sub in db.query(CalendarSubscription).all():
            try:
                refresh_subscription(db, sub, fetch_ics(sub.url))
            except Exception as e:
                from datetime import datetime

                sub.last_synced = datetime.now(UTC).replace(tzinfo=None).isoformat()
                sub.last_status = f"error: {e}"
                db.commit()
    finally:
        db.close()


# ── invites + RSVP + video links (8b) ─────────────────────────────────────────


def _att_out(a: EventAttendee) -> dict:
    return {
        "id": a.id,
        "event_id": a.event_id,
        "name": a.name,
        "email": a.email,
        "status": a.status,
        "token": a.token,
    }


def _send_invite_email(att: EventAttendee, ev: CalendarEvent) -> bool:
    """best-effort invite email. returns True if sent. isolated so tests stub it."""
    from core.settings import load_settings
    from services.mail import send_mail

    accts = load_settings().get("mail_accounts") or []
    if not accts or not att.email:
        return False
    acct = accts[0]
    body = f"You're invited to: {ev.title}\nWhen: {ev.start_dt}\nRSVP: /rsvp/{att.token}"
    send_mail(acct, att.email, f"Invite: {ev.title}", body)
    return True


class InviteBody(BaseModel):
    name: str = ""
    email: str = ""


@router.post("/calendar/{eid}/invite")
def invite(eid: str, body: InviteBody, db: DbSession = Depends(get_db)):
    ev = db.get(CalendarEvent, eid)
    if not ev:
        raise HTTPException(404)
    att = EventAttendee(event_id=eid, name=body.name.strip(), email=body.email.strip())
    db.add(att)
    db.commit()
    db.refresh(att)
    try:
        _send_invite_email(att, ev)
    except Exception:
        pass  # never fail the invite on a mail hiccup
    return _att_out(att)


@router.get("/calendar/{eid}/attendees")
def list_attendees(eid: str, db: DbSession = Depends(get_db)):
    rows = db.query(EventAttendee).filter(EventAttendee.event_id == eid).all()
    return [_att_out(a) for a in rows]


@router.delete("/calendar/attendees/{aid}")
def delete_attendee(aid: str, db: DbSession = Depends(get_db)):
    a = db.get(EventAttendee, aid)
    if not a:
        raise HTTPException(404)
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/calendar/{eid}/invite-suggestions")
def invite_suggestions(eid: str, db: DbSession = Depends(get_db)):
    """4a smart-invite: people in your contacts linked to whoever's already invited."""
    ev = db.get(CalendarEvent, eid)
    if not ev:
        raise HTTPException(404)
    from services import contacts_graph

    atts = db.query(EventAttendee).filter(EventAttendee.event_id == eid).all()
    sugg = contacts_graph.suggest_for_attendees(
        db, [{"name": a.name, "email": a.email} for a in atts]
    )
    return {"suggestions": sugg}


@router.post("/calendar/{eid}/meeting-link")
def add_meeting_link(eid: str, db: DbSession = Depends(get_db)):
    """generate a Jitsi room for an event and store it."""
    from services.meet import jitsi_url

    ev = db.get(CalendarEvent, eid)
    if not ev:
        raise HTTPException(404)
    ev.meeting_url = jitsi_url(ev.title)
    db.commit()
    return {"meeting_url": ev.meeting_url}


# ── booking pages (8b) ────────────────────────────────────────────────────────
def _bp_out(b: BookingPage) -> dict:
    return {
        "id": b.id,
        "token": b.token,
        "title": b.title,
        "duration_min": b.duration_min,
        "work_start": b.work_start,
        "work_end": b.work_end,
        "days_ahead": b.days_ahead,
        "calendar_id": b.calendar_id,
        "url": f"/book/{b.token}",
    }


class BookingPageBody(BaseModel):
    title: str = "Book a time"
    duration_min: int = 30
    work_start: int = 9
    work_end: int = 17
    days_ahead: int = 14
    calendar_id: str = ""


@router.get("/calendar/booking-pages")
def list_booking_pages(db: DbSession = Depends(get_db)):
    return [_bp_out(b) for b in db.query(BookingPage).all()]


def _check_hours(start: int, end: int) -> None:
    if not (0 <= start <= 23 and 1 <= end <= 24 and start < end):
        raise HTTPException(400, "working hours run from 0 to 24, and they end after they start")


@router.post("/calendar/booking-pages")
def create_booking_page(body: BookingPageBody, db: DbSession = Depends(get_db)):
    _check_hours(body.work_start, body.work_end)
    b = BookingPage(
        title=body.title or "Book a time",
        duration_min=max(5, body.duration_min),
        work_start=body.work_start,
        work_end=body.work_end,
        days_ahead=max(1, body.days_ahead),
        calendar_id=body.calendar_id or calendar_events.default_calendar_id(db),
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return _bp_out(b)


@router.delete("/calendar/booking-pages/{bid}")
def delete_booking_page(bid: str, db: DbSession = Depends(get_db)):
    b = db.get(BookingPage, bid)
    if not b:
        raise HTTPException(404)
    db.delete(b)
    db.commit()
    return {"ok": True}
