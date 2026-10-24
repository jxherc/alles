"""m0074 - calendar times are wall time: rewrite rows that still carry an offset.

old .ics imports and api writes stored "...Z" / "+02:00" times while everything else stores naive
wall time, so the week grid, agenda, free time and conflicts each read those rows differently.
this moves each zoned start/end to wall time in the owner's timezone setting and drops the offset.

only a zone the owner chose is used. with the setting blank ("follow the browser") nothing is
rewritten: a server in a container is usually on utc, and converting there would move a toronto
3:30 meeting to 7:30 for good. those rows keep their offset, which is correct data: every reader
turns it into wall time (services.calendar_events.wall_time). all-day rows hold plain dates and
are left alone, and so are repeating rows: their weekdays, last day and skipped days belong to
the offset's own frame (sunday 01:00 utc is saturday evening in toronto), and the readers repeat
them in that frame (services.calendar_events.occurrence_starts). running it again finds nothing
to change.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

VERSION = 74
NAME = "calendar_wall_times"


def _owner_zone():
    try:
        from core.settings import load_settings

        name = str(load_settings().get("timezone") or "").strip()
    except Exception:  # unreadable settings: same as blank, nothing is guessed
        return None
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _parse(value):
    if not isinstance(value, str) or len(value) <= 10:
        return None
    try:
        return datetime.fromisoformat(value)  # takes Z, +02:00 and +0200
    except ValueError:
        return None


def wall_pair(start, end, zone):
    """both ends as wall time in `zone`. one that would end at or before its start (an event
    across the autumn change, or an offset on one side only) keeps its length, else an hour."""
    s0, e0 = _parse(start), _parse(end)
    s1 = s0.astimezone(zone).replace(tzinfo=None) if s0 and s0.tzinfo else s0
    e1 = e0.astimezone(zone).replace(tzinfo=None) if e0 and e0.tzinfo else e0
    new_start = s1.isoformat() if s0 and s0.tzinfo else start
    new_end = e1.isoformat() if e0 and e0.tzinfo else end
    if s1 and e1 and e1 <= s1 and (new_start, new_end) != (start, end):
        length = e0 - s0 if s0.tzinfo and e0.tzinfo and e0 > s0 else timedelta(hours=1)
        new_end = (s1 + length).isoformat()
    return new_start, new_end


def up(conn):
    have = {
        row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    }
    if "calendar_events" not in have:
        return
    zone = _owner_zone()
    if zone is None:
        return
    rows = conn.execute(
        text(
            "SELECT id, start_dt, end_dt FROM calendar_events"
            " WHERE COALESCE(all_day, 0) = 0 AND COALESCE(recurrence, '') = ''"
        )
    ).fetchall()
    for event_id, start, end in rows:
        new_start, new_end = wall_pair(start, end, zone)
        if (new_start, new_end) != (start, end):
            conn.execute(
                text("UPDATE calendar_events SET start_dt = :start, end_dt = :end WHERE id = :id"),
                {"start": new_start, "end": new_end, "id": event_id},
            )
