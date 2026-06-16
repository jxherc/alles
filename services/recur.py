"""
recurrence expansion — turn an event + its rule into concrete occurrences.

a small RRULE-ish engine: FREQ daily/weekly/monthly/yearly, INTERVAL (every N),
weekly BYDAY (MO,WE,FR), COUNT (end after N), UNTIL (end date), and EXDATE
(excluded occurrence dates). kept deliberately simple — single-user calendar, not
a groupware server — but enough to match what the UI lets you build.
"""
import calendar as _cal
import json
from datetime import datetime, date, timedelta

_WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _parse_dt(s):
    if not s:
        return None
    s = str(s)
    try:
        return datetime.fromisoformat(s[:16]) if "T" in s else datetime.fromisoformat(s[:10])
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(s[:10]), datetime.min.time())
        except ValueError:
            return None


def _end_of_day(s):
    d = _parse_dt(s)
    return d.replace(hour=23, minute=59, second=59) if d else None


def _byday(s):
    return {_WD[t.strip().upper()] for t in (s or "").split(",") if t.strip().upper() in _WD}


def _json_list(s):
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return d.replace(year=y, month=m, day=min(d.day, _cal.monthrange(y, m)[1]))


def _weekly_stream(start, interval, byday):
    days = byday or {start.weekday()}
    monday = (start - timedelta(days=start.weekday())).replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0)
    wk = 0
    while True:
        base = monday + timedelta(weeks=wk * interval)
        for wd in sorted(days):
            cand = base + timedelta(days=wd)
            if cand >= start.replace(second=0, microsecond=0):
                yield cand
        wk += 1


def _step_stream(start, rec, interval):
    if rec in ("daily", "weekly"):
        cur = start
        delta = timedelta(days=interval) if rec == "daily" else timedelta(weeks=interval)
        while True:
            yield cur
            cur = cur + delta
    else:
        # monthly/yearly: recompute from `start` each step so a clamped short month
        # (feb 28) doesn't permanently drag the day-of-month down
        months = interval if rec == "monthly" else 12 * interval
        i = 0
        while True:
            yield _add_months(start, i * months)
            i += 1


def expand(event: dict, rs: datetime, re: datetime, cap: int = 1500) -> list[datetime]:
    """occurrence start-datetimes of `event` within [rs, re). honours interval,
    weekly byday, count, until and excluded dates."""
    start = _parse_dt(event.get("start_dt"))
    if not start:
        return []
    rec = (event.get("recurrence") or "").strip()
    if not rec:
        return [start] if rs <= start < re else []

    interval = max(1, int(event.get("recur_interval") or 1))
    until = _end_of_day(event.get("recur_until"))
    count = event.get("recur_count")
    count = int(count) if count else None
    byday = _byday(event.get("recur_byday")) if rec == "weekly" else set()
    excepts = {str(x)[:10] for x in _json_list(event.get("recur_except"))}

    stream = _weekly_stream(start, interval, byday) if rec == "weekly" else _step_stream(start, rec, interval)
    out, emitted, guard = [], 0, 0
    for cand in stream:
        guard += 1
        if guard > cap * 4:
            break
        if until and cand > until:
            break
        if count is not None and emitted >= count:
            break
        emitted += 1                                  # COUNT counts pre-exclusion (RFC)
        if cand.date().isoformat() in excepts:
            continue
        if cand >= re:
            break
        if cand >= rs:
            out.append(cand)
        if len(out) >= cap:
            break
    return out
