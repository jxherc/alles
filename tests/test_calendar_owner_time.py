"""calendar times on a utc server for an owner in toronto: reminders, "today", quick add and
export all read the owner's wall clock (the timezone setting, else the last browser zone seen)."""

import asyncio
import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from core.database import CalendarEvent
from core.settings import save_settings
from services import cal_notify
from tests._client import ApiTest

TOR = ZoneInfo("America/Toronto")
TORONTO = {"x-alles-time-zone": "America/Toronto"}


class UtcServer(ApiTest):
    def setUp(self):
        super().setUp()
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        save_settings({"timezone": "", "detected_timezone": ""})
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()
        super().tearDown()


class OwnerTimeOnUtcServerTest(UtcServer):
    def fire(self):
        sent = []

        async def fake(payload):
            sent.append(payload["body"])
            return {"sent": 1, "uncertain": 0}

        with tempfile.TemporaryDirectory() as tmp:
            old = cal_notify._FIRES, cal_notify._fired, cal_notify._fired_path
            cal_notify._FIRES = Path(tmp) / "fires.json"
            cal_notify._fired = None
            try:
                with mock.patch("services.push_delivery.broadcast_result", fake):
                    asyncio.run(cal_notify.fire_due())
            finally:
                cal_notify._FIRES, cal_notify._fired, cal_notify._fired_path = old
        return sent

    def seed_due_events(self):
        # both start ten minutes from now, with a reminder ten minutes before: due right now
        soon = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=10)
        d = self.db()
        d.add(
            CalendarEvent(
                title="editor made",
                start_dt=soon.astimezone(TOR).replace(tzinfo=None).isoformat(),
                reminders="[10]",
            )
        )
        d.add(
            CalendarEvent(
                title="kept offset",
                start_dt=soon.strftime("%Y-%m-%dT%H:%M:%SZ"),
                reminders="[10]",
            )
        )
        d.commit()
        d.close()

    def test_reminders_fire_on_the_remembered_browser_zone(self):
        self.seed_due_events()
        # the server's clock is utc and nobody set a timezone: before a browser said where the
        # owner is, a toronto wall time can't be told from a utc one
        self.client.get("/api/calendar", headers=TORONTO)  # the calendar page remembers it
        fired = self.fire()
        self.assertEqual(
            sorted(body.split(" — ")[0] for body in fired), ["editor made", "kept offset"]
        )

    def test_reminders_fire_on_the_timezone_setting(self):
        save_settings({"timezone": "America/Toronto"})
        self.seed_due_events()
        fired = self.fire()
        self.assertEqual(
            sorted(body.split(" — ")[0] for body in fired), ["editor made", "kept offset"]
        )

    def test_agenda_and_quick_add_use_the_owners_day(self):
        today = datetime.now(TOR).date()
        self.client.post(
            "/api/calendar",
            json={"title": "late", "start_dt": f"{today.isoformat()}T23:30", "end_dt": None},
        )
        days = self.client.get("/api/calendar/agenda", params={"days": 2}, headers=TORONTO).json()[
            "days"
        ]
        self.assertEqual(days[0]["date"], today.isoformat())
        made = self.client.post(
            "/api/calendar/quick", json={"text": "lunch today 1pm"}, headers=TORONTO
        ).json()
        self.assertEqual(made["start_dt"], f"{today.isoformat()}T13:00")

    def test_search_dates_a_kept_offset_on_the_owners_day(self):
        self.client.post(
            "/api/calendar",
            json={"title": "zplate call", "start_dt": "2026-11-10T02:00:00Z", "end_dt": None},
        )
        hit = self.client.get("/api/search", params={"q": "zplate"}, headers=TORONTO).json()
        self.assertEqual(hit["calendar"][0]["when"], "2026-11-09")  # 21:00 the night before

    def test_timeline_reads_a_kept_offset(self):
        save_settings({"timezone": "America/Toronto"})
        when = (datetime.now(UTC) - timedelta(days=1)).replace(second=0, microsecond=0)
        d = self.db()
        d.add(CalendarEvent(title="kept offset", start_dt=when.isoformat()))
        d.commit()
        d.close()
        r = self.client.get("/api/timeline", params={"types": "calendar"})
        self.assertEqual(r.status_code, 200)
        row = next(ev for ev in r.json()["events"] if ev["title"] == "kept offset")
        self.assertEqual(row["subtitle"], when.astimezone(TOR).strftime("%H:%M"))

    def test_export_sends_wall_time_as_utc(self):
        self.client.post(
            "/api/calendar",
            json={"title": "local", "start_dt": "2026-11-10T10:00", "end_dt": "2026-11-10T11:00"},
        )
        self.client.post(
            "/api/calendar",
            json={"title": "zoned", "start_dt": "2026-11-10T20:00:00Z", "end_dt": None},
        )
        floating = self.client.get("/api/calendar/export.ics").text
        self.assertIn("DTSTART:20261110T100000\r\n", floating)  # nothing known: floating
        self.assertIn("DTSTART:20261110T200000Z\r\n", floating)
        self.client.get("/api/calendar", headers=TORONTO)
        sent = self.client.get("/api/calendar/export.ics").text
        # 10:00 in toronto in november is 15:00 utc. utc needs no VTIMEZONE, which a TZID does
        self.assertIn("DTSTART:20261110T150000Z\r\n", sent)
        self.assertIn("DTEND:20261110T160000Z\r\n", sent)
        self.assertIn("DTSTART:20261110T200000Z\r\n", sent)
        self.assertNotIn("TZID", sent)
        # a summer day keeps its own offset
        self.client.post(
            "/api/calendar",
            json={"title": "summer", "start_dt": "2026-07-01T10:00", "end_dt": None},
        )
        self.assertIn(
            "DTSTART:20260701T140000Z\r\n", self.client.get("/api/calendar/export.ics").text
        )
        from services.ics import parse_ics

        back = parse_ics(sent, zone=TOR)
        self.assertIn(("local", "2026-11-10T10:00:00"), [(e["title"], e["start_dt"]) for e in back])


