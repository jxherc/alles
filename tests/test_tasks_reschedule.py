import unittest
from datetime import date

from core.database import Task
from services.task_nl import reschedule_date
from tests._client import ApiTest

T = date(2026, 6, 18)  # a Thursday (weekday 3)


class RescheduleDateTests(unittest.TestCase):
    def test_today(self):
        self.assertEqual(reschedule_date("today", T), "2026-06-18")

    def test_tomorrow(self):
        self.assertEqual(reschedule_date("tomorrow", T), "2026-06-19")

    def test_next_week(self):
        self.assertEqual(reschedule_date("next_week", T), "2026-06-25")

    def test_weekend_is_saturday(self):
        self.assertEqual(reschedule_date("weekend", T), "2026-06-20")

    def test_named_weekday_future(self):
        self.assertEqual(reschedule_date("monday", T), "2026-06-22")

    def test_named_weekday_tomorrow(self):
        self.assertEqual(reschedule_date("friday", T), "2026-06-19")

    def test_same_weekday_jumps_a_week(self):
        # today is Thursday → "thursday" means next week, not today
        self.assertEqual(reschedule_date("thursday", T), "2026-06-25")

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            reschedule_date("someday", T)


class RescheduleApiTests(ApiTest):
    def test_reschedule_sets_due(self):
        d = self.db()
        t = Task(title="pay rent", due_date="2026-06-01")
        d.add(t)
        d.commit()
        tid = t.id
        d.close()
        r = self.client.post(f"/api/tasks/{tid}/reschedule", json={"when": "tomorrow"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/tasks").json()[0]["due_date"], r.json()["due_date"])

    def test_reschedule_unknown_404(self):
        self.assertEqual(
            self.client.post("/api/tasks/nope/reschedule", json={"when": "today"}).status_code, 404
        )

    def test_reschedule_bad_when_400(self):
        d = self.db()
        t = Task(title="x")
        d.add(t)
        d.commit()
        tid = t.id
        d.close()
        self.assertEqual(
            self.client.post(f"/api/tasks/{tid}/reschedule", json={"when": "bogus"}).status_code,
            400,
        )


if __name__ == "__main__":
    unittest.main()
