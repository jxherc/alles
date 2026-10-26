import asyncio
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

    def test_delete_cleans_up_auto_created_calendar(self):
        from core.database import Calendar

        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            d = self._create()
        sid, cid = d["id"], d["calendar_id"]
        self._refresh(sid, ICS_2)
        self.client.delete(f"/api/calendar/subscriptions/{sid}")
        db = self.db()
        self.assertIsNone(db.get(Calendar, cid))  # orphan feed layer removed, not left behind
        db.close()

    def test_duplicate_drops_subscription_id(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        self._refresh(sid, ICS_2)
        ev = self._events_for(sid)[0]
        # find the event id
        evs = self.client.get("/api/calendar").json()
        eid = next(
            e["id"]
            for e in (evs if isinstance(evs, list) else evs.get("events", []))
            if e["title"] == ev[0]
        )
        dup = self.client.post(f"/api/calendar/{eid}/duplicate").json()
        from core.database import CalendarEvent

        db = self.db()
        clone = db.get(CalendarEvent, dup["id"])
        self.assertFalse(clone.subscription_id)  # a duplicate is a local event, not feed-owned
        db.close()

    def test_list_with_counts(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            sid = self._create()["id"]
        self._refresh(sid, ICS_2)
        lst = self.client.get("/api/calendar/subscriptions").json()
        sub = next(s for s in lst if s["id"] == sid)
        self.assertEqual(sub["event_count"], 2)

    def test_list_counts_per_sub_multiple(self):
        # batched grouped count must map each sub to ITS own count (2, 1, and 0 for an empty one)
        with mock.patch("routes.calendar.fetch_ics", return_value=""):
            a = self._create(name="A", url="https://example.com/a.ics")["id"]
            b = self._create(name="B", url="https://example.com/b.ics")["id"]
            c = self._create(name="C", url="https://example.com/c.ics")["id"]
        self._refresh(a, ICS_2)  # 2 events
        self._refresh(b, ICS_1)  # 1 event
        # c stays empty
        lst = {
            s["id"]: s["event_count"] for s in self.client.get("/api/calendar/subscriptions").json()
        }
        self.assertEqual(lst[a], 2)
        self.assertEqual(lst[b], 1)
        self.assertEqual(lst[c], 0)

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


BERLIN = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:b1
SUMMARY:berlin standup
DTSTART;TZID=Europe/Berlin:20261026T090000
DTEND;TZID=Europe/Berlin:20261026T091500
RRULE:FREQ=WEEKLY;BYDAY=MO,WE
END:VEVENT
BEGIN:VEVENT
UID:b2
SUMMARY:berlin one-off
DTSTART;TZID=Europe/Berlin:20261104T150000
DTEND;TZID=Europe/Berlin:20261104T160000
END:VEVENT
END:VCALENDAR
"""


class FeedZoneTests(ApiTest):
    """a feed's times land in the owner's zone, and with none known they keep their own"""

    def setUp(self):
        super().setUp()
        from core.settings import save_settings

        save_settings({"timezone": "", "detected_timezone": ""})
        self.addCleanup(save_settings, {"timezone": "", "detected_timezone": ""})

    def _rows(self):
        db = self.db()
        out = {e.title: (e.start_dt, e.source_zone or "") for e in db.query(CalendarEvent).all()}
        db.close()
        return out

    def test_the_browsers_zone_is_used_on_create_and_refresh(self):
        tor = {"x-alles-time-zone": "America/Toronto"}
        with mock.patch("routes.calendar.fetch_ics", return_value=BERLIN):
            sid = self.client.post(
                "/api/calendar/subscriptions",
                json={"name": "f", "url": "https://x.test/a.ics"},
                headers=tor,
            ).json()["id"]
        self.assertEqual(self._rows()["berlin one-off"][0], "2026-11-04T09:00:00")
        with mock.patch("routes.calendar.fetch_ics", return_value=BERLIN):
            self.client.post(f"/api/calendar/subscriptions/{sid}/refresh", headers=tor)
        rows = self._rows()
        self.assertEqual(rows["berlin one-off"][0], "2026-11-04T09:00:00")
        # berlin changes its clocks a week before toronto: the series repeats in berlin
        self.assertEqual(rows["berlin standup"], ("2026-10-26T09:00:00+01:00", "Europe/Berlin"))

    def test_with_no_zone_known_nothing_keeps_the_sources_wall_time(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=BERLIN):
            self.client.post(
                "/api/calendar/subscriptions", json={"name": "f", "url": "https://x.test/a.ics"}
            )
        rows = self._rows()
        self.assertEqual(rows["berlin one-off"][0], "2026-11-04T15:00:00+01:00")
        self.assertEqual(rows["berlin standup"], ("2026-10-26T09:00:00+01:00", "Europe/Berlin"))
        # the hourly job reads in the owner's zone: the last browser zone seen
        from core.settings import save_settings
        from routes.calendar import refresh_all_subscriptions

        save_settings({"detected_timezone": "America/Toronto"})
        with mock.patch("routes.calendar.fetch_ics", return_value=BERLIN):
            asyncio.run(refresh_all_subscriptions())
        self.assertEqual(self._rows()["berlin one-off"][0], "2026-11-04T09:00:00")

    def test_an_error_page_keeps_the_feeds_events(self):
        with mock.patch("routes.calendar.fetch_ics", return_value=BERLIN):
            sid = self.client.post(
                "/api/calendar/subscriptions", json={"name": "f", "url": "https://x.test/a.ics"}
            ).json()["id"]
        page = "<!doctype html><html><body>sign in to see this calendar</body></html>"
        with mock.patch("routes.calendar.fetch_ics", return_value=page):
            out = self.client.post(f"/api/calendar/subscriptions/{sid}/refresh").json()
        self.assertEqual(out["event_count"], 2)
        self.assertEqual(out["last_status"], "error: choose a complete .ics calendar file")
