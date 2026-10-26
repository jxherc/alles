"""repeating events through .ics: a series goes out as one RRULE with its skipped days and comes
back as the same series, in the owner's zone, a kept offset or as dates, and what alles can't
show keeps its first time with a count for the import receipt."""

import re
import unittest
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from core.database import CalendarEvent
from services import ics
from services.calendar_events import occurrence_starts
from tests._client import ApiTest

TOR = ZoneInfo("America/Toronto")
TOKYO = ZoneInfo("Asia/Tokyo")
WINDOW = (datetime(2026, 1, 1), datetime(2029, 1, 1))

try:  # an independent RFC 5545 reading of what goes out, when the venv happens to have it
    from dateutil.rrule import rrulestr
except ImportError:  # pragma: no cover
    rrulestr = None


def row(**fields):
    return {
        "id": fields.pop("id", "x"),
        "title": fields.pop("title", "x"),
        "all_day": False,
        "end_dt": None,
        "recurrence": "",
        "recur_interval": 1,
        "recur_byday": "",
        "recur_count": None,
        "recur_until": None,
        "recur_except": [],
        **fields,
    }


def moments(event, viewer=TOR):
    """what a viewer in `viewer` sees: utc instants, or dates for an all-day series"""
    seen = occurrence_starts(event, *WINDOW, viewer, cap=5000)
    if event.get("all_day"):
        return [s.date() for s in seen]
    return [s.replace(tzinfo=viewer).astimezone(UTC) for s in seen]


def vevents(text):
    unfolded = text.replace("\r\n ", "")
    return re.findall(r"BEGIN:VEVENT\r\n(.*?)END:VEVENT", unfolded, re.S)


def prop(block, name):
    return next(
        (line for line in block.split("\r\n") if line.split(":")[0].split(";")[0] == name), ""
    )


SERIES = {
    "daily": row(
        start_dt="2026-03-02T07:30:00", end_dt="2026-03-02T08:00:00", recurrence="daily",
        recur_interval=2, recur_count=40,
    ),
    "weekly": row(
        start_dt="2026-10-27T09:00:00", end_dt="2026-10-27T09:15:00", recurrence="weekly",
        recur_byday="MO,WE,FR", recur_interval=2, recur_until="2027-03-31",
        recur_except=["2026-11-04"],
    ),
    "monthly_31st": row(
        start_dt="2026-01-31T18:00:00", recurrence="monthly", recur_count=14
    ),
    "monthly_30th": row(
        start_dt="2026-01-30T18:00:00", recurrence="monthly", recur_until="2027-06-30"
    ),
    "yearly_feb_29": row(start_dt="2028-02-29T10:00:00", recurrence="yearly"),
    "all_day_monthly": row(
        start_dt="2026-01-31", end_dt="2026-02-01", all_day=True, recurrence="monthly",
        recur_count=12, recur_except=["2026-04-30"],
    ),
    "all_day_yearly": row(start_dt="2026-05-01", all_day=True, recurrence="yearly"),
}  # fmt: skip


class RepeatsGoOutAsRulesTest(unittest.TestCase):
    def test_each_frequency_goes_out_as_one_rule(self):
        text = ics.to_ics([{**e, "id": k} for k, e in SERIES.items()], zone=TOR)
        blocks = {re.search(r"UID:(\S+)@alles", b).group(1): b for b in vevents(text)}
        self.assertEqual(len(blocks), len(SERIES))
        want = {
            "daily": "RRULE:FREQ=DAILY;INTERVAL=2;COUNT=40",
            "weekly": "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR;WKST=MO;UNTIL=20270401T035959Z",
            "monthly_31st": "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1;COUNT=14",
            "monthly_30th": "RRULE:FREQ=MONTHLY;BYMONTHDAY=30,-1;BYSETPOS=1;UNTIL=20270701T035959Z",
            "yearly_feb_29": "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29,-1;BYSETPOS=1",
            "all_day_monthly": "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1;COUNT=12",
            "all_day_yearly": "RRULE:FREQ=YEARLY",
        }
        for key, rule in want.items():
            with self.subTest(key=key):
                self.assertEqual(prop(blocks[key], "RRULE"), rule)
        # times carry the owner's zone; the weekly series starts on its first real day (a tuesday
        # start with mo/we/fr days is first seen wednesday)
        self.assertEqual(
            prop(blocks["weekly"], "DTSTART"), "DTSTART;TZID=America/Toronto:20261028T090000"
        )
        self.assertEqual(
            prop(blocks["weekly"], "EXDATE"), "EXDATE;TZID=America/Toronto:20261104T090000"
        )
        self.assertEqual(prop(blocks["all_day_monthly"], "DTSTART"), "DTSTART;VALUE=DATE:20260131")
        self.assertEqual(prop(blocks["all_day_monthly"], "DTEND"), "DTEND;VALUE=DATE:20260202")
        self.assertEqual(prop(blocks["all_day_monthly"], "EXDATE"), "EXDATE;VALUE=DATE:20260430")
        self.assertEqual(text.count("BEGIN:VTIMEZONE"), 1)
        self.assertTrue(all(len(line.encode()) <= 75 for line in text.split("\r\n")))

    def test_every_frequency_round_trips(self):
        text = ics.to_ics(list(SERIES.values()), zone=TOR)
        back = ics.read_ics(text, zone=TOR)
        self.assertEqual((back["first_only"], back["broken"]), (0, 0))
        for (key, sent), got in zip(SERIES.items(), back["events"], strict=True):
            with self.subTest(key=key):
                self.assertEqual(got["recurrence"], sent["recurrence"])
                self.assertEqual(moments(got), moments(sent))
        weekly = back["events"][1]
        self.assertEqual(
            (weekly["recur_byday"], weekly["recur_until"], weekly["recur_except"]),
            ("MO,WE,FR", "2027-03-31", ["2026-11-04"]),
        )

    def test_with_no_zone_known_times_float(self):
        from unittest.mock import patch

        with patch("services.calendar_events.load_settings", return_value={}):
            text = ics.to_ics([SERIES["weekly"]])
        block = vevents(text)[0]
        self.assertEqual(prop(block, "DTSTART"), "DTSTART:20261028T090000")
        self.assertIn("UNTIL=20270331T235959", prop(block, "RRULE"))
        self.assertEqual(prop(block, "EXDATE"), "EXDATE:20261104T090000")
        self.assertNotIn("VTIMEZONE", text)

    def test_a_series_with_nothing_left_stays_out(self):
        gone = row(start_dt="2026-10-27T09:00:00", recurrence="weekly", recur_count=0)
        self.assertEqual(vevents(ics.to_ics([gone], zone=TOR)), [])


