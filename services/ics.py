"""
iCalendar (.ics) export/import — so the calendar talks to Apple Calendar, Google,
Outlook, anything. stdlib only, generates + parses VEVENTs. not a full RFC 5545
implementation, just the fields the app actually uses (summary/start/end/all-day/
description), which is what real calendars round-trip.
"""
import re
from datetime import datetime


def _esc(s: str) -> str:
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _unesc(s: str) -> str:
    return (s.replace("\\n", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def _fmt_dt(iso: str, all_day: bool) -> str:
    """ISO string -> ICS date/datetime. '2026-06-19T14:00' -> 20260619T140000."""
    iso = (iso or "").strip()
    if all_day or len(iso) <= 10:
        d = iso[:10].replace("-", "")
        return d  # caller adds ;VALUE=DATE
    s = iso.replace("-", "").replace(":", "")
    s = s.split(".")[0]                 # drop fractional seconds
    if "T" not in s and len(s) >= 8:
        s = s[:8] + "T" + s[8:]
    s = (s + "000000")[:15] if "T" in s else s
    return s


def to_ics(events: list[dict]) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//alles//calendar//EN", "CALSCALE:GREGORIAN"]
    for e in events:
        all_day = bool(e.get("all_day"))
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{e.get('id') or _fmt_dt(e.get('start_dt',''), all_day)}@alles")
        lines.append(f"SUMMARY:{_esc(e.get('title', ''))}")
        if all_day:
            lines.append(f"DTSTART;VALUE=DATE:{_fmt_dt(e.get('start_dt',''), True)}")
            if e.get("end_dt"):
                lines.append(f"DTEND;VALUE=DATE:{_fmt_dt(e.get('end_dt',''), True)}")
        else:
            lines.append(f"DTSTART:{_fmt_dt(e.get('start_dt',''), False)}")
            if e.get("end_dt"):
                lines.append(f"DTEND:{_fmt_dt(e.get('end_dt',''), False)}")
        if e.get("description"):
            lines.append(f"DESCRIPTION:{_esc(e['description'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _parse_dt(val: str) -> tuple[str, bool]:
    """ICS date/datetime -> (ISO string, all_day)."""
    val = val.strip()
    if "T" in val:                      # 20260619T140000
        m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?", val)
        if m:
            y, mo, d, h, mi, s = m.groups()
            return f"{y}-{mo}-{d}T{h}:{mi}:{s or '00'}", False
    m = re.match(r"(\d{4})(\d{2})(\d{2})", val)   # 20260619
    if m:
        y, mo, d = m.groups()
        return f"{y}-{mo}-{d}", True
    return val, False


def parse_ics(text: str) -> list[dict]:
    events, cur = [], None
    # unfold continuation lines (RFC 5545: a leading space continues the prior line)
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"\n[ \t]", "", raw)
    for line in raw.split("\n"):
        if line == "BEGIN:VEVENT":
            cur = {"title": "", "start_dt": "", "end_dt": None, "all_day": False, "description": ""}
        elif line == "END:VEVENT":
            if cur and cur["start_dt"]:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, val = line.split(":", 1)
            name = key.split(";")[0].upper()
            if name == "SUMMARY":
                cur["title"] = _unesc(val)
            elif name == "DESCRIPTION":
                cur["description"] = _unesc(val)
            elif name == "DTSTART":
                cur["start_dt"], cur["all_day"] = _parse_dt(val)
            elif name == "DTEND":
                cur["end_dt"], _ = _parse_dt(val)
    return events
