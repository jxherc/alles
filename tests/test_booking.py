from core.database import CalendarEvent, EventAttendee
from tests._client import ApiTest

DAY = "2026-07-06"  # a future Monday


class BookingTests(ApiTest):
    def _page(self, **kw):
        body = {"title": "Chat", "duration_min": 30, "work_start": 9, "work_end": 11}
        body.update(kw)
        return self.client.post("/api/calendar/booking-pages", json=body).json()

    def _busy(self, start, end):
        db = self.db()
        db.add(CalendarEvent(title="busy", start_dt=start, end_dt=end))
        db.commit()
        db.close()

    def _slots(self, token, day=DAY):
        return self.client.get(f"/book/{token}/slots?date={day}").json()["slots"]

    def test_create_booking_page(self):
        d = self._page()
        self.assertIn("id", d)
        self.assertEqual(d["duration_min"], 30)

    def test_page_has_token(self):
        self.assertTrue(self._page()["token"])

    def test_slots_excludes_busy(self):
        tok = self._page(work_start=9, work_end=11, duration_min=60)["token"]
        self._busy(f"{DAY}T09:00:00", f"{DAY}T10:00:00")
        starts = [s["start"][11:16] for s in self._slots(tok)]
        self.assertNotIn("09:00", starts)
        self.assertIn("10:00", starts)

    def test_slots_respect_work_hours(self):
        tok = self._page(work_start=9, work_end=11, duration_min=30)["token"]
        for s in self._slots(tok):
            hh = int(s["start"][11:13])
            self.assertGreaterEqual(hh, 9)
            self.assertLess(hh, 11)

    def test_book_creates_event(self):
        tok = self._page()["token"]
        before = len(self.client.get("/api/calendar").json())
        r = self.client.post(
            f"/book/{tok}", json={"date": DAY, "time": "10:00", "name": "Sam", "email": "s@x.com"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.client.get("/api/calendar").json()), before + 1)

    def test_book_sets_duration(self):
        tok = self._page(duration_min=45, work_start=10, work_end=12)["token"]
        self.client.post(
            f"/book/{tok}", json={"date": DAY, "time": "10:00", "name": "S", "email": "s@x.com"}
        )
        db = self.db()
        ev = db.query(CalendarEvent).filter(CalendarEvent.start_dt == f"{DAY}T10:00:00").first()
        from datetime import datetime

        dur = datetime.fromisoformat(ev.end_dt) - datetime.fromisoformat(ev.start_dt)
        db.close()
        self.assertEqual(dur.total_seconds(), 45 * 60)

    def test_book_adds_attendee(self):
        tok = self._page()["token"]
        self.client.post(
            f"/book/{tok}", json={"date": DAY, "time": "10:00", "name": "Sam", "email": "s@x.com"}
        )
        db = self.db()
        att = db.query(EventAttendee).filter(EventAttendee.email == "s@x.com").first()
        db.close()
        self.assertIsNotNone(att)
        self.assertEqual(att.status, "accepted")

    def test_book_unknown_token_404(self):
        r = self.client.post(
            "/book/nope", json={"date": DAY, "time": "10:00", "name": "x", "email": "x@x.com"}
        )
        self.assertEqual(r.status_code, 404)

    def test_book_past_or_busy_rejected(self):
        tok = self._page(work_start=9, work_end=11, duration_min=60)["token"]
        self._busy(f"{DAY}T09:00:00", f"{DAY}T10:00:00")
        r = self.client.post(
            f"/book/{tok}", json={"date": DAY, "time": "09:00", "name": "x", "email": "x@x.com"}
        )
        self.assertEqual(r.status_code, 409)

    def test_delete_booking_page(self):
        bid = self._page()["id"]
        self.client.delete(f"/api/calendar/booking-pages/{bid}")
        self.assertEqual(len(self.client.get("/api/calendar/booking-pages").json()), 0)
