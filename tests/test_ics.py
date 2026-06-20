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
