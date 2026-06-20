from unittest import mock

from core.database import CalendarEvent, CalendarSubscription
from tests._client import ApiTest

ICS_2 = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Holiday Party
DTSTART:20260701T180000
DTEND:20260701T210000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Team Offsite
DTSTART:20260715T090000
DTEND:20260715T170000
END:VEVENT
END:VCALENDAR
"""

ICS_1 = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Only One
DTSTART:20260801T120000
DTEND:20260801T130000
END:VEVENT
END:VCALENDAR
"""


class CalendarSubscriptionTests(ApiTest):
    def _create(self, name="Holidays", url="https://example.com/cal.ics"):
        return self.client.post(
            "/api/calendar/subscriptions", json={"name": name, "url": url}
        ).json()

    def _refresh(self, sid, text):
        with mock.patch("routes.calendar.fetch_ics", return_value=text):
            return self.client.post(f"/api/calendar/subscriptions/{sid}/refresh")

    def _events_for(self, sid):
        db = self.db()
        rows = db.query(CalendarEvent).filter(CalendarEvent.subscription_id == sid).all()
        out = [(e.title, e.calendar_id) for e in rows]
        db.close()
        return out

    def test_create_subscription(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            d = self._create()
        self.assertIn("id", d)
        self.assertTrue(d["calendar_id"])

    def test_refresh_imports_events(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        self._refresh(sid, ICS_2)
        self.assertEqual(len(self._events_for(sid)), 2)

    def test_refresh_replaces_no_dupes(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        self._refresh(sid, ICS_2)
        self._refresh(sid, ICS_2)
        self.assertEqual(len(self._events_for(sid)), 2)

    def test_refresh_updates_changed(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        self._refresh(sid, ICS_2)
        self._refresh(sid, ICS_1)
        titles = [t for t, _ in self._events_for(sid)]
        self.assertEqual(titles, ["Only One"])

    def test_delete_removes_sub_and_events(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        self._refresh(sid, ICS_2)
        self.client.delete(f"/api/calendar/subscriptions/{sid}")
        self.assertEqual(len(self._events_for(sid)), 0)
        db = self.db()
        self.assertIsNone(db.get(CalendarSubscription, sid))
        db.close()

    def test_list_with_counts(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        self._refresh(sid, ICS_2)
        lst = self.client.get("/api/calendar/subscriptions").json()
        sub = next(s for s in lst if s["id"] == sid)
        self.assertEqual(sub["event_count"], 2)

    def test_events_linked_to_calendar(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            d = self._create()
        sid, cid = d["id"], d["calendar_id"]
        self._refresh(sid, ICS_2)
        for _, calendar_id in self._events_for(sid):
            self.assertEqual(calendar_id, cid)

    def test_last_synced_status_set(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        self._refresh(sid, ICS_2)
        db = self.db()
        sub = db.get(CalendarSubscription, sid)
        self.assertTrue(sub.last_synced)
        self.assertEqual(sub.last_status, "ok")
        db.close()

    def test_empty_ics_ok(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        r = self._refresh(sid, "")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self._events_for(sid)), 0)

    def test_fetch_error_status(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        with mock.patch("routes.calendar.fetch_ics", side_effect=RuntimeError("dns fail")):
            r = self.client.post(f"/api/calendar/subscriptions/{sid}/refresh")
        self.assertEqual(r.status_code, 200)
        db = self.db()
        self.assertTrue(db.get(CalendarSubscription, sid).last_status.startswith("error"))
        db.close()
