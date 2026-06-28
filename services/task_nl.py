"""
parse a natural-language quick-add line into structured task fields.
no external deps — deterministic, covers the common cases people actually type:

  "pay rent every 1st"            -> repeat monthly, due the 1st
  "call mom tomorrow !"           -> due tomorrow, priority high
  "submit report friday #work"    -> due next friday, tag work
  "water plants every week"       -> repeat weekly
  "renew passport in 3 weeks"     -> due +21d
"""

import re
from datetime import date, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD = {w: i for i, w in enumerate(WEEKDAYS)}
_WD.update({w[:3]: i for w, i in list(_WD.items())})  # mon, tue, ...


def _next_weekday(today: date, wd: int, allow_today=False) -> date:
    delta = (wd - today.weekday()) % 7
    if delta == 0 and not allow_today:
        delta = 7
    return today + timedelta(days=delta)


def reschedule_date(when: str, today: date | None = None) -> str:
    """new due date for a quick-reschedule: today | tomorrow | next_week | weekend |
    <weekday>. raises ValueError on anything else."""
    today = today or date.today()
    w = (when or "").strip().lower().replace(" ", "_")
    if w == "today":
        return today.isoformat()
    if w == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if w == "next_week":
        return (today + timedelta(days=7)).isoformat()
    if w == "weekend":
        return _next_weekday(today, 5, allow_today=True).isoformat()  # Saturday
    if w in _WD:
        return _next_weekday(today, _WD[w], allow_today=False).isoformat()
    raise ValueError("unknown reschedule target")


def parse_task(text: str, today: date | None = None) -> dict:
    today = today or date.today()
    out = {"title": "", "due_date": None, "repeat": "", "priority": 0, "tags": ""}
    t = f" {text.strip()} "

    # priority — a standalone ! (high-ish) or !! (high), on the app's 0=none..3=high scale
    m = re.search(r"\s(!{1,2})(?=\s)", t)
    if m:
        out["priority"] = 3 if len(m.group(1)) == 2 else 2
        t = re.sub(r"\s!{1,2}(?=\s)", " ", t)

    # tags — #word
    tags = re.findall(r"#([\w-]+)", t)
    if tags:
        out["tags"] = ",".join(dict.fromkeys(tags))
        t = re.sub(r"#[\w-]+", " ", t)

    # recurrence — "every X". consumes the phrase so it doesn't pollute the title.
    m = re.search(
        r"\bevery\s+(day|week|month|year|"
        r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|"
        r"(\d{1,2})(?:st|nd|rd|th))\b",
        t,
        re.I,
    )
    if m:
        word = m.group(1).lower()
        if word.startswith("day"):
            out["repeat"] = "daily"
        elif word.startswith("week"):
            out["repeat"] = "weekly"
        elif word.startswith("month"):
            out["repeat"] = "monthly"
        elif word.startswith("year"):
            out["repeat"] = "yearly"
        elif m.group(2):  # "every 1st" → monthly on that day
            import calendar

            out["repeat"] = "monthly"
            dom = int(m.group(2))
            # clamp to this month's real last day, not a flat 28 — otherwise "every 31st" always
            # landed on the 28th. max(1,...) guards a junk "every 0th" from hitting day=0.
            last = calendar.monthrange(today.year, today.month)[1]
            cand = today.replace(day=max(1, min(dom, last)))
            out["due_date"] = (cand if cand >= today else _add_month(cand)).isoformat()
        else:  # weekday → weekly, anchor to next one
            out["repeat"] = "weekly"
            out["due_date"] = out["due_date"] or _next_weekday(today, _WD[word[:3]]).isoformat()
        t = t[: m.start()] + " " + t[m.end() :]

    # one-off due date phrases (only if recurrence didn't already set one)
    if not out["due_date"]:
        out["due_date"], t = _extract_date(t, today)

    out["title"] = re.sub(r"\s+", " ", t).strip(" -,") or text.strip()
    return out


def _extract_date(t: str, today: date):
    def strip(span):
        return t[: span[0]] + " " + t[span[1] :]

    # ISO date — only accept a real calendar date, else it crashes
    # date.fromisoformat() downstream (e.g. "2026-13-40" → 500).
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    if m:
        try:
            date.fromisoformat(m.group(1))
            return m.group(1), strip(m.span())
        except ValueError:
            pass

    m = re.search(r"\b(today|tonight)\b", t, re.I)
    if m:
        return today.isoformat(), strip(m.span())
    m = re.search(r"\b(tomorrow|tmr)\b", t, re.I)
    if m:
        return (today + timedelta(days=1)).isoformat(), strip(m.span())

    m = re.search(r"\bin\s+(\d{1,3})\s+(day|days|week|weeks)\b", t, re.I)
    if m:
        n = int(m.group(1)) * (7 if m.group(2).startswith("week") else 1)
        return (today + timedelta(days=n)).isoformat(), strip(m.span())

    m = re.search(
        r"\bnext\s+(week|month|"
        r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
        t,
        re.I,
    )
    if m:
        w = m.group(1).lower()
        if w == "week":
            return (today + timedelta(days=7)).isoformat(), strip(m.span())
        if w == "month":
            return _add_month(today).isoformat(), strip(m.span())
        return _next_weekday(today, _WD[w[:3]]).isoformat(), strip(m.span())

    # bare weekday → next occurrence
    m = re.search(
        r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
        r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b",
        t,
        re.I,
    )
    if m:
        return _next_weekday(today, _WD[m.group(1).lower()[:3]]).isoformat(), strip(m.span())

    return None, t


def _add_month(d: date, anchor: int | None = None) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    import calendar

    return date(y, m, min(anchor or d.day, calendar.monthrange(y, m)[1]))


def advance(due: str, repeat: str, anchor: int | None = None) -> str | None:
    """next due date for a recurring task once the current one is done. `anchor` is the original
    day-of-month — pass it so monthly/yearly don't drift the day down after a short month."""
    if not due or not repeat:
        return None
    try:
        d = date.fromisoformat(due[:10])
    except ValueError:
        return None
    if repeat == "daily":
        return (d + timedelta(days=1)).isoformat()
    if repeat == "weekly":
        return (d + timedelta(days=7)).isoformat()
    if repeat == "monthly":
        return _add_month(d, anchor).isoformat()
    if repeat == "yearly":
        import calendar
        y = d.year + 1
        return date(y, d.month, min(anchor or d.day, calendar.monthrange(y, d.month)[1])).isoformat()
    return None