class KeptOffsetSeriesTest(unittest.TestCase):
    """a row that kept its offset repeats in that offset's frame and goes out in utc"""

    def test_its_days_move_onto_utcs(self):
        monday = row(
            start_dt="2026-11-02T08:00:00+09:00", end_dt="2026-11-02T09:00:00+09:00",
            recurrence="weekly", recur_byday="MO", recur_except=["2026-11-16"],
        )  # fmt: skip
        block = vevents(ics.to_ics([monday], zone=TOR))[0]
        # monday 08:00 in tokyo is sunday 23:00 utc
        self.assertEqual(prop(block, "DTSTART"), "DTSTART:20261101T230000Z")
        self.assertEqual(prop(block, "RRULE"), "RRULE:FREQ=WEEKLY;BYDAY=SU")
        self.assertEqual(prop(block, "EXDATE"), "EXDATE:20261115T230000Z")
        for owner in (TOR, TOKYO, ZoneInfo("Europe/Berlin")):
            with self.subTest(owner=owner.key):
                back = ics.parse_ics(ics.to_ics([monday], zone=owner), zone=owner)
                self.assertEqual(moments(back[0], owner), moments(monday, owner))

    def test_a_rule_utc_cant_say_goes_out_in_its_own_offset(self):
        for kept in (
            # every other week on two days: utc's monday would split them
            row(start_dt="2026-11-02T08:00:00+09:00", recurrence="weekly", recur_byday="MO,TU",
                recur_interval=2),
            # the 31st at 08:00 in tokyo is the 30th (or the 28th) in utc
            row(start_dt="2026-01-31T08:00:00+09:00", recurrence="monthly"),
        ):  # fmt: skip
            with self.subTest(rule=kept["recurrence"]):
                text = ics.to_ics([kept], zone=TOR)
                self.assertIn("DTSTART;TZID=Etc/GMT-9:", prop(vevents(text)[0], "DTSTART"))
                self.assertIn("TZID:Etc/GMT-9", text)
                back = ics.parse_ics(text, zone=TOR)
                self.assertEqual(moments(back[0]), moments(kept))


@unittest.skipIf(rrulestr is None, "dateutil isn't installed")
class RulesReadTheSameElsewhereTest(unittest.TestCase):
    """what goes out, read by another RFC 5545 implementation, shows the same times alles does"""

    def other_reading(self, text):
        block = vevents(text)[0]
        head, value = prop(block, "DTSTART").split(":")
        tzid = dict(p.split("=") for p in head.split(";")[1:]).get("TZID")
        start = datetime.strptime(value[:15], "%Y%m%dT%H%M%S" if "T" in value else "%Y%m%d")
        if value.endswith("Z"):
            start = start.replace(tzinfo=UTC)
        elif tzid:
            start = start.replace(tzinfo=ZoneInfo(tzid))
        skipped = set()
        line = prop(block, "EXDATE")
        for stamp in line.split(":", 1)[1].split(",") if line else []:
            when = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S")
            skipped.add(when.replace(tzinfo=UTC if stamp.endswith("Z") else start.tzinfo))
        rule = rrulestr(prop(block, "RRULE"), dtstart=start)
        stop = datetime(2029, 1, 1, tzinfo=start.tzinfo)
        return [t.astimezone(UTC) for t in rule.between(start, stop, inc=True) if t not in skipped]

    def test_timed_series(self):
        for key in ("daily", "weekly", "monthly_31st", "monthly_30th", "yearly_feb_29"):
            for sent in (
                SERIES[key],
                {**SERIES[key], "start_dt": SERIES[key]["start_dt"] + "+05:30"},
            ):
                with self.subTest(key=key, start=sent["start_dt"]):
                    seen = [m for m in moments(sent) if m >= datetime(2026, 1, 1, tzinfo=UTC)]
                    other = self.other_reading(ics.to_ics([sent], zone=TOR))
                    self.assertEqual(other[: len(seen)], seen)
                    self.assertEqual(len(other), len(seen))


