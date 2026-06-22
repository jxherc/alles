"""the "today" dashboard - one call that gathers what matters right now. the
heavy lifting now lives in services.signals (shared with the briefing + the
proactive agent); this route just rolls overdue subs forward and reshapes the
signals into the dict the home widget expects.

the client passes ?date=YYYY-MM-DD (its LOCAL date). never default to the
server's date for user-facing day math - the server may run in UTC.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from core.database import Subscription, Task, get_db
from services import signals
from services.signals import (
    _event_occurs_on,  # noqa: F401  re-export for routes.today._event_occurs_on
)

router = APIRouter(prefix="/api")


def _safe_date(s: str) -> date:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return date.today()


@router.get("/today")
def today_view(date_q: str = Query("", alias="date"), db: DbSession = Depends(get_db)):
    today = _safe_date(date_q) if date_q else date.today()

    # roll overdue subs forward first (a write) so signals reads fresh next_due
    from routes.subscriptions import _roll

    subs = db.query(Subscription).filter(Subscription.active == True).all()  # noqa: E712
    if any(_roll(s, today) for s in subs):
        db.commit()

    g = signals.by_category(
        signals.gather(db, today, categories={"task", "event", "reminder", "sub", "day_event"})
    )

    # events - timed sorted by time, all-day last
    events = [
        {"id": d["id"], "title": d["title"], "time": d["time"], "all_day": d["all_day"]}
        for d in (s["data"] for s in g.get("event", []))
    ]
    events.sort(key=lambda x: (x["time"] == "", x["time"]))

    overdue, due_today = [], []
    for d in (s["data"] for s in g.get("task", [])):
        item = {"id": d["id"], "title": d["title"], "due": d["due"], "priority": d["priority"]}
        (overdue if d["overdue"] else due_today).append(item)
    overdue.sort(key=lambda x: x["due"])

    reminders = [
        {"id": d["id"], "text": d["text"], "at": d["at"]}
        for d in (s["data"] for s in g.get("reminder", []))
    ]

    renewing = [
        {"id": d["id"], "name": d["name"], "in_days": d["in_days"], "price": d["price"],
         "currency": d["currency"]}
        for d in (s["data"] for s in g.get("sub", []))
        if 0 <= d["in_days"] <= 7
    ]
    renewing.sort(key=lambda x: x["in_days"])

    day_events = [
        {"id": d["id"], "name": d["name"], "in_days": d["in_days"]}
        for d in (s["data"] for s in g.get("day_event", []))
        if 0 <= d["in_days"] <= 3
    ]
    day_events.sort(key=lambda x: x["in_days"])

    open_count = db.query(Task).filter(Task.done == False).count()  # noqa: E712

    # docs - most recently modified (stays local, not a "signal")
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
        "date": today.isoformat(),
        "events": events,
        "tasks": {"overdue": overdue, "due_today": due_today, "open_count": open_count},
        "reminders": reminders,
        "renewing": renewing,
        "day_events": day_events,
        "recent_docs": recent_docs,
    }
