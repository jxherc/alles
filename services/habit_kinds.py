"""What a habit's day log can hold, per habit type, and the checks that keep it clean.

a habit's kind says what a done day records. "check" records nothing (a tap marks the day).
the others carry a small json object on that day's log row:

  workout   {"rows": [{exercise, weight (lb or null), reps, sets, note}]}
  reading   {amount, unit ("pages" | "chapters"), book}
  count     {amount}               the habit's own unit (glasses, steps, ...)
  duration  {minutes}
  distance  {distance, unit ("km" | "mi"), minutes (or null)}

weights follow the owner's notes: pounds, dumbbells per hand, machines per side. a set row
without reps is 10 reps, without sets is one set.
"""

import json
import math

KINDS = ("check", "workout", "reading", "count", "duration", "distance")
READING_UNITS = ("pages", "chapters")
DISTANCE_UNITS = ("km", "mi")
MAX_ROWS = 50
UNIT_CHARS = 24
NAME_CHARS = 80
NOTE_CHARS = 200
BOOK_CHARS = 120
DEFAULT_REPS = 10


class HabitLogError(ValueError):
    """a log or habit type the server won't store; the message reaches the screen."""


def check_kind(kind) -> str:
    kind = str(kind or "check").strip().lower()
    if kind not in KINDS:
        raise HabitLogError("that habit type doesn't exist")
    return kind


def check_unit(unit) -> str:
    unit = str(unit or "").strip()
    if len(unit) > UNIT_CHARS:
        raise HabitLogError("these log details don't fit this habit")
    return unit


def _bad():
    return HabitLogError("these log details don't fit this habit")


def _number(value, low, high, *, whole=False, required=True):
    if value is None or value == "":
        if required:
            raise _bad()
        return None
    if isinstance(value, bool):
        raise _bad()
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _bad() from None
    if not math.isfinite(number) or not low <= number <= high:
        raise _bad()
    if whole:
        if number != int(number):
            raise _bad()
        return int(number)
    number = round(number, 2)
    return int(number) if number == int(number) else number


def _text(value, cap):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _bad()
    value = " ".join(value.split())
    if len(value) > cap:
        raise _bad()
    return value


def _choice(value, options):
    value = str(value or options[0]).strip().lower()
    if value not in options:
        raise _bad()
    return value


def _workout(data):
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise _bad()
    if len(rows) > MAX_ROWS:
        raise HabitLogError("a workout log holds at most 50 rows")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise _bad()
        exercise = _text(row.get("exercise"), NAME_CHARS)
        if not exercise:
            raise _bad()
        reps = _number(row.get("reps"), 1, 1000, whole=True, required=False)
        sets = _number(row.get("sets"), 1, 100, whole=True, required=False)
        out.append(
            {
                "exercise": exercise,
                "weight": _number(row.get("weight"), 0, 2000, required=False),
                "reps": DEFAULT_REPS if reps is None else reps,
                "sets": 1 if sets is None else sets,
                "note": _text(row.get("note"), NOTE_CHARS),
            }
        )
    return {"rows": out} if out else None


def clean_log(kind: str, data):
    """the stored form of a day's details, or None when there is nothing beyond "done"."""
    if data is None:
        return None
    if kind == "check":
        raise HabitLogError("this habit is a simple check and has no log details")
    if not isinstance(data, dict):
        raise _bad()
    if kind == "workout":
        return _workout(data)
    if kind == "reading":
        return {
            "amount": _number(data.get("amount"), 0, 10000),
            "unit": _choice(data.get("unit"), READING_UNITS),
            "book": _text(data.get("book"), BOOK_CHARS),
        }
    if kind == "count":
        return {"amount": _number(data.get("amount"), 0, 1_000_000)}
    if kind == "duration":
        return {"minutes": _number(data.get("minutes"), 0, 1440)}
    if kind == "distance":
        return {
            "distance": _number(data.get("distance"), 0, 1000),
            "unit": _choice(data.get("unit"), DISTANCE_UNITS),
            "minutes": _number(data.get("minutes"), 0, 1440, required=False),
        }
    raise HabitLogError("that habit type doesn't exist")


def dump(data) -> str | None:
    return None if data is None else json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def load(raw):
    """a stored log's details; an unreadable old value reads as no details."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def exercise_names(logs) -> list[str]:
    """names used in past workout logs, newest day first, each once (any case)."""
    seen, out = set(), []
    for _day, data in sorted(logs, key=lambda item: item[0], reverse=True):
        for row in (data or {}).get("rows") or []:
            name = str(row.get("exercise") or "").strip() if isinstance(row, dict) else ""
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
    return out[:200]
