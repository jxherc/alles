"""a task's due moment: a day (due_date, "2026-10-20") and an optional wall clock time
(due_time, "09:30"). every reader of a due date goes through here, so sorting, overdue checks
and the calendar overlay agree on what "due" means."""

import re
from datetime import date, datetime

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_CLOCK = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?")


def clean_day(value) -> str | None:
    """the day part of a stored or sent due date; None when there is none."""
    text = str(value or "").strip()
    return text[:10] if _DAY.fullmatch(text[:10]) else None


def clean_clock(value) -> str | None:
    """ "9:30" or "09:30" or "09:30:00" -> "09:30"; None for empty. raises ValueError otherwise."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    found = _CLOCK.fullmatch(text)
    if not found:
        raise ValueError("use a time like 09:30")
    return f"{int(found.group(1)):02d}:{found.group(2)}"


def split_due(value) -> tuple[str | None, str | None]:
    """ "2026-10-20T09:30" -> ("2026-10-20", "09:30"); a plain day -> (day, None)."""
    text = str(value or "").strip()
    day = clean_day(text)
    if not day:
        return None, None
    clock = None
    if len(text) > 10 and text[10] in "T ":
        try:
            clock = clean_clock(text[11:])
        except ValueError:
            clock = None
    return day, clock


def sort_key(due_date, due_time) -> tuple[str, str]:
    """earliest first; a task due any time that day follows the ones with a time."""
    return (clean_day(due_date) or "9999", clean_clock_or_none(due_time) or "99:99")


def clean_clock_or_none(value) -> str | None:
    try:
        return clean_clock(value)
    except ValueError:
        return None


def is_overdue(due_date, due_time, now: datetime) -> bool:
    """past due at `now` (the owner's wall clock). a day with no time runs to the end of the
    day; a day with a time is over at that time."""
    day = clean_day(due_date)
    if not day:
        return False
    today = now.date()
    due_day = date.fromisoformat(day)
    if due_day < today:
        return True
    if due_day > today:
        return False
    clock = clean_clock_or_none(due_time)
    return bool(clock) and clock < now.strftime("%H:%M")
