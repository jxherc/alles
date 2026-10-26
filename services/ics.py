"""
iCalendar (.ics) export and import, so the calendar talks to apple calendar, google, outlook,
anything. stdlib only. not all of RFC 5545, just what alles keeps: title, times, notes, repeats.

a repeating series goes out as one VEVENT with an RRULE and its skipped days as EXDATE. wall times
go out with the owner's zone as a TZID, described by a VTIMEZONE block built from zoneinfo; a row
that kept its offset goes out in utc, its rule moved onto utc's days, and a series that repeats in
the zone it came from (source_zone) goes out in that zone. coming back in, RRULE,
EXDATE, RECURRENCE-ID and VTIMEZONE are read. a repeat alles can't show (the 2nd tuesday of a
month, extra RDATE days, hourly) keeps its first time only, and the reader counts those.
"""

import calendar as _cal
import re
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
_FREQS = ("daily", "weekly", "monthly", "yearly")
_EMPTY = {
    "recurrence": "",
    "recur_interval": 1,
    "recur_byday": "",
    "recur_count": None,
    "recur_until": None,
    "recur_except": [],
}


def _add_days(iso: str, days: int) -> str:
    """shift a YYYY-MM-DD string by N days (handles month/year rollover)."""
    return (date.fromisoformat(iso[:10]) + timedelta(days=days)).isoformat()


def _esc(s: str) -> str:
    return (
        str(s or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _unesc(s: str) -> str:
    # one pass, so an escaped backslash followed by an n stays a backslash and an n
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), s)


def _fold(line: str) -> str:
    """a line past 75 octets carries on after CRLF and a space, never inside a character"""
    if len(line.encode()) <= 75:
        return line
    parts, chunk, size, room = [], "", 0, 75
    for ch in line:
        n = len(ch.encode())
        if size + n > room:
            parts.append(chunk)
            chunk, size, room = "", 0, 74  # the space that starts a continuation counts
        chunk += ch
        size += n
    parts.append(chunk)
    return "\r\n ".join(parts)


# ── export ───────────────────────────────────────────────────────────────────


def _stamp(when: datetime) -> str:
    return when.strftime("%Y%m%dT%H%M%S")


