from datetime import date, timedelta

from core.database import Subscription
from tests._client import ApiTest


class SubForecastTests(ApiTest):
    def _sub(self, **kw):
        d = self.db()
        s = Subscription(
            name=kw.get("name", "S"),
            price=kw.get("price", 10.0),
            cycle=kw.get("cycle", "monthly"),
            cycle_days=kw.get("cycle_days", 30),
            next_due=kw.get("next_due", date.today().isoformat()),
            active=kw.get("active", True),
        )
        d.add(s)
        d.commit()
        d.close()

    def _fc(self, months=6):
        return self.client.get(f"/api/subscriptions/forecast?months={months}").json()

    def test_forecast_length(self):
        self._sub()
        self.assertEqual(len(self._fc(6)["forecast"]), 6)

    def test_months_param(self):
        self._sub()
        self.assertEqual(len(self._fc(3)["forecast"]), 3)

    def test_monthly_each_month(self):
        self._sub(price=10.0, cycle="monthly", next_due=date.today().isoformat())
        fc = self._fc(6)
        self.assertTrue(all(m["total"] == 10.0 for m in fc["forecast"]))
        self.assertEqual(fc["total"], 60.0)

    def test_yearly_once_in_window(self):
        self._sub(price=120.0, cycle="yearly", next_due=date.today().isoformat())
        fc = self._fc(6)
        self.assertEqual(fc["total"], 120.0)
        self.assertEqual(fc["forecast"][0]["total"], 120.0)
        self.assertEqual(fc["forecast"][1]["total"], 0.0)

    def test_quarterly_two_in_six_months(self):
        self._sub(price=30.0, cycle="quarterly", next_due=date.today().isoformat())
        self.assertEqual(self._fc(6)["total"], 60.0)

    def test_weekly_multiple_per_month(self):
        self._sub(price=5.0, cycle="weekly", next_due=date.today().isoformat())
        fc = self._fc(6)
        self.assertGreater(fc["total"], 100.0)  # ~26 weeks * 5

    def test_paused_excluded(self):
        self._sub(price=10.0, active=False, next_due=date.today().isoformat())
        self.assertEqual(self._fc(6)["total"], 0.0)

    def test_grand_total_sums_months(self):
        self._sub(price=10.0, cycle="monthly")
        self._sub(price=7.0, cycle="monthly")
        fc = self._fc(6)
        self.assertEqual(round(sum(m["total"] for m in fc["forecast"]), 2), fc["total"])

    def test_overdue_not_double_counted(self):
        old = (date.today() - timedelta(days=70)).isoformat()
        self._sub(price=10.0, cycle="monthly", next_due=old)
        fc = self._fc(6)
        # future charges only — each month exactly one, none doubled from the backlog
        self.assertTrue(all(m["total"] in (0.0, 10.0) for m in fc["forecast"]))
        self.assertLessEqual(fc["total"], 60.0)

    def test_empty_no_subs(self):
        fc = self._fc(6)
        self.assertEqual(fc["total"], 0.0)
        self.assertEqual(fc["currency"], "$")
        self.assertEqual(len(fc["forecast"]), 6)