class ZonesTest(unittest.TestCase):
    def test_a_vtimezone_describes_the_zone_across_daylight_saving(self):
        for key in ("America/Toronto", "Europe/Berlin", "Australia/Sydney", "Asia/Kolkata"):
            zone = ZoneInfo(key)
            lo, hi = datetime(2026, 1, 1), datetime(2028, 1, 1)
            block = "\r\n".join(ics._vtimezone("Custom", zone, lo, hi))
            # read back as a zone of its own, under a name nothing else knows
            text = f"BEGIN:VCALENDAR\r\n{block}\r\nEND:VCALENDAR"
            defined = ics._Zones(ics._tree(text)).get("Custom")
            with self.subTest(zone=key):
                self.assertIsNotNone(defined)
                at = datetime(2026, 1, 1, tzinfo=UTC)
                while at < datetime(2031, 1, 1, tzinfo=UTC):  # past hi too: the rules stay open
                    self.assertEqual(
                        at.astimezone(defined).utcoffset(), at.astimezone(zone).utcoffset()
                    )
                    wall = at.astimezone(zone).replace(tzinfo=None)
                    self.assertEqual(
                        wall.replace(tzinfo=defined).utcoffset(),
                        wall.replace(tzinfo=zone).utcoffset(),
                    )
                    at += timedelta(hours=7)

    def test_a_weekly_meeting_keeps_its_time_across_the_autumn_change(self):
        series = row(start_dt="2026-10-20T09:00:00", recurrence="weekly", recur_count=4)
        text = ics.to_ics([series], zone=TOR)
        self.assertIn("TZOFFSETFROM:-0400\r\nTZOFFSETTO:-0500", text)
        back = ics.parse_ics(text, zone=TOR)[0]
        self.assertEqual(back["start_dt"], "2026-10-20T09:00:00")
        hours = [m.hour for m in moments(back)]
        self.assertEqual(hours, [13, 13, 14, 14])  # 09:00 edt, then 09:00 est
        # tokyo has no daylight saving, so neither its wall time nor a fixed offset follows
        # toronto's change: the series keeps toronto as its own zone and repeats there
        tokyo = ics.parse_ics(text, zone=TOKYO)[0]
        self.assertEqual(tokyo["start_dt"], "2026-10-20T09:00:00-04:00")
        self.assertEqual(tokyo["source_zone"], "America/Toronto")
        self.assertEqual(moments(tokyo, TOKYO), moments(back))


GOOGLE = """BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-TIMEZONE:America/Toronto
BEGIN:VTIMEZONE
TZID:America/Toronto
X-LIC-LOCATION:America/Toronto
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
DTSTART;TZID=America/Toronto:20260907T093000
DTEND;TZID=America/Toronto:20260907T100000
RRULE:FREQ=WEEKLY;WKST=SU;UNTIL=20261222T045959Z;BYDAY=MO,WE
EXDATE;TZID=America/Toronto:20261012T093000
DTSTAMP:20260901T120000Z
UID:standup123@google.com
DESCRIPTION:daily sync\\, short
SEQUENCE:0
STATUS:CONFIRMED
SUMMARY:standup
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:This is an event reminder
TRIGGER:-P0DT0H10M0S
END:VALARM
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Toronto:20260916T110000
DTEND;TZID=America/Toronto:20260916T113000
DTSTAMP:20260901T120000Z
UID:standup123@google.com
RECURRENCE-ID;TZID=America/Toronto:20260916T093000
SUMMARY:standup (moved)
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Toronto:20260921T093000
DTEND;TZID=America/Toronto:20260921T100000
UID:standup123@google.com
RECURRENCE-ID;TZID=America/Toronto:20260921T093000
STATUS:CANCELLED
SUMMARY:standup
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260501
DTEND;VALUE=DATE:20260502
RRULE:FREQ=YEARLY
UID:bday@google.com
SUMMARY:sam's birthday
END:VEVENT
END:VCALENDAR
"""

OUTLOOK = """BEGIN:VCALENDAR
METHOD:PUBLISH
PRODID:Microsoft Exchange Server 2010
VERSION:2.0
BEGIN:VTIMEZONE
TZID:W. Europe Standard Time
BEGIN:STANDARD
DTSTART:16010101T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:Customized Time Zone
BEGIN:STANDARD
DTSTART:16010101T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
DESCRIPTION:\\n
RRULE:FREQ=MONTHLY;UNTIL=20270615T080000Z;INTERVAL=1;BYMONTHDAY=15
UID:040000008200E00074C5B7101A82E00800000000
SUMMARY:review
DTSTART;TZID=W. Europe Standard Time:20260915T100000
DTEND;TZID=W. Europe Standard Time:20260915T110000
CLASS:PUBLIC
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
RRULE:FREQ=MONTHLY;COUNT=10;BYDAY=2TU
UID:040000008200E00074C5B7101A82E00800000001
SUMMARY:board meeting
DTSTART;TZID=Customized Time Zone:20260908T140000
DTEND;TZID=Customized Time Zone:20260908T150000
END:VEVENT
END:VCALENDAR
"""

