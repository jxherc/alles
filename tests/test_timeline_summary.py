from datetime import date, timedelta

from core.database import Account, Task, Transaction
from tests._client import ApiTest


class TimelineSummaryTests(ApiTest):
    def setUp(self):
        super().setUp()
        d = self.db()
        acct = Account(name="Checking", opening=0)
        d.add(acct)
        d.flush()
        today = date.today().isoformat()
        yest = (date.today() - timedelta(days=1)).isoformat()
        # 3 money today, 1 money yesterday
        for i in range(3):
            d.add(Transaction(account_id=acct.id, date=today, amount=-(i + 1), payee=f"p{i}"))
        d.add(Transaction(account_id=acct.id, date=yest, amount=-9, payee="y"))
        # 1 task added today
        d.add(Task(title="a task", done=False))
        d.commit()
        d.close()

    def _sum(self, **params):
        # scope to DB-backed sources so filesystem sources (docs/agent) in the real
        # data dir can't leak into these deterministic counts
        return self.client.get(
            "/api/timeline/summary", params={"days": 30, "types": "money,task", **params}
        ).json()

    def test_total_count(self):
        # 4 money + 1 task = 5
        self.assertEqual(self._sum()["total"], 5)

    def test_by_type_counts(self):
        d = {x["type"]: x["count"] for x in self._sum()["by_type"]}
        self.assertEqual(d["money"], 4)
        self.assertEqual(d["task"], 1)

    def test_by_type_sorted_desc(self):
        counts = [x["count"] for x in self._sum()["by_type"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_busiest_day(self):
        # today has 3 money + 1 task = 4, yesterday has 1 → today is busiest
        busiest = self._sum()["busiest"]
        self.assertEqual(busiest["date"], date.today().isoformat())
        self.assertEqual(busiest["count"], 4)

    def test_busiest_none_when_empty(self):
        # restrict to a type with no events
        r = self._sum(types="mail")
        self.assertIsNone(r["busiest"])
        self.assertEqual(r["total"], 0)

    def test_types_filter(self):
        r = self._sum(types="task")
        self.assertEqual(r["total"], 1)
        self.assertEqual([x["type"] for x in r["by_type"]], ["task"])

    def test_days_window_excludes_old(self):
        d = self.db()
        acct = d.query(Account).first()
        old = (date.today() - timedelta(days=60)).isoformat()
        d.add(Transaction(account_id=acct.id, date=old, amount=-5, payee="old"))
        d.commit()
        d.close()
        self.assertEqual(self._sum(days=30)["total"], 5)  # old one excluded

    def test_response_shape(self):
        r = self._sum()
        for k in ("days", "total", "by_type", "busiest"):
            self.assertIn(k, r)

    def test_empty_by_type_when_no_events(self):
        r = self._sum(types="photo")
        self.assertEqual(r["by_type"], [])

    def test_days_default(self):
        self.assertGreater(self._sum()["days"], 0)
