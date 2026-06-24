import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from core.database import (
    BookingPage,
    Calendar,
    CalendarEvent,
    CalendarSubscription,
    EventAttendee,
    get_db,
)

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
        "meeting_url": e.meeting_url or "",
        "created_at": e.created_at.isoformat(),
    }


def _default_duration() -> int:
    """minutes to use when an event has a start but no end (8a). settings, else 60."""
    from core.settings import load_settings

    try:
        v = int(load_settings().get("cal_default_duration_min") or 60)
        return v if v > 0 else 60
    except (ValueError, TypeError):
        return 60


def _plus_minutes(iso: str, minutes: int):
    from datetime import datetime, timedelta

    try:
        return (datetime.fromisoformat(iso) + timedelta(minutes=minutes)).isoformat()
    except (ValueError, TypeError):
        return None


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


@router.get("/calendar/conflicts")
def calendar_conflicts(db: DbSession = Depends(get_db)):
    """4a - overlapping timed events (scheduling advisor)."""
    from services import cal_conflict

    rows = [_fmt(e) for e in db.query(CalendarEvent).all()]
    return {"conflicts": cal_conflict.conflicts(rows)}


@router.get("/calendar/free-slots")
def calendar_free_slots(
    day: str,
    day_start: str = "09:00",
    day_end: str = "17:00",
    duration_min: int = 30,
    db: DbSession = Depends(get_db),
):
    """4a - open slots on `day` that fit a `duration_min` meeting."""
    from services import cal_conflict

    rows = [_fmt(e) for e in db.query(CalendarEvent).all()]
    slots = cal_conflict.free_slots(
        rows, day, day_start=day_start, day_end=day_end, duration_min=duration_min
    )
    return {"day": day, "slots": slots}


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


@router.post("/calendar/{eid}/duplicate")
def duplicate_event(eid: str, db: DbSession = Depends(get_db)):
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
    clone = CalendarEvent(**{c: getattr(e, c) for c in cols})
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _fmt(clone)


@router.get("/calendar/free")
def free_time(
    date: str,
    minutes: int = 60,
    work_start: int = 9,
    work_end: int = 18,
    db: DbSession = Depends(get_db),
):
    """open slots on a given date that fit `minutes`, avoiding existing timed events."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    from services.recur import expand, free_slots

    try:
        day = _date.fromisoformat(date)
    except ValueError:
        raise HTTPException(400, "bad date")
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
            for occ in expand(_fmt(e), rs, re_):
                busy.append((occ, occ + dur))
        elif rs <= base_s < re_:
            busy.append((base_s, base_e))
    return {"date": date, "slots": free_slots(busy, day, minutes, work_start, work_end)}


@router.get("/calendar/agenda")
def agenda(days: int = 30, db: DbSession = Depends(get_db)):
    """upcoming events grouped by day — a flat agenda list for the next N days. recurring events
    are expanded into their occurrences (a weekly event whose master start is in the past still
    has upcoming instances), matching the month/week views."""
    from datetime import date, datetime, timedelta

    from services.recur import expand

    today = date.today()
    until = today + timedelta(days=days)
    today_s, until_s = today.isoformat(), until.isoformat()
    rs = datetime.combine(today, datetime.min.time())
    re_ = datetime.combine(until, datetime.max.time())
    groups: dict[str, list] = {}
    for e in db.query(CalendarEvent).all():
        base = _fmt(e)
        if e.recurrence:
            try:
                start0 = datetime.fromisoformat(e.start_dt)
                dur = (datetime.fromisoformat(e.end_dt) - start0) if e.end_dt else timedelta(hours=1)
            except (ValueError, TypeError):
                continue
            for occ in expand(base, rs, re_):
                ev = dict(base, start_dt=occ.isoformat(), end_dt=(occ + dur).isoformat(), recurring=True)
                groups.setdefault(occ.date().isoformat(), []).append(ev)
        else:
            d = (e.start_dt or "")[:10]
            if today_s <= d <= until_s:
                groups.setdefault(d, []).append(base)
    for evs in groups.values():
        evs.sort(key=lambda x: x["start_dt"])
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
    end = p["end_dt"]
    if not p["all_day"] and not end and p["start_dt"]:
        end = _plus_minutes(p["start_dt"], _default_duration()) or end
    e = CalendarEvent(
        title=p["title"],
        start_dt=p["start_dt"],
        end_dt=end,
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
    meeting_url: str = ""


@router.post("/calendar")
def create_event(body: EventBody, db: DbSession = Depends(get_db)):
    data = body.model_dump()
    data["calendar_id"] = data.get("calendar_id") or _default_cal(db)
    data["reminders"] = json.dumps(data.get("reminders") or [])
    data["recur_except"] = json.dumps(data.get("recur_except") or [])
    if not data["all_day"] and not data.get("end_dt") and data.get("start_dt"):
        data["end_dt"] = _plus_minutes(data["start_dt"], _default_duration()) or data.get("end_dt")
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
    meeting_url: Optional[str] = None


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
    # no FK on EventAttendee.event_id, clean up its rows by hand
    db.query(EventAttendee).filter(EventAttendee.event_id == eid).delete()
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


# ── ICS URL subscriptions (8a) ────────────────────────────────────────────────
def fetch_ics(url: str) -> str:
    """fetch a remote .ics. isolated so tests can patch it (no network)."""
    import httpx

    # webcal:// is just http(s) for an ICS feed
    u = url.strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[len("webcal://") :]
    from services.net_guard import assert_safe_url

    assert_safe_url(u)  # SSRF guard: a subscription url can't point at internal/metadata addresses
    r = httpx.get(u, timeout=20, follow_redirects=True)
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
    sub.last_synced = datetime.utcnow().isoformat()
    sub.last_status = "ok"
    db.commit()
    return n


def _sub_out(db, s: CalendarSubscription) -> dict:
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
    return [_sub_out(db, s) for s in db.query(CalendarSubscription).all()]


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

        sub.last_synced = datetime.utcnow().isoformat()
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

                sub.last_synced = datetime.utcnow().isoformat()
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
            for occ in expand(_fmt(e), rs, re_):
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


@router.post("/calendar/booking-pages")
def create_booking_page(body: BookingPageBody, db: DbSession = Depends(get_db)):
    b = BookingPage(
        title=body.title or "Book a time",
        duration_min=max(5, body.duration_min),
        work_start=body.work_start,
        work_end=body.work_end,
        days_ahead=max(1, body.days_ahead),
        calendar_id=body.calendar_id or _default_cal(db),
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
