"""Shared rules for creating owner-managed calendar events."""

import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.database import BookingPage, Calendar, CalendarEvent, EventAttendee, SessionLocal
from core.settings import load_settings
from services.commitment_requests import create_request
from services.commitment_sources import source_dict, source_json

log = logging.getLogger("alles.calendar")


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


def _zone(name):
    name = str(name or "").strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return None


# times are stored as the owner's wall time, or kept with the offset they came with when no
# zone the owner chose was known. readers turn both into wall time with wall_time(); nothing is
# ever rewritten in a guessed zone (a container's server is usually on utc)


def write_zone(name: str = ""):
    """a zone it's safe to store a zoned time in as wall time: the browser's for this request,
    else the timezone setting. None keeps the offset as sent."""
    return _zone(name) or _zone(load_settings().get("timezone"))


def owner_zone(name: str = "", settings: dict | None = None):
    """the zone to read times in: the browser's for this request, else the timezone setting, else
    the last browser zone seen (for reminders and other background work), else None, which is
    the server's own zone."""
    settings = load_settings() if settings is None else settings
    return (
        _zone(name) or _zone(settings.get("timezone")) or _zone(settings.get("detected_timezone"))
    )


# names a browser reports when it doesn't know where it is (a server, a vm, privacy modes)
_UTC_NAMES = {
    "UTC", "UCT", "Universal", "Zulu", "GMT", "GMT0", "GMT+0", "GMT-0", "Greenwich",
    "Etc/UTC", "Etc/UCT", "Etc/Universal", "Etc/Zulu", "Etc/GMT", "Etc/GMT0", "Etc/GMT+0",
    "Etc/GMT-0", "Etc/Greenwich",
}  # fmt: skip


def remember_zone(name: str = "") -> None:
    """keep the browser's zone for background work while the owner hasn't set one. it only saves
    when it changed, and setting a timezone in settings always wins. a browser that only says utc
    doesn't replace a real zone seen before: set the timezone if you really live on utc."""
    zone = _zone(name)
    if zone is None:
        return
    known = str(load_settings().get("detected_timezone") or "")
    if known == zone.key or (zone.key in _UTC_NAMES and known and known not in _UTC_NAMES):
        return
    from core.settings import save_settings

    # a hint for background work: a full disk or a locked file mustn't fail the calendar read
    try:
        save_settings({"detected_timezone": zone.key})
    except Exception as exc:
        log.warning("couldn't remember the browser's time zone: %s", type(exc).__name__)


def owner_now(zone=None) -> datetime:
    """now as the owner's wall clock (naive), to compare with stored wall times"""
    zone = zone or owner_zone()
    return datetime.now(zone).replace(tzinfo=None) if zone else datetime.now()


def same_time(a, b) -> bool:
    """two stored times name the same moment: equal wall times, or offsets at the same instant.
    the editor sends an untouched offset back in its own format (z instead of +09:00)"""
    if a == b:
        return True
    try:
        x, y = datetime.fromisoformat(a), datetime.fromisoformat(b)
    except (TypeError, ValueError):
        return False
    return (x.tzinfo is None) == (y.tzinfo is None) and x == y


def times_moved(patch: dict, base: dict) -> bool:
    return any(k in patch and not same_time(patch[k], base.get(k)) for k in ("start_dt", "end_dt"))


def wall_time(value, zone):
    """stored times are naive wall time like the rest of plan; free/agenda/reminders compare
    them with naive datetimes, so an offset is moved to `zone` and dropped. zone None reads it
    in the server's zone, which is only ever used for a read, never stored."""
    if not isinstance(value, str) or len(value) <= 10:
        return value
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return value
    if when.tzinfo is None:
        return value
    return when.astimezone(zone).replace(tzinfo=None).isoformat()


def wall_pair(start, end, zone):
    """start/end as wall time. an event across the autumn change (1:30 edt to 1:30 est) or one
    with an offset on one side only can come out ending at or before its start; it keeps its
    length instead (an hour when that can't be told), or it could never be edited again."""
    new_start, new_end = wall_time(start, zone), wall_time(end, zone)
    if (new_start, new_end) == (start, end) or not end:
        return new_start, new_end
    try:
        s0, e0 = datetime.fromisoformat(start), datetime.fromisoformat(end)
        s1, e1 = datetime.fromisoformat(new_start), datetime.fromisoformat(new_end)
    except (TypeError, ValueError):
        return new_start, new_end
    if len(new_start) <= 10 or len(new_end) <= 10 or e1 > s1:
        return new_start, new_end
    both = s0.tzinfo is not None and e0.tzinfo is not None
    length = e0 - s0 if both and e0 > s0 else timedelta(hours=1)
    return new_start, (s1 + length).isoformat()


