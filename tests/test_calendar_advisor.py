"""4a - http tests for the scheduling-advisor routes the editor now surfaces:
conflict detection + the free-slot finder."""

from core.database import CalendarEvent
from tests._client import ApiTest


class CalendarAdvisorTests(ApiTest):
    def _ev(self, title, s, e, all_day=False):
        db = self.db()
        db.add(CalendarEvent(title=title, start_dt=s, end_dt=e, all_day=all_day))
        db.commit()
        db.close()

    def test_conflicts_detects_overlap(self):
        self._ev("A", "2026-07-01T10:00:00", "2026-07-01T11:00:00")
        self._ev("B", "2026-07-01T10:30:00", "2026-07-01T11:30:00")
        c = self.client.get("/api/calendar/conflicts").json()["conflicts"]
        self.assertEqual(len(c), 1)
        self.assertEqual({c[0]["a"], c[0]["b"]}, {"A", "B"})

    def test_conflicts_none_when_touching(self):
        self._ev("A", "2026-07-01T10:00:00", "2026-07-01T11:00:00")
        self._ev("B", "2026-07-01T11:00:00", "2026-07-01T12:00:00")  # back-to-back, not overlapping
        self.assertEqual(self.client.get("/api/calendar/conflicts").json()["conflicts"], [])

    def test_free_slots_finds_gap(self):
        self._ev("A", "2026-07-01T09:00:00", "2026-07-01T10:00:00")
        self._ev("B", "2026-07-01T11:00:00", "2026-07-01T12:00:00")
        slots = self.client.get(
            "/api/calendar/free-slots?day=2026-07-01&duration_min=30"
        ).json()["slots"]
        self.assertTrue(any(s["start"] == "10:00" and s["end"] == "11:00" for s in slots))

    def test_free_slots_respects_duration(self):
        # a 30-min gap can't hold a 60-min meeting
        self._ev("A", "2026-07-02T09:00:00", "2026-07-02T10:00:00")
        self._ev("B", "2026-07-02T10:30:00", "2026-07-02T17:00:00")
        slots = self.client.get(
            "/api/calendar/free-slots?day=2026-07-02&duration_min=60"
        ).json()["slots"]
        self.assertFalse(any(s["start"] == "10:00" for s in slots))

    def test_free_slots_bad_day_no_500(self):
        r = self.client.get("/api/calendar/free-slots?day=notaday")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["slots"], [])

    def test_free_slots_event_after_hours_does_not_extend_window(self):
        # an 18:00-19:00 event is outside the 09:00-17:00 window; the free slot must end at 17:00,
        # not spill out to 18:00 (the event start)
        self._ev("Dinner", "2026-07-03T18:00:00", "2026-07-03T19:00:00")
        slots = self.client.get(
            "/api/calendar/free-slots?day=2026-07-03&duration_min=30"
        ).json()["slots"]
        self.assertEqual(slots, [{"start": "09:00", "end": "17:00"}])

    def test_free_slots_event_spanning_close_clips_to_window(self):
        # event runs 16:30-20:00; the busy time inside hours ends at 17:00, so no slot after it
        self._ev("Long", "2026-07-04T16:30:00", "2026-07-04T20:00:00")
        slots = self.client.get(
            "/api/calendar/free-slots?day=2026-07-04&duration_min=30"
        ).json()["slots"]
        self.assertTrue(all(s["end"] <= "17:00" for s in slots))
        self.assertFalse(any(s["start"] >= "17:00" for s in slots))
