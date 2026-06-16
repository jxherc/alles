import json

from tests._client import ApiTest
from core.database import Calendar, CalendarEvent


class CalendarsApiTest(ApiTest):
    def test_seed_and_list(self):
        cals = self.client.get("/api/calendars").json()
        self.assertTrue(any(c["is_default"] for c in cals))
        self.assertEqual(cals[0]["name"], "Personal")

    def test_create_event_gets_default_calendar(self):
        ev = self.client.post("/api/calendar", json={"title": "x", "start_dt": "2026-06-01T10:00"}).json()
        self.assertTrue(ev["calendar_id"])

    def test_event_carries_new_fields(self):
        ev = self.client.post("/api/calendar", json={
            "title": "standup", "start_dt": "2026-06-01T09:00", "location": "zoom",
            "guests": "a@x, b@y", "reminders": [10, 60], "recurrence": "weekly",
            "recur_byday": "MO,WE", "recur_interval": 1}).json()
        self.assertEqual(ev["location"], "zoom")
        self.assertEqual(ev["reminders"], [10, 60])
        self.assertEqual(ev["recur_byday"], "MO,WE")

    def test_delete_scope_this_adds_exception(self):
        ev = self.client.post("/api/calendar", json={"title": "daily", "start_dt": "2026-06-01T09:00", "recurrence": "daily"}).json()
        self.client.delete(f"/api/calendar/{ev['id']}?scope=this&occ=2026-06-03")
        got = self.client.get("/api/calendar").json()
        row = next(e for e in got if e["id"] == ev["id"])
        self.assertIn("2026-06-03", row["recur_except"])   # excluded, event still exists

    def test_delete_scope_following_sets_until(self):
        ev = self.client.post("/api/calendar", json={"title": "daily", "start_dt": "2026-06-01T09:00", "recurrence": "daily"}).json()
        self.client.delete(f"/api/calendar/{ev['id']}?scope=following&occ=2026-06-05")
        row = next(e for e in self.client.get("/api/calendar").json() if e["id"] == ev["id"])
        self.assertEqual(row["recur_until"], "2026-06-04")

    def test_delete_all_removes(self):
        ev = self.client.post("/api/calendar", json={"title": "z", "start_dt": "2026-06-01T09:00"}).json()
        self.client.delete(f"/api/calendar/{ev['id']}")
        self.assertFalse(any(e["id"] == ev["id"] for e in self.client.get("/api/calendar").json()))

    def test_delete_calendar_moves_events_to_default(self):
        cal = self.client.post("/api/calendars", json={"name": "Work", "color": "green"}).json()
        ev = self.client.post("/api/calendar", json={"title": "w", "start_dt": "2026-06-01T09:00", "calendar_id": cal["id"]}).json()
        r = self.client.delete(f"/api/calendars/{cal['id']}").json()
        moved = next(e for e in self.client.get("/api/calendar").json() if e["id"] == ev["id"])
        self.assertEqual(moved["calendar_id"], r["moved_to"])

    def test_cannot_delete_default(self):
        d = next(c for c in self.client.get("/api/calendars").json() if c["is_default"])
        self.assertEqual(self.client.delete(f"/api/calendars/{d['id']}").status_code, 400)