def day_only(data: dict) -> dict:
    """a day is the same day everywhere: an all-day date sent as midnight utc keeps its date
    instead of sliding to the evening before in toronto. no zone ever touches it"""
    if data.get("all_day"):
        for key in ("start_dt", "end_dt"):
            if isinstance(data.get(key), str) and len(data[key]) > 10:
                data[key] = data[key][:10]
    return data


def wall_times(data: dict, zone) -> dict:
    if data.get("all_day"):
        return day_only(data)
    start, end = wall_pair(data.get("start_dt"), data.get("end_dt"), zone)
    if "start_dt" in data:
        data["start_dt"] = start
    if "end_dt" in data:
        data["end_dt"] = end
    return data


_WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def date_shift(before, after) -> int:
    """days between two stored times' own dates (sunday 09:00 +09:00 vs saturday 20:00 here)"""
    try:
        return (date.fromisoformat(str(after)[:10]) - date.fromisoformat(str(before)[:10])).days
    except ValueError:
        return 0


def follow_date(row: dict, shift: int, keys=("recur_byday", "recur_until", "recur_except")) -> dict:
    """a repeat's days move with its start when a write turns it into wall time somewhere else:
    sunday 09:00 in tokyo is saturday evening in toronto, so is every sunday of the rule, its last
    day and each day it skips"""
    if not shift or not row.get("recurrence"):
        return row
    if "recur_byday" in keys and row.get("recur_byday"):
        days = [d.strip().upper() for d in row["recur_byday"].split(",")]
        row["recur_byday"] = ",".join(
            _WEEKDAYS[(_WEEKDAYS.index(d) + shift) % 7] for d in days if d in _WEEKDAYS
        )
    if "recur_until" in keys and row.get("recur_until"):
        last = date.fromisoformat(str(row["recur_until"])[:10]) + timedelta(days=shift)
        row["recur_until"] = last.isoformat()
    if "recur_except" in keys and row.get("recur_except"):
        row["recur_except"] = [
            (date.fromisoformat(str(d)[:10]) + timedelta(days=shift)).isoformat()
            for d in (
                row["recur_except"]
                if isinstance(row["recur_except"], list)
                else json_list(row["recur_except"])
            )
        ]
    return row


def to_wall_series(data: dict, zone, before, picked=frozenset()) -> dict:
    """turn an event dict into wall time in zone, as a write picked there does. `before` is the
    start as it was stored (the frame its repeat days belong to); a repeat's days that weren't
    just picked here move with the start's date. a monthly repeat whose date would move stays in
    its own frame: "the 1st" in tokyo is the last day of a month in toronto, which no monthly
    rule says, so a time picked here is written in that frame instead"""
    frame = None if data.get("all_day") else frame_of(before)
    if frame is None:
        return wall_times(data, zone)
    shift = date_shift(before, wall_time(before, zone))
    if shift and data.get("recurrence") == "monthly":
        for key in ("start_dt", "end_dt"):
            value = data.get(key)
            if isinstance(value, str) and len(value) > 10:
                when = datetime.fromisoformat(value)
                when = when if when.tzinfo else when.replace(tzinfo=zone)
                data[key] = when.astimezone(frame).isoformat()
        return follow_date(data, -shift, keys=tuple(k for k in ("recur_until",) if k in picked))
    wall_times(data, zone)
    kept = tuple(k for k in ("recur_byday", "recur_until", "recur_except") if k not in picked)
    return follow_date(data, shift, keys=kept)


def frame_of(value):
    """the fixed offset a stored time kept, or None for wall time"""
    try:
        return datetime.fromisoformat(str(value)).tzinfo
    except ValueError:
        return None


def _seen(when, frame, zone):
    """a time in a kept offset's frame as wall time in zone (None: the server's)"""
    aware = when.replace(tzinfo=frame)
    return (aware.astimezone(zone) if zone else aware.astimezone()).replace(tzinfo=None)