APPLE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Apple Inc.//macOS 15.0//EN
CALSCALE:GREGORIAN
BEGIN:VTIMEZONE
TZID:Europe/London
BEGIN:DAYLIGHT
TZOFFSETFROM:+0000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
DTSTART:19810329T010000
TZNAME:BST
TZOFFSETTO:+0100
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0100
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
DTSTART:19961027T020000
TZNAME:GMT
TZOFFSETTO:+0000
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
CREATED:20260801T100000Z
UID:5F1C2A4B-1111-2222-3333-444455556666
DTEND;TZID=Europe/London:20260904T193000
RRULE:FREQ=WEEKLY;INTERVAL=2;UNTIL=20261231T235959Z
EXDATE;TZID=Europe/London:20261016T183000
TRANSP:OPAQUE
SUMMARY:climbing
DTSTART;TZID=Europe/London:20260904T183000
DTSTAMP:20260801T100000Z
SEQUENCE:0
END:VEVENT
BEGIN:VEVENT
UID:5F1C2A4B-1111-2222-3333-444455556667
DTSTART;TZID=Europe/London:20260905T090000
DTEND;TZID=Europe/London:20260905T100000
RRULE:FREQ=WEEKLY;BYDAY=SA
RDATE;TZID=Europe/London:20260910T090000
SUMMARY:parkrun
END:VEVENT
END:VCALENDAR
"""


class RealCalendarFilesTest(unittest.TestCase):
    def test_google(self):
        back = ics.read_ics(GOOGLE, zone=TOR)
        self.assertEqual((back["first_only"], back["broken"]), (0, 0))
        standup, birthday, moved = back["events"]
        self.assertEqual(
            (standup["title"], standup["description"]), ("standup", "daily sync, short")
        )  # the reminder's own description stays out
        self.assertEqual(
            (standup["start_dt"], standup["recurrence"], standup["recur_byday"]),
            ("2026-09-07T09:30:00", "weekly", "MO,WE"),
        )
        # 04:59:59 utc on the 22nd is 23:59:59 on the 21st in toronto: monday the 21st is the last
        self.assertEqual(standup["recur_until"], "2026-12-21")
        # the skipped day, the moved one and the cancelled one are all off the series
        self.assertEqual(standup["recur_except"], ["2026-09-16", "2026-09-21", "2026-10-12"])
        self.assertEqual(
            (moved["title"], moved["start_dt"], moved["recurrence"]),
            ("standup (moved)", "2026-09-16T11:00:00", ""),
        )
        self.assertEqual(
            (birthday["start_dt"], birthday["end_dt"], birthday["recurrence"]),
            ("2026-05-01", "2026-05-01", "yearly"),
        )
        days = [m.astimezone(TOR).date().isoformat() for m in moments(standup)]
        self.assertEqual(days[:4], ["2026-09-07", "2026-09-09", "2026-09-14", "2026-09-23"])
        self.assertEqual(days[-1], "2026-12-21")

    def test_outlook(self):
        back = ics.read_ics(OUTLOOK, zone=TOR)
        self.assertEqual((back["first_only"], back["broken"]), (1, 0))
        review, board = back["events"]
        # outlook's windows zone is berlin. the two zones change clocks on different weekends
        # (march 15th sits between them), so the series repeats in berlin and every time is
        # read in toronto
        self.assertEqual(
            (review["start_dt"], review["source_zone"], review["recurrence"]),
            ("2026-09-15T10:00:00+02:00", "Europe/Berlin", "monthly"),
        )
        self.assertEqual(review["recur_until"], "2027-06-15")
        berlin = [m.astimezone(ZoneInfo("Europe/Berlin")).hour for m in moments(review)]
        self.assertEqual(berlin, [10] * 10)  # sep 15 to jun 15
        # a monthly "2nd tuesday" is one alles can't show yet: its first time only, in a zone
        # the file describes itself
        self.assertEqual(
            (board["title"], board["recurrence"], board["start_dt"]),
            ("board meeting", "", "2026-09-08T08:00:00"),
        )

    def test_apple(self):
        back = ics.read_ics(APPLE, zone=ZoneInfo("Europe/London"))
        self.assertEqual((back["first_only"], back["broken"]), (1, 0))
        climbing, parkrun = back["events"]
        self.assertEqual(
            (climbing["start_dt"], climbing["recur_interval"], climbing["recur_until"]),
            ("2026-09-04T18:30:00", 2, "2026-12-31"),
        )
        self.assertEqual(climbing["recur_except"], ["2026-10-16"])
        # RDATE adds a day RRULE doesn't have: only the first time comes in
        self.assertEqual((parkrun["recurrence"], parkrun["start_dt"]), ("", "2026-09-05T09:00:00"))


def calendar(*blocks):
    return "BEGIN:VCALENDAR\r\n" + "".join(blocks) + "END:VCALENDAR\r\n"


def vevent(*lines, start="DTSTART:20260907T093000Z"):
    return (
        "BEGIN:VEVENT\r\nSUMMARY:x\r\n"
        + start
        + "\r\n"
        + "".join(f"{x}\r\n" for x in lines)
        + "END:VEVENT\r\n"
    )


class RulesAllesCantShowTest(unittest.TestCase):
    def test_they_keep_their_first_time(self):
        for rule in (
            "RRULE:FREQ=HOURLY;COUNT=5",
            "RRULE:FREQ=MONTHLY;BYDAY=-1FR",
            "RRULE:FREQ=MONTHLY;BYMONTHDAY=1,15",
            "RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
            "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=4TH",
            "RRULE:FREQ=WEEKLY;BYDAY=1MO",
            "RRULE:FREQ=WEEKLY;BYMONTH=6,7,8",
            "RRULE:FREQ=DAILY;INTERVAL=2;BYDAY=MO",
            "RRULE:FREQ=WEEKLY;INTERVAL=2;WKST=SU;BYDAY=SU,MO",
            "RRULE:FREQ=MONTHLY",  # from the 30th: RFC skips february, alles would move it
            "RRULE:FREQ=WEEKLY\r\nRDATE:20260920T093000Z",
            "RRULE:FREQ=WEEKLY\r\nEXRULE:FREQ=MONTHLY",
            "RRULE:FREQ=WEEKLY\r\nRRULE:FREQ=DAILY",
            "RRULE:FREQ=SOMETIMES",
        ):
            start = (
                "DTSTART:20260930T093000Z"
                if rule == "RRULE:FREQ=MONTHLY"
                else "DTSTART:20260907T093000Z"
            )
            with self.subTest(rule=rule):
                back = ics.read_ics(calendar(vevent(rule, start=start)), zone=TOR)
                self.assertEqual((back["first_only"], back["broken"]), (1, 0))
                (event,) = back["events"]
                self.assertEqual(event["recurrence"], "")
                self.assertEqual(
                    event["start_dt"][:10], start[8:12] + "-" + start[12:14] + "-" + start[14:16]
                )

    def test_ones_it_can_say_another_way_still_repeat(self):
        for rule, field in (
            ("RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR", ("weekly", "MO,TU,WE,TH,FR")),
            ("RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO,WE;INTERVAL=2", ("weekly", "MO,WE")),
            ("RRULE:FREQ=MONTHLY;BYMONTHDAY=7", ("monthly", "")),
            ("RRULE:FREQ=YEARLY;BYMONTH=9;BYMONTHDAY=7", ("yearly", "")),
            ("RRULE:FREQ=DAILY;BYHOUR=9;BYMINUTE=30", ("daily", "")),
        ):
            with self.subTest(rule=rule):
                back = ics.read_ics(calendar(vevent(rule)), zone=ZoneInfo("UTC"))
                (event,) = back["events"]
                self.assertEqual((event["recurrence"], event["recur_byday"]), field)
                self.assertEqual(back["first_only"], 0)

    def test_a_start_off_the_rules_days_is_its_own_first_time(self):
        # RFC counts DTSTART even on a tuesday when the rule says mondays
        text = calendar(
            vevent("RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=3", start="DTSTART:20260908T093000Z")
        )
        first, series = ics.read_ics(text, zone=ZoneInfo("UTC"))["events"]
        self.assertEqual((first["start_dt"], first["recurrence"]), ("2026-09-08T09:30:00", ""))
        self.assertEqual((series["start_dt"], series["recur_count"]), ("2026-09-14T09:30:00", 2))

    def test_until_reads_in_the_series_own_frame(self):
        cases = (
            # utc until after the time on the last day: that day is in
            (
                "DTSTART;TZID=America/Toronto:20260907T093000",
                "UNTIL=20260921T140000Z",
                "2026-09-21",
            ),
            # utc until before the time that day (09:00 toronto): the day before is the last
            (
                "DTSTART;TZID=America/Toronto:20260907T093000",
                "UNTIL=20260921T130000Z",
                "2026-09-20",
            ),
            # a floating until on a floating start is local already
            ("DTSTART:20260907T093000", "UNTIL=20260921T093000", "2026-09-21"),
            # a date until counts its whole day
            ("DTSTART;VALUE=DATE:20260907", "UNTIL=20260921", "2026-09-21"),
            # outlook's all-day until is local midnight in utc
            ("DTSTART;VALUE=DATE:20260907", "UNTIL=20260921T040000Z", "2026-09-21"),
        )
        for start, until, last in cases:
            with self.subTest(start=start, until=until):
                text = calendar(vevent(f"RRULE:FREQ=DAILY;{until}", start=start))
                (event,) = ics.read_ics(text, zone=TOR)["events"]
                self.assertEqual(event["recur_until"], last)

    def test_utc_series_keep_their_moments_for_an_owner_with_daylight_saving(self):
        # 14:00 utc every week is 10:00 in toronto's summer and 09:00 in its winter
        text = calendar(vevent("RRULE:FREQ=WEEKLY;COUNT=12", start="DTSTART:20261007T140000Z"))
        (event,) = ics.read_ics(text, zone=TOR)["events"]
        self.assertEqual(event["start_dt"], "2026-10-07T14:00:00+00:00")
        self.assertTrue(all(m.hour == 14 for m in moments(event)))
        # with no owner zone known the offset is kept as well
        (event,) = ics.read_ics(text, zone=None)["events"]
        self.assertEqual(event["start_dt"], "2026-10-07T14:00:00+00:00")


class ImportReceiptTest(ApiTest):
    def setUp(self):
        super().setUp()
        from core.settings import save_settings

        # a request's zone is remembered for background work; don't hand it to the next test
        self.addCleanup(save_settings, {"detected_timezone": ""})

    def test_the_import_says_how_many_kept_their_first_time(self):
        r = self.client.post(
            "/api/calendar/import",
            json={"ics": OUTLOOK},
            headers={"x-alles-time-zone": "America/Toronto"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"imported": 2, "first_only": 1})
        saved = {e["title"]: e for e in self.client.get("/api/calendar").json()}
        self.assertEqual(saved["review"]["recurrence"], "monthly")
        self.assertEqual(saved["board meeting"]["recurrence"], "")

    def test_overrides_and_skips_come_in_once(self):
        r = self.client.post(
            "/api/calendar/import",
            json={"ics": GOOGLE},
            headers={"x-alles-time-zone": "America/Toronto"},
        )
        self.assertEqual(r.json(), {"imported": 3, "first_only": 0})
        rows = {e["title"]: e for e in self.client.get("/api/calendar").json()}
        self.assertEqual(
            rows["standup"]["recur_except"], ["2026-09-16", "2026-09-21", "2026-10-12"]
        )
        self.assertEqual(rows["standup (moved)"]["start_dt"], "2026-09-16T11:00:00")

    def test_export_then_import_keeps_the_series(self):
        d = self.db()
        d.add(
            CalendarEvent(
                title="yoga", start_dt="2026-10-26T18:00:00", end_dt="2026-10-26T19:00:00",
                recurrence="weekly", recur_byday="MO,TH", recur_until="2026-12-31",
                recur_except='["2026-11-05"]',
            )
        )  # fmt: skip
        d.commit()
        d.close()
        tor = {"x-alles-time-zone": "America/Toronto"}
        self.client.get("/api/calendar", headers=tor)  # the owner's zone, seen once
        sent = self.client.get("/api/calendar/export.ics").text
        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=MO,TH;UNTIL=20270101T045959Z", sent)
        d = self.db()
        d.query(CalendarEvent).delete()
        d.commit()
        d.close()
        r = self.client.post("/api/calendar/import", json={"ics": sent}, headers=tor)
        self.assertEqual(r.json(), {"imported": 1, "first_only": 0})
        (back,) = self.client.get("/api/calendar").json()
        self.assertEqual(
            (back["start_dt"], back["recurrence"], back["recur_byday"], back["recur_until"]),
            ("2026-10-26T18:00:00", "weekly", "MO,TH", "2026-12-31"),
        )
        self.assertEqual(back["recur_except"], ["2026-11-05"])


class FeedRepeatsTest(ApiTest):
    def test_a_feed_shows_every_time_of_its_series(self):
        from unittest.mock import patch

        start = datetime.now(UTC).date() - timedelta(days=21)
        feed = calendar(
            vevent(
                "UID:gym@feed",
                "RRULE:FREQ=WEEKLY;COUNT=10",
                start=f"DTSTART:{start:%Y%m%d}T170000Z",
            )
        )
        with patch("routes.calendar.fetch_ics", return_value=feed):
            r = self.client.post(
                "/api/calendar/subscriptions",
                json={"name": "gym", "url": "https://example.com/gym.ics"},
            )
        self.assertEqual(r.status_code, 200, r.text)
        days = self.client.get("/api/calendar/agenda", params={"days": 60}).json()["days"]
        seen = [d["date"] for d in days for e in d["events"] if e["title"] == "x"]
        self.assertEqual(len(seen), 7)  # 10 weekly times from three weeks ago: 7 still ahead


def truth(zone, start, rule, skip=()):
    """an independent RFC reading: the rule repeated in its own zone, as utc instants"""
    first = datetime.fromisoformat(start).replace(tzinfo=ZoneInfo(zone))
    hits = rrulestr(f"RRULE:{rule}", dtstart=first).between(
        first, datetime(2028, 12, 31, tzinfo=UTC), inc=True
    )
    return [h.astimezone(UTC) for h in hits if h.astimezone(UTC) not in skip]


def zoned(zone, start, rule, *extra, end_minutes=60):
    first = datetime.fromisoformat(start)
    stamp = lambda w: f"{w:%Y%m%dT%H%M%S}"  # noqa: E731
    return vevent(
        f"DTEND;TZID={zone}:{stamp(first + timedelta(minutes=end_minutes))}",
        f"RRULE:{rule}",
        *extra,
        start=f"DTSTART;TZID={zone}:{stamp(first)}",
    )


@unittest.skipIf(rrulestr is None, "needs dateutil for the independent reading")
class SeriesFromAnotherZoneTest(unittest.TestCase):
    """a series written in a zone whose clocks change on other days than the owner's repeats in
    its own zone, and each time is read in the owner's"""

    def series(self, text, zone=TOR):
        rows = [r for r in ics.read_ics(text, zone=zone)["events"] if r["recurrence"]]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_rule_days_that_shift_across_midnight_are_checked(self):
        rule = "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TU,SU;COUNT=40"
        # sunday 21:00 in los angeles is monday 00:00 in toronto, a week later for the rule
        got = self.series(calendar(zoned("America/Los_Angeles", "2026-10-25T21:00", rule)))
        self.assertEqual(moments(got), truth("America/Los_Angeles", "2026-10-25T21:00", rule))

    def test_a_month_day_that_shifts_past_the_months_end(self):
        rule = "FREQ=MONTHLY;COUNT=14"
        got = self.series(calendar(zoned("America/Los_Angeles", "2026-10-28T21:00", rule)))
        want = truth("America/Los_Angeles", "2026-10-28T21:00", rule)
        self.assertEqual(moments(got), want)
        # february 28th 21:00 there is march 1st here, not the 28th or the 29th
        self.assertIn(datetime(2027, 3, 1, 5, tzinfo=UTC), want)

    def test_skipped_and_cancelled_times_stay_gone_around_daylight_saving(self):
        rule = "FREQ=WEEKLY;BYDAY=TU;UNTIL=20270601T000000Z"
        # london changed clocks a week before toronto: 04:30 tuesday is 00:30 tuesday here, not
        # monday 23:30 like every other week. the same in march, the other way round
        cancelled = "RECURRENCE-ID;TZID=Europe/London:20261027T043000"
        text = calendar(
            zoned("Europe/London", "2026-10-20T04:30", rule, "UID:ldn", "EXDATE:20270316T043000Z"),
            vevent("UID:ldn", "STATUS:CANCELLED", cancelled, start="DTSTART;TZID=Europe/London:20261027T043000"),
        )  # fmt: skip
        gone = {datetime(2026, 10, 27, 4, 30, tzinfo=UTC), datetime(2027, 3, 16, 4, 30, tzinfo=UTC)}
        got = self.series(text)
        self.assertEqual(moments(got), truth("Europe/London", "2026-10-20T04:30", rule, gone))
        self.assertEqual(len(ics.read_ics(text, zone=TOR)["events"]), 1)

    def test_zones_with_other_daylight_saving_dates(self):
        for zone in ("Europe/Berlin", "Australia/Sydney", "Pacific/Auckland", "America/Santiago"):
            for rule in ("FREQ=WEEKLY;BYDAY=MO,TH;COUNT=104", "FREQ=DAILY;INTERVAL=3;COUNT=150"):
                with self.subTest(zone=zone, rule=rule):
                    got = self.series(calendar(zoned(zone, "2026-10-01T09:00", rule)))
                    self.assertEqual(got["source_zone"], zone)
                    self.assertEqual(moments(got), truth(zone, "2026-10-01T09:00", rule))
                    # every viewer sees the same moments
                    self.assertEqual(moments(got, TOKYO), moments(got))

    def test_it_goes_back_out_in_its_own_zone(self):
        rule = "FREQ=WEEKLY;BYDAY=MO;UNTIL=20271231T230000Z"
        skip = "EXDATE;TZID=Europe/Berlin:20261130T090000"
        got = self.series(calendar(zoned("Europe/Berlin", "2026-10-05T09:00", rule, skip)))
        text = ics.to_ics([{**got, "id": "b", "title": "b"}], zone=TOR)
        self.assertIn("DTSTART;TZID=Europe/Berlin:20261005T090000", text)
        self.assertIn("EXDATE;TZID=Europe/Berlin:20261130T090000", text)
        self.assertIn("BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin", text)
        again = self.series(text)
        self.assertEqual(moments(again), moments(got))
        self.assertEqual(len(moments(got)), 64)

    def test_with_no_owner_zone_it_never_keeps_a_wall_time(self):
        rule = "FREQ=WEEKLY;BYDAY=MO;COUNT=30"
        got = self.series(calendar(zoned("Europe/Berlin", "2026-10-05T09:00", rule)), zone=None)
        self.assertEqual(
            (got["start_dt"], got["source_zone"]), ("2026-10-05T09:00:00+02:00", "Europe/Berlin")
        )
        for viewer in (TOR, TOKYO, None):
            seen = occurrence_starts(got, *WINDOW, viewer, cap=5000)
            # a naive time with no viewer is the server's own local time
            instants = [
                (s.replace(tzinfo=viewer) if viewer else s.astimezone()).astimezone(UTC)
                for s in seen
            ]
            self.assertEqual(instants, truth("Europe/Berlin", "2026-10-05T09:00", rule))