def _zone_off_the_utc_date():
    """a zone whose date isn't utc's right now, so a server-date slip shows"""
    return ZoneInfo("Pacific/Kiritimati" if datetime.now(UTC).hour >= 10 else "Pacific/Pago_Pago")


class OwnerZoneEverywhereTest(UtcServer):
    def remember(self, zone):
        self.client.get("/api/calendar", headers={"x-alles-time-zone": zone.key})

    def test_background_today_uses_the_remembered_zone(self):
        from core import settings as core_settings
        from core.settings import load_settings
        from services import briefing, signals

        zone = _zone_off_the_utc_date()
        self.remember(zone)
        day = datetime.now(zone).date()
        self.assertNotEqual(day, datetime.now(UTC).date())
        self.assertEqual(signals.calendar_today(), day)
        d = self.db()
        d.add(CalendarEvent(title="owner today", start_dt=f"{day}T12:00", end_dt=f"{day}T13:00"))
        d.commit()
        lines = briefing.compose_briefing(d)["lines"]
        d.close()
        self.assertTrue(any("owner today" in line for line in lines), lines)
        line = core_settings._today_line(load_settings())
        self.assertIn(day.isoformat(), line)
        self.assertIn(zone.key, line)
        today = self.client.get("/api/today").json()
        self.assertEqual(today["date"], day.isoformat())
        self.assertIn("owner today", [e["title"] for e in today["events"]])

    def test_a_browser_saying_utc_keeps_the_zone_seen_before(self):
        from core.settings import load_settings

        self.client.get("/api/calendar", headers={"x-alles-time-zone": "UTC"})
        self.assertEqual(load_settings()["detected_timezone"], "UTC")  # nothing better known
        self.remember(ZoneInfo("Asia/Tokyo"))
        for name in ("UTC", "Etc/UTC", "Etc/GMT"):
            self.client.get("/api/calendar", headers={"x-alles-time-zone": name})
            self.assertEqual(load_settings()["detected_timezone"], "Asia/Tokyo")
        self.remember(ZoneInfo("Europe/London"))  # a real zone on utc's offset still counts
        self.assertEqual(load_settings()["detected_timezone"], "Europe/London")

    def test_timeline_compares_with_the_owners_clock(self):
        self.remember(TOR)
        now = datetime.now(TOR).replace(tzinfo=None, second=0, microsecond=0)
        for title, when in (
            ("ahead", now + timedelta(hours=2)),
            ("behind", now - timedelta(hours=2)),
        ):
            self.client.post(
                "/api/calendar",
                json={
                    "title": title,
                    "start_dt": when.isoformat(timespec="minutes"),
                    "end_dt": None,
                },
            )
        rows = self.client.get("/api/timeline", params={"types": "calendar", "days": 2}).json()
        titles = [row["title"] for row in rows["events"]]
        self.assertIn("behind", titles)
        self.assertNotIn("ahead", titles)  # utc now is 4-5 hours later than toronto's wall clock

    def test_title_edit_leaves_a_kept_offset_alone(self):
        tokyo = {"x-alles-time-zone": "Asia/Tokyo"}
        eid = self.client.post(
            "/api/calendar",
            json={
                "title": "z",
                "start_dt": "2026-10-27T19:30:00Z",
                "end_dt": "2026-10-27T20:30:00Z",
            },
        ).json()["id"]
        row = self.client.patch(
            f"/api/calendar/{eid}", json={"title": "renamed"}, headers=tokyo
        ).json()
        self.assertEqual(
            (row["start_dt"], row["end_dt"]), ("2026-10-27T19:30:00Z", "2026-10-27T20:30:00Z")
        )
        # the editor sends the untouched time back in its own format: still the same moment
        row = self.client.patch(
            f"/api/calendar/{eid}",
            json={"title": "again", "start_dt": "2026-10-28T04:30:00+09:00"},
            headers=tokyo,
        ).json()
        self.assertEqual(row["start_dt"], "2026-10-28T04:30:00+09:00")
        self.assertEqual(row["end_dt"], "2026-10-27T20:30:00Z")
        # a time picked in tokyo becomes tokyo wall time, start and end together
        row = self.client.patch(
            f"/api/calendar/{eid}", json={"start_dt": "2026-10-28T05:00:00"}, headers=tokyo
        ).json()
        self.assertEqual(
            (row["start_dt"], row["end_dt"]), ("2026-10-28T05:00:00", "2026-10-28T05:30:00")
        )

    def test_series_edit_and_exception_in_one_zone_mean_the_same_day_everywhere(self):
        toronto = {"x-alles-time-zone": "America/Toronto"}
        body = {
            "title": "late",
            "start_dt": "2026-10-20T23:30:00-04:00",
            "end_dt": "2026-10-21T00:30:00-04:00",
            "recurrence": "daily",
        }
        eid = self.client.post("/api/calendar", json=body).json()["id"]
        # a title change on one occurrence: the new event keeps its moment, nothing is rewritten
        # into tokyo's wall clock
        self.client.patch(
            f"/api/calendar/{eid}",
            params={"scope": "this", "occ": "2026-10-23"},
            json={"title": "late once"},
            headers=toronto,
        )
        rows = {e["title"]: e for e in self.client.get("/api/calendar").json()}
        once = datetime.fromisoformat(rows["late once"]["start_dt"])
        self.assertEqual(
            once.astimezone(TOR).replace(tzinfo=None).isoformat(), "2026-10-23T23:30:00"
        )
        # the series keeps its offset; the skipped day is named in that offset's own frame, so
        # every zone skips the same moment
        self.assertEqual(rows["late"]["start_dt"], "2026-10-20T23:30:00-04:00")
        self.assertEqual(rows["late"]["recur_except"], ["2026-10-23"])
        self.client.delete(
            f"/api/calendar/{eid}", params={"scope": "this", "occ": "2026-10-25"}, headers=toronto
        )
        row = next(e for e in self.client.get("/api/calendar").json() if e["id"] == eid)
        self.assertEqual(row["recur_except"], ["2026-10-23", "2026-10-25"])
        # with no zone known at all, a kept offset stays as it is
        other = self.client.post("/api/calendar", json=body).json()["id"]
        self.client.delete(f"/api/calendar/{other}", params={"scope": "this", "occ": "2026-10-25"})
        row = next(e for e in self.client.get("/api/calendar").json() if e["id"] == other)
        self.assertEqual(row["start_dt"], "2026-10-20T23:30:00-04:00")


