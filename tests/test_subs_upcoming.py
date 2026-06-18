from datetime import date, timedelta

from core.database import Subscription
from tests._client import ApiTest


def _due_in(n):
    return (date.today() + timedelta(days=n)).isoformat()


class SubUpcomingTests(ApiTest):
    def _seed(self, **kw):
        d = self.db()
        defaults = dict(name="X", price=5.0, currency="$", cycle="monthly", active=True)
        defaults.update(kw)
        d.add(Subscription(**defaults))
        d.commit()
        d.close()

    def _get(self, days=None):
        params = {} if days is None else {"days": days}
        return self.client.get("/api/subscriptions/upcoming", params=params).json()

    def test_includes_due_within_window(self):
        self._seed(name="Soon", next_due=_due_in(3))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertIn("Soon", names)

    def test_excludes_beyond_window(self):
        self._seed(name="Far", next_due=_due_in(20))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertNotIn("Far", names)

    def test_excludes_paused(self):
        self._seed(name="Paused", next_due=_due_in(2), active=False)
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertNotIn("Paused", names)

    def test_excludes_overdue(self):
        self._seed(name="Overdue", next_due=_due_in(-3))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertNotIn("Overdue", names)

    def test_today_included(self):
        self._seed(name="Today", next_due=_due_in(0))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertIn("Today", names)

    def test_boundary_inclusive(self):
        self._seed(name="Edge", next_due=_due_in(7))
        names = [i["name"] for i in self._get(7)["items"]]
        self.assertIn("Edge", names)

    def test_sorted_soonest_first(self):
        self._seed(name="B", next_due=_due_in(5))
        self._seed(name="A", next_due=_due_in(1))
        names = [i["name"] for i in self._get(14)["items"]]
        self.assertEqual(names[:2], ["A", "B"])

    def test_total_sums_price(self):
        self._seed(name="One", price=10.0, next_due=_due_in(1))
        self._seed(name="Two", price=2.5, next_due=_due_in(2))
        self._seed(name="Out", price=99.0, next_due=_due_in(40))
        self.assertEqual(self._get(7)["total"], 12.5)

    def test_currency_from_first_item(self):
        self._seed(name="Eur", price=3.0, currency="€", next_due=_due_in(1))
        self.assertEqual(self._get(7)["currency"], "€")

    def test_empty_window(self):
        self._seed(name="Later", next_due=_due_in(60))
        r = self._get(7)
        self.assertEqual(r["items"], [])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["currency"], "$")

    def test_default_days_window(self):
        # default window should exclude something 60 days out
        self._seed(name="Default", next_due=_due_in(60))
        self.assertEqual(self._get()["items"], [])

    def test_response_shape(self):
        self._seed(name="S", next_due=_due_in(2))
        r = self._get(7)
        for k in ("days", "count", "total", "currency", "items"):
            self.assertIn(k, r)
        self.assertEqual(r["count"], len(r["items"]))