class ZoneNamesTest(unittest.TestCase):
    def test_central_asia_is_bishkek(self):
        text = calendar(vevent(start="DTSTART;TZID=Central Asia Standard Time:20261102T090000"))
        (got,) = ics.parse_ics(text, zone=None)
        self.assertEqual(got["start_dt"], "2026-11-02T09:00:00+06:00")

    def test_the_files_own_vtimezone_wins_over_a_name_alles_only_maps(self):
        def file(daylight_starts):
            return calendar(
                "BEGIN:VTIMEZONE\r\nTZID:Eastern Standard Time\r\n"
                "BEGIN:STANDARD\r\nDTSTART:16010101T020000\r\nTZOFFSETFROM:-0400\r\n"
                "TZOFFSETTO:-0500\r\nRRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11\r\nEND:STANDARD\r\n"
                "BEGIN:DAYLIGHT\r\nDTSTART:16010101T020000\r\nTZOFFSETFROM:-0500\r\n"
                f"TZOFFSETTO:-0400\r\nRRULE:FREQ=YEARLY;BYDAY={daylight_starts};BYMONTH=3\r\n"
                "END:DAYLIGHT\r\nEND:VTIMEZONE\r\n",
                vevent(start="DTSTART;TZID=Eastern Standard Time:20270320T090000"),
            )

        # the file says daylight saving starts on the last sunday of march, not the 2nd
        (own,) = ics.parse_ics(file("-1SU"), zone=None)
        self.assertEqual(own["start_dt"], "2027-03-20T09:00:00-05:00")
        (mapped,) = ics.parse_ics(file("2SU"), zone=None)
        self.assertEqual(mapped["start_dt"], "2027-03-20T09:00:00-04:00")

    def test_a_described_zone_knows_the_repeated_hour(self):
        text = calendar(
            "BEGIN:VTIMEZONE\r\nTZID:Custom\r\n"
            "BEGIN:STANDARD\r\nDTSTART:16010101T020000\r\nTZOFFSETFROM:-0400\r\n"
            "TZOFFSETTO:-0500\r\nRRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11\r\nEND:STANDARD\r\n"
            "BEGIN:DAYLIGHT\r\nDTSTART:16010101T020000\r\nTZOFFSETFROM:-0500\r\n"
            "TZOFFSETTO:-0400\r\nRRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3\r\nEND:DAYLIGHT\r\n"
            "END:VTIMEZONE\r\n"
        )
        custom = ics._Zones(ics._tree(text)).get("Custom")
        self.assertIsInstance(custom, ics._Defined)
        for utc in (
            datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
            datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
        ):
            local = utc.astimezone(custom)
            self.assertEqual(local.replace(tzinfo=None), datetime(2026, 11, 1, 1, 30))
            self.assertEqual(local.astimezone(UTC), utc)  # the second 01:30 stays the second
        self.assertEqual([custom.utcoffset(datetime(2026, 11, 1, 1, 30, fold=f)) for f in (0, 1)],
                         [timedelta(hours=-4), timedelta(hours=-5)])  # fmt: skip


