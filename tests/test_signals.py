from datetime import date, datetime, timedelta

from core.database import (
    Book,
    CalendarEvent,
    Habit,
    HabitLog,
    Reminder,
    Subscription,
    Task,
)
from services import signals
from tests._client import ApiTest


def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


class SignalsTests(ApiTest):
    def _gather(self, **kw):
        d = self.db()
        try:
            return signals.gather(d, **kw)
        finally:
            d.close()

    def test_overdue_task_signal(self):
        d = self.db()
        d.add(Task(title="pay rent", done=False, due_date=_iso(-2), priority=1))
        d.commit()
        d.close()
        sigs = self._gather()
        t = [s for s in sigs if s["category"] == "task"]
        self.assertEqual(len(t), 1)
        self.assertTrue(t[0]["key"].startswith("task_overdue:"))
        self.assertTrue(t[0]["data"]["overdue"])
        self.assertGreaterEqual(t[0]["urgency"], 70)

    def test_due_today_task_signal(self):
        d = self.db()
        d.add(Task(title="standup", done=False, due_date=_iso(0)))
        d.commit()
        d.close()
        t = [s for s in self._gather() if s["category"] == "task"]
        self.assertEqual(len(t), 1)
        self.assertTrue(t[0]["key"].startswith("task_due:"))

    def test_future_and_done_tasks_excluded(self):
        d = self.db()
        d.add(Task(title="later", done=False, due_date=_iso(10)))
        d.add(Task(title="finished", done=True, due_date=_iso(-1)))
        d.commit()
        d.close()
        self.assertEqual([s for s in self._gather() if s["category"] == "task"], [])

    def test_sub_signal_and_key_has_period(self):
        d = self.db()
        d.add(Subscription(name="netflix", price=9.0, currency="$", cycle="monthly",
                           active=True, next_due=_iso(3)))
        d.commit()
        d.close()
        s = [x for x in self._gather() if x["category"] == "sub"]
        self.assertEqual(len(s), 1)
        self.assertIn(_iso(3), s[0]["key"])
        self.assertEqual(s[0]["data"]["in_days"], 3)

    def test_far_sub_excluded(self):
        d = self.db()
        d.add(Subscription(name="far", price=1.0, currency="$", cycle="yearly",
                           active=True, next_due=_iso(40), remind_days=1))
        d.commit()
        d.close()
        self.assertEqual([s for s in self._gather() if s["category"] == "sub"], [])

    def test_habit_gap_signal(self):
        d = self.db()
        d.add(Habit(name="floss", archived=False, cadence="daily"))
        d.commit()
        d.close()
        h = [s for s in self._gather() if s["category"] == "habit"]
        self.assertEqual(len(h), 1)
        self.assertIn("habit_gap:", h[0]["key"])

    def test_habit_done_today_excluded(self):
        d = self.db()
        h = Habit(name="floss", archived=False, cadence="daily")
        d.add(h)
        d.commit()
        d.add(HabitLog(habit_id=h.id, date=date.today().isoformat()))
        d.commit()
        d.close()
        self.assertEqual([s for s in self._gather() if s["category"] == "habit"], [])

    def test_event_today_signal(self):
        d = self.db()
        d.add(CalendarEvent(title="lunch", start_dt=_iso(0) + "T12:00", all_day=False))
        d.commit()
        d.close()
        e = [s for s in self._gather() if s["category"] == "event"]
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["data"]["time"], "12:00")

    def test_reminder_signal(self):
        d = self.db()
        d.add(Reminder(text="call mom", trigger_at=datetime.utcnow(), fired=False))
        d.commit()
        d.close()
        r = [s for s in self._gather() if s["category"] == "reminder"]
        self.assertEqual(len(r), 1)

    def test_categories_filter(self):
        d = self.db()
        d.add(Task(title="t", done=False, due_date=_iso(0)))
        d.add(Habit(name="h", archived=False))
        d.commit()
        d.close()
        only = self._gather(categories={"task"})
        self.assertTrue(only)
        self.assertTrue(all(s["category"] == "task" for s in only))

    def test_keys_stable_across_calls(self):
        d = self.db()
        d.add(Task(title="x", done=False, due_date=_iso(-1)))
        d.add(Subscription(name="s", price=1, currency="$", cycle="monthly",
                           active=True, next_due=_iso(2)))
        d.commit()
        d.close()
        k1 = sorted(s["key"] for s in self._gather())
        k2 = sorted(s["key"] for s in self._gather())
        self.assertEqual(k1, k2)

    def test_sorted_by_urgency_desc(self):
        d = self.db()
        d.add(Book(title="b", status="reading"))          # urgency 15
        d.add(Task(title="t", done=False, due_date=_iso(-1)))  # urgency 70
        d.commit()
        d.close()
        sigs = self._gather()
        urg = [s["urgency"] for s in sigs]
        self.assertEqual(urg, sorted(urg, reverse=True))

    def test_by_category_groups(self):
        d = self.db()
        d.add(Task(title="t", done=False, due_date=_iso(0)))
        d.commit()
        d.close()
        g = signals.by_category(self._gather())
        self.assertIn("task", g)
        self.assertIsInstance(g["task"], list)
