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
from datetime import date, datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD = {w: i for i, w in enumerate(WEEKDAYS)}
_WD.update({w[:3]: i for w, i in list(_WD.items())})  # mon, tue, ...


class NotADate(ValueError):
    """the text names a date or time that doesn't exist, like 'feb 30' or '25:00'."""


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


def _owner_clock(today: date):
    """the owner's clock while `today` is the owner's today. a day picked by hand has no now"""
    from services.calendar_events import owner_now

    now = owner_now()
    return now if now.date() == today else None


def parse_task(
    text: str,
    today: date | None = None,
    language: str = "en",
    strict: bool = False,
    now: datetime | None = None,
) -> dict:
    """strict refuses a date that can't exist ("feb 30") instead of moving it to a real one.
    now is the owner's clock; without it the owner's own is used when today is their today"""
    from services.event_nl import time_still_ahead
    from services.localized_input import normalize_quick_add

    today = today or (now.date() if now else date.today())
    out = {"title": "", "due_date": None, "repeat": "", "priority": 0, "tags": ""}
    t = f" {normalize_quick_add(text, language)} "
    if strict:
        check_dates(t, today)
    # "call mom friday 3pm" typed on a friday morning is due today. the time stays in the title
    ahead = time_still_ahead(t, today, now if now is not None else _owner_clock(today))

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

    # recurrence — "every X" or a canonical localized token. consumes the phrase so it
    # doesn't pollute the title.
    m = re.search(
        r"\b(?:(?:every\s+(day|week|month|year|"
        r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|"
        r"(\d{1,2})(?:st|nd|rd|th|er)))|(daily|weekly|monthly|yearly))\b",
        t,
        re.I,
    )
    if m:
        word = (m.group(1) or m.group(3)).lower()
        if word == "daily" or word.startswith("day"):
            out["repeat"] = "daily"
        elif word == "weekly" or word.startswith("week"):
            out["repeat"] = "weekly"
        elif word == "monthly" or word.startswith("month"):
            out["repeat"] = "monthly"
        elif word == "yearly" or word.startswith("year"):
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
            first = _next_weekday(today, _WD[word[:3]], allow_today=ahead)
            out["due_date"] = out["due_date"] or first.isoformat()
        t = t[: m.start()] + " " + t[m.end() :]

    # one-off due date phrases (only if recurrence didn't already set one)
    if not out["due_date"]:
        out["due_date"], t = _extract_date(t, today, same_day=ahead)

    # "On Monday: standup" leaves a stray colon once the day is taken out
    out["title"] = re.sub(r"\s+", " ", t).strip(" -,:;") or text.strip()
    return out


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_RE = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)


def _month_name_date(t: str, today: date):
    """parse 'june 20' / '20 jun' / 'dec 25, 2027' → (iso, span). a bare month+day with
    no year that's already past this year rolls to next year. returns None if no match."""
    import calendar as _c

    # the (?!\d) after the day stops "june 2027" from reading "20" as the day-of-month
    for pat, order in (
        (rf"\b({_MONTH_RE})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)(?:,?\s+(\d{{4}}))?\b", "md"),
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)\s+({_MONTH_RE})\b(?:,?\s+(\d{{4}}))?", "dm"),
    ):
        m = re.search(pat, t, re.I)
        if not m:
            continue
        if order == "md":
            mon, day, yr = _MONTHS[m.group(1).lower()[:3]], int(m.group(2)), m.group(3)
        else:
            day, mon, yr = int(m.group(1)), _MONTHS[m.group(2).lower()[:3]], m.group(3)
        if not (1 <= day <= 31):
            continue
        year = int(yr) if yr else today.year
        # roll a bare (no explicit year) month+day that's already past to next year, THEN clamp
        # the day once so e.g. "feb 30" -> feb 28 and we never build an invalid date.
        if not yr and (mon, day) < (today.month, today.day):
            year += 1
        day = min(day, _c.monthrange(year, mon)[1])
        return date(year, mon, day).isoformat(), m.span()
    return None


def check_dates(t: str, today: date) -> None:
    """raise NotADate for an explicit date that can't exist. the parser would quietly clamp
    "feb 30" to the 28th or skip "2026-13-45", and the item would land on the wrong day."""
    import calendar as _c

    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        try:
            date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            raise NotADate(f"{m.group(0)} isn't a date") from None
    # only days 29-31 past the month's end: "may 45 people" isn't trying to be a date
    for pat, order in (
        (rf"\b({_MONTH_RE})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)(?:,?\s+(\d{{4}}))?\b", "md"),
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)\s+({_MONTH_RE})\b(?:,?\s+(\d{{4}}))?", "dm"),
    ):
        for m in re.finditer(pat, t, re.I):
            name, day = (m.group(1), m.group(2)) if order == "md" else (m.group(2), m.group(1))
            mon, day, yr = _MONTHS[name.lower()[:3]], int(day), m.group(3)
            if not 29 <= day <= 31:
                continue
            year = int(yr) if yr else today.year
            if not yr and (mon, day) < (today.month, today.day):
                year += 1
            if day > _c.monthrange(year, mon)[1]:
                when = re.sub(r"\s+", " ", m.group(0).strip()).lower()
                leap = mon == 2 and day == 29 and not yr
                raise NotADate(f"{when} isn't a date in {year}" if leap else f"{when} isn't a date")


