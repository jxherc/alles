import unittest
from datetime import date, timedelta

from core.database import Subscription
from routes.subscriptions import _advance
from tests._client import ApiTest


class AdvanceHelperTests(unittest.TestCase):
    def test_weekly(self):
        self.assertEqual(_advance(date(2026, 6, 18), "weekly", 30), date(2026, 6, 25))

    def test_monthly(self):
        self.assertEqual(_advance(date(2026, 6, 18), "monthly", 30), date(2026, 7, 18))

    def test_quarterly(self):
        self.assertEqual(_advance(date(2026, 6, 18), "quarterly", 30), date(2026, 9, 18))

    def test_yearly(self):
        self.assertEqual(_advance(date(2026, 6, 18), "yearly", 30), date(2027, 6, 18))

    def test_custom_days(self):
        self.assertEqual(_advance(date(2026, 6, 18), "custom", 45), date(2026, 8, 2))

    def test_month_end_clamps(self):
        self.assertEqual(_advance(date(2026, 1, 31), "monthly", 30), date(2026, 2, 28))


class MarkPaidApiTests(ApiTest):
    def _sub(self, **kw):
        d = self.db()
        s = Subscription(
            name=kw.get("name", "Sub"),
            price=kw.get("price", 10.0),
            cycle=kw.get("cycle", "monthly"),
            cycle_days=kw.get("cycle_days", 30),
            next_due=kw["next_due"],
            active=True,
        )
        d.add(s)
        d.commit()
        sid = s.id
        d.close()
        return sid

    def _due(self, sid):
        return self.client.get("/api/subscriptions").json()
        # not used directly

    def _paid(self, sid):
        return self.client.post(f"/api/subscriptions/{sid}/paid").json()["next_due"]

    def test_yearly_advances_one_year_not_month(self):
        # anchor on today so the test can't rot as the real date moves past a hardcoded due
        base = date.today()
        sid = self._sub(cycle="yearly", next_due=base.isoformat())
        self.assertEqual(self._paid(sid), _advance(base, "yearly", 0).isoformat())

    def test_weekly_advances_week(self):
        base = date.today()
        sid = self._sub(cycle="weekly", next_due=base.isoformat())
        self.assertEqual(self._paid(sid), (base + timedelta(days=7)).isoformat())

    def test_ontime_monthly_advances_one_month(self):
        today = date.today()
        sid = self._sub(cycle="monthly", next_due=today.isoformat())
        nxt = date.fromisoformat(self._paid(sid))
        self.assertGreater(nxt, today)
        self.assertLessEqual((nxt - today).days, 31)

    def test_overdue_rolls_to_future(self):
        # 3 months overdue monthly — one click must land strictly in the future
        old = (date.today() - timedelta(days=95)).isoformat()
        sid = self._sub(cycle="monthly", next_due=old)
        nxt = date.fromisoformat(self._paid(sid))
        self.assertGreater(nxt, date.today())

    def test_overdue_weekly_rolls_to_future(self):
        old = (date.today() - timedelta(days=60)).isoformat()
        sid = self._sub(cycle="weekly", next_due=old)
        nxt = date.fromisoformat(self._paid(sid))
        self.assertGreater(nxt, date.today())

    def test_future_due_rejected_not_due(self):
        # paying early (not due yet) must be refused — no infinite advancing
        due = date.today() + timedelta(days=5)
        sid = self._sub(cycle="monthly", next_due=due.isoformat())
        r = self.client.post(f"/api/subscriptions/{sid}/paid")
        self.assertEqual(r.status_code, 400)
        # unchanged
        rows = self.client.get("/api/subscriptions").json()["subscriptions"]
        self.assertEqual([s for s in rows if s["id"] == sid][0]["next_due"], due.isoformat())


if __name__ == "__main__":
    unittest.main()
