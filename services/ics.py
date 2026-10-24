"""
iCalendar (.ics) export/import — so the calendar talks to Apple Calendar, Google,
Outlook, anything. stdlib only, generates + parses VEVENTs. not a full RFC 5545
implementation, just the fields the app actually uses (summary/start/end/all-day/
description), which is what real calendars round-trip.
"""

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _add_days(iso: str, days: int) -> str:
    """shift a YYYY-MM-DD string by N days (handles month/year rollover)."""
    return (date.fromisoformat(iso[:10]) + timedelta(days=days)).isoformat()


def _esc(s: str) -> str:
    return (
        str(s or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _unesc(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _fmt_dt(iso: str, all_day: bool) -> str:
    """ISO string -> ICS date/datetime. '2026-06-19T14:00' -> 20260619T140000."""
    iso = (iso or "").strip()
    if all_day or len(iso) <= 10:
        d = iso[:10].replace("-", "")
        return d  # caller adds ;VALUE=DATE
    try:
        aware = datetime.fromisoformat(iso)
    except ValueError:
        aware = None
    # stored times are naive local and go out floating; an older row that kept
    # its offset goes out as utc
    if aware is not None and aware.tzinfo is not None:
        return aware.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    s = iso.replace("-", "").replace(":", "")
    s = s.split(".")[0]  # drop fractional seconds
    if "T" not in s and len(s) >= 8:
        s = s[:8] + "T" + s[8:]
    s = (s + "000000")[:15] if "T" in s else s
    return s


def _timed(name: str, iso: str, zone) -> str:
    """a timed DTSTART/DTEND line in utc. naive wall time is read in the owner's zone first, so
    another calendar shows the same moment. utc needs no VTIMEZONE block, which a TZID does
    (outlook refuses one without it), and nothing here repeats, so no daylight saving rule is
    lost. with no zone known it stays floating."""
    value = _fmt_dt(iso, False)
    if zone is not None and not value.endswith("Z"):
        try:
            when = datetime.fromisoformat(iso.strip()).replace(tzinfo=zone)
        except ValueError:
            return f"{name}:{value}"
        return f"{name}:{when.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    return f"{name}:{value}"


def to_ics(events: list[dict], zone=None) -> str:
    """zone: the owner's (timezone setting, else the last browser zone seen) unless given"""
    if zone is None:
        from services.calendar_events import owner_zone

        zone = owner_zone()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//alles//calendar//EN",
        "CALSCALE:GREGORIAN",
    ]
    for e in events:
        all_day = bool(e.get("all_day"))
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{e.get('id') or _fmt_dt(e.get('start_dt', ''), all_day)}@alles")
        lines.append(f"SUMMARY:{_esc(e.get('title', ''))}")
        if all_day:
            lines.append(f"DTSTART;VALUE=DATE:{_fmt_dt(e.get('start_dt', ''), True)}")
            if e.get("end_dt"):
                # all-day DTEND is exclusive in RFC 5545 (an event on the 1st ends
                # the 2nd). we store the inclusive last day, so emit end + 1 day —
                # otherwise the final day is dropped in Apple/Google/Outlook.
                lines.append(f"DTEND;VALUE=DATE:{_fmt_dt(_add_days(e['end_dt'], 1), True)}")
        else:
            lines.append(_timed("DTSTART", e.get("start_dt", ""), zone))
            if e.get("end_dt"):
                lines.append(_timed("DTEND", e.get("end_dt", ""), zone))
        if e.get("description"):
            lines.append(f"DESCRIPTION:{_esc(e['description'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _parse_dt(val: str, tzid: str = "") -> tuple[str, bool]:
    """ICS date/datetime -> (ISO string, all_day). returns ('', …) when the value
    is digit-shaped but not a real date (e.g. month 13) so a single broken VEVENT
    can't crash the whole import/feed-sync. a utc "Z" or a TZID time keeps its offset
    here; parse_ics moves it to the owner's wall time when that zone is known."""
    val = val.strip()
    if "T" in val:  # 20260619T140000
        m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z)?", val)
        if m:
            y, mo, d, h, mi, s, utc = m.groups()
            iso = f"{y}-{mo}-{d}T{h}:{mi}:{s or '00'}"
            try:
                when = datetime.fromisoformat(iso)
            except ValueError:
                return "", False
            zone = None
            if utc:
                zone = UTC
            elif tzid:
                try:
                    zone = ZoneInfo(tzid)
                except (ValueError, ZoneInfoNotFoundError):
                    pass  # an outlook-only zone name: keep the wall time
            if zone is not None:
                return when.replace(tzinfo=zone).isoformat(), False
            return iso, False
    m = re.match(r"(\d{4})(\d{2})(\d{2})", val)  # 20260619
    if m:
        y, mo, d = m.groups()
        iso = f"{y}-{mo}-{d}"
        try:
            date.fromisoformat(iso)
        except ValueError:
            return "", True
        return iso, True
    return val, False


def _tzid(key: str) -> str:
    """'DTSTART;TZID=America/New_York' -> 'America/New_York'."""
    for part in key.split(";")[1:]:
        if part.upper().startswith("TZID="):
            return part.split("=", 1)[1].strip('"')
    return ""


_OWNER = object()


def parse_ics(text: str, zone=_OWNER) -> list[dict]:
    """zoned times land on wall time in `zone` (default: the timezone setting), so a 19:00Z
    meeting from google doesn't show at 19:00 local. with no zone to go by they keep their
    offset, which every reader converts; a guessed server zone (utc in a container) would move
    them for good."""
    from services.calendar_events import wall_pair, write_zone

    if zone is _OWNER:
        zone = write_zone()
    events, cur = [], None
    # unfold continuation lines (RFC 5545: a leading space continues the prior line)
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"\n[ \t]", "", raw)
    for line in raw.split("\n"):
        if line == "BEGIN:VEVENT":
            cur = {"title": "", "start_dt": "", "end_dt": None, "all_day": False, "description": ""}
        elif line == "END:VEVENT":
            if cur and cur["start_dt"]:
                if zone is not None:
                    cur["start_dt"], cur["end_dt"] = wall_pair(cur["start_dt"], cur["end_dt"], zone)
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
                cur["start_dt"], cur["all_day"] = _parse_dt(val, _tzid(key))
            elif name == "DTEND":
                end_iso, end_all_day = _parse_dt(val, _tzid(key))
                if end_iso:
                    # reverse the export: an all-day exclusive end → inclusive last day
                    cur["end_dt"] = _add_days(end_iso, -1) if end_all_day else end_iso
    return events
