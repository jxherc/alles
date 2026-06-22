"""daily briefing - a small morning digest pulled from the local apps (calendar,
tasks, habits, reading list, subscriptions, health). the per-app queries now live
in services.signals (shared with the today widget + proactive agent); this just
formats the signals into digest lines. the job in app.py broadcasts it via web
push once a day."""

from datetime import date


def compose_briefing(db, today=None) -> dict:
    """gather today's digest. returns {title, body, lines, has_content}."""
    from services import signals

    today = today or date.today()
    g = signals.by_category(
        signals.gather(db, today, categories={"event", "task", "habit", "book", "sub", "health"})
    )
    lines = []

    # today's calendar events (sorted by start, first 4)
    evs = sorted(g.get("event", []), key=lambda s: s["data"]["start_dt"])
    if evs:
        names = ", ".join(s["data"]["title"] for s in evs[:4])
        more = f" +{len(evs) - 4} more" if len(evs) > 4 else ""
        lines.append(f"{len(evs)} event{'s' if len(evs) != 1 else ''} today — {names}{more}")

    # tasks - due/overdue first, else fall back to any open task
    due = sorted((s["data"] for s in g.get("task", [])), key=lambda d: (d["due"], d["title"]))
    if due:
        names = ", ".join(d["title"] for d in due[:4])
        lines.append(f"{len(due)} due task{'s' if len(due) != 1 else ''} — {names}")
    else:
        from core.database import Task

        opens = db.query(Task).filter(Task.done == False).all()  # noqa: E712
        if opens:
            names = ", ".join(t.title for t in opens[:4])
            lines.append(f"{len(opens)} open task{'s' if len(opens) != 1 else ''} — {names}")

    # habits not yet done today (first 6)
    todo = [s["data"] for s in g.get("habit", [])]
    if todo:
        lines.append(f"habits left — {', '.join(d['name'] for d in todo[:6])}")

    # currently reading (first 4)
    reading = [s["data"] for s in g.get("book", [])]
    if reading:
        lines.append(f"reading — {', '.join(d['title'] for d in reading[:4])}")

    # subscriptions renewing within their own reminder window (first 4)
    soon = [d for d in (s["data"] for s in g.get("sub", [])) if d["in_days"] <= d["remind_days"]]
    soon.sort(key=lambda d: d["in_days"])
    if soon:
        bits = ", ".join(f"{d['name']} ({d['currency']}{d['price']:g})" for d in soon[:4])
        lines.append(f"renewing soon — {bits}")

    # latest weight (the most-tracked metric)
    w = [s["data"] for s in g.get("health", [])]
    if w:
        d0 = w[0]
        unit = f" {d0['unit']}" if d0["unit"] else ""
        lines.append(f"weight — {d0['value']:g}{unit} (last logged {d0['date']})")

    return {
        "title": f"your {today:%A} briefing",
        "body": "\n".join(lines) if lines else "nothing on the agenda — enjoy the day.",
        "lines": lines,
        "has_content": bool(lines),
    }