class BookingWindowTest(UtcServer):
    def page(self, **kw):
        from core.database import BookingPage

        d = self.db()
        d.add(
            BookingPage(
                token="t1",
                duration_min=60,
                **{"work_start": 0, "work_end": 24, "days_ahead": 7, **kw},
            )
        )
        d.commit()
        d.close()

    def slots(self, day):
        return self.client.get("/book/t1/slots", params={"date": day.isoformat()}).json()["slots"]

    def test_slots_stay_inside_the_window_and_the_future(self):
        zone = _zone_off_the_utc_date()
        self.client.get("/api/calendar", headers={"x-alles-time-zone": zone.key})
        self.page()
        now = datetime.now(zone).replace(tzinfo=None)
        today = now.date()
        starts = [s["start"] for s in self.slots(today)]
        self.assertTrue(all(datetime.fromisoformat(s) > now for s in starts), starts[:3])
        self.assertEqual(self.slots(today - timedelta(days=1)), [])
        self.assertEqual(self.slots(today + timedelta(days=8)), [])
        tomorrow = self.slots(today + timedelta(days=1))
        self.assertEqual(
            (tomorrow[0]["start"][11:], tomorrow[-1]["start"][11:]), ("00:00", "23:00")
        )
        if now.hour:  # an hour already gone today can't be booked
            gone = f"{now.hour - 1:02d}:00"
            r = self.client.post(
                "/book/t1", json={"date": today.isoformat(), "time": gone, "name": "v"}
            )
            self.assertEqual(r.status_code, 409)
        page = self.client.get("/book/t1").text
        self.assertIn(f"dEl.value = dEl.min = '{today.isoformat()}'", page)
        self.assertIn(f"dEl.max = '{(today + timedelta(days=7)).isoformat()}'", page)

    def test_working_hours_run_to_24(self):
        made = self.client.post(
            "/api/calendar/booking-pages", json={"work_start": 20, "work_end": 24}
        )
        self.assertEqual(made.status_code, 200)
        for start, end in ((9, 25), (-1, 5), (12, 12), (24, 24)):
            r = self.client.post(
                "/api/calendar/booking-pages", json={"work_start": start, "work_end": end}
            )
            self.assertEqual(r.status_code, 400, (start, end))
            self.assertIn("working hours", r.json()["detail"])
        r = self.client.get("/api/calendar/free", params={"date": "2026-11-10", "work_end": 24})
        self.assertEqual(r.json()["slots"][-1]["end"], "2026-11-11T00:00")
        self.assertEqual(
            self.client.get(
                "/api/calendar/free", params={"date": "2026-11-10", "work_end": 30}
            ).status_code,
            400,
        )


