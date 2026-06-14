from tests._client import ApiTest
from core.database import CalendarEvent
from services import ics


class IcsServiceTest(ApiTest):   # ApiTest only for convenience; these are pure
    def test_roundtrip_timed(self):
        evs = [{"id": "1", "title": "Demo, with comma", "start_dt": "2026-06-19T14:00:00",
                "end_dt": "2026-06-19T15:00:00", "all_day": False, "description": "line1\nline2"}]
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

    def test_parses_real_world_ics(self):
        text = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Team sync\r\n"
                "DTSTART:20260620T090000\r\nDTEND:20260620T093000\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        out = ics.parse_ics(text)
        self.assertEqual(out[0]["title"], "Team sync")
        self.assertEqual(out[0]["start_dt"], "2026-06-20T09:00:00")


class IcsApiTest(ApiTest):
    def test_export_then_import(self):
        d = self.db()
        d.add(CalendarEvent(title="Exported", start_dt="2026-06-19T14:00:00", all_day=False))
        d.commit(); d.close()
        r = self.client.get("/api/calendar/export.ics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/calendar", r.headers["content-type"])
        self.assertIn("Exported", r.text)
        # import it back into a clean calendar
        d = self.db()
        for e in d.query(CalendarEvent).all():
            d.delete(e)
        d.commit(); d.close()
        imp = self.client.post("/api/calendar/import", json={"ics": r.text})
        self.assertEqual(imp.json()["imported"], 1)
        self.assertEqual(self.client.get("/api/calendar").json()[0]["title"], "Exported")