class SmallFileQuirksTest(unittest.TestCase):
    def test_a_cancelled_series_stays_out(self):
        text = calendar(vevent("UID:gone", "STATUS:CANCELLED", "RRULE:FREQ=WEEKLY;COUNT=5"))
        self.assertEqual(ics.read_ics(text, zone=TOR)["events"], [])

    def test_an_all_day_end_on_its_start_is_that_day(self):
        text = calendar(vevent("DTEND;VALUE=DATE:20261102", start="DTSTART;VALUE=DATE:20261102"))
        (got,) = ics.parse_ics(text, zone=TOR)
        self.assertEqual((got["start_dt"], got["end_dt"]), ("2026-11-02", "2026-11-02"))

    def test_outlooks_empty_note_and_a_location(self):
        text = calendar(vevent("DESCRIPTION:\\n", "LOCATION:room 4\\, east wing"))
        (got,) = ics.parse_ics(text, zone=TOR)
        self.assertEqual((got["description"], got["location"]), ("", "room 4, east wing"))
        self.assertIn("LOCATION:room 4\\, east wing", ics.to_ics([{**got, "id": "l"}], zone=TOR))

    def test_far_off_years_still_export(self):
        rows = [
            row(start_dt="9999-12-30T10:00:00", end_dt="9999-12-30T11:00:00", id="a"),
            row(start_dt="9999-12-30T10:00:00", recurrence="weekly", id="b"),
            row(start_dt="0001-01-01T10:00:00", id="c"),
            row(start_dt="9999-12-30", end_dt="9999-12-31", all_day=True, id="d"),
            row(start_dt="9999-12-31T23:00:00-05:00", id="e"),
            row(start_dt="2026-11-02T09:00:00", id="ok"),
        ]
        for zone in (TOR, TOKYO, None):
            text = ics.to_ics(rows, zone=zone)
            self.assertIn("UID:ok@alles", text)