def _utc(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _offset(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    hours, rest = divmod(abs(total), 3600)
    minutes, seconds = divmod(rest, 60)
    tail = f"{seconds:02d}" if seconds else ""
    return f"{'-' if total < 0 else '+'}{hours:02d}{minutes:02d}{tail}"


def _reading(tz, when: datetime):
    """(offset, daylight saving?, name) of tz at a naive utc instant"""
    local = when.replace(tzinfo=UTC).astimezone(tz)
    return local.utcoffset(), bool(local.dst()), local.tzname() or ""


def _changes(tz, lo: datetime, hi: datetime) -> list[datetime]:
    """the naive utc minutes in (lo, hi] where tz starts reading differently"""
    out, at, here = [], lo, _reading(tz, lo)
    while at < hi:
        nxt = min(at + timedelta(days=1), hi)
        there = _reading(tz, nxt)
        if there != here:
            a, b = 0, int((nxt - at).total_seconds() // 60)
            while b - a > 1:
                mid = (a + b) // 2
                if _reading(tz, at + timedelta(minutes=mid)) == here:
                    a = mid
                else:
                    b = mid
            nxt = at + timedelta(minutes=b)
            out.append(nxt)
            there = _reading(tz, nxt)
        at, here = nxt, there
    return out


def _observance(dst, before, after, name, onset, rule="") -> list[str]:
    kind = "DAYLIGHT" if dst else "STANDARD"
    lines = [
        f"BEGIN:{kind}",
        f"DTSTART:{_stamp(onset)}",
        f"TZOFFSETFROM:{_offset(before)}",
        f"TZOFFSETTO:{_offset(after)}",
    ]
    if name:
        lines.append(f"TZNAME:{_esc(name)}")
    if rule:
        lines.append(f"RRULE:{rule}")
    return [*lines, f"END:{kind}"]


def _nth(day: date) -> set:
    """the ways a yearly rule can name this weekday in its month: {2} for the 2nd, and -1 too
    when it's the month's last"""
    forms = {(day.day - 1) // 7 + 1}
    if day.day + 7 > _cal.monthrange(day.year, day.month)[1]:
        forms.add(-1)
    return forms


def _vtimezone(tzid: str, tz, lo: datetime, hi: datetime) -> list[str]:
    """a VTIMEZONE for tz between two naive utc times. a kind of change that keeps to one yearly
    rule ("2nd sunday of march, 02:00") is one observance with an RRULE, left open while the zone
    still follows it, so a calendar reads the zone past hi too. anything else is listed as is"""
    lo = lo.replace(second=0, microsecond=0)
    hi = hi.replace(second=0, microsecond=0)
    end = hi + timedelta(days=800)  # looking past hi tells a rule still in use from one that ended
    offset, dst, name = _reading(tz, lo)
    lines = [
        "BEGIN:VTIMEZONE",
        f"TZID:{tzid}",
        *_observance(dst, offset, offset, name, lo + offset),
    ]
    runs, done, before = {}, [], offset
    for when in _changes(tz, lo, end):
        after, dst, name = _reading(tz, when)
        onset = when + before  # an observance starts on the old clock
        key = (dst, before, after, name)
        shape = (onset.month, onset.weekday(), onset.time())
        run = runs.get(key)
        if (
            run
            and run["shape"] == shape
            and onset.year == run["onsets"][-1].year + 1
            and run["forms"] & _nth(onset.date())
        ):
            run["onsets"].append(onset)
            run["forms"] &= _nth(onset.date())
            run["last"] = when
        elif when <= hi:
            if run:
                done.append((key, run))
            runs[key] = {
                "shape": shape,
                "onsets": [onset],
                "forms": _nth(onset.date()),
                "last": when,
            }
        before = after
    done += list(runs.items())
    for (dst, before, after, name), run in sorted(done, key=lambda item: item[1]["onsets"][0]):
        first, rule = run["onsets"][0], ""
        if len(run["onsets"]) > 1:
            n = -1 if -1 in run["forms"] else min(run["forms"])
            rule = f"FREQ=YEARLY;BYMONTH={first.month};BYDAY={n}{_DAYS[first.weekday()]}"
            if run["last"] < end - timedelta(days=400):
                rule += f";UNTIL={run['last']:%Y%m%dT%H%M%SZ}"
        lines += _observance(dst, before, after, name, first, rule)
    return [*lines, "END:VTIMEZONE"]


def _fixed(frame, when: datetime):
    """a TZID for a kept offset whose repeat no utc rule can say: an Etc/GMT zone for whole hours"""
    offset = frame.utcoffset(when) or timedelta(0)
    hours, rest = divmod(int(offset.total_seconds()), 3600)
    if not rest and -12 <= hours <= 14:
        key = "Etc/GMT" if not hours else f"Etc/GMT{-hours:+d}"  # Etc/GMT-9 is utc+9
        try:
            return key, ZoneInfo(key)
        except (ValueError, ZoneInfoNotFoundError):
            pass
    return f"UTC{_offset(offset)}", timezone(offset)


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _excepts(value) -> list[date]:
    import json

    if isinstance(value, str):
        try:
            value = json.loads(value or "[]")
        except ValueError:
            value = []
    days = {_day(v) for v in value} if isinstance(value, list) else set()
    return sorted(d for d in days if d)


def _first_weekly(start: datetime, interval: int, days: set) -> datetime:
    """the first time a weekly series happens: its start, unless that weekday isn't one of its
    days. RFC counts DTSTART as a time, so the series goes out from the first real one"""
    wd = start.weekday()
    later = [d for d in sorted(days) if d >= wd]
    if later:
        return start + timedelta(days=later[0] - wd)
    return start + timedelta(days=7 * interval - wd + min(days))


def _local_rule(rec, interval, days, first, picked) -> list[str]:
    """the RRULE of a series in its own frame"""
    parts = [f"FREQ={rec.upper()}"]
    if interval > 1:
        parts.append(f"INTERVAL={interval}")
    if rec == "weekly" and picked:
        parts.append("BYDAY=" + ",".join(_DAYS[d] for d in sorted(days)))
        if interval > 1 and len(days) > 1:
            parts.append("WKST=MO")
    elif rec == "monthly" and first.day > 28:
        # alles moves the 30th to a short month's last day; a plain rule would skip that month
        parts.append(
            "BYMONTHDAY=-1" if first.day == 31 else f"BYMONTHDAY={first.day},-1;BYSETPOS=1"
        )
    elif rec == "yearly" and (first.month, first.day) == (2, 29):
        parts.append("BYMONTH=2;BYMONTHDAY=29,-1;BYSETPOS=1")
    return parts


def _utc_rule(rec, interval, days, first, shift, picked):
    """the rule of a series kept in a fixed offset, on utc's days. `first` is in that offset and
    utc's date is `shift` days off it. None when a plain utc rule can't say the same: weeks that
    would split at utc's monday, or a month day that would cross a month's end. that series goes
    out in its own offset instead"""
    if not shift:
        return _local_rule(rec, interval, days, first, picked)
    if rec == "weekly" and interval > 1 and len(days) > 1:
        return None
    if rec == "monthly" and not (first.day <= 28 and 1 <= first.day + shift <= 28):
        return None
    if rec == "yearly":
        size = 28 if first.month == 2 else _cal.monthrange(2001, first.month)[1]
        if (first.month, first.day) == (2, 29) or not 1 <= first.day + shift <= size:
            return None
    parts = [f"FREQ={rec.upper()}"]
    if interval > 1:
        parts.append(f"INTERVAL={interval}")
    if rec == "weekly" and picked:
        parts.append("BYDAY=" + ",".join(_DAYS[d] for d in sorted((d + shift) % 7 for d in days)))
    return parts


def _when(e: dict, zone, zones: dict):
    """DTSTART, DTEND and the repeat lines of one event. None when its series has no time left.
    all-day goes out as dates, wall time with the owner's zone as a TZID (floating with none), and
    a kept offset in utc"""
    all_day = bool(e.get("all_day"))
    raw = str(e.get("start_dt") or "").strip()
    try:
        start = datetime.fromisoformat(raw[:10] if all_day else raw)
    except ValueError:
        return [f"DTSTART:{re.sub(r'[^0-9T]', '', raw)[:15]}"]  # nothing readable to repeat
    end = None
    if e.get("end_dt"):
        try:
            end = datetime.fromisoformat(str(e["end_dt"])[:10] if all_day else str(e["end_dt"]))
        except ValueError:
            end = None
    rec = str(e.get("recurrence") or "").strip()
    rec = rec if rec in _FREQS else ""
    interval = max(1, int(e.get("recur_interval") or 1))
    count = e.get("recur_count")
    count = int(count) if count is not None and str(count) != "" else None
    until = _day(e.get("recur_until")) if rec else None
    frame = None if all_day else start.tzinfo
    source = _source_zone(e) if frame is not None else None
    if source is not None:
        start = start.astimezone(source)
    local = start.replace(tzinfo=None)
    days = set()
    if rec == "weekly":
        byday = str(e.get("recur_byday") or "").upper().split(",")
        days = {_DAYS.index(d.strip()) for d in byday if d.strip() in _DAYS}
    first = _first_weekly(local, interval, days or {local.weekday()}) if days else local
    if rec and (count == 0 or (until and first.date() > until)):
        return None
    delta = first - local
    excepts = _excepts(e.get("recur_except")) if rec else []

    if all_day:
        lines = [f"DTSTART;VALUE=DATE:{first:%Y%m%d}"]
        if end and end >= start:
            # all-day DTEND is exclusive in RFC 5545 (an event on the 1st ends the 2nd); alles
            # keeps the last day, so the end goes out a day later or calendars drop that day
            lines.append(f"DTEND;VALUE=DATE:{end + delta + timedelta(days=1):%Y%m%d}")
        if not rec:
            return lines
        rule = _local_rule(rec, interval, days, first, bool(days))
        if count is not None:
            rule.append(f"COUNT={count}")
        if until:
            rule.append(f"UNTIL={until:%Y%m%d}")
        lines.append("RRULE:" + ";".join(rule))
        if excepts:
            lines.append("EXDATE;VALUE=DATE:" + ",".join(f"{d:%Y%m%d}" for d in excepts))
        return lines

    if end is not None:
        if frame is None and end.tzinfo is not None:
            end = end.astimezone(zone) if zone else end.astimezone()
            end = end.replace(tzinfo=None)
        elif frame is not None and end.tzinfo is None:
            end = end.replace(tzinfo=frame)
        end = end + delta

    rule, tz, tzid = [], None, ""
    if source is not None:
        # a series from another zone repeats in it: its own TZID, so the round trip is exact
        tz, tzid = source, source.key
        rule = _local_rule(rec, interval, days, first, bool(days)) if rec else []
        if end is not None:
            end = end.astimezone(tz).replace(tzinfo=None)
    elif frame is not None:
        # a kept offset repeats in its own frame; in utc each of its days is `shift` days off
        aware = first.replace(tzinfo=frame)
        shift = (aware.astimezone(UTC).date() - first.date()).days
        rule = _utc_rule(rec, interval, days, first, shift, bool(days)) if rec else []
        if rule is None:
            tzid, tz = _fixed(frame, first)
            rule = _local_rule(rec, interval, days, first, bool(days))
            if end is not None:
                end = end.astimezone(tz).replace(tzinfo=None)
    elif zone is not None:
        tz, tzid = zone, getattr(zone, "key", "") or str(zone)
        rule = _local_rule(rec, interval, days, first, bool(days)) if rec else []
    else:
        rule = _local_rule(rec, interval, days, first, bool(days)) if rec else []

    def put(name, *whens):
        if tz is not None:
            return f"{name};TZID={tzid}:" + ",".join(_stamp(w) for w in whens)
        if frame is not None:
            return f"{name}:" + ",".join(_utc(w.replace(tzinfo=frame)) for w in whens)
        return f"{name}:" + ",".join(_stamp(w) for w in whens)

    def last(day):  # the end of the series' last day, as UNTIL wants it
        when = datetime.combine(day, time(23, 59, 59))
        if tz is not None:
            return _utc(when.replace(tzinfo=tz))
        return _utc(when.replace(tzinfo=frame)) if frame is not None else _stamp(when)

    lines = [put("DTSTART", first)]
    if end is not None:
        lines.append(put("DTEND", end) if tz is not None or frame is None else f"DTEND:{_utc(end)}")
    if rec:
        if count is not None:
            rule.append(f"COUNT={count}")
        if until:
            rule.append(f"UNTIL={last(until)}")
        lines.append("RRULE:" + ";".join(rule))
        if excepts:
            lines.append(put("EXDATE", *(datetime.combine(d, first.time()) for d in excepts)))
    if tz is not None:
        lo = first.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
        ends = [lo]
        if end is not None:
            ends.append(end.replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None))
        if until:
            ends.append(datetime.combine(until, time(23, 59)))
        span = zones.setdefault(tzid, [tz, None, None])
        span[1] = min(lo, span[1] or lo)
        span[2] = max(*ends, span[2] or lo)
    return lines


def _source_zone(e: dict):
    """the IANA zone an imported series repeats in, or None"""
    name = str(e.get("source_zone") or "").strip()
    if not name or not e.get("recurrence"):
        return None
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _dtstamp(created) -> str:
    try:
        when = created if isinstance(created, datetime) else datetime.fromisoformat(str(created))
    except (TypeError, ValueError):
        return ""
    if when.tzinfo is not None:
        when = when.astimezone(UTC).replace(tzinfo=None)
    return f"{when:%Y%m%dT%H%M%S}Z"  # created_at is kept in utc


_FIRST, _LAST = datetime(1900, 1, 1), datetime(2200, 12, 31)


def to_ics(events: list[dict], zone=None) -> str:
    """zone: the owner's (timezone setting, else the last browser zone seen) unless given. with no
    zone known, wall times go out floating"""
    if zone is None:
        from services.calendar_events import owner_zone

        zone = owner_zone()
    zones, body = {}, []
    for e in events:
        try:
            when = _when(e, zone, zones)
        except OverflowError:
            continue  # a year no calendar file can hold (9999, or 0001 east of utc)
        if when is None:
            continue
        uid = e.get("id") or re.sub(r"[^0-9T]", "", str(e.get("start_dt") or ""))
        body += ["BEGIN:VEVENT", f"UID:{uid}@alles"]
        stamp = _dtstamp(e.get("created_at"))
        if stamp:
            body.append(f"DTSTAMP:{stamp}")
        body.append(f"SUMMARY:{_esc(e.get('title', ''))}")
        body += when
        if e.get("description"):
            body.append(f"DESCRIPTION:{_esc(e['description'])}")
        if e.get("location"):
            body.append(f"LOCATION:{_esc(e['location'])}")
        body.append("END:VEVENT")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//alles//calendar//EN",
        "CALSCALE:GREGORIAN",
    ]
    today = datetime.combine(datetime.now(UTC).date(), time())
    for tzid, (tz, lo, hi) in zones.items():
        # a far-off date (an old import, 9999) can't widen the description past what it can say
        lo, hi = max(lo, _FIRST), min(max(hi, today), _LAST)
        lines += _vtimezone(tzid, tz, lo - timedelta(days=1), hi + timedelta(days=366))
    lines += [*body, "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


# ── import ───────────────────────────────────────────────────────────────────

# outlook writes windows zone names (CLDR windowsZones, the main zone for each)
_WINDOWS = dict(
    pair.split("=", 1)
    for pair in (
        "Dateline Standard Time=Etc/GMT+12|UTC-11=Etc/GMT+11|Aleutian Standard Time=America/Adak|"
        "Hawaiian Standard Time=Pacific/Honolulu|Marquesas Standard Time=Pacific/Marquesas|"
        "Alaskan Standard Time=America/Anchorage|UTC-09=Etc/GMT+9|UTC-08=Etc/GMT+8|"
        "Pacific Standard Time (Mexico)=America/Tijuana|Pacific Standard Time=America/Los_Angeles|"
        "US Mountain Standard Time=America/Phoenix|Mountain Standard Time (Mexico)=America/Mazatlan|"
        "Mountain Standard Time=America/Denver|Yukon Standard Time=America/Whitehorse|"
        "Central America Standard Time=America/Guatemala|Central Standard Time=America/Chicago|"
        "Easter Island Standard Time=Pacific/Easter|"
        "Central Standard Time (Mexico)=America/Mexico_City|"
        "Canada Central Standard Time=America/Regina|SA Pacific Standard Time=America/Bogota|"
        "Eastern Standard Time (Mexico)=America/Cancun|Eastern Standard Time=America/New_York|"
        "Haiti Standard Time=America/Port-au-Prince|Cuba Standard Time=America/Havana|"
        "US Eastern Standard Time=America/Indiana/Indianapolis|"
        "Turks And Caicos Standard Time=America/Grand_Turk|Paraguay Standard Time=America/Asuncion|"
        "Atlantic Standard Time=America/Halifax|Venezuela Standard Time=America/Caracas|"
        "Central Brazilian Standard Time=America/Cuiaba|SA Western Standard Time=America/La_Paz|"
        "Pacific SA Standard Time=America/Santiago|Newfoundland Standard Time=America/St_Johns|"
        "Tocantins Standard Time=America/Araguaina|E. South America Standard Time=America/Sao_Paulo|"
        "SA Eastern Standard Time=America/Cayenne|"
        "Argentina Standard Time=America/Argentina/Buenos_Aires|"
        "Greenland Standard Time=America/Nuuk|Montevideo Standard Time=America/Montevideo|"
        "Magallanes Standard Time=America/Punta_Arenas|Saint Pierre Standard Time=America/Miquelon|"
        "Bahia Standard Time=America/Bahia|UTC-02=Etc/GMT+2|Azores Standard Time=Atlantic/Azores|"
        "Cape Verde Standard Time=Atlantic/Cape_Verde|UTC=Etc/UTC|"
        "GMT Standard Time=Europe/London|Greenwich Standard Time=Atlantic/Reykjavik|"
        "Sao Tome Standard Time=Africa/Sao_Tome|Morocco Standard Time=Africa/Casablanca|"
        "W. Europe Standard Time=Europe/Berlin|Central Europe Standard Time=Europe/Budapest|"
        "Romance Standard Time=Europe/Paris|Central European Standard Time=Europe/Warsaw|"
        "W. Central Africa Standard Time=Africa/Lagos|Jordan Standard Time=Asia/Amman|"
        "GTB Standard Time=Europe/Bucharest|Middle East Standard Time=Asia/Beirut|"
        "Egypt Standard Time=Africa/Cairo|E. Europe Standard Time=Europe/Chisinau|"
        "Syria Standard Time=Asia/Damascus|West Bank Standard Time=Asia/Hebron|"
        "South Africa Standard Time=Africa/Johannesburg|FLE Standard Time=Europe/Kyiv|"
        "Israel Standard Time=Asia/Jerusalem|South Sudan Standard Time=Africa/Juba|"
        "Kaliningrad Standard Time=Europe/Kaliningrad|Sudan Standard Time=Africa/Khartoum|"
        "Libya Standard Time=Africa/Tripoli|Namibia Standard Time=Africa/Windhoek|"
        "Arabic Standard Time=Asia/Baghdad|Turkey Standard Time=Europe/Istanbul|"
        "Arab Standard Time=Asia/Riyadh|Belarus Standard Time=Europe/Minsk|"
        "Russian Standard Time=Europe/Moscow|E. Africa Standard Time=Africa/Nairobi|"
        "Volgograd Standard Time=Europe/Volgograd|Iran Standard Time=Asia/Tehran|"
        "Arabian Standard Time=Asia/Dubai|Astrakhan Standard Time=Europe/Astrakhan|"
        "Azerbaijan Standard Time=Asia/Baku|Russia Time Zone 3=Europe/Samara|"
        "Mauritius Standard Time=Indian/Mauritius|Saratov Standard Time=Europe/Saratov|"
        "Georgian Standard Time=Asia/Tbilisi|Caucasus Standard Time=Asia/Yerevan|"
        "Afghanistan Standard Time=Asia/Kabul|West Asia Standard Time=Asia/Tashkent|"
        "Ekaterinburg Standard Time=Asia/Yekaterinburg|Pakistan Standard Time=Asia/Karachi|"
        "Qyzylorda Standard Time=Asia/Qyzylorda|India Standard Time=Asia/Kolkata|"
        "Sri Lanka Standard Time=Asia/Colombo|Nepal Standard Time=Asia/Kathmandu|"
        "Central Asia Standard Time=Asia/Bishkek|Bangladesh Standard Time=Asia/Dhaka|"
        "Omsk Standard Time=Asia/Omsk|Myanmar Standard Time=Asia/Yangon|"
        "SE Asia Standard Time=Asia/Bangkok|Altai Standard Time=Asia/Barnaul|"
        "W. Mongolia Standard Time=Asia/Hovd|North Asia Standard Time=Asia/Krasnoyarsk|"
        "N. Central Asia Standard Time=Asia/Novosibirsk|Tomsk Standard Time=Asia/Tomsk|"
        "China Standard Time=Asia/Shanghai|North Asia East Standard Time=Asia/Irkutsk|"
        "Singapore Standard Time=Asia/Singapore|W. Australia Standard Time=Australia/Perth|"
        "Taipei Standard Time=Asia/Taipei|Ulaanbaatar Standard Time=Asia/Ulaanbaatar|"
        "Aus Central W. Standard Time=Australia/Eucla|Transbaikal Standard Time=Asia/Chita|"
        "Tokyo Standard Time=Asia/Tokyo|North Korea Standard Time=Asia/Pyongyang|"
        "Korea Standard Time=Asia/Seoul|Yakutsk Standard Time=Asia/Yakutsk|"
        "Cen. Australia Standard Time=Australia/Adelaide|AUS Central Standard Time=Australia/Darwin|"
        "E. Australia Standard Time=Australia/Brisbane|AUS Eastern Standard Time=Australia/Sydney|"
        "West Pacific Standard Time=Pacific/Port_Moresby|Tasmania Standard Time=Australia/Hobart|"
        "Vladivostok Standard Time=Asia/Vladivostok|Lord Howe Standard Time=Australia/Lord_Howe|"
        "Bougainville Standard Time=Pacific/Bougainville|Russia Time Zone 10=Asia/Srednekolymsk|"
        "Magadan Standard Time=Asia/Magadan|Norfolk Standard Time=Pacific/Norfolk|"
        "Sakhalin Standard Time=Asia/Sakhalin|Central Pacific Standard Time=Pacific/Guadalcanal|"
        "Russia Time Zone 11=Asia/Kamchatka|New Zealand Standard Time=Pacific/Auckland|"
        "UTC+12=Etc/GMT-12|Fiji Standard Time=Pacific/Fiji|"
        "Chatham Islands Standard Time=Pacific/Chatham|UTC+13=Etc/GMT-13|"
        "Tonga Standard Time=Pacific/Tongatapu|Samoa Standard Time=Pacific/Apia|"
        "Line Islands Standard Time=Pacific/Kiritimati"
    ).split("|")
)


def _lines(text: str) -> list[str]:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n[ \t]", "", raw).split("\n")  # a leading space continues the line before


def _prop(line: str):
    """'DTSTART;TZID="a:b":2026…' -> ('DTSTART', {'TZID': 'a:b'}, '2026…'); None for no property"""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            break
    else:
        return None
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', line[:i])
    if not parts:
        return None
    params = {}
    for part in parts[1:]:
        key, _, value = part.partition("=")
        params[key.strip().upper()] = value.strip().strip('"')
    return parts[0].strip().upper(), params, line[i + 1 :]


def _tree(text: str) -> dict:
    """the file as nested components. one cut off before its END stays open (closed False)"""
    root = {"name": "", "props": [], "parts": [], "closed": True}
    stack = [root]
    for line in _lines(text):
        prop = _prop(line)
        if prop is None:
            continue
        name, _, value = prop
        if name == "BEGIN":
            comp = {"name": value.strip().upper(), "props": [], "parts": [], "closed": False}
            stack[-1]["parts"].append(comp)
            stack.append(comp)
        elif name == "END":
            for i in range(len(stack) - 1, 0, -1):
                if stack[i]["name"] == value.strip().upper():
                    stack[i]["closed"] = True
                    del stack[i:]
                    break
        else:
            stack[-1]["props"].append(prop)
    return root


def _walk(comp: dict, name: str):
    for part in comp["parts"]:
        if part["name"] == name:
            yield part
        yield from _walk(part, name)


def _value(value: str, params: dict, zones):
    """a DATE or DATE-TIME: a date, (naive, tz) with tz None when floating, or None when it isn't a
    real one. a utc "Z" or a known TZID keeps its zone here; the reader moves it to wall time"""
    m = re.match(r"\s*(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?", value or "")
    if not m:
        return None
    y, mo, d, h, mi, s, z = m.groups()
    try:
        if h is None or params.get("VALUE", "").upper() == "DATE":
            return date(int(y), int(mo), int(d))
        when = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError:
        return None
    if z:
        return when, UTC
    tzid = params.get("TZID", "")
    return when, (zones.get(tzid) if tzid and zones is not None else None)


def _duration(value: str):
    m = re.fullmatch(
        r"\s*([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?\s*", value or ""
    )
    if not m or not any(m.groups()[1:]):
        return None
    sign, w, d, h, mi, s = m.groups()
    span = timedelta(
        weeks=int(w or 0),
        days=int(d or 0),
        hours=int(h or 0),
        minutes=int(mi or 0),
        seconds=int(s or 0),
    )
    return -span if sign == "-" else span


class _Defined(tzinfo):
    """a zone the file describes itself (outlook's "Customized Time Zone"): its observances' yearly
    rules or listed dates say when the offset changes. ambiguous and skipped wall times read like
    zoneinfo: fold=0 on the clock from before the change, fold=1 on the one after"""

    def __init__(self, key: str, observances: list[dict]):
        self.key = key
        self._obs = observances
        self._seen = {}

    def _onsets(self, year: int) -> list:
        """(utc instant, offset after, daylight?, name) for every change up to year+1, oldest first"""
        if year not in self._seen:
            out = []
            for o in self._obs:
                for local in _onset_days(o, year + 1):
                    utc = local - o["before"]
                    if o["until"] is None or utc <= o["until"]:
                        out.append((utc, o["after"], o["dst"], o["name"], o["before"]))
            out.sort(key=lambda item: item[0])
            self._seen[year] = out
        return self._seen[year]

    def _initial(self):
        o = min(self._obs, key=lambda o: o["start"])
        return (None, o["before"], False, o["name"], o["before"])

    def _local(self, dt):
        local, found = dt.replace(tzinfo=None), self._initial()
        pick = min if dt.fold else max
        for item in self._onsets(local.year):
            if local >= item[0] + pick(item[1], item[4]):
                found = item
        return found

    def utcoffset(self, dt):
        return None if dt is None else self._local(dt)[1]

    def dst(self, dt):
        return timedelta(hours=1) if dt is not None and self._local(dt)[2] else timedelta(0)

    def tzname(self, dt):
        return None if dt is None else self._local(dt)[3]

    def fromutc(self, dt):
        utc, found = dt.replace(tzinfo=None), self._initial()
        for item in self._onsets(utc.year):
            if item[0] <= utc:
                found = item
        # the clocks went back: the first hour after the change is the second pass (fold=1)
        again = found[0] is not None and utc < found[0] + (found[4] - found[1])
        return (utc + found[1]).replace(tzinfo=self, fold=int(again))


def _onset_days(o: dict, upto: int):
    """the local times an observance starts, up to the end of a year"""
    if o["start"].year <= upto:
        yield o["start"]
    for when in o["rdates"]:
        if when.year <= upto:
            yield when
    rule = o["rule"]
    if not rule:
        return
    for year in range(o["start"].year, upto + 1):
        day = _rule_day(year, rule)
        if day:
            when = datetime.combine(day, o["start"].time())
            if when > o["start"]:
                yield when


def _rule_day(year: int, rule: dict):
    month = rule["month"]
    last = _cal.monthrange(year, month)[1]
    days = [d if d > 0 else last + 1 + d for d in rule["monthdays"]] or list(range(1, last + 1))
    days = sorted(d for d in days if 1 <= d <= last)
    if rule["wd"] is None:
        return date(year, month, days[0]) if rule["monthdays"] and days else None
    hits = [d for d in days if date(year, month, d).weekday() == rule["wd"]]
    n = rule["n"] or 1
    try:
        return date(year, month, hits[n - 1] if n > 0 else hits[n])
    except IndexError:
        return None


def _zone_offset(value: str) -> timedelta:
    m = re.fullmatch(r"\s*([+-])(\d{2})(\d{2})(\d{2})?\s*", value or "")
    if not m:
        raise ValueError(value)
    sign, h, mi, s = m.groups()
    span = timedelta(hours=int(h), minutes=int(mi), seconds=int(s or 0))
    return -span if sign == "-" else span


def _defined(tzid: str, block: dict):
    observances = []
    for part in block["parts"]:
        if part["name"] not in ("STANDARD", "DAYLIGHT"):
            continue
        one, rdates = {}, []
        for name, params, value in part["props"]:
            if name == "RDATE":
                rdates += [_value(v, params, None) for v in value.split(",")]
            else:
                one.setdefault(name, value)
        start = _value(one.get("DTSTART", ""), {}, None)
        try:
            before, after = _zone_offset(one["TZOFFSETFROM"]), _zone_offset(one["TZOFFSETTO"])
        except (KeyError, ValueError):
            continue
        if not isinstance(start, tuple):
            continue
        rule, until = None, None
        parts = dict(p.partition("=")[::2] for p in one.get("RRULE", "").upper().split(";") if p)
        if parts.get("FREQ") == "YEARLY" and parts.get("BYMONTH", "").isdigit():
            day = re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", parts.get("BYDAY", ""))
            try:
                monthdays = [int(d) for d in parts.get("BYMONTHDAY", "").split(",") if d]
            except ValueError:
                monthdays = []
            rule = {
                "month": int(parts["BYMONTH"]),
                "n": int(day.group(1)) if day and day.group(1) else None,
                "wd": _DAYS.index(day.group(2)) if day else None,
                "monthdays": monthdays,
            }
            stop = _value(parts.get("UNTIL", ""), {}, None)
            if isinstance(stop, tuple):
                until = stop[0]
        observances.append(
            {
                "start": start[0],
                "before": before,
                "after": after,
                "dst": part["name"] == "DAYLIGHT",
                "name": _unesc(one.get("TZNAME", "")) or tzid,
                "rule": rule if rule and 1 <= rule["month"] <= 12 else None,
                "until": until,
                "rdates": [r[0] for r in rdates if isinstance(r, tuple)],
            }
        )
    return _Defined(tzid, observances) if observances else None


class _Zones:
    """TZID -> tzinfo: an IANA name (also behind a /mozilla.org/… prefix), a windows name, or the
    file's own VTIMEZONE for it. None keeps the wall time as written"""

    def __init__(self, root: dict):
        self.blocks, self.found = {}, {}
        for comp in _walk(root, "VTIMEZONE"):
            tzid = next((v for n, _, v in comp["props"] if n == "TZID"), "").strip()
            if tzid:
                self.blocks[tzid] = comp

    def get(self, tzid: str):
        tzid = tzid.strip()
        if tzid not in self.found:
            self.found[tzid] = self._find(tzid)
        return self.found[tzid]

    def _find(self, tzid: str):
        names = [tzid]
        if "/" in tzid:
            parts = tzid.strip("/").split("/")
            names += ["/".join(parts[i:]) for i in range(1, len(parts))]
        mapped = None
        for name in [*names, _WINDOWS.get(tzid, "")]:
            if not name:
                continue
            try:
                mapped = ZoneInfo(name)
            except (ValueError, OSError, ZoneInfoNotFoundError):
                continue
            if name == tzid:
                return mapped  # a real IANA name
            break
        block = self.blocks.get(tzid)
        own = _defined(tzid, block) if block else None
        # a windows or prefixed name is only a guess at the zone; the file's own description of
        # it is what the times were written in
        if mapped is not None and (own is None or _agree(mapped, own)):
            return mapped
        return own or mapped


def _agree(zone, own: _Defined) -> bool:
    """does a zone read like a file's own description of it from last year to two years ahead?
    both only change at their clock changes, so the minute before and at each one says it"""
    year = datetime.now(UTC).year
    lo, hi = datetime(year - 1, 1, 1), datetime(year + 3, 1, 1)
    marks = {lo, *_changes(zone, lo, hi)}
    marks.update(item[0] for item in own._onsets(year + 2) if lo <= item[0] <= hi)
    for mark in marks:
        for at in (mark - timedelta(minutes=1), mark):
            at = at.replace(tzinfo=UTC)
            if at.astimezone(zone).utcoffset() != at.astimezone(own).utcoffset():
                return False
    return True


def _read_event(comp: dict, zones: _Zones):
    """one VEVENT's fields, or None when it has no real start"""
    one, many = {}, {"RRULE": [], "RDATE": [], "EXDATE": [], "EXRULE": []}
    for name, params, value in comp["props"]:
        if name in many:
            many[name].append((params, value))
        else:
            one.setdefault(name, (params, value))
    if "DTSTART" not in one:
        return None
    params, value = one["DTSTART"]
    start = _value(value, params, zones)
    if start is None:
        return None
    timed = isinstance(start, tuple)
    end, bad = None, False
    if "DTEND" in one:
        params, value = one["DTEND"]
        end = _value(value, params, zones)
        if end is None or isinstance(end, tuple) != timed:
            end, bad = None, True
    elif "DURATION" in one:
        span = _duration(one["DURATION"][1])
        if span is None:
            bad = True
        elif timed:
            end = (start[0] + span, start[1])
        else:
            end = start + timedelta(days=span.days)
    if not timed and end == start:
        end = start + timedelta(days=1)  # an all-day end on its own start is that one day
    rid = None
    if "RECURRENCE-ID" in one:
        params, value = one["RECURRENCE-ID"]
        rid = _value(value, params, zones)
    exdates = []
    for params, value in many["EXDATE"]:
        exdates += [v for v in (_value(x, params, zones) for x in value.split(",")) if v]
    text = lambda key: _unesc(one[key][1]) if key in one else ""  # noqa: E731
    return {
        "uid": text("UID").strip(),
        "title": text("SUMMARY"),
        # outlook writes an empty note as one escaped newline
        "description": text("DESCRIPTION").strip(),
        "location": text("LOCATION").strip(),
        "status": text("STATUS").strip().upper(),
        "start": start,
        "end": end,
        "bad_end": bad,
        "rrules": [value for _, value in many["RRULE"]],
        "odd": bool(many["RDATE"] or many["EXRULE"]),
        "exdates": exdates,
        "rid": rid,
    }


def _ints(text: str):
    try:
        return {int(x) for x in text.split(",") if x}
    except ValueError:
        return None


def _rule(ev: dict, zones: _Zones):
    """the RRULE as alles fields, in the series' own frame. None when alles can't show it the same
    way: a monthly or yearly weekday rule, a month day that only some months have, RDATE, hourly"""
    if len(ev["rrules"]) != 1 or ev["odd"]:
        return None
    start = ev["start"][0] if isinstance(ev["start"], tuple) else ev["start"]
    parts = {}
    for chunk in ev["rrules"][0].strip().upper().split(";"):
        key, _, value = chunk.partition("=")
        if not key or key in parts:
            return None
        parts[key.strip()] = value.strip()
    freq = parts.pop("FREQ", "")
    try:
        interval = int(parts.pop("INTERVAL", "1"))
        count = int(parts.pop("COUNT")) if "COUNT" in parts else None
    except ValueError:
        return None
    if interval < 1 or (count is not None and count < 1):
        return None
    until = None
    if "UNTIL" in parts:
        until = _value(parts.pop("UNTIL"), {}, zones)
        if until is None:
            return None
    wkst = parts.pop("WKST", "MO")
    # an hour or minute that only repeats the start's own changes nothing
    for key, unit in (("BYHOUR", "hour"), ("BYMINUTE", "minute"), ("BYSECOND", "second")):
        if key in parts and parts.pop(key) != str(getattr(start, unit, -1)):
            return None
    byday, bysetpos = parts.pop("BYDAY", ""), parts.pop("BYSETPOS", "")
    months, monthdays = _ints(parts.pop("BYMONTH", "")), _ints(parts.pop("BYMONTHDAY", ""))
    if parts or wkst not in _DAYS or months is None or monthdays is None:
        return None
    rule = {"recurrence": freq.lower(), "interval": interval, "byday": "", "count": count}
    rule["until"] = until
    if freq == "DAILY" and byday and interval == 1:
        rule["recurrence"], freq = "weekly", "WEEKLY"  # every weekday is weekly on those days
    if freq == "DAILY":
        return rule if not (byday or months or monthdays or bysetpos) else None
    if freq == "WEEKLY":
        days = [d for d in byday.split(",") if d]
        if months or monthdays or bysetpos or any(d not in _DAYS for d in days):
            return None
        picked = {_DAYS.index(d) for d in days}
        w = _DAYS.index(wkst)
        # alles weeks start monday; a sunday-start week holding sunday and monday groups them apart
        if interval > 1 and w and any(d >= w for d in picked) and any(d < w for d in picked):
            return None
        rule["byday"] = ",".join(_DAYS[d] for d in sorted(picked))
        return rule
    d = start.day
    if freq == "MONTHLY":
        if byday or months:
            return None
        if bysetpos:
            ok = bysetpos in ("1", "+1") and monthdays == {d, -1}  # "the dth, or the month's end"
        elif monthdays == {-1}:
            ok = d == 31
        else:
            # a plain 30th skips february in RFC; alles moves it to the 28th
            ok = (not monthdays or monthdays == {d}) and d <= 28
        return rule if ok else None
    if freq == "YEARLY":
        if byday or (months and months != {start.month}):
            return None
        if bysetpos:
            ok = bysetpos in ("1", "+1") and (start.month, d) == (2, 29) and monthdays == {29, -1}
        else:
            ok = (not monthdays or monthdays == {d}) and (start.month, d) != (2, 29)
        return rule if ok else None
    return None


def _iso(value) -> str:
    naive, tz = value
    return naive.replace(tzinfo=tz).isoformat() if tz else naive.isoformat()


def _single(start, end, zone) -> dict:
    """a one-off: dates as they are, zoned times on wall time in zone (kept as sent with none)"""
    from services.calendar_events import wall_pair

    if not isinstance(start, tuple):
        last = (end - timedelta(days=1)).isoformat() if end is not None else None
        return {
            **_EMPTY,
            "recur_except": [],
            "start_dt": start.isoformat(),
            "end_dt": last,
            "all_day": True,
        }
    s_iso, e_iso = _iso(start), (_iso(end) if end else None)
    if zone is not None:
        s_iso, e_iso = wall_pair(s_iso, e_iso, zone)
    return {**_EMPTY, "recur_except": [], "start_dt": s_iso, "end_dt": e_iso, "all_day": False}


def _in(value, tz):
    """a parsed time as naive wall time in tz (a floating one is taken as already there)"""
    naive, own = value
    if own is None or tz is None:
        return naive
    return naive.replace(tzinfo=own).astimezone(tz).replace(tzinfo=None)


# how far to compare two ways of storing a series: long enough for every daylight saving change
# to land on it (a yearly date sits on each side of a change some years, so 28 of them)
_COMPARE = {"daily": 731, "weekly": 1100, "monthly": 3700, "yearly": 10230}


def _instants(row: dict, tz, cutoff: datetime) -> list:
    """the utc moments a stored series shows before cutoff, read in tz (skipped days aside)"""
    from services.recur import expand

    start = datetime.fromisoformat(row["start_dt"]).replace(tzinfo=None)
    probe = {**row, "start_dt": start.isoformat(), "recur_except": []}
    days = (cutoff - start.replace(tzinfo=UTC)).days + 2
    hits = expand(probe, start - timedelta(days=1), start + timedelta(days=days), cap=800)
    out = [h.replace(tzinfo=tz).astimezone(UTC) for h in hits]
    return [h for h in out if h < cutoff]


def _zoned(fields: dict, first: datetime, stop, src, zone):
    """how a zoned series is stored: as wall time in the owner's zone when that shows every time
    where the source does, else in the source's offset when that's fixed (utc, tokyo), else in
    the source's own IANA zone: the rule repeats there and each time is read in the owner's
    (london seen from toronto, a week a year apart). only a zone the file describes itself with
    no IANA name stays as close as it gets. returns (row, days its dates moved)"""
    from services.calendar_events import follow_date, wall_pair

    aware = first.replace(tzinfo=src)
    after = stop.replace(tzinfo=src) if stop else None
    fixed = timezone(aware.utcoffset())
    kept = {
        **fields,
        "start_dt": aware.astimezone(fixed).isoformat(),
        "end_dt": after.astimezone(fixed).isoformat() if after else None,
    }
    named = src.key if isinstance(src, ZoneInfo) else ""
    span = _COMPARE[fields["recurrence"]] * fields["recur_interval"]
    cutoff = aware.astimezone(UTC) + timedelta(days=min(span, 36600))
    local = {**fields, "start_dt": first.isoformat()}
    source = set(_instants(local, src, cutoff))
    wall, shift = None, 0
    if zone is not None:
        w_start, w_end = wall_pair(aware.isoformat(), after.isoformat() if after else None, zone)
        shift = (date.fromisoformat(w_start[:10]) - first.date()).days
        wall = follow_date(
            {**fields, "start_dt": w_start, "end_dt": w_end},
            shift,
            keys=("recur_byday", "recur_until"),
        )
        if named and named == getattr(zone, "key", None):
            return wall, shift
        if source == set(_instants(wall, zone, cutoff)):
            return wall, shift
    if src is UTC or named in ("UTC", "Etc/UTC") or source == set(_instants(local, fixed, cutoff)):
        return kept, 0
    if named:
        return {
            **fields,
            "start_dt": aware.isoformat(),
            "end_dt": after.isoformat() if after else None,
            "source_zone": named,
        }, 0
    if wall is None:
        return kept, 0  # never the source's wall time read as if it were the owner's
    w_miss = len(source ^ set(_instants(wall, zone, cutoff)))
    f_miss = len(source ^ set(_instants(local, fixed, cutoff)))
    return (kept, 0) if f_miss < w_miss else (wall, shift)


def _place(ev: dict, zone, zones: _Zones) -> dict:
    """the rows one master VEVENT becomes, and how to name its days for EXDATE and RECURRENCE-ID"""
    base = {
        "title": ev["title"],
        "description": ev["description"],
        "location": ev["location"],
        "ics_uid": ev["uid"] or None,
        "ics_rid": None,
    }
    start, end = ev["start"], ev["end"]
    repeats = bool(ev["rrules"] or ev["odd"])
    rule = _rule(ev, zones) if repeats else None
    placed = {"title": ev["title"], "start": start, "series": None, "single": None, "day": None}
    if rule is None:
        placed["single"] = {**base, **_single(start, end, zone)}
        return {**placed, "rows": [placed["single"]], "first_only": int(repeats)}

    timed = isinstance(start, tuple)
    src = start[1] if timed else None
    first = start[0] if timed else datetime.combine(start, time())
    stop = None
    if end is not None:
        stop = _in(end, src) if timed else datetime.combine(end - timedelta(days=1), time())
    last = None
    if isinstance(rule["until"], tuple):
        naive, own = rule["until"]
        if not timed and own is not None and zone is not None:
            last = naive.replace(tzinfo=own).astimezone(zone).date()  # outlook's local midnight
        elif not timed:
            last = naive.date()
        else:
            naive = _in(rule["until"], src) if src else naive
            last = (
                naive.date() if naive.time() >= first.time() else naive.date() - timedelta(days=1)
            )
    elif rule["until"] is not None:
        last = rule["until"]
    count, extra = rule["count"], False
    if rule["byday"]:
        days = {_DAYS.index(d) for d in rule["byday"].split(",")}
        if first.weekday() not in days:
            # RFC counts DTSTART as the first time even off the rule's days: it stays a one-off
            moved = _first_weekly(first, rule["interval"], days)
            stop = stop + (moved - first) if stop else None
            first, extra = moved, True
            count = count - 1 if count else count
    if count == 0 or (last and last < first.date()):
        # nothing repeats after the first time
        placed["single"] = {**base, **_single(start, end, zone)}
        return {**placed, "rows": [placed["single"]], "first_only": 0}
    fields = {
        "recurrence": rule["recurrence"],
        "recur_interval": rule["interval"],
        "recur_byday": rule["byday"],
        "recur_count": count,
        "recur_until": last.isoformat() if last else None,
        "recur_except": [],
    }
    if not timed:
        row = {**fields, "start_dt": first.date().isoformat(), "all_day": True}
        row["end_dt"] = stop.date().isoformat() if stop else None
        shift = 0
    elif src is None:
        row = {**fields, "start_dt": first.isoformat(), "all_day": False}
        row["end_dt"] = stop.isoformat() if stop else None
        shift = 0
    else:
        row, shift = _zoned(fields, first, stop, src, zone)
        row["all_day"] = False

    def day(value):
        """the stored day of a skipped or moved time: its date where the series was written,
        moved as the rule's days were. read in the owner's zone instead, a time near midnight
        lands a day off in the week the two zones change their clocks apart"""
        if not isinstance(value, tuple):
            return value + timedelta(days=shift)
        local = _in(value, src) if src and value[1] else value[0]
        return local.date() + timedelta(days=shift)

    series = {**base, **row}
    series["recur_except"] = sorted({day(v).isoformat() for v in ev["exdates"]})
    placed.update(series=series, day=day)
    rows = [series]
    if extra:
        placed["single"] = {**base, **_single(start, end, zone)}
        rows.insert(0, placed["single"])
    return {**placed, "rows": rows, "first_only": 0}


def _rid(value) -> str:
    """a RECURRENCE-ID as one stored string: the moment in utc, or the date"""
    if not isinstance(value, tuple):
        return value.isoformat()
    naive, own = value
    return naive.replace(tzinfo=own).astimezone(UTC).isoformat() if own else naive.isoformat()


def _same(a, b) -> bool:
    if isinstance(a, tuple) and isinstance(b, tuple):
        if a[1] is not None and b[1] is not None:
            return a[0].replace(tzinfo=a[1]) == b[0].replace(tzinfo=b[1])
        return a[0] == b[0]
    as_day = lambda v: v[0].date() if isinstance(v, tuple) else v  # noqa: E731
    return as_day(a) == as_day(b)


_OWNER = object()


def read_ics(text: str, zone=_OWNER) -> dict:
    """the events of a calendar file, ready to store, with what an import needs to know: broken
    VEVENTs (no real start, an end that isn't a date, cut off before END), the closed VEVENT
    blocks, and series kept at their first time only.

    zoned times land on wall time in `zone` (default: the timezone setting), so a 19:00Z meeting
    from google doesn't show at 19:00 local. with no zone to go by they keep their offset, which
    every reader converts; a guessed server zone (utc in a container) would move them for good.
    a moved or cancelled time of a series (RECURRENCE-ID) is skipped in the series, and a moved
    one is its own event. a cancelled series is left out. uids and rids name what the file holds
    (UIDs with their main VEVENT, and (UID, RECURRENCE-ID) pairs), so an import can replace it"""
    from services.calendar_events import write_zone

    if zone is _OWNER:
        zone = write_zone()
    root = _tree(text)
    zones = _Zones(root)
    out = {"events": [], "broken": 0, "blocks": 0, "first_only": 0, "uids": set(), "rids": set()}
    masters, moved = {}, []
    for comp in _walk(root, "VEVENT"):
        if not comp["closed"]:
            out["broken"] += 1
            continue
        out["blocks"] += 1
        ev = _read_event(comp, zones)
        if ev is None:
            out["broken"] += 1
            continue
        out["broken"] += ev["bad_end"]
        if ev["rid"] is not None:
            moved.append(ev)
            if ev["uid"]:
                out["rids"].add((ev["uid"], _rid(ev["rid"])))
            continue
        if ev["uid"]:
            out["uids"].add(ev["uid"])
        if ev["status"] == "CANCELLED":
            continue  # a cancelled series or event isn't on the calendar
        placed = _place(ev, zone, zones)
        out["first_only"] += placed["first_only"]
        out["events"] += placed["rows"]
        if ev["uid"]:
            masters[ev["uid"]] = placed
    dropped = []
    for ev in moved:
        master = masters.get(ev["uid"])
        if master and master["single"] is not None and _same(ev["rid"], master["start"]):
            dropped.append(master["single"])  # the first time itself moved
        elif master and master["series"] is not None:
            skip = master["day"](ev["rid"]).isoformat()
            if skip not in master["series"]["recur_except"]:
                master["series"]["recur_except"] = sorted([*master["series"]["recur_except"], skip])
        if ev["status"] != "CANCELLED":
            title = ev["title"] or (master or {}).get("title", "")
            out["events"].append(
                {
                    "title": title,
                    "description": ev["description"],
                    "location": ev["location"],
                    "ics_uid": ev["uid"] or None,
                    "ics_rid": _rid(ev["rid"]),
                    **_single(ev["start"], ev["end"], zone),
                }
            )
    out["events"] = [row for row in out["events"] if not any(row is d for d in dropped)]
    return out


def parse_ics(text: str, zone=_OWNER) -> list[dict]:
    """the events of a calendar file, ready to store (see read_ics)"""
    return read_ics(text, zone)["events"]
