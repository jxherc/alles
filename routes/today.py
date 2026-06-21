"""
the "today" dashboard — one call that gathers what matters right now from
calendar, tasks, reminders, subscriptions, day-events, and docs.

the client passes ?date=YYYY-MM-DD (its LOCAL date). never default to the
server's date for user-facing day math — the server may run in UTC.
"""

from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession
from core.database import get_db, CalendarEvent, Task, Reminder, Subscription, DayEvent

router = APIRouter(prefix="/api")


def _safe_date(s: str) -> date:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return date.today()


def _event_occurs_on(e: CalendarEvent, day: date) -> bool:
    try:
        start = date.fromisoformat(str(e.start_dt)[:10])
    except ValueError:
        return False
    if start > day:
        return False
    rec = (e.recurrence or "").strip()
    if e.recur_until:
        try:
            if date.fromisoformat(str(e.recur_until)[:10]) < day:
                return False
        except ValueError:
            pass
    if not rec:
        return start == day
    if rec == "daily":
        return True
    if rec == "weekly":
        return start.weekday() == day.weekday()
    if rec == "monthly":
        return start.day == day.day
    return start == day


@router.get("/today")
def today_view(date_q: str = Query("", alias="date"), db: DbSession = Depends(get_db)):
    today = _safe_date(date_q) if date_q else date.today()
    today_iso = today.isoformat()

    # calendar — today's events, recurrence-aware
    events = []
    for e in db.query(CalendarEvent).all():
        if _event_occurs_on(e, today):
            t = str(e.start_dt)[11:16] if len(str(e.start_dt)) > 10 else ""
            events.append(
                {"id": e.id, "title": e.title, "time": "" if e.all_day else t, "all_day": e.all_day}
            )
    events.sort(key=lambda x: (x["time"] == "", x["time"]))

    # tasks — overdue and due today (open only), plus the open count
    open_tasks = db.query(Task).filter(Task.done == False).all()
    overdue, due_today = [], []
    for t in open_tasks:
        if not t.due_date:
            continue
        d = str(t.due_date)[:10]
        if d < today_iso:
            overdue.append({"id": t.id, "title": t.title, "due": d, "priority": t.priority})
        elif d == today_iso:
            due_today.append({"id": t.id, "title": t.title, "due": d, "priority": t.priority})
    overdue.sort(key=lambda x: x["due"])

    # reminders — unfired ones for today (or already past)
    reminders = []
    for r in db.query(Reminder).filter(Reminder.fired == False).all():
        if r.trigger_at and r.trigger_at.date() <= today:
            reminders.append({"id": r.id, "text": r.text, "at": r.trigger_at.strftime("%H:%M")})

    # subscriptions — renewing within 7 days
    from routes.subscriptions import _roll, _parse as _sub_parse

    subs = db.query(Subscription).filter(Subscription.active == True).all()
    if any(_roll(s, today) for s in subs):
        db.commit()
    renewing = []
    for s in subs:
        days_until = (_sub_parse(s.next_due) - today).days
        if 0 <= days_until <= 7:
            renewing.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "in_days": days_until,
                    "price": s.price,
                    "currency": s.currency,
                }
            )
    renewing.sort(key=lambda x: x["in_days"])

    # day-events — today or within 3 days
    from routes.days import _occurrence, _parse as _day_parse

    day_events = []
    for ev in db.query(DayEvent).all():
        orig = _day_parse(ev.date)
        if ev.repeat in ("yearly", "monthly"):
            target, _nth = _occurrence(orig, today, ev.repeat)
        else:
            target = orig
            if target < today:
                continue
        diff = (target - today).days
        if 0 <= diff <= 3:
            day_events.append({"id": ev.id, "name": ev.name, "in_days": diff})
    day_events.sort(key=lambda x: x["in_days"])

    # docs — most recently modified
    recent_docs = []
    try:
        from services.vault_md import _all_md, vault_dir

        root = vault_dir()
        files = sorted(_all_md(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        recent_docs = [
            {"path": str(p.relative_to(root)).replace("\\", "/"), "name": p.stem} for p in files
        ]
    except Exception:
        pass

    return {
        "date": today_iso,
        "events": events,
        "tasks": {"overdue": overdue, "due_today": due_today, "open_count": len(open_tasks)},
        "reminders": reminders,
        "renewing": renewing,
        "day_events": day_events,
        "recent_docs": recent_docs,
    }
