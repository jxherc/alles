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
        return time(12, 0), t[:m.start()] + " " + t[m.end():]
    m = re.search(r"\b(midnight)\b", t, re.I)
    if m:
        return time(0, 0), t[:m.start()] + " " + t[m.end():]
    # 1pm, 1:30pm, 9 am
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)\b", t, re.I)
    if m:
        h = int(m.group(1)) % 12
        if m.group(3).lower().startswith("p"):
            h += 12
        mn = int(m.group(2) or 0)
        return time(h % 24, mn), t[:m.start()] + " " + t[m.end():]
    # 24h 13:00
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t)
    if m:
        return time(int(m.group(1)), int(m.group(2))), t[:m.start()] + " " + t[m.end():]
    return None, t


def parse_event(text: str, today: date | None = None) -> dict:
    today = today or date.today()
    out = {"title": "", "start_dt": None, "end_dt": None, "all_day": False}
    t = f" {text.strip()} "

    due, t = _extract_date(t, today)
    tm, t = _extract_time(t)
    d = date.fromisoformat(due) if due else today

    if tm is not None:
        start = datetime.combine(d, tm)
        out["start_dt"] = start.isoformat(timespec="minutes")
        out["end_dt"] = (start + timedelta(hours=1)).isoformat(timespec="minutes")
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
