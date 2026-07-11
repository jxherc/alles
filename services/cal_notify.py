"""
calendar event reminders — fire a web-push N minutes before an event (incl. each
occurrence of a recurring one). dedup is persisted to disk so a reminder fires
once even across the 30s job ticks; all-day events anchor their reminders to 09:00.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from core.settings import data_dir

_FIRES: Path | None = None
_fired = None
_fired_path: Path | None = None
_GRACE = 120  # seconds after the reminder time we still consider it "due"
log = logging.getLogger("alles.calendar-reminders")


def _fires_file() -> Path:
    return _FIRES or data_dir() / "cal_fires.json"


def _load():
    global _fired, _fired_path
    path = _fires_file()
    if _fired is None or _fired_path != path:
        try:
            _fired = set(json.loads(path.read_text("utf-8")))
        except Exception:
            _fired = set()
        _fired_path = path
    return _fired


def _save():
    try:
        path = _fires_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(sorted(_fired)), "utf-8")
        os.replace(temporary, path)
        return True
    except Exception:
        return False


def _ev_dict(e):
    return {
        "start_dt": e.start_dt,
        "recurrence": e.recurrence or "",
        "recur_interval": e.recur_interval or 1,
        "recur_byday": e.recur_byday or "",
        "recur_count": e.recur_count,
        "recur_until": e.recur_until,
        "recur_except": e.recur_except or "[]",
        "all_day": e.all_day,
    }


async def fire_due():
    from core.database import CalendarEvent, SessionLocal
    from routes.push import broadcast_result
    from services import recur

    fired = _load()
    now = datetime.now()
    rs, re = now - timedelta(minutes=2), now + timedelta(hours=26)
    db = SessionLocal()
    changed = False
    try:
        for e in db.query(CalendarEvent).all():
            try:
                mins = [
                    int(m) for m in json.loads(e.reminders or "[]") if isinstance(m, (int, float))
                ]
            except Exception:
                mins = []
            if not mins:
                continue
            for occ in recur.expand(_ev_dict(e), rs, re, cap=200):
                anchor = (
                    occ.replace(hour=9, minute=0, second=0, microsecond=0) if e.all_day else occ
                )
                for off in mins:
                    ft = anchor - timedelta(minutes=off)
                    if not (ft <= now < ft + timedelta(seconds=_GRACE)):
                        continue
                    key = f"{e.id}|{occ.date().isoformat()}|{off}"
                    pending_key = f"pending:{key}"
                    uncertain_key = f"uncertain:{key}"
                    if key in fired or pending_key in fired or uncertain_key in fired:
                        continue
                    when = (
                        "now" if off <= 0 else (f"in {off} min" if off < 60 else f"in {off // 60}h")
                    )
                    at = "" if e.all_day else f" at {occ.strftime('%H:%M')}"
                    fired.add(pending_key)
                    if not _save():
                        fired.discard(pending_key)
                        log.warning("calendar reminder claim could not be saved; delivery skipped")
                        continue
                    try:
                        result = await broadcast_result(
                            {
                                "title": "event reminder",
                                "body": f"{e.title} — {when}{at}",
                                "url": "/",
                                "tag": key,
                            }
                        )
                        fired.discard(pending_key)
                        if result["sent"]:
                            fired.add(key)
                        elif result["uncertain"]:
                            fired.add(uncertain_key)
                        changed = True
                        _save()
                    except Exception as exc:
                        fired.discard(pending_key)
                        fired.add(uncertain_key)
                        changed = True
                        _save()
                        log.warning("calendar reminder outcome uncertain: %s", type(exc).__name__)
    finally:
        db.close()
    if changed:
        cutoff = (now.date() - timedelta(days=2)).isoformat()
        for k in [k for k in fired if k.split("|")[1] < cutoff]:
            fired.discard(k)
        _save()
