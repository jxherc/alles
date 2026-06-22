"""briefing must keep its digest lines after moving onto services.signals.
seeded with non-recurring, single-per-line data so ordering is unambiguous."""

from datetime import date, timedelta

from core.database import (
    Book,
    CalendarEvent,
    Habit,
    HealthEntry,
    Subscription,
    Task,
)
from services.briefing import compose_briefing
from tests._client import ApiTest


def _iso(n):
    return (date.today() + timedelta(days=n)).isoformat()


class BriefingSignalsTests(ApiTest):
    def _seed(self):
        d = self.db()
        d.add(CalendarEvent(title="lunch", start_dt=_iso(0) + "T12:00", all_day=False))
        d.add(Task(title="rent", done=False, due_date=_iso(-2)))
        d.add(Task(title="standup", done=False, due_date=_iso(0)))
        d.add(Habit(name="floss", archived=False, cadence="daily"))
        d.add(Book(title="dune", status="reading"))
        d.add(Subscription(name="netflix", price=9.0, currency="$", cycle="monthly",
                           active=True, next_due=_iso(0), remind_days=1))
        d.add(HealthEntry(kind="weight", value=70.0, unit="kg", date=_iso(0)))
        d.commit()
        d.close()

    def test_briefing_lines(self):
        self._seed()
        d = self.db()
        try:
            b = compose_briefing(d, date.today())
        finally:
            d.close()
        self.assertEqual(b["lines"], [
            "1 event today — lunch",
            "2 due tasks — rent, standup",
            "habits left — floss",
            "reading — dune",
            "renewing soon — netflix ($9)",
            f"weight — 70 kg (last logged {_iso(0)})",
        ])
        self.assertTrue(b["has_content"])
        self.assertEqual(b["title"], f"your {date.today():%A} briefing")

    def test_empty_is_quiet(self):
        d = self.db()
        try:
            b = compose_briefing(d, date.today())
        finally:
            d.close()
        self.assertFalse(b["has_content"])
        self.assertEqual(b["lines"], [])

    def test_open_fallback_when_no_due(self):
        d = self.db()
        d.add(Task(title="future", done=False, due_date=_iso(9)))
        d.add(Task(title="nodue", done=False))
        d.commit()
        d.close()
        d2 = self.db()
        try:
            b = compose_briefing(d2, date.today())
        finally:
            d2.close()
        # no due/overdue tasks -> falls back to listing open tasks
        line = [x for x in b["lines"] if "task" in x]
        self.assertEqual(len(line), 1)
        self.assertIn("open task", line[0])