class ImportAgainTest(ApiTest):
    def setUp(self):
        super().setUp()
        from core.settings import save_settings

        self.addCleanup(save_settings, {"detected_timezone": ""})

    def test_the_same_file_twice_replaces_its_events(self):
        tor = {"x-alles-time-zone": "America/Toronto"}
        for _ in range(2):
            r = self.client.post("/api/calendar/import", json={"ics": GOOGLE}, headers=tor)
            self.assertEqual(r.json(), {"imported": 3, "first_only": 0})
        rows = self.client.get("/api/calendar").json()
        self.assertEqual(
            sorted(e["title"] for e in rows), ["sam's birthday", "standup", "standup (moved)"]
        )
        # a file with just a newer version of the moved time replaces only that time
        moved = GOOGLE.split("BEGIN:VEVENT")[2].split("END:VEVENT")[0].replace("T110000", "T120000")
        r = self.client.post(
            "/api/calendar/import",
            json={
                "ics": f"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT{moved}END:VEVENT\nEND:VCALENDAR"
            },
            headers=tor,
        )
        self.assertEqual(r.json()["imported"], 1)
        rows = {e["title"]: e for e in self.client.get("/api/calendar").json()}
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows["standup (moved)"]["start_dt"], "2026-09-16T12:00:00")
        self.assertEqual(rows["standup"]["recurrence"], "weekly")

    def test_a_far_off_year_is_refused_and_old_ones_still_export(self):
        r = self.client.post(
            "/api/calendar", json={"title": "x", "start_dt": "9999-12-30T10:00:00"}
        )
        self.assertEqual(
            (r.status_code, r.json()["detail"]), (400, "pick a year from 1900 to 2200")
        )
        d = self.db()
        d.add(CalendarEvent(title="old", start_dt="9999-12-30", end_dt="9999-12-31", all_day=True))
        d.add(CalendarEvent(title="older", start_dt="0001-01-01T10:00:00+09:00"))
        d.commit()
        d.close()
        self.assertEqual(self.client.get("/api/calendar/export.ics").status_code, 200)


