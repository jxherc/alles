from datetime import date, datetime

from tests._client import ApiTest
from core.database import CalendarEvent, Task, Reminder


class TodayApiTest(ApiTest):
    def test_aggregates_events_tasks_reminders(self):
        today = date.today().isoformat()
        d = self.db()
        d.add(CalendarEvent(title="today event", start_dt=f"{today}T10:00:00", all_day=False))
        d.add(Task(title="due today", due_date=today, done=False))
        d.add(Task(title="way overdue", due_date="2000-01-01", done=False))
        d.add(Task(title="done already", due_date=today, done=True))
        d.add(Reminder(text="ping me", trigger_at=datetime.utcnow(), fired=False, type="reminder"))
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        self.assertIn("today event", [e["title"] for e in r["events"]])
        self.assertIn("due today", [t["title"] for t in r["tasks"]["due_today"]])
        self.assertIn("way overdue", [t["title"] for t in r["tasks"]["overdue"]])
        self.assertIn("ping me", [x["text"] for x in r["reminders"]])
        # the completed task isn't counted as open
        self.assertNotIn("done already", [t["title"] for t in r["tasks"]["due_today"]])

    def test_empty_day(self):
        r = self.client.get("/api/today").json()
        self.assertEqual(r["events"], [])
        self.assertEqual(r["tasks"]["overdue"], [])
        self.assertEqual(r["tasks"]["open_count"], 0)
