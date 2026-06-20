from datetime import date, datetime, timedelta

from core.database import CalendarEvent, Reminder, Task
from tests._client import ApiTest


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

    def test_date_query_param(self):
        # pass a specific date; only that date's event should show up
        target = "2030-03-15"
        d = self.db()
        d.add(CalendarEvent(title="march event", start_dt=f"{target}T09:00:00", all_day=False))
        d.add(CalendarEvent(title="other day", start_dt="2030-03-16T09:00:00", all_day=False))
        d.commit()
        d.close()

        r = self.client.get(f"/api/today?date={target}").json()
        titles = [e["title"] for e in r["events"]]
        self.assertIn("march event", titles)
        self.assertNotIn("other day", titles)
        self.assertEqual(r["date"], target)

    def test_open_count_includes_tasks_without_due_date(self):
        d = self.db()
        d.add(Task(title="no due date", done=False))
        d.add(Task(title="also no due", done=False))
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        self.assertGreaterEqual(r["tasks"]["open_count"], 2)

    def test_fired_reminder_not_returned(self):
        d = self.db()
        d.add(Reminder(text="old fired", trigger_at=datetime.utcnow(), fired=True, type="reminder"))
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        self.assertNotIn("old fired", [x["text"] for x in r["reminders"]])

    def test_future_reminder_not_returned(self):
        tomorrow = datetime.utcnow() + timedelta(days=2)
        d = self.db()
        d.add(Reminder(text="future ping", trigger_at=tomorrow, fired=False, type="reminder"))
        d.commit()
        d.close()

        # use today's date so "tomorrow" is definitely in the future
        today = date.today().isoformat()
        r = self.client.get(f"/api/today?date={today}").json()
        self.assertNotIn("future ping", [x["text"] for x in r["reminders"]])

    def test_all_day_event_has_empty_time(self):
        today = date.today().isoformat()
        d = self.db()
        d.add(CalendarEvent(title="all day thing", start_dt=today, all_day=True))
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        match = next((e for e in r["events"] if e["title"] == "all day thing"), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["time"], "")
        self.assertTrue(match["all_day"])

    def test_weekly_recurring_event_appears_on_matching_weekday(self):
        # find next monday from today
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7  # skip today if today is monday
        next_monday = today + timedelta(days=days_until_monday)

        # create a weekly event that started on a past monday
        past_monday = next_monday - timedelta(weeks=2)
        d = self.db()
        d.add(CalendarEvent(
            title="weekly monday",
            start_dt=past_monday.isoformat() + "T08:00:00",
            recurrence="weekly",
            all_day=False,
        ))
        d.commit()
        d.close()

        r = self.client.get(f"/api/today?date={next_monday.isoformat()}").json()
        titles = [e["title"] for e in r["events"]]
        self.assertIn("weekly monday", titles)

    def test_task_without_due_date_not_in_overdue_or_due_today(self):
        d = self.db()
        d.add(Task(title="floaty task", done=False))
        d.commit()
        d.close()

        r = self.client.get("/api/today").json()
        all_due = r["tasks"]["due_today"] + r["tasks"]["overdue"]
        self.assertNotIn("floaty task", [t["title"] for t in all_due])
        # but it does count toward open_count
        self.assertGreaterEqual(r["tasks"]["open_count"], 1)

    def test_response_structure_always_present(self):
        r = self.client.get("/api/today").json()
        self.assertIn("date", r)
        self.assertIn("events", r)
        self.assertIn("tasks", r)
        self.assertIn("reminders", r)
        self.assertIn("renewing", r)
        self.assertIn("day_events", r)
        self.assertIn("recent_docs", r)
        self.assertIn("overdue", r["tasks"])
        self.assertIn("due_today", r["tasks"])
        self.assertIn("open_count", r["tasks"])

    def test_weekly_recurring_not_on_wrong_weekday(self):
        # a weekly event on monday shouldn't appear on tuesday
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        next_monday = today + timedelta(days=days_until_monday)
        next_tuesday = next_monday + timedelta(days=1)

        past_monday = next_monday - timedelta(weeks=2)
        d = self.db()
        d.add(CalendarEvent(
            title="monday only",
            start_dt=past_monday.isoformat() + "T08:00:00",
            recurrence="weekly",
            all_day=False,
        ))
        d.commit()
        d.close()

        r = self.client.get(f"/api/today?date={next_tuesday.isoformat()}").json()
        self.assertNotIn("monday only", [e["title"] for e in r["events"]])
