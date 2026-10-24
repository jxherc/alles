from datetime import date, timedelta
from unittest.mock import patch

from core.database import CalendarEvent
from services import ics
from tests._client import ApiTest


class IcsServiceTest(ApiTest):  # ApiTest only for convenience; these are pure
    def test_roundtrip_timed(self):
        evs = [
            {
                "id": "1",
                "title": "Demo, with comma",
                "start_dt": "2026-06-19T14:00:00",
                "end_dt": "2026-06-19T15:00:00",
                "all_day": False,
                "description": "line1\nline2",
            }
        ]
        out = ics.parse_ics(ics.to_ics(evs))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Demo, with comma")
        self.assertEqual(out[0]["start_dt"], "2026-06-19T14:00:00")
        self.assertFalse(out[0]["all_day"])
        self.assertIn("line2", out[0]["description"])

    def test_roundtrip_all_day(self):
        evs = [{"id": "2", "title": "Birthday", "start_dt": "2026-07-01", "all_day": True}]
        out = ics.parse_ics(ics.to_ics(evs))
        self.assertTrue(out[0]["all_day"])
        self.assertEqual(out[0]["start_dt"], "2026-07-01")

    def test_all_day_multiday_end_is_exclusive(self):
        # a 3-day all-day event (Jun 30 - Jul 2 inclusive) must export an
        # exclusive DTEND of Jul 3, and round-trip back to the inclusive Jul 2
        evs = [
            {
                "id": "3",
                "title": "Trip",
                "start_dt": "2026-06-30",
                "end_dt": "2026-07-02",
                "all_day": True,
            }
        ]
        text = ics.to_ics(evs)
        self.assertIn("DTEND;VALUE=DATE:20260703", text)  # +1 day, crosses the month
        out = ics.parse_ics(text)
        self.assertEqual(out[0]["start_dt"], "2026-06-30")
        self.assertEqual(out[0]["end_dt"], "2026-07-02")

    def test_parses_real_world_ics(self):
        text = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Team sync\r\n"
            "DTSTART:20260620T090000\r\nDTEND:20260620T093000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        out = ics.parse_ics(text)
        self.assertEqual(out[0]["title"], "Team sync")
        self.assertEqual(out[0]["start_dt"], "2026-06-20T09:00:00")

    def test_special_chars_in_title_roundtrip(self):
        evs = [
            {
                "id": "5",
                "title": "Colon: yes; backslash\\ here",
                "start_dt": "2026-08-01T10:00:00",
                "all_day": False,
            }
        ]
        out = ics.parse_ics(ics.to_ics(evs))
        self.assertEqual(out[0]["title"], "Colon: yes; backslash\\ here")

    def test_description_newlines_survive_roundtrip(self):
        evs = [
            {
                "id": "6",
                "title": "X",
                "start_dt": "2026-09-01T08:00:00",
                "all_day": False,
                "description": "line a\nline b\nline c",
            }
        ]
        out = ics.parse_ics(ics.to_ics(evs))
        self.assertIn("line a", out[0]["description"])
        self.assertIn("line b", out[0]["description"])

    def test_event_missing_end_dt_ok(self):
        evs = [{"id": "7", "title": "No end", "start_dt": "2026-10-01T09:00:00", "all_day": False}]
        out = ics.parse_ics(ics.to_ics(evs))
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0].get("end_dt"))

    def test_multiple_events(self):
        evs = [
            {"id": "a", "title": "First", "start_dt": "2026-01-01T00:00:00", "all_day": False},
            {"id": "b", "title": "Second", "start_dt": "2026-01-02T00:00:00", "all_day": False},
        ]
        out = ics.parse_ics(ics.to_ics(evs))
        self.assertEqual(len(out), 2)
        titles = {e["title"] for e in out}
        self.assertEqual(titles, {"First", "Second"})

    def test_parse_empty_string(self):
        self.assertEqual(ics.parse_ics(""), [])

    def test_malformed_date_doesnt_crash_feed(self):
        # a digit-shaped but impossible date (month 13) used to raise inside parse_ics
        # and abort the whole import — wiping a subscription mid-sync. now it's skipped
        # and the valid event around it still comes through.
        text = (
            "BEGIN:VCALENDAR\r\n"
            "BEGIN:VEVENT\r\nSUMMARY:Broken\r\nDTSTART:20261399\r\nDTEND:20261499\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nSUMMARY:Good\r\nDTSTART:20260620T090000\r\nDTEND:20260620T093000\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        out = ics.parse_ics(text)
        self.assertEqual([e["title"] for e in out], ["Good"])

    def test_malformed_dtend_keeps_event(self):
        # bad DTEND alone shouldn't drop the event or crash — just leaves end open
        text = (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Half\r\n"
            "DTSTART:20260620T090000\r\nDTEND:20260640T990000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        out = ics.parse_ics(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Half")
        self.assertIsNone(out[0]["end_dt"])


_NY = {"timezone": "America/New_York"}


class IcsZoneTest(ApiTest):  # pure too
    def test_utc_and_tzid_times_land_on_local_wall_time(self):
        text = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:utc\nDTSTART:20261029T190000Z\n"
            "DTEND:20261029T200000Z\nEND:VEVENT\nBEGIN:VEVENT\nSUMMARY:la\n"
            "DTSTART;TZID=America/Los_Angeles:20261029T090000\nEND:VEVENT\n"
            "BEGIN:VEVENT\nSUMMARY:outlook\nDTSTART;TZID=Pacific Standard Time:20261029T090000\n"
            "END:VEVENT\nEND:VCALENDAR"
        )
        with patch("services.calendar_events.load_settings", return_value=_NY):
            utc, la, outlook = ics.parse_ics(text)
        # stored naive, in the owner's zone, like events made in the app
        self.assertEqual(utc["start_dt"], "2026-10-29T15:00:00")
        self.assertEqual(utc["end_dt"], "2026-10-29T16:00:00")
        self.assertEqual(la["start_dt"], "2026-10-29T12:00:00")
        self.assertEqual(outlook["start_dt"], "2026-10-29T09:00:00")

    def test_no_owner_zone_keeps_the_offset_instead_of_guessing(self):
        # a container's server zone is usually utc; converting there would move the event for
        # good, so with no zone to go by the instant is kept as it was sent
        for stamp, want in (
            ("20270115T190000Z", "2027-01-15T19:00:00+00:00"),
            ("20270715T190000Z", "2027-07-15T19:00:00+00:00"),
        ):
            text = f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:{stamp}\nEND:VEVENT\nEND:VCALENDAR"
            for blank in ({"timezone": ""}, {"timezone": "Not/AZone"}, {}):
                with patch("services.calendar_events.load_settings", return_value=blank):
                    got = ics.parse_ics(text)[0]["start_dt"]
                self.assertEqual(got, want, (stamp, blank))
        # with the browser's zone given, winter and summer each get their own offset
        from zoneinfo import ZoneInfo

        text = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20270115T190000Z\nEND:VEVENT\n"
            "BEGIN:VEVENT\nDTSTART:20270715T190000Z\nEND:VEVENT\nEND:VCALENDAR"
        )
        winter, summer = ics.parse_ics(text, zone=ZoneInfo("America/Toronto"))
        self.assertEqual(winter["start_dt"], "2027-01-15T14:00:00")
        self.assertEqual(summer["start_dt"], "2027-07-15T15:00:00")

    def test_an_event_across_the_autumn_change_keeps_its_length(self):
        from zoneinfo import ZoneInfo

        text = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:late\nDTSTART:20261101T053000Z\n"
            "DTEND:20261101T063000Z\nEND:VEVENT\nEND:VCALENDAR"
        )
        (event,) = ics.parse_ics(text, zone=ZoneInfo("America/Toronto"))
        self.assertEqual(
            (event["start_dt"], event["end_dt"]), ("2026-11-01T01:30:00", "2026-11-01T02:30:00")
        )

    def test_an_older_zoned_row_exports_as_utc_and_comes_back_local(self):
        out = ics.to_ics(
            [{"title": "x", "start_dt": "2026-10-29T09:00:00-07:00", "all_day": False}]
        )
        self.assertIn("DTSTART:20261029T160000Z", out)
        with patch("services.calendar_events.load_settings", return_value=_NY):
            self.assertEqual(ics.parse_ics(out)[0]["start_dt"], "2026-10-29T12:00:00")

    def test_an_imported_utc_event_blocks_free_time_and_shows_in_agenda(self):
        day = date.today() + timedelta(days=1)
        stamp = day.strftime("%Y%m%d")
        text = (
            "BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:google call\n"
            f"DTSTART:{stamp}T140000Z\nDTEND:{stamp}T150000Z\nEND:VEVENT\nEND:VCALENDAR"
        )
        with patch("services.calendar_events.load_settings", return_value={"timezone": "UTC"}):
            r = self.client.post("/api/calendar/import", json={"ics": text})
        self.assertEqual(r.status_code, 200, r.text)
        free = self.client.get("/api/calendar/free", params={"date": day.isoformat()})
        self.assertEqual(free.status_code, 200, free.text)
        d = day.isoformat()
        self.assertEqual(
            free.json()["slots"],
            [
                {"start": f"{d}T09:00", "end": f"{d}T14:00"},
                {"start": f"{d}T15:00", "end": f"{d}T18:00"},
            ],
        )
        days = self.client.get("/api/calendar/agenda", params={"days": 3}).json()["days"]
        hit = [e for g in days if g["date"] == d for e in g["events"]]
        self.assertEqual([e["start_dt"] for e in hit], [f"{d}T14:00:00"])