class EditingASeriesFromAnotherZoneTest(ApiTest):
    def setUp(self):
        super().setUp()
        from core.settings import save_settings

        self.addCleanup(save_settings, {"detected_timezone": ""})
        self.tor = {"x-alles-time-zone": "America/Toronto"}
        text = calendar(zoned("Europe/Berlin", "2026-10-26T09:00", "FREQ=WEEKLY;BYDAY=MO;COUNT=30"))
        self.client.post("/api/calendar/import", json={"ics": text}, headers=self.tor)
        (self.event,) = self.client.get("/api/calendar").json()

    def days(self):
        """each time as toronto sees it, the way the agenda and the reminders read it"""
        (event,) = self.client.get("/api/calendar").json()
        seen = occurrence_starts(event, *WINDOW, TOR)
        return [(s.date().isoformat(), s.strftime("%H:%M")) for s in seen]

    def test_skip_one_time_and_rename(self):
        eid = self.event["id"]
        self.assertEqual(self.event["source_zone"], "Europe/Berlin")
        # berlin has changed its clocks, toronto not yet: 09:00 there is 04:00 here
        self.assertIn(("2026-10-26", "04:00"), self.days())
        self.client.delete(f"/api/calendar/{eid}?scope=this&occ=2026-10-26", headers=self.tor)
        self.client.patch(f"/api/calendar/{eid}", json={"title": "standup"}, headers=self.tor)
        (after,) = self.client.get("/api/calendar").json()
        self.assertEqual(
            (after["source_zone"], after["recur_except"]), ("Europe/Berlin", ["2026-10-26"])
        )
        self.assertEqual(self.days()[0], ("2026-11-02", "03:00"))
        self.assertEqual(len(self.days()), 29)

    def test_a_time_picked_here_makes_it_wall_time_here(self):
        eid = self.event["id"]
        body = {"start_dt": "2026-10-26T08:00:00", "end_dt": "2026-10-26T09:00:00"}
        r = self.client.patch(f"/api/calendar/{eid}", json=body, headers=self.tor)
        self.assertEqual((r.json()["start_dt"], r.json()["source_zone"]), (body["start_dt"], ""))
        self.assertEqual({t for _, t in self.days()}, {"08:00"})


class SeriesSourceMigrationTest(unittest.TestCase):
    def test_it_adds_the_columns_once_and_keeps_old_rows(self):
        from sqlalchemy import create_engine, text

        from core.migrations import m0075_calendar_series_source as m

        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            m.up(conn)  # no calendar yet: nothing to do
            conn.execute(text("CREATE TABLE calendar_events (id TEXT, start_dt TEXT)"))
            conn.execute(text("INSERT INTO calendar_events VALUES ('a', '2026-10-26T09:00:00')"))
            m.up(conn)
            m.up(conn)
            have = [r[1] for r in conn.execute(text("PRAGMA table_info(calendar_events)"))]
            row = conn.execute(text("SELECT * FROM calendar_events")).one()
        self.assertEqual(have, ["id", "start_dt", "source_zone", "ics_uid", "ics_rid"])
        self.assertEqual(tuple(row), ("a", "2026-10-26T09:00:00", None, None, None))
