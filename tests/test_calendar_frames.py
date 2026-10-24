"""a repeat stored with an offset repeats in that offset's own frame (its weekdays, weeks, month
day, last day and skipped days) and every reader shows the same moments in every zone."""

import os
import time
from datetime import UTC, date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from core.database import BookingPage, CalendarEvent
from core.settings import save_settings
from services import cal_notify, calendar_events, recur, signals
from tests._client import ApiTest

ZONES = [ZoneInfo("America/Toronto"), ZoneInfo("Asia/Tokyo"), ZoneInfo("America/Los_Angeles")]
TOR = {"x-alles-time-zone": "America/Toronto"}
TYO = {"x-alles-time-zone": "Asia/Tokyo"}
SERIES = {
    "tokyo_sun": dict(
        start_dt="2026-10-25T09:00:00+09:00",
        end_dt="2026-10-25T10:00:00+09:00",
        recurrence="weekly",
        recur_byday="SU",
        recur_until="2026-11-22",
        recur_except=["2026-11-08"],
    ),
    "la_mo_we": dict(
        start_dt="2026-10-26T20:00:00-07:00",
        end_dt="2026-10-26T21:00:00-07:00",
        recurrence="weekly",
        recur_byday="MO,WE",
        recur_count=6,
    ),
    "tor_biweekly": dict(
        start_dt="2026-10-29T23:30:00-04:00",
        end_dt="2026-10-30T00:30:00-04:00",
        recurrence="weekly",
        recur_interval=2,
        recur_byday="TH",
        recur_until="2026-12-24",
    ),
    "utc_z_mo": dict(
        start_dt="2026-10-26T02:00:00Z",
        end_dt="2026-10-26T03:00:00Z",
        recurrence="weekly",
        recur_byday="MO",
        recur_count=5,
        recur_except=["2026-11-02"],
    ),
    "tokyo_monthly_1st": dict(
        start_dt="2026-12-01T09:00:00+09:00",
        end_dt="2026-12-01T10:00:00+09:00",
        recurrence="monthly",
        recur_count=5,
    ),
    "tokyo_daily": dict(
        start_dt="2026-10-30T07:00:00+09:00",
        end_dt="2026-10-30T07:30:00+09:00",
        recurrence="daily",
        recur_until="2026-11-05",
        recur_except=["2026-11-02"],
    ),
    "tokyo_biweekly_mo_su": dict(
        start_dt="2026-10-26T08:00:00+09:00",
        end_dt="2026-10-26T09:00:00+09:00",
        recurrence="weekly",
        recur_interval=2,
        recur_byday="MO,SU",
        recur_count=6,
    ),
    "la_biweekly_sa_su": dict(
        start_dt="2026-10-24T18:00:00-07:00",
        end_dt="2026-10-24T19:00:00-07:00",
        recurrence="weekly",
        recur_interval=2,
        recur_byday="SA,SU",
        recur_count=6,
    ),
    "tokyo_1330_mo": dict(
        start_dt="2026-10-26T13:30:00+09:00",
        end_dt="2026-10-26T14:00:00+09:00",
        recurrence="weekly",
        recur_byday="MO",
        recur_count=4,
    ),
}
WINDOW = (datetime(2026, 10, 1), datetime(2027, 6, 1))


def truth(series):
    """the series expanded in its offset's own fixed frame, as utc moments"""
    start = datetime.fromisoformat(series["start_dt"])
    local = dict(series, start_dt=start.replace(tzinfo=None).isoformat())
    return [
        o.replace(tzinfo=start.tzinfo).astimezone(UTC)
        for o in recur.expand(local, datetime(2026, 1, 1), datetime(2028, 1, 1))
    ]


def moments(walls, zone):
    return [w.replace(tzinfo=zone).astimezone(UTC) for w in walls]


