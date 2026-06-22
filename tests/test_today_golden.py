"""golden guard for GET /api/today - it must keep its exact shape/content after
being refactored onto services.signals. ids are random uuids so we compare the
stable fields (titles, times, order, counts, in_days)."""

from datetime import date, datetime, timedelta

from core.database import CalendarEvent, DayEvent, Reminder, Subscription, Task
from tests._client import ApiTest


def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


class TodayGoldenTests(ApiTest):
    def _seed(self):
        d = self.db()
        # events: a recurring weekly (occurs today), a timed one, an all-day one
        d.add(CalendarEvent(title="weekly sync", start_dt=_iso(-7) + "T09:00",
                            all_day=False, recurrence="weekly"))
        d.add(CalendarEvent(title="lunch", start_dt=_iso(0) + "T12:00", all_day=False))
        d.add(CalendarEvent(title="holiday", start_dt=_iso(0), all_day=True))
        # tasks: overdue, due-today, future, no-due (last two only bump open_count)
        d.add(Task(title="rent", done=False, due_date=_iso(-2), priority=1))
        d.add(Task(title="standup", done=False, due_date=_iso(0)))
        d.add(Task(title="later", done=False, due_date=_iso(5)))
        d.add(Task(title="someday", done=False))
        # reminder unfired for now
        d.add(Reminder(text="call", trigger_at=datetime.utcnow(), fired=False))
        # subs: one within 7d, one far out (excluded)
        d.add(Subscription(name="netflix", price=9.0, currency="$", cycle="monthly",
                           active=True, next_due=_iso(3)))
        d.add(Subscription(name="far", price=1.0, currency="$", cycle="yearly",
                           active=True, next_due=_iso(20)))
        # day-events: one within 3d, one far out (excluded)
        d.add(DayEvent(name="trip", date=_iso(2), repeat="none"))
        d.add(DayEvent(name="far day", date=_iso(10), repeat="none"))
        d.commit()
        d.close()

    def test_today_golden(self):
        self._seed()
        r = self.client.get("/api/today", params={"date": date.today().isoformat()}).json()

        self.assertEqual(r["date"], date.today().isoformat())

        # events: timed sorted by time, all-day last
        evs = [(e["title"], e["time"], e["all_day"]) for e in r["events"]]
        self.assertEqual(evs, [
            ("weekly sync", "09:00", False),
            ("lunch", "12:00", False),
            ("holiday", "", True),
        ])

        # tasks
        self.assertEqual([t["title"] for t in r["tasks"]["overdue"]], ["rent"])
        self.assertEqual(r["tasks"]["overdue"][0]["priority"], 1)
        self.assertEqual(r["tasks"]["overdue"][0]["due"], _iso(-2))
        self.assertEqual([t["title"] for t in r["tasks"]["due_today"]], ["standup"])
        self.assertEqual(r["tasks"]["open_count"], 4)

        # reminders
        self.assertEqual([x["text"] for x in r["reminders"]], ["call"])

        # subscriptions renewing within 7d
        self.assertEqual([(s["name"], s["in_days"]) for s in r["renewing"]], [("netflix", 3)])

        # day-events within 3d
        self.assertEqual([(x["name"], x["in_days"]) for x in r["day_events"]], [("trip", 2)])

        # keys present
        for k in ("date", "events", "tasks", "reminders", "renewing", "day_events", "recent_docs"):
            self.assertIn(k, r)
