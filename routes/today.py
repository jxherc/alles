"""the "today" dashboard - one call that gathers what matters right now. the
heavy lifting now lives in services.signals (shared with the briefing + the
proactive agent); this route just rolls overdue subs forward and reshapes the
signals into the dict the home widget expects.

the client passes ?date=YYYY-MM-DD&timezone=IANA (its displayed date and zone).
Date-only callers use the configured owner timezone, then server local time.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from core.database import Subscription, Task, get_db
from core.settings import load_settings, save_settings
from services import actual_finance, signals
from services.recovery_consistency import recovery_consistency_lock
from services.signals import (
    _event_occurs_on,  # noqa: F401  re-export for routes.today._event_occurs_on
)

router = APIRouter(prefix="/api")

_SECTION_KEYS = ("needs_you", "today", "in_progress", "briefs", "shortcuts")
_DEFAULT_SHORTCUTS = ("plan", "wiki", "files")
_SHORTCUT_ALIASES = {
    "plan": "plan",
    "calendar": "plan",
    "tasks": "plan",
    "days": "plan",
    "reminders": "plan",
    "inbox": "inbox",
    "mail": "inbox",
    "contacts": "inbox",
    "wiki": "wiki",
    "notes": "wiki",
    "journal": "wiki",
    "files": "files",
    "photos": "files",
    "gallery": "files",
    "library": "library",
    "books": "library",
    "read": "library",
    "health": "health",
    "habits": "health",
    "finance": "finance",
    "money": "finance",
    "subs": "finance",
    "vault": "vault",
    "secrets": "vault",
    "system": "system",
    "server": "system",
    "watch": "system",
    "activity": "system",
}


class TodayPreferences(BaseModel):
    order: list[str] = Field(default_factory=lambda: list(_SECTION_KEYS), max_length=5)
    visible: list[str] = Field(default_factory=lambda: list(_SECTION_KEYS), max_length=5)
    density: str = "comfortable"
    shortcuts: list[str] = Field(default_factory=lambda: list(_DEFAULT_SHORTCUTS), max_length=20)


def _preferences(value=None) -> dict:
    raw = value if isinstance(value, dict) else {}
    order = list(dict.fromkeys(key for key in raw.get("order", []) if key in _SECTION_KEYS))
    order.extend(key for key in _SECTION_KEYS if key not in order)
    visible = list(
        dict.fromkeys(key for key in raw.get("visible", _SECTION_KEYS) if key in _SECTION_KEYS)
    )
    if "needs_you" not in visible:
        visible.insert(0, "needs_you")
    shortcuts = list(
        dict.fromkeys(
            canonical
            for view in raw.get("shortcuts", _DEFAULT_SHORTCUTS)
            if (canonical := _SHORTCUT_ALIASES.get(str(view).strip().lower())) is not None
        )
    )[:20]
    return {
        "order": order,
        "visible": visible,
        "density": "compact" if raw.get("density") == "compact" else "comfortable",
        "shortcuts": shortcuts,
    }


@router.get("/today/preferences")
def today_preferences():
    return _preferences(load_settings().get("today_layout"))


@router.put("/today/preferences")
def update_today_preferences(body: TodayPreferences):
    value = _preferences(body.model_dump())
    save_settings({"today_layout": value})
    return value


@router.post("/today/preferences/import-legacy")
def import_legacy_home_preferences(body: TodayPreferences):
    # Ordinary preference saves take this same lock inside save_settings.
    with recovery_consistency_lock:
        saved = load_settings().get("today_layout")
        if saved is not None:
            return {"preferences": _preferences(saved), "imported": False}
        value = _preferences(body.model_dump())
        save_settings({"today_layout": value})
        return {"preferences": value, "imported": True}


def _safe_date(s: str, timezone_name=None) -> date:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return signals.calendar_today(timezone_name)


@router.get("/today")
def today_view(
    date_q: str = Query("", alias="date"),
    timezone_q: str = Query("", alias="timezone", max_length=120),
    db: DbSession = Depends(get_db),
):
    try:
        signals.calendar_zone(timezone_q)
    except (KeyError, ValueError):
        raise HTTPException(400, "timezone must be a valid IANA name")
    current_day = signals.calendar_today(timezone_q)
    today = _safe_date(date_q, timezone_q) if date_q else current_day

    # Date previews are reads; only the current-day view advances Finance's ledger.
    if today == current_day:
        from routes.subscriptions import _roll_and_post

        finance_day = date.today()
        with actual_finance.AUTHORITY_LOCK:
            subs = db.query(Subscription).filter(Subscription.active == True).all()  # noqa: E712
            changed = False
            for sub in subs:
                try:
                    changed = _roll_and_post(sub, finance_day, db) or changed
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
            if changed:
                db.commit()

    unavailable = set()
    g = signals.by_category(
        signals.gather(
            db,
            today,
            categories={"task", "event", "reminder", "sub", "day_event", "habit"},
            timezone_name=timezone_q,
            unavailable=unavailable,
        )
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
        {
            "id": d["id"],
            "name": d["name"],
            "in_days": d["in_days"],
            "price": d["price"],
            "currency": d["currency"],
        }
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

    habits = [
        {"id": d["id"], "name": d["name"]}
        for d in (signal["data"] for signal in g.get("habit", []))
    ]

    open_count = db.query(Task).filter(Task.done == False).count()  # noqa: E712

    # docs - most recently modified (stays local, not a "signal")
    recent_docs = []
    partial_sources = sorted(unavailable)
    try:
        from services.vault_md import _all_md, vault_dir

        root = vault_dir()
        files = sorted(_all_md(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        recent_docs = [
            {"path": str(p.relative_to(root)).replace("\\", "/"), "name": p.stem} for p in files
        ]
    except Exception:
        partial_sources.append("recent_docs")

    response = {
        "date": today.isoformat(),
        "events": events,
        "tasks": {"overdue": overdue, "due_today": due_today, "open_count": open_count},
        "reminders": reminders,
        "renewing": renewing,
        "day_events": day_events,
        "habits": habits,
        "recent_docs": recent_docs,
        "partial_sources": partial_sources,
    }
    from services.today_sections import build

    response["sections"] = build(db, response.copy())
    return response