class WritesKeepTheirMeaningTest(UtcServer):
    toronto = {"x-alles-time-zone": "America/Toronto"}

    def test_a_skipped_day_is_named_in_the_series_own_frame(self):
        made = self.client.post(
            "/api/calendar",
            json={
                "title": "sunday 9 in tokyo",
                "start_dt": "2026-11-01T09:00:00+09:00",
                "end_dt": "2026-11-01T10:00:00+09:00",
                "recurrence": "weekly",
                "recur_byday": "SU",
                "recur_until": "2026-12-27",
            },
        ).json()
        self.client.delete(
            f"/api/calendar/{made['id']}",
            params={"scope": "this", "occ": "2026-11-14"},
            headers=self.toronto,
        )
        row = next(e for e in self.client.get("/api/calendar").json() if e["id"] == made["id"])
        # the series keeps its tokyo frame; saturday the 14th in toronto is tokyo's sunday 15th
        self.assertEqual(row["start_dt"], "2026-11-01T09:00:00+09:00")
        self.assertEqual((row["recur_byday"], row["recur_until"]), ("SU", "2026-12-27"))
        self.assertEqual(row["recur_except"], ["2026-11-15"])
        days = self.client.get("/api/calendar/agenda", params={"days": 70}, headers=self.toronto)
        seen = [
            e["start_dt"] for d in days.json()["days"] for e in d["events"] if e["id"] == made["id"]
        ]
        self.assertNotIn("2026-11-14T19:00:00", seen)
        self.assertIn("2026-11-21T19:00:00", seen)
        # a monthly "1st" can't become "the last day" in toronto: that series keeps its offset
        monthly = self.client.post(
            "/api/calendar",
            json={**{k: made[k] for k in ("title", "start_dt", "end_dt")}, "recurrence": "monthly"},
        ).json()
        self.client.delete(
            f"/api/calendar/{monthly['id']}",
            params={"scope": "this", "occ": "2026-11-30"},
            headers=self.toronto,
        )
        row = next(e for e in self.client.get("/api/calendar").json() if e["id"] == monthly["id"])
        # the 30th in toronto is tokyo's december 1st: that's the day it skips, in every zone
        self.assertEqual(row["start_dt"], "2026-11-01T09:00:00+09:00")
        self.assertEqual(row["recur_except"], ["2026-12-01"])

    def test_an_all_day_date_never_moves_through_a_zone(self):
        for headers in (self.toronto, {}):
            made = self.client.post(
                "/api/calendar",
                json={
                    "title": "holiday",
                    "start_dt": "2026-11-12T00:00:00.000Z",
                    "end_dt": "2026-11-12T00:00:00.000Z",
                    "all_day": True,
                },
                headers=headers,
            ).json()
            self.assertEqual((made["start_dt"], made["end_dt"]), ("2026-11-12", "2026-11-12"))
        row = self.client.patch(
            f"/api/calendar/{made['id']}",
            json={"start_dt": "2026-11-13T00:00:00Z", "end_dt": "2026-11-13T00:00:00Z"},
            headers=self.toronto,
        ).json()
        self.assertEqual((row["start_dt"], row["end_dt"]), ("2026-11-13", "2026-11-13"))

    def test_a_settings_file_that_cant_be_saved_doesnt_fail_the_calendar(self):
        with mock.patch("core.settings.save_settings", side_effect=OSError("disk full")):
            r = self.client.get("/api/calendar", headers={"x-alles-time-zone": "Asia/Tokyo"})
        self.assertEqual(r.status_code, 200)

    def test_last_nights_events_still_block_this_morning(self):
        save_settings({"timezone": "America/Toronto"})
        day = datetime.now(TOR).date() + timedelta(days=2)
        night = day - timedelta(days=1)
        self.client.post(
            "/api/calendar",
            json={
                "title": "nightly",
                "start_dt": f"{night - timedelta(days=3)}T23:00",
                "end_dt": f"{night - timedelta(days=2)}T01:00",
                "recurrence": "daily",
            },
        )
        self.client.post(
            "/api/calendar",
            json={"title": "late once", "start_dt": f"{night}T22:00", "end_dt": f"{day}T02:00"},
        )
        free = self.client.get(
            "/api/calendar/free",
            params={"date": day.isoformat(), "work_start": 0, "work_end": 24, "minutes": 30},
        ).json()
        self.assertEqual(free["slots"][0]["start"], f"{day}T02:00")
        slots = self.client.get(
            "/api/calendar/free-slots",
            params={"day": day.isoformat(), "day_start": "00:00", "day_end": "23:59"},
        ).json()["slots"]
        self.assertEqual(slots[0]["start"], "02:00")
        from core.database import BookingPage

        d = self.db()
        d.add(BookingPage(token="night", duration_min=30, work_start=0, work_end=24, days_ahead=7))
        d.commit()
        d.close()
        booked = self.client.get("/book/night/slots", params={"date": day.isoformat()}).json()
        self.assertEqual(booked["slots"][0]["start"], f"{day}T02:00")
        r = self.client.post(
            "/book/night", json={"date": day.isoformat(), "time": "00:00", "name": "v"}
        )
        self.assertEqual(r.status_code, 409)

    def test_free_time_needs_a_length(self):
        for params in ({"minutes": 0}, {"minutes": -30}):
            r = self.client.get("/api/calendar/free", params={"date": "2026-11-10", **params})
            self.assertEqual(r.status_code, 400)
        r = self.client.get(
            "/api/calendar/free-slots", params={"day": "2026-11-10", "duration_min": 0}
        )
        self.assertEqual(r.status_code, 400)

    def test_the_booking_page_says_whose_clock_the_times_are_on(self):
        save_settings({"timezone": "Asia/Tokyo"})
        from core.database import BookingPage

        d = self.db()
        d.add(BookingPage(token="tz", duration_min=60, work_start=9, work_end=17, days_ahead=7))
        d.commit()
        d.close()
        page = self.client.get("/book/tz").text
        self.assertIn("times in Asia/Tokyo", page)
        self.assertIn("your time", page)  # a visitor elsewhere also sees their own clock
        day = (datetime.now(ZoneInfo("Asia/Tokyo")).date() + timedelta(days=1)).isoformat()
        slot = self.client.get("/book/tz/slots", params={"date": day}).json()["slots"][0]
        self.assertEqual(slot["at"], f"{day}T09:00:00+09:00")

    def test_a_repeat_kept_in_tokyo_reads_on_toronto_weekdays(self):
        self.client.post(
            "/api/calendar",
            json={
                "title": "sunday 9 in tokyo",
                "start_dt": "2026-11-01T09:00:00+09:00",
                "end_dt": "2026-11-01T10:00:00+09:00",
                "recurrence": "weekly",
                "recur_byday": "SU",
            },
        )
        from services import calendar_events

        d = self.db()
        row = calendar_events.event_dict(d.query(CalendarEvent).one())
        d.close()
        starts = calendar_events.occurrence_starts(
            row, datetime(2026, 10, 25), datetime(2026, 11, 15), TOR
        )
        # saturday evening every week in toronto, and an hour earlier once the clocks go back
        self.assertEqual(
            [s.isoformat() for s in starts],
            ["2026-10-31T20:00:00", "2026-11-07T19:00:00", "2026-11-14T19:00:00"],
        )

        def free_on(day):
            free = self.client.get(
                "/api/calendar/free",
                params={"date": day, "work_start": 18, "work_end": 22, "minutes": 60},
                headers=self.toronto,
            ).json()["slots"]
            return [(s["start"][11:], s["end"][11:]) for s in free]

        saturday, sunday = free_on("2026-11-07"), free_on("2026-11-08")
        self.assertEqual(saturday, [("18:00", "19:00"), ("20:00", "22:00")])
        self.assertEqual(sunday, [("18:00", "22:00")])

    def test_new_repeat_days_are_picked_in_the_browsers_zone(self):
        made = self.client.post(
            "/api/calendar",
            json={
                "title": "sunday 9 in tokyo",
                "start_dt": "2026-11-01T09:00:00+09:00",
                "end_dt": "2026-11-01T10:00:00+09:00",
                "recurrence": "weekly",
                "recur_byday": "SU",
                "recur_until": "2026-12-27",
            },
        ).json()
        # picked in toronto, where the occurrences show on saturdays: those are toronto days now
        row = self.client.patch(
            f"/api/calendar/{made['id']}", json={"recur_byday": "FR,SA"}, headers=self.toronto
        ).json()
        self.assertEqual(row["start_dt"], "2026-10-31T20:00:00")
        self.assertEqual(row["recur_byday"], "FR,SA")
        self.assertEqual(row["recur_until"], "2026-12-26")  # untouched: moved with the start


class QuickAddWeekdaysTest(UtcServer):
    def test_a_short_weekday_first_lands_on_that_day(self):
        from services.task_nl import _next_weekday

        today = datetime.now(TOR).date()  # calendar quick add reads the owner's today
        fri, sat = _next_weekday(today, 4), _next_weekday(today, 5)
        for text, start, title in (
            ("fri dinner 7pm", f"{fri}T19:00", "dinner"),
            ("sat brunch 11am", f"{sat}T11:00", "brunch"),
            ("dinner fri with sam", f"{fri}", "dinner with sam"),
        ):
            with self.subTest(text=text):
                made = self.client.post(
                    "/api/calendar/quick", json={"text": text}, headers=TORONTO
                ).json()
                self.assertEqual((made["start_dt"], made["title"]), (start, title))
        friday = "2026-10-23"
        task = self.client.post("/api/tasks/quick", json={"text": "mon standup", "today": friday})
        self.assertEqual((task.json()["due_date"], task.json()["title"]), ("2026-10-26", "standup"))
        task = self.client.post(
            "/api/tasks/quick", json={"text": "buy sun screen", "today": friday}
        )
        self.assertEqual((task.json()["due_date"], task.json()["title"]), (None, "buy sun screen"))
