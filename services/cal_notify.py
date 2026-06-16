"""
calendar event reminders — fire a web-push N minutes before an event (incl. each
occurrence of a recurring one). dedup is persisted to disk so a reminder fires
once even across the 30s job ticks; all-day events anchor their reminders to 09:00.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

_FIRES = Path(__file__).parent.parent / "data" / "cal_fires.json"
_fired = None
_GRACE = 120   # seconds after the reminder time we still consider it "due"


def _load():
    global _fired
    if _fired is None:
        try:
            _fired = set(json.loads(_FIRES.read_text("utf-8")))
        except Exception:
            _fired = set()
    return _fired


def _save():
    try:
        _FIRES.parent.mkdir(parents=True, exist_ok=True)
        _FIRES.write_text(json.dumps(sorted(_fired)), "utf-8")
    except Exception:
        pass


def _ev_dict(e):
    return {"start_dt": e.start_dt, "recurrence": e.recurrence or "",
            "recur_interval": e.recur_interval or 1, "recur_byday": e.recur_byday or "",
            "recur_count": e.recur_count, "recur_until": e.recur_until,
            "recur_except": e.recur_except or "[]", "all_day": e.all_day}


async def fire_due():
    from core.database import SessionLocal, CalendarEvent
    from services import recur
    from routes.push import broadcast

    fired = _load()
    now = datetime.now()
    rs, re = now - timedelta(minutes=2), now + timedelta(hours=26)
    db = SessionLocal()
    changed = False
    try:
        for e in db.query(CalendarEvent).all():
            try:
                mins = [int(m) for m in json.loads(e.reminders or "[]") if isinstance(m, (int, float))]
            except Exception:
                mins = []
            if not mins:
                continue
            for occ in recur.expand(_ev_dict(e), rs, re, cap=200):
                anchor = occ.replace(hour=9, minute=0, second=0, microsecond=0) if e.all_day else occ
                for off in mins:
                    ft = anchor - timedelta(minutes=off)
                    if not (ft <= now < ft + timedelta(seconds=_GRACE)):
                        continue
                    key = f"{e.id}|{occ.date().isoformat()}|{off}"
                    if key in fired:
                        continue
                    fired.add(key); changed = True
                    when = "now" if off <= 0 else (f"in {off} min" if off < 60 else f"in {off // 60}h")
                    at = "" if e.all_day else f" at {occ.strftime('%H:%M')}"
                    try:
                        await broadcast({"title": "event reminder",
                                         "body": f"{e.title} — {when}{at}", "url": "/", "tag": key})
                    except Exception:
                        pass
    finally:
        db.close()
    if changed:
        cutoff = (now.date() - timedelta(days=2)).isoformat()
        for k in [k for k in fired if k.split("|")[1] < cutoff]:
            fired.discard(k)
        _save()