class FrameExpansionTest(ApiTest):
    def test_every_zone_sees_the_offsets_own_moments(self):
        for name, series in SERIES.items():
            for zone in ZONES:
                with self.subTest(series=name, zone=zone.key):
                    seen = calendar_events.occurrence_starts(series, *WINDOW, zone)
                    self.assertEqual(moments(seen, zone), truth(series))

    def test_a_wall_time_repeat_expands_as_it_always_has(self):
        naive = dict(
            start_dt="2026-10-26T09:00",
            end_dt="2026-10-26T10:00",
            recurrence="weekly",
            recur_interval=2,
            recur_byday="MO,TH",
            recur_except=["2026-11-05"],
            recur_until="2026-12-10",
        )
        for zone in (*ZONES, None):
            self.assertEqual(
                calendar_events.occurrence_starts(naive, *WINDOW, zone),
                recur.expand(naive, *WINDOW),
            )

    def test_readers_agree_with_the_frame(self):
        save_settings({"timezone": "", "detected_timezone": ""})
        made = {}
        for name in ("tokyo_sun", "tor_biweekly", "tokyo_monthly_1st", "tokyo_daily"):
            made[name] = self.client.post(
                "/api/calendar", json={"title": name, **SERIES[name]}
            ).json()
        days = self.client.get("/api/calendar/agenda", params={"days": 220}, headers=TOR).json()
        tor = ZoneInfo("America/Toronto")
        today = datetime.now(tor).replace(tzinfo=None)
        for name, row in made.items():
            with self.subTest(series=name):
                walls = [
                    datetime.fromisoformat(e["start_dt"])
                    for d in days["days"]
                    for e in d["events"]
                    if e["id"] == row["id"]
                ]
                want = [m for m in truth(SERIES[name]) if m.astimezone(tor).date() >= today.date()]
                self.assertEqual(moments(walls, tor), want)
        # the today widget and briefing land each occurrence on the right toronto day
        d = self.db()
        row = d.get(CalendarEvent, made["tokyo_sun"]["id"])
        landing = [
            day
            for day in (date(2026, 10, 24) + timedelta(days=i) for i in range(40))
            if signals._event_occurs_on(row, day, tor)
        ]
        d.close()
        self.assertEqual(
            [x.isoformat() for x in landing],
            ["2026-10-24", "2026-10-31", "2026-11-14", "2026-11-21"],
        )
        # free time is busy at 19:00 the saturday after the clocks went back, not at 20:00
        free = self.client.get(
            "/api/calendar/free",
            params={"date": "2026-11-14", "work_start": 18, "work_end": 21, "minutes": 60},
            headers=TOR,
        ).json()["slots"]
        self.assertEqual(
            [(s["start"][11:], s["end"][11:]) for s in free],
            [("18:00", "19:00"), ("20:00", "21:00")],
        )

    def test_a_reminder_fires_at_the_frames_moment_across_daylight_saving(self):
        save_settings({"timezone": "America/Toronto"})
        d = self.db()
        series = dict(SERIES["tokyo_sun"], recur_except='["2026-11-08"]')
        e = CalendarEvent(title="tokyo sunday", reminders="[10]", **series)
        d.add(e)
        d.commit()
        eid = e.id
        d.close()
        tor = ZoneInfo("America/Toronto")
        # sunday 09:00 in tokyo on the 15th is saturday 19:00 in toronto (est), not 20:00
        for clock, fires in (("2026-11-14T18:50", True), ("2026-11-14T19:50", False)):
            with (
                mock.patch.object(
                    calendar_events,
                    "owner_now",
                    lambda zone=None, c=clock: datetime.fromisoformat(c),
                ),
                mock.patch.object(calendar_events, "owner_zone", lambda *a, **k: tor),
            ):
                _, due = cal_notify._due_now(set())
            self.assertEqual(any(k.startswith(eid) for k, _ in due), fires, clock)
        save_settings({"timezone": ""})