class IcsApiTest(ApiTest):
    def test_export_then_import(self):
        d = self.db()
        d.add(CalendarEvent(title="Exported", start_dt="2026-06-19T14:00:00", all_day=False))
        d.commit()
        d.close()
        r = self.client.get("/api/calendar/export.ics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/calendar", r.headers["content-type"])
        self.assertIn("Exported", r.text)
        # import it back into a clean calendar
        d = self.db()
        for e in d.query(CalendarEvent).all():
            d.delete(e)
        d.commit()
        d.close()
        imp = self.client.post("/api/calendar/import", json={"ics": r.text})
        self.assertEqual(imp.json()["imported"], 1)
        self.assertEqual(self.client.get("/api/calendar").json()[0]["title"], "Exported")


class EventColorTest(ApiTest):
    def test_a_colour_must_be_a_palette_name_or_hex(self):
        bad = self.client.post(
            "/api/calendar",
            json={"title": "x", "start_dt": "2026-10-29T09:00", "color": '#fff" onclick="x'},
        )
        self.assertEqual(bad.status_code, 422)
        ok = self.client.post(
            "/api/calendar", json={"title": "x", "start_dt": "2026-10-29T09:00", "color": "#5b8def"}
        )
        self.assertEqual(ok.status_code, 200, ok.text)


class AgendaSpanTest(ApiTest):
    def test_a_multi_day_event_shows_on_each_of_its_days(self):
        from datetime import date, timedelta

        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=2)
        self.client.post(
            "/api/calendar",
            json={
                "title": "camping",
                "start_dt": start.isoformat(),
                "end_dt": end.isoformat(),
                "all_day": True,
            },
        )
        days = self.client.get("/api/calendar/agenda", params={"days": 8}).json()["days"]
        with_camping = [
            d["date"] for d in days if any(e["title"] == "camping" for e in d["events"])
        ]
        self.assertEqual(with_camping, [(start + timedelta(days=i)).isoformat() for i in range(3)])