def wall_exists(when, zone) -> bool:
    """does this wall time happen in zone? the hour the clocks skip in spring doesn't"""
    from datetime import UTC

    there = when.replace(tzinfo=zone).astimezone(UTC).astimezone(zone).replace(tzinfo=None)
    return there == when


def _framed(when, frame, zone):
    """wall time in zone (None: the server's) as wall time in a kept offset's frame"""
    aware = when.replace(tzinfo=zone) if zone else when.astimezone()
    return aware.astimezone(frame).replace(tzinfo=None)


def _frame_occurrences(row, frame, rs, re, zone, cap=1500):
    """(start in the frame, start seen in zone) for each occurrence seen in [rs, re)"""
    from services.recur import expand

    local = {
        **row,
        "start_dt": datetime.fromisoformat(row["start_dt"]).replace(tzinfo=None).isoformat(),
    }
    lo, hi = (
        _framed(rs, frame, zone) - timedelta(days=1),
        _framed(re, frame, zone) + timedelta(days=1),
    )
    for occ in expand(local, lo, hi, cap=cap):
        seen = _seen(occ, frame, zone)
        if rs <= seen < re:
            yield occ, seen


def occurrence_starts(row: dict, rs: datetime, re: datetime, zone, cap: int = 1500) -> list:
    """every start of a stored event in [rs, re), as wall time in zone (None: the server's).
    a wall-time row expands just as it always has. a row that kept its offset repeats in that
    offset's own frame - its weekdays, its weeks, the day of its month, its last day and the days
    it skips are that frame's - and each start is then read in zone on its own, so every viewer
    sees the same moments, across daylight saving too"""
    from services.recur import expand

    frame = None if row.get("all_day") else frame_of(row.get("start_dt"))
    if frame is None:
        return expand(row, rs, re, cap=cap)
    return [seen for _, seen in _frame_occurrences(row, frame, rs, re, zone, cap)]


def frame_day(row: dict, day, zone) -> str:
    """the date, in a kept offset's own frame, of the occurrence a viewer in zone picked on `day`:
    that frame's days are the ones a skip or a last day names. wall time: the same date"""
    frame = None if row.get("all_day") else frame_of(row.get("start_dt"))
    if frame is None:
        return str(day)[:10]
    when = datetime.fromisoformat(str(day)[:10])
    for occ, _ in _frame_occurrences(
        {**row, "recur_except": []}, frame, when, when + timedelta(days=1), zone
    ):
        return occ.date().isoformat()
    return str(day)[:10]


def frame_occurrence(row: dict, day, zone):
    """the occurrence a viewer in zone sees on `day`, as moments in the kept offset's frame:
    (start, end) aware, or None. a scoped edit copies that occurrence at the same moments"""
    frame = None if row.get("all_day") else frame_of(row.get("start_dt"))
    if frame is None:
        return None
    when = datetime.fromisoformat(str(day)[:10])
    start0 = datetime.fromisoformat(row["start_dt"])
    end0 = datetime.fromisoformat(row["end_dt"]) if row.get("end_dt") else None
    rows = _frame_occurrences(
        {**row, "recur_except": []}, frame, when, when + timedelta(days=1), zone
    )
    for occ, _ in rows:
        # the engine counts in minutes; the copy keeps the stored seconds
        start = occ.replace(second=start0.second, microsecond=start0.microsecond, tzinfo=frame)
        # the same elapsed length, whatever the clocks did in between
        return start, (start + (end0 - start0) if end0 and end0.tzinfo else None)
    return None


def wall_event(event: CalendarEvent, zone=None) -> dict:
    """event_dict with wall-time start/end, for readers that compare one event's times. repeats go
    through occurrence_starts, which keeps a kept offset's own days"""
    return wall_times(event_dict(event), zone)


def validate_event(data):
    if not str(data.get("title") or "").strip():
        raise HTTPException(400, "an event needs a title")
    try:
        start = datetime.fromisoformat(data.get("start_dt") or "")
        end = datetime.fromisoformat(data["end_dt"]) if data.get("end_dt") else None
        if end and (end.date() < start.date() if data.get("all_day") else end <= start):
            raise HTTPException(400, "the end must be after the start")
    except (ValueError, TypeError):
        raise HTTPException(400, "use a real start and end date") from None


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


