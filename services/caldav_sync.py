"""
CalDAV two-way sync (iCloud / Google / any CalDAV server).

caldav is an optional dep (pip install caldav) and the actual sync needs the
user's own server creds, so everything here is lazy + defensive: it never
crashes the app, it returns {"error": ...} strings the UI can show. Config is
stored in data/caldav.json (gitignored, like the rest of data/).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _ics_esc(s) -> str:
    """RFC-5545 TEXT escaping + strip raw CR/LF so a title can't inject extra ical lines/components."""
    return (
        str(s or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r", "")
        .replace("\n", "\\n")
    )


CFG_PATH = ROOT / "data" / "caldav.json"


def available() -> bool:
    try:
        import caldav  # noqa: F401

        return True
    except Exception:
        return False


def load_cfg() -> dict:
    try:
        return json.loads(CFG_PATH.read_text("utf-8"))
    except Exception:
        return {}


def save_cfg(cfg: dict):
    cur = load_cfg()
    # keep the existing password if a blank one is sent (UI doesn't echo it back)
    if not cfg.get("password") and cur.get("password"):
        cfg["password"] = cur["password"]
    CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CFG_PATH.write_text(json.dumps(cfg), "utf-8")


def status() -> dict:
    cfg = load_cfg()
    return {
        "available": available(),
        "connected": bool(cfg.get("url") and cfg.get("username") and cfg.get("password")),
        "url": cfg.get("url", ""),
        "username": cfg.get("username", ""),
    }


def _iso(dt) -> str:
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    # date only
    return dt.strftime("%Y-%m-%d") + "T00:00:00"


def sync() -> dict:
    if not available():
        return {"error": "caldav not installed — run: pip install caldav"}
    cfg = load_cfg()
    if not (cfg.get("url") and cfg.get("username")):
        return {"error": "not configured — add your CalDAV url + username first"}

    try:
        import caldav
    except Exception as e:
        return {"error": f"caldav import failed: {e}"}

    try:
        client = caldav.DAVClient(
            url=cfg["url"], username=cfg["username"], password=cfg.get("password", "")
        )
        principal = client.principal()
        cals = principal.calendars()
    except Exception as e:
        return {"error": f"connect failed: {str(e)[:160]}"}
    if not cals:
        return {"error": "no calendars found on the server"}
    cal = cals[0]

    from core.database import CalendarEvent, SessionLocal

    start = datetime.utcnow() - timedelta(days=180)
    end = datetime.utcnow() + timedelta(days=180)
    pulled = pushed = 0
    db = SessionLocal()
    try:
        # ── pull remote → local ──
        try:
            remote = cal.search(start=start, end=end, event=True, expand=False)
        except Exception:
            remote = cal.events()
        for ev in remote:
            try:
                comp = ev.icalendar_component
                uid = str(comp.get("uid", "")) or None
                if not uid:
                    continue
                title = str(comp.get("summary", "(untitled)"))
                desc = str(comp.get("description", "") or "")
                ds = comp.get("dtstart")
                de = comp.get("dtend")
                start_dt = _iso(ds.dt) if ds else None
                end_dt = _iso(de.dt) if de else None
                if not start_dt:
                    continue
                all_day = ds and not isinstance(ds.dt, datetime)
                row = db.query(CalendarEvent).filter(CalendarEvent.caldav_uid == uid).first()
                if row:
                    row.title, row.description, row.start_dt, row.end_dt, row.all_day = (
                        title,
                        desc,
                        start_dt,
                        end_dt,
                        bool(all_day),
                    )
                else:
                    db.add(
                        CalendarEvent(
                            title=title,
                            description=desc,
                            start_dt=start_dt,
                            end_dt=end_dt,
                            all_day=bool(all_day),
                            caldav_uid=uid,
                        )
                    )
                pulled += 1
            except Exception:
                continue  # skip a bad event, keep going

        # ── push local-only → remote ──
        locals_ = (
            db.query(CalendarEvent)
            .filter(
                (CalendarEvent.caldav_uid == None) | (CalendarEvent.caldav_uid == "")  # noqa: E711
            )
            .all()
        )
        for le in locals_:
            try:
                uid = f"alles-{le.id}@alles"
                dt = (le.start_dt or "").replace("-", "").replace(":", "")
                ics = (
                    "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//alles//EN\nBEGIN:VEVENT\n"
                    f"UID:{uid}\nSUMMARY:{_ics_esc(le.title)}\nDTSTART:{dt}\nEND:VEVENT\nEND:VCALENDAR\n"
                )
                cal.save_event(ics)
                le.caldav_uid = uid
                pushed += 1
            except Exception:
                continue

        db.commit()
    finally:
        db.close()

    return {"pulled": pulled, "pushed": pushed}