_FULL_WD = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_ABBR_WD = r"mon|tue|wed|thu|fri|sat|sun"


def _bare_weekday(t: str):
    """the first weekday that's being used as a day, with a leading on/this/by. a full name
    counts anywhere, and so do tue/thu/fri, which mean nothing else. "sun", "sat", "mon" and
    "wed" count as the first word ("sat brunch 11am") or where a day goes (after on/this/by/
    until/due, or with nothing, a time or punctuation after it), so "buy sun screen" stays about
    sunscreen. the weekday in "last friday" isn't one."""
    for m in re.finditer(
        rf"\b(?:(on|this|by|until|till|due)\s+)?({_FULL_WD}|{_ABBR_WD})\b\.?", t, re.I
    ):
        before, after = t[: m.start()], t[m.end() :]
        if re.search(r"\blast\s+$", before, re.I):
            continue
        short = len(m.group(2)) == 3 and m.group(2).lower() not in ("tue", "thu", "fri")
        if short and not m.group(1) and before.strip():
            placed = re.search(r"\b(?:until|till|due|from|every)\s+$", before, re.I) or re.match(
                r"\s*(?:$|[,;!?]|\d|@|(?:at|noon|midnight|morning|afternoon|evening|night|tonight)\b)",
                after,
                re.I,
            )
            if not placed:
                continue
        return m
    return None


def _extract_date(t: str, today: date, same_day: bool = False):
    def strip(span):
        # A possessive date is part of the title even when it also suggests a due date.
        if re.match(r"['’]s\b", t[span[1] :], re.I):
            return t
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

    # month-name dates: "june 20", "20 jun", "dec 25 2027", "jan 3rd"
    md = _month_name_date(t, today)
    if md:
        return md[0], strip(md[1])

    # "next week monday" / "monday next week": that day in the week after this one (weeks
    # start monday). a plain "next monday" is still the next monday to come
    monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
    # a short day right next to "next week" is the day too ("next week fri review")
    m = re.search(
        rf"\bnext\s+week\s+(?:on\s+)?({_FULL_WD}|{_ABBR_WD})\b\.?"
        rf"|\b(?:on\s+)?({_FULL_WD}|{_ABBR_WD})\.?\s+next\s+week\b",
        t,
        re.I,
    )
    if m:
        due = monday + timedelta(days=_WD[(m.group(1) or m.group(2)).lower()[:3]])
        return due.isoformat(), strip(m.span())
    nw = re.search(r"\bnext\s+week\b", t, re.I)
    if nw:
        blanked = t[: nw.start()] + " " * (nw.end() - nw.start()) + t[nw.end() :]
        wm = _bare_weekday(blanked)
        if wm:
            due = monday + timedelta(days=_WD[wm.group(2).lower()[:3]])
            rest = t
            for a, b in sorted([nw.span(), wm.span()], reverse=True):
                rest = rest[:a] + " " + rest[b:]
            return due.isoformat(), rest

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

    # bare weekday → next occurrence. it runs before the past days, so "send yesterday
    # photos friday" is still due friday; "on monday" takes its "on" with it. same_day lets
    # today's own weekday be today (the caller checks the time hasn't gone by)
    m = _bare_weekday(t)
    if m:
        wd = _WD[m.group(2).lower()[:3]]
        return _next_weekday(today, wd, allow_today=same_day).isoformat(), strip(m.span())

    # past days come after every forward date. "yesterday's" / "last thursday's" name a
    # thing, not when it's due
    m = re.search(r"\byesterday\b(?!['’]s\b)", t, re.I)
    if m:
        return (today - timedelta(days=1)).isoformat(), strip(m.span())
    # "last friday" is the one that just went by; read as a bare weekday it landed next week
    m = re.search(
        r"\blast\s+(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
        r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b(?!['’]s\b)",
        t,
        re.I,
    )
    if m:
        back = (today.weekday() - _WD[m.group(1).lower()[:3]]) % 7 or 7
        return (today - timedelta(days=back)).isoformat(), strip(m.span())

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
        return date(
            y, d.month, min(anchor or d.day, calendar.monthrange(y, d.month)[1])
        ).isoformat()
    return None