def create_event(db: Session, data: dict, time_zone: str = "") -> CalendarEvent:
    # every writer (the editor, capture, aide tools) stores wall time in a zone the owner chose;
    # with none known the offset stays and readers convert it
    zone = write_zone(time_zone)
    data = to_wall_series(dict(data), zone, data.get("start_dt")) if zone else day_only(dict(data))
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


def delete_event(db: Session, event: CalendarEvent, expected: dict | None = None) -> None:
    if expected is not None:
        columns = tuple(CalendarEvent.__mapper__.columns)
        current = {column.key: getattr(event, column.key) for column in columns}
        if json.dumps(expected, sort_keys=True) != json.dumps(event_dict(event), sort_keys=True):
            raise HTTPException(
                409, "this event changed after quick add. the newer changes were kept"
            )
        try:
            matched = (
                db.query(CalendarEvent)
                .filter(*(column == current[column.key] for column in columns))
                .delete(synchronize_session=False)
            )
            if matched != 1:
                raise HTTPException(
                    409, "this event changed after quick add. the newer changes were kept"
                )
            db.query(EventAttendee).filter(EventAttendee.event_id == current["id"]).delete()
            # Bulk deletion bypasses the mapper hook that records accepted changes.
            from services import events

            events._emit(db.connection(), event, "delete", {})
            db.commit()
        except Exception:
            db.rollback()
            raise
        return
    # Invitees have no FK cascade; their RSVP tokens must retire with the event.
    db.query(EventAttendee).filter(EventAttendee.event_id == event.id).delete()
    db.delete(event)
    db.commit()


def work_hours(start, end) -> tuple[int, int]:
    """a day's working hours as whole hours, 0 to 24 (24 is midnight at the end of the day). an
    older page saved with hours out of range still gets a usable window"""
    start = min(max(int(start or 0), 0), 23)
    end = 24 if end is None else min(max(int(end), start + 1), 24)
    return start, end


def compute_booking_slots(db, page: BookingPage, date_str: str) -> list[dict]:
    """discrete bookable start times on a date for a booking page (steps the free
    windows by the page's duration). returns [{start,end}] ISO (minute precision)."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from services.recur import free_slots

    try:
        day = _date.fromisoformat(date_str)
    except ValueError:
        return []
    rs = _dt.combine(day, _dt.min.time())
    re_ = rs + _td(days=1)
    # a visitor's page: the owner's zone, never the visitor's
    zone = owner_zone()
    now = owner_now(zone)
    if day < now.date() or day > now.date() + _td(days=max(0, page.days_ahead or 0)):
        return []
    busy = []
    for e in db.query(CalendarEvent).all():
        if e.all_day:
            continue
        try:
            row = wall_event(e, zone)
            base_s = _dt.fromisoformat(row["start_dt"])
            base_e = _dt.fromisoformat(row["end_dt"]) if row["end_dt"] else base_s + _td(hours=1)
            dur = base_e - base_s
        except (ValueError, TypeError):
            continue
        # anything overlapping the day counts: last night's 23:00-01:00, a repeat's too
        if e.recurrence:
            for occ in occurrence_starts(event_dict(e), rs - _td(days=1), re_, zone):
                if occ + dur > rs:
                    busy.append((occ, occ + dur))
        elif base_s < re_ and base_e > rs:
            busy.append((base_s, base_e))
    start, end = work_hours(page.work_start, page.work_end)
    windows = free_slots(busy, day, page.duration_min, start, end)
    step = _td(minutes=page.duration_min)
    out = []
    for w in windows:
        cur = _dt.fromisoformat(w["start"])
        wend = _dt.fromisoformat(w["end"])
        while cur + step <= wend:
            # today's earlier times are gone, and so is a time the clocks skip (02:30 on the
            # spring-forward night): nobody can meet then
            if cur <= now or (zone and not wall_exists(cur, zone)):
                cur += step
                continue
            out.append(
                {
                    "start": cur.isoformat(timespec="minutes"),
                    "end": (cur + step).isoformat(timespec="minutes"),
                    # the moment itself, so a visitor elsewhere sees it on their own clock too
                    "at": (cur.replace(tzinfo=zone) if zone else cur.astimezone()).isoformat(),
                }
            )
            cur += step
    return out


def booking_zone_name() -> str:
    """the zone booking times are in, for the public page"""
    zone = owner_zone()
    return zone.key if zone else (datetime.now().astimezone().tzname() or "")
