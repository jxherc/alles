"""4a - calendar conflict detection + a free-slot scheduling advisor. pure over event dicts
{title, start_dt, end_dt, all_day}. timed events only (all-day events never conflict)."""

from datetime import datetime, timedelta


def _dt(s):
    try:
        return datetime.fromisoformat((s or "")[:16])
    except ValueError:
        return None


def _span(ev):
    if ev.get("all_day"):
        return None
    a = _dt(ev.get("start_dt"))
    b = _dt(ev.get("end_dt")) or (a + timedelta(minutes=30) if a else None)
    if not a or not b or b <= a:
        return None
    return a, b


def conflicts(events):
    """pairs of timed events whose intervals overlap (touching end==start is NOT a conflict)."""
    spans = [(ev, _span(ev)) for ev in events]
    spans = [(ev, sp) for ev, sp in spans if sp]
    out = []
    for i in range(len(spans)):
        ea, (sa, eaend) = spans[i]
        for j in range(i + 1, len(spans)):
            eb, (sb, ebend) = spans[j]
            if sa < ebend and sb < eaend:  # strict overlap
                out.append({"a": ea.get("title", ""), "b": eb.get("title", "")})
    return out


def free_slots(events, day, *, day_start="09:00", day_end="17:00", duration_min=30):
    """gaps on `day` (>= duration_min) not covered by any timed event, within the working window."""
    lo = datetime.fromisoformat(f"{day}T{day_start}")
    hi = datetime.fromisoformat(f"{day}T{day_end}")
    busy = []
    for ev in events:
        sp = _span(ev)
        if sp and sp[0].date().isoformat() == day:
            busy.append(sp)
    busy.sort()
    out = []
    cursor = lo
    for s, e in busy:
        if s > cursor and (s - cursor) >= timedelta(minutes=duration_min):
            out.append({"start": cursor.strftime("%H:%M"), "end": s.strftime("%H:%M")})
        cursor = max(cursor, e)
    if hi > cursor and (hi - cursor) >= timedelta(minutes=duration_min):
        out.append({"start": cursor.strftime("%H:%M"), "end": hi.strftime("%H:%M")})
    return out
