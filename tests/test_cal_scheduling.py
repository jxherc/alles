import unittest
from datetime import date, datetime, time

from core.database import CalendarEvent
from services.recur import free_slots
from tests._client import ApiTest

DAY = date(2026, 6, 20)


def _dt(h, m=0):
    return datetime.combine(DAY, time(h, m))


class FreeSlotTests(unittest.TestCase):
    def test_empty_day_is_one_slot(self):
        s = free_slots([], DAY, 60)
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["start"].endswith("09:00"))
        self.assertTrue(s[0]["end"].endswith("18:00"))

    def test_event_splits_day(self):
        s = free_slots([(_dt(12), _dt(13))], DAY, 60)
        self.assertEqual(
            [(x["start"][-5:], x["end"][-5:]) for x in s], [("09:00", "12:00"), ("13:00", "18:00")]
        )

    def test_full_day_busy_no_slots(self):
        self.assertEqual(free_slots([(_dt(9), _dt(18))], DAY, 60), [])

    def test_minutes_longer_than_window(self):
        self.assertEqual(free_slots([], DAY, 600), [])

    def test_back_to_back_merge(self):
        s = free_slots([(_dt(10), _dt(11)), (_dt(11), _dt(12))], DAY, 60)
        self.assertEqual(
            [(x["start"][-5:], x["end"][-5:]) for x in s], [("09:00", "10:00"), ("12:00", "18:00")]
        )

    def test_event_before_window_ignored(self):
        s = free_slots([(_dt(7), _dt(8))], DAY, 60)
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["start"].endswith("09:00"))

    def test_custom_work_hours(self):
        s = free_slots([], DAY, 60, work_start=8, work_end=20)
        self.assertTrue(s[0]["start"].endswith("08:00"))
        self.assertTrue(s[0]["end"].endswith("20:00"))

    def test_short_gap_excluded(self):
        s = free_slots([(_dt(12), _dt(12, 30)), (_dt(13), _dt(18))], DAY, 60)
        self.assertEqual([(x["start"][-5:], x["end"][-5:]) for x in s], [("09:00", "12:00")])


class SchedulingApiTests(ApiTest):
    def test_duplicate_clones_event(self):
        e = self.client.post(
            "/api/calendar",
            json={"title": "Standup", "start_dt": "2026-06-20T09:00", "end_dt": "2026-06-20T09:30"},
        ).json()
        dup = self.client.post(f"/api/calendar/{e['id']}/duplicate").json()
        self.assertEqual(dup["title"], "Standup")
        self.assertNotEqual(dup["id"], e["id"])
        self.assertEqual(len(self.client.get("/api/calendar").json()), 2)

    def test_duplicate_unknown_404(self):
        self.assertEqual(self.client.post("/api/calendar/nope/duplicate").status_code, 404)

    def test_free_endpoint(self):
        d = self.db()
        d.add(CalendarEvent(title="busy", start_dt="2026-06-20T12:00", end_dt="2026-06-20T13:00"))
        d.commit()
        d.close()
        slots = self.client.get(
            "/api/calendar/free", params={"date": "2026-06-20", "minutes": 60}
        ).json()["slots"]
        labels = [(x["start"][-5:], x["end"][-5:]) for x in slots]
        self.assertIn(("09:00", "12:00"), labels)
        self.assertIn(("13:00", "18:00"), labels)


if __name__ == "__main__":
    unittest.main()
