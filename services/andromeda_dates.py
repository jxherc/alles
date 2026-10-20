"""date answers for andromeda: today's date, days until or since a day, and n days from today.

all of it is local arithmetic on the server's own calendar. nothing leaves the machine.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"


def _easter(year: int) -> date:
    # anonymous gregorian computus
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    return date(year, month, (h + m - 7 * n + 114) % 31 + 1)


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))


_HOLIDAYS = {
    "christmas": lambda y: date(y, 12, 25),
    "christmas day": lambda y: date(y, 12, 25),
    "christmas eve": lambda y: date(y, 12, 24),
    "new year": lambda y: date(y, 1, 1),
    "new years": lambda y: date(y, 1, 1),
    "new year's": lambda y: date(y, 1, 1),
    "new year's day": lambda y: date(y, 1, 1),
    "new years day": lambda y: date(y, 1, 1),
    "new year's eve": lambda y: date(y, 12, 31),
    "new years eve": lambda y: date(y, 12, 31),
    "halloween": lambda y: date(y, 10, 31),
    "valentine's day": lambda y: date(y, 2, 14),
    "valentines day": lambda y: date(y, 2, 14),
    "valentines": lambda y: date(y, 2, 14),
    "canada day": lambda y: date(y, 7, 1),
    "independence day": lambda y: date(y, 7, 4),
    "4th of july": lambda y: date(y, 7, 4),
    "fourth of july": lambda y: date(y, 7, 4),
    "easter": _easter,
    "thanksgiving": lambda y: _nth_weekday(y, 11, 3, 4),
    "canadian thanksgiving": lambda y: _nth_weekday(y, 10, 0, 2),
    "mother's day": lambda y: _nth_weekday(y, 5, 6, 2),
    "mothers day": lambda y: _nth_weekday(y, 5, 6, 2),
    "father's day": lambda y: _nth_weekday(y, 6, 6, 3),
    "fathers day": lambda y: _nth_weekday(y, 6, 6, 3),
}


def parse_day(text: str, today: date) -> tuple[date, str] | None:
    """a day from plain words. a day without a year means the next one on or after today."""
    value = re.sub(r"\s+", " ", str(text or "").strip().lower()).strip(" ?.")
    value = re.sub(r"^(?:the |next )", "", value)
    if not value:
        return None
    if value in ("today", "now"):
        return today, "today"
    if value == "tomorrow":
        return today + timedelta(days=1), "tomorrow"
    if value == "yesterday":
        return today - timedelta(days=1), "yesterday"
    if value in _HOLIDAYS:
        day = _HOLIDAYS[value](today.year)
        if day < today:
            day = _HOLIDAYS[value](today.year + 1)
        return day, value
    if value in _WEEKDAYS:
        ahead = (_WEEKDAYS.index(value) - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead), value
    found = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if found:
        return _safe(int(found[1]), int(found[2]), int(found[3]))
    found = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if found:
        # month first, the way the owner's locale writes it
        return _safe(int(found[3]), int(found[1]), int(found[2]))
    found = re.fullmatch(rf"{_MONTH} (\d{{1,2}})(?:st|nd|rd|th)?(?:,? (\d{{4}}))?", value)
    if found:
        month, day, year = _MONTHS[found[1]], int(found[2]), found[3]
    else:
        found = re.fullmatch(
            rf"(\d{{1,2}})(?:st|nd|rd|th)? (?:of )?{_MONTH}(?:,? (\d{{4}}))?", value
        )
        if not found:
            return None
        month, day, year = _MONTHS[found[2]], int(found[1]), found[3]
    if year:
        return _safe(int(year), month, day), ""
    picked = _safe(today.year, month, day)
    if picked and picked[0] < today:
        picked = _safe(today.year + 1, month, day)
    return picked


def _safe(year: int, month: int, day: int):
    try:
        return date(year, month, day), ""
    except ValueError:
        return None


_UNIT_DAYS = {"day": 1, "week": 7}


def detect(low: str) -> dict | None:
    """a date question, or None. the found dict carries the words; resolve() does the dates."""
    if re.fullmatch(
        r"(?:what(?:'s| is) )?(?:today'?s date|the date(?: today)?|date today|todays date|"
        r"what day is (?:it|today)|what day is it today|current date)",
        low,
    ):
        return {"kind": "date", "mode": "today"}
    found = re.fullmatch(
        r"(?:how many days (?:until|till|til|to|before)|days (?:until|till|til|to|left until|left till)|"
        r"how long (?:until|till|til)|countdown (?:to|until|till)|time (?:until|till))\s+(.+)",
        low,
    )
    if found:
        return {
            "kind": "date",
            "mode": "until",
            "day": found[1],
            "live": low.startswith("countdown"),
        }
    found = re.fullmatch(
        r"(?:how many days since|days since|how long since|how long ago was)\s+(.+)", low
    )
    if found:
        return {"kind": "date", "mode": "since", "day": found[1]}
    found = re.fullmatch(r"(?:how many )?days (?:between|from) (.+?) (?:and|to|until) (.+)", low)
    if found:
        return {"kind": "date", "mode": "between", "day": found[1], "other": found[2]}
    found = re.fullmatch(
        r"(?:what(?:'s| is) (?:the date )?)?(\d{1,4}) (days?|weeks?) (from (?:today|now)|ago|later|from now)",
        low,
    )
    if found:
        sign = -1 if found[3] == "ago" else 1
        return {
            "kind": "date",
            "mode": "offset",
            "days": sign * int(found[1]) * _UNIT_DAYS[found[2].rstrip("s")],
        }
    found = re.fullmatch(r"what day (?:of the week )?(?:is|was|will be|is it on) (.+)", low)
    if found and found[1] not in ("it", "today", "it today"):
        return {"kind": "date", "mode": "weekday", "day": found[1]}
    return None


def resolve(found: dict, today: date | None = None) -> dict | None:
    today = today or datetime.now().astimezone().date()
    mode = found["mode"]
    out = {"kind": "date", "mode": mode, "today": today.isoformat()}
    if mode == "today":
        return {**out, "date": today.isoformat()}
    if mode == "offset":
        target = today + timedelta(days=found["days"])
        return {**out, "date": target.isoformat(), "days": found["days"]}
    parsed = parse_day(found["day"], today)
    if not parsed:
        return None
    day, name = parsed
    if mode == "weekday":
        return {**out, "date": day.isoformat(), "name": name}
    if mode == "between":
        other = parse_day(found["other"], today)
        if not other:
            return None
        return {
            **out,
            "date": day.isoformat(),
            "other": other[0].isoformat(),
            "days": abs((other[0] - day).days),
        }
    if mode == "since" and day > today:
        # "days since christmas" in october means last christmas
        try:
            day = day.replace(year=day.year - 1)
        except ValueError:
            day = day - timedelta(days=365)
    days = (day - today).days if mode == "until" else (today - day).days
    return {
        **out,
        "date": day.isoformat(),
        "name": name,
        "days": days,
        "live": bool(found.get("live")),
    }
