"""the daily-briefing composer — gathers a morning digest from the local apps."""

from datetime import date

import core.database as D
from services import briefing
from tests._client import ApiTest


class BriefingTests(ApiTest):
    DAY = date(2026, 6, 21)
    ISO = "2026-06-21"

    def test_empty_briefing_has_no_content(self):
        b = briefing.compose_briefing(self.db(), today=self.DAY)
        self.assertFalse(b["has_content"])
        self.assertEqual(b["lines"], [])

    def test_briefing_gathers_todays_stuff(self):
        db = self.db()
        db.add(D.Task(title="file taxes", done=False))
        db.add(D.CalendarEvent(title="standup", start_dt=self.ISO + "T09:00:00"))
        db.add(D.Habit(name="Read"))
        db.add(D.Book(title="Dune", status="reading"))
        db.add(D.Subscription(name="Netflix", next_due=self.ISO, remind_days=1))
        db.add(D.HealthEntry(kind="weight", value=72.5, unit="kg", date=self.ISO))
        db.commit()
        b = briefing.compose_briefing(db, today=self.DAY)
        self.assertTrue(b["has_content"])
        body = b["body"]
        for needle in ("standup", "file taxes", "Read", "Dune", "Netflix", "72.5"):
            self.assertIn(needle, body, f"{needle!r} missing from briefing:\n{body}")

    def test_done_habit_is_not_listed(self):
        db = self.db()
        h = D.Habit(name="Read")
        db.add(h)
        db.commit()
        db.add(D.HabitLog(habit_id=h.id, date=self.ISO))
        db.commit()
        b = briefing.compose_briefing(db, today=self.DAY)
        self.assertNotIn("Read", b["body"])

    def test_completed_task_is_not_listed(self):
        db = self.db()
        db.add(D.Task(title="done thing", done=True))
        db.commit()
        b = briefing.compose_briefing(db, today=self.DAY)
        self.assertNotIn("done thing", b["body"])

    def test_far_future_renewal_excluded(self):
        db = self.db()
        db.add(D.Subscription(name="FarAway", next_due="2026-12-31", remind_days=1))
        db.commit()
        b = briefing.compose_briefing(db, today=self.DAY)
        self.assertNotIn("FarAway", b["body"])


class BriefingRouteTests(ApiTest):
    def test_preview_endpoint_returns_digest(self):
        db = self.db()
        db.add(D.Book(title="Dune", status="reading"))
        db.commit()
        r = self.client.get("/api/briefing")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("has_content", body)
        self.assertIn("Dune", body["body"])
