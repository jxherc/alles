"""daily briefing — a small morning digest pulled from the local apps (calendar,
tasks, habits, reading list, subscriptions, health). pure compose_briefing() so it's
testable; the job in app.py broadcasts it via web push once a day."""

from datetime import date, timedelta


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def compose_briefing(db, today=None) -> dict:
    """gather today's digest. returns {title, body, lines, has_content}."""
    from core.database import (
        Book,
        CalendarEvent,
        Habit,
        HabitLog,
        HealthEntry,
        Subscription,
        Task,
    )

    today = today or date.today()
    iso = today.isoformat()
    lines = []

    # today's calendar events
    evs = (
        db.query(CalendarEvent)
        .filter(CalendarEvent.start_dt.like(iso + "%"))
        .order_by(CalendarEvent.start_dt)
        .all()
    )
    if evs:
        names = ", ".join(e.title for e in evs[:4])
        more = f" +{len(evs) - 4} more" if len(evs) > 4 else ""
        lines.append(f"{len(evs)} event{'s' if len(evs) != 1 else ''} today — {names}{more}")

    # open tasks (overdue / due-today first)
    tasks = db.query(Task).filter(Task.done == False).all()  # noqa: E712
    if tasks:
        due = [t for t in tasks if t.due_date and _d(t.due_date) and _d(t.due_date) <= today]
        pick = due or tasks
        names = ", ".join(t.title for t in pick[:4])
        label = "due" if due else "open"
        lines.append(f"{len(pick)} {label} task{'s' if len(pick) != 1 else ''} — {names}")

    # habits not yet done today
    habits = db.query(Habit).filter(Habit.archived == False).all()  # noqa: E712
    todo = [
        h
        for h in habits
        if not db.query(HabitLog)
        .filter(HabitLog.habit_id == h.id, HabitLog.date == iso)
        .first()
    ]
    if todo:
        lines.append(f"habits left — {', '.join(h.name for h in todo[:6])}")

    # currently reading
    reading = db.query(Book).filter(Book.status == "reading").all()
    if reading:
        lines.append(f"reading — {', '.join(b.title for b in reading[:4])}")

    # subscriptions renewing within their reminder window (or overdue)
    soon = []
    for s in db.query(Subscription).filter(Subscription.active == True).all():  # noqa: E712
        d = _d(s.next_due)
        if d and d <= today + timedelta(days=max(0, s.remind_days or 0)):
            soon.append(s)
    if soon:
        bits = ", ".join(f"{s.name} ({s.currency}{s.price:g})" for s in soon[:4])
        lines.append(f"renewing soon — {bits}")

    # latest weight (the most-tracked metric)
    w = (
        db.query(HealthEntry)
        .filter(HealthEntry.kind == "weight")
        .order_by(HealthEntry.id.desc())
        .first()
    )
    if w:
        unit = f" {w.unit}" if w.unit else ""
        lines.append(f"weight — {w.value:g}{unit} (last logged {w.date})")

    return {
        "title": f"your {today:%A} briefing",
        "body": "\n".join(lines) if lines else "nothing on the agenda — enjoy the day.",
        "lines": lines,
        "has_content": bool(lines),
    }