class FrameWritesTest(ApiTest):
    def setUp(self):
        super().setUp()
        save_settings({"timezone": "", "detected_timezone": ""})

    def tearDown(self):
        save_settings({"timezone": "", "detected_timezone": ""})
        super().tearDown()

    def make(self, name, **extra):
        return self.client.post(
            "/api/calendar", json={"title": name, **SERIES[name], **extra}
        ).json()

    def row(self, eid):
        return next(e for e in self.client.get("/api/calendar").json() if e["id"] == eid)

    def walls(self, eid, headers):
        days = self.client.get("/api/calendar/agenda", params={"days": 220}, headers=headers).json()
        return [e["start_dt"][:16] for d in days["days"] for e in d["events"] if e["id"] == eid]

    def test_skipping_a_day_names_the_frames_day_and_keeps_the_series(self):
        weekly = self.make("tokyo_sun")
        self.client.delete(
            f"/api/calendar/{weekly['id']}",
            params={"scope": "this", "occ": "2026-11-14"},
            headers=TOR,
        )
        row = self.row(weekly["id"])
        self.assertEqual(row["start_dt"], "2026-10-25T09:00:00+09:00")
        self.assertEqual(row["recur_except"], ["2026-11-08", "2026-11-15"])
        self.assertNotIn("2026-11-15T09:00", self.walls(weekly["id"], TYO))
        monthly = self.make("tokyo_monthly_1st")
        self.client.delete(
            f"/api/calendar/{monthly['id']}",
            params={"scope": "this", "occ": "2026-11-30"},
            headers=TOR,
        )
        row = self.row(monthly["id"])
        self.assertEqual(
            (row["start_dt"], row["recur_except"]), ("2026-12-01T09:00:00+09:00", ["2026-12-01"])
        )
        self.assertNotIn("2026-12-01T09:00", self.walls(monthly["id"], TYO))

    def test_ending_a_series_names_the_frames_day(self):
        weekly = self.make("tokyo_sun")
        self.client.delete(
            f"/api/calendar/{weekly['id']}",
            params={"scope": "following", "occ": "2026-11-14"},
            headers=TOR,
        )
        self.assertEqual(self.row(weekly["id"])["recur_until"], "2026-11-14")
        self.assertEqual(
            self.walls(weekly["id"], TYO),
            [w for w in self.walls(weekly["id"], TYO) if w < "2026-11-15"],
        )
        self.assertIn("2026-11-01T09:00", self.walls(weekly["id"], TYO))

    def test_a_time_change_in_toronto_moves_every_day_of_the_rule(self):
        weekly = self.make("tokyo_sun")
        body = {
            k: SERIES["tokyo_sun"][k]
            for k in ("recurrence", "recur_byday", "recur_until", "recur_except")
        }
        row = self.client.patch(
            f"/api/calendar/{weekly['id']}",
            json={**body, "start_dt": "2026-10-24T21:00", "end_dt": "2026-10-24T22:00"},
            headers=TOR,
        ).json()
        self.assertEqual(
            (row["start_dt"], row["recur_byday"], row["recur_until"], row["recur_except"]),
            ("2026-10-24T21:00", "SA", "2026-11-21", ["2026-11-07"]),
        )

    def test_a_title_edit_and_a_copy_leave_the_moments_alone(self):
        weekly = self.make("tokyo_sun")
        row = self.client.patch(
            f"/api/calendar/{weekly['id']}", json={"title": "renamed"}, headers=TOR
        ).json()
        self.assertEqual({k: row[k] for k in SERIES["tokyo_sun"]}, SERIES["tokyo_sun"])
        copy = self.client.post(f"/api/calendar/{weekly['id']}/duplicate", headers=TOR).json()
        self.assertEqual(self.walls(copy["id"], TOR), self.walls(weekly["id"], TOR))

    def test_one_occurrence_edited_from_toronto(self):
        weekly = self.make("tokyo_sun")
        moved = self.client.patch(
            f"/api/calendar/{weekly['id']}",
            params={"scope": "this", "occ": "2026-10-31", "time_zone": "America/Toronto"},
            json={"title": "moved", "start_dt": "2026-10-31T18:00", "end_dt": "2026-10-31T19:00"},
            headers=TOR,
        ).json()
        self.assertEqual(moved["start_dt"], "2026-10-31T18:00")
        row = self.row(weekly["id"])
        self.assertEqual(
            (row["start_dt"], row["recur_except"]),
            (SERIES["tokyo_sun"]["start_dt"], ["2026-11-08", "2026-11-01"]),
        )

    def test_a_monthly_time_change_stays_in_its_frame(self):
        monthly = self.make("tokyo_monthly_1st")
        row = self.client.patch(
            f"/api/calendar/{monthly['id']}",
            params={"time_zone": "America/Toronto"},
            json={"start_dt": "2026-11-30T18:00", "end_dt": "2026-11-30T19:00"},
            headers=TOR,
        ).json()
        # 18:00 on the 30th in toronto is 08:00 on the 1st in tokyo: still "the 1st"
        self.assertEqual(
            (row["start_dt"], row["recurrence"]), ("2026-12-01T08:00:00+09:00", "monthly")
        )
        self.assertEqual(
            self.walls(monthly["id"], TYO)[:2], ["2026-12-01T08:00", "2027-01-01T08:00"]
        )

    def test_creating_with_a_zone_set_moves_every_day_of_the_rule(self):
        save_settings({"timezone": "America/Toronto"})
        row = self.make("tokyo_sun")
        self.assertEqual(
            (row["start_dt"], row["recur_byday"], row["recur_until"], row["recur_except"]),
            ("2026-10-24T20:00:00", "SA", "2026-11-21", ["2026-11-07"]),
        )


class BookingTimesTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        save_settings({"timezone": "America/Toronto", "detected_timezone": ""})
        d = self.db()
        d.add(BookingPage(token="b", duration_min=30, work_start=0, work_end=12, days_ahead=400))
        d.commit()
        d.close()

    def tearDown(self):
        save_settings({"timezone": "", "detected_timezone": ""})
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()
        super().tearDown()

    def test_times_must_be_plain_hours_and_minutes(self):
        day = (datetime.now(ZoneInfo("America/Toronto")).date() + timedelta(days=2)).isoformat()
        for bad in ("10:30x", "10:30Z", "11:00+09:00", "11:30:00.5", "25:00", "1", "10:00:00"):
            r = self.client.post("/book/b", json={"date": day, "time": bad, "name": "v"})
            self.assertEqual(
                (r.status_code, r.json()["detail"]), (400, "use a time like 09:30"), bad
            )

    def test_the_spring_forward_night_offers_no_missing_times(self):
        starts = [
            s["start"][11:]
            for s in self.client.get("/book/b/slots", params={"date": "2027-03-14"}).json()["slots"]
        ]
        self.assertNotIn("02:00", starts)
        self.assertNotIn("02:30", starts)
        self.assertIn("03:00", starts)
        r = self.client.post("/book/b", json={"date": "2027-03-14", "time": "02:30", "name": "v"})
        self.assertEqual(r.json()["detail"], "the clocks skip that time that night")

    def test_a_refusal_says_what_happened(self):
        day = (datetime.now(ZoneInfo("America/Toronto")).date() + timedelta(days=2)).isoformat()
        self.assertEqual(
            self.client.post(
                "/book/b", json={"date": day, "time": "10:00", "name": "a"}
            ).status_code,
            200,
        )
        cases = {
            "10:00": "that time was just taken",
            "12:00": "that isn't one of the times this page offers",
        }
        for when, why in cases.items():
            r = self.client.post("/book/b", json={"date": day, "time": when, "name": "b"})
            self.assertEqual((r.status_code, r.json()["detail"]), (409, why), when)
        far = (date.fromisoformat(day) + timedelta(days=500)).isoformat()
        r = self.client.post("/book/b", json={"date": far, "time": "10:00", "name": "b"})
        self.assertEqual(r.json()["detail"], "that date is outside the booking window")
        page = self.client.get("/book/b").text
        self.assertIn("why.detail", page)  # the visitor reads the reason, not always "taken"


class AllDayDatesTest(ApiTest):
    def test_an_all_day_date_lands_on_its_date_for_home_too(self):
        tor = ZoneInfo("America/Toronto")
        d = self.db()
        once = CalendarEvent(title="once", start_dt="2026-10-30T00:00:00Z", all_day=True)
        weekly = CalendarEvent(
            title="weekly", start_dt="2026-10-30T00:00:00+00:00", all_day=True, recurrence="weekly"
        )
        d.add_all([once, weekly])
        d.commit()
        for row in (once, weekly):
            days = [
                x.isoformat()
                for x in (date(2026, 10, 28) + timedelta(days=i) for i in range(10))
                if signals._event_occurs_on(row, x, tor)
            ]
            self.assertEqual(days[:1], ["2026-10-30"], row.title)  # not the evening of the 29th
        d.close()
