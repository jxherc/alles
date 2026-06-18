"""
parse a natural-language calendar line into a title + start/end datetime.
reuses the date extraction from task_nl and adds time-of-day parsing.

  "lunch with sam friday 1pm"   -> fri, 13:00-14:00
  "dentist june 20 9:30am"      -> that date, 09:30-10:30
  "team sync tomorrow"          -> tomorrow, all-day (no time given)
  "standup every weekday 9am"   -> next day, 09:00 (recurrence left to caller)
"""

import re
from datetime import date, datetime, time, timedelta

from services.task_nl import _extract_date


def _extract_time(t: str):
    """return (time, remaining_text) or (None, t)."""
    m = re.search(r"\b(noon|midday)\b", t, re.I)
    if m:
        return time(12, 0), t[: m.start()] + " " + t[m.end() :]
    m = re.search(r"\b(midnight)\b", t, re.I)
    if m:
        return time(0, 0), t[: m.start()] + " " + t[m.end() :]
    # 1pm, 1:30pm, 9 am
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)\b", t, re.I)
    if m:
        h = int(m.group(1)) % 12
        if m.group(3).lower().startswith("p"):
            h += 12
        mn = int(m.group(2) or 0)
        return time(h % 24, mn), t[: m.start()] + " " + t[m.end() :]
    # 24h 13:00
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t)
    if m:
        return time(int(m.group(1)), int(m.group(2))), t[: m.start()] + " " + t[m.end() :]
    return None, t


def _extract_duration(t: str):
    """pull a 'for N hours/minutes' clause → (minutes, remaining)."""
    m = re.search(r"\bfor\s+(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", t, re.I)
    if not m:
        return None, t
    n, unit = int(m.group(1)), m.group(2).lower()
    mins = n * 60 if unit.startswith("h") else n
    return mins, t[: m.start()] + " " + t[m.end() :]


def _parse_clock(s: str):
    """parse a bare clock token → (time, had_meridiem) or (None, False)."""
    s = s.strip()
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?$", s, re.I)
    if m:
        h = int(m.group(1)) % 12
        if m.group(3).lower() == "p":
            h += 12
        return time(h % 24, int(m.group(2) or 0)), True
    m = re.match(r"(\d{1,2})(?::(\d{2}))?$", s)
    if m:
        return time(int(m.group(1)) % 24, int(m.group(2) or 0)), False
    return None, False


def _extract_time_range(t: str):
    """'1-2pm' / '3pm to 4:30pm' / '9-10am' → (start, end, remaining). the end must
    carry an am/pm; a start without one inherits it."""
    m = re.search(
        r"\b(\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?)\s*(?:to|until|-|–)\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)\b",
        t,
        re.I,
    )
    if not m:
        return None, None, t
    st, st_mer = _parse_clock(m.group(1))
    en, en_mer = _parse_clock(m.group(2))
    if st is None or en is None:
        return None, None, t
    if not st_mer and en_mer and st.hour < 12 and en.hour >= 12:
        st = time((st.hour + 12) % 24, st.minute)
    return st, en, t[: m.start()] + " " + t[m.end() :]


def _extract_until(t: str, today: date):
    """pull a trailing 'until/till <date>' clause → (recur_until_iso, remaining)."""
    m = re.search(r"\b(?:until|till|til)\b", t, re.I)
    if not m:
        return None, t
    due, _ = _extract_date(" " + t[m.end() :] + " ", today)
    if due:
        return due, t[: m.start()] + " "
    return None, t


def _extract_recurrence(t: str):
    """detect daily/weekly/monthly (frontend-supported cycles). for 'every <weekday>'
    the weekday is LEFT in the text so the date parser sets the first occurrence."""
    m = re.search(r"\bevery\s+(?=mon|tue|wed|thu|fri|sat|sun)", t, re.I)
    if m:
        return "weekly", t[: m.start()] + " " + t[m.end() :]
    for pat, rec in (
        (r"\b(?:every\s*day|daily)\b", "daily"),
        (r"\b(?:every\s*week|weekly)\b", "weekly"),
        (r"\b(?:every\s*month|monthly)\b", "monthly"),
    ):
        m = re.search(pat, t, re.I)
        if m:
            return rec, t[: m.start()] + " " + t[m.end() :]
    return "", t


def parse_event(text: str, today: date | None = None) -> dict:
    today = today or date.today()
    out = {
        "title": "",
        "start_dt": None,
        "end_dt": None,
        "all_day": False,
        "recurrence": "",
        "recur_until": None,
    }
    t = f" {text.strip()} "

    recur_until, t = _extract_until(t, today)
    recurrence, t = _extract_recurrence(t)
    out["recurrence"] = recurrence
    out["recur_until"] = (
        recur_until if recurrence else None
    )  # 'until' is meaningless without a cycle

    dur_min, t = _extract_duration(t)
    rng_start, rng_end, t = _extract_time_range(t)
    due, t = _extract_date(t, today)
    d = date.fromisoformat(due) if due else today

    tm = rng_start
    if rng_start is not None:
        start = datetime.combine(d, rng_start)
        end = datetime.combine(d, rng_end)
        if end <= start:
            end += timedelta(hours=12)  # e.g. crossed midday wrong way
        out["start_dt"] = start.isoformat(timespec="minutes")
        out["end_dt"] = end.isoformat(timespec="minutes")
        out["all_day"] = False
    else:
        tm, t = _extract_time(t)
        if tm is not None:
            start = datetime.combine(d, tm)
            mins = dur_min if dur_min else 60
            out["start_dt"] = start.isoformat(timespec="minutes")
            out["end_dt"] = (start + timedelta(minutes=mins)).isoformat(timespec="minutes")
            out["all_day"] = False
        else:
            out["start_dt"] = d.isoformat()
            out["all_day"] = True

    # only scrub date/time connector words if we actually pulled a date/time out,
    # so a plain title like "look at code" keeps its words
    if due or tm is not None:
        t = re.sub(r"\b(at|on|by|this|next)\b", " ", t, flags=re.I)
    out["title"] = re.sub(r"\s+", " ", t).strip(" -,") or text.strip()
    return out
