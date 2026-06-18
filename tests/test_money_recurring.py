from datetime import date, timedelta

from tests._client import ApiTest


class MoneyRecurringTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.acct = self.client.post(
            "/api/money/accounts", json={"name": "Checking", "opening": 1000}
        ).json()["id"]

    def _mk(self, **kw):
        body = {
            "account_id": self.acct,
            "amount": -50,
            "category": "rent",
            "payee": "Landlord",
            "cycle": "monthly",
            "next_date": date.today().isoformat(),
        }
        body.update(kw)
        return self.client.post("/api/money/recurring", json=body)

    def _txns(self):
        return self.client.get("/api/money/transactions").json()

    def test_create_recurring(self):
        r = self._mk()
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["id"])
        self.assertEqual(j["payee"], "Landlord")
        self.assertEqual(j["cycle"], "monthly")

    def test_list_recurring(self):
        self._mk(payee="Spotify")
        names = [x["payee"] for x in self.client.get("/api/money/recurring").json()]
        self.assertIn("Spotify", names)

    def test_patch_recurring(self):
        rid = self._mk().json()["id"]
        self.client.patch(f"/api/money/recurring/{rid}", json={"amount": -99})
        got = [x for x in self.client.get("/api/money/recurring").json() if x["id"] == rid][0]
        self.assertEqual(got["amount"], -99)

    def test_delete_recurring(self):
        rid = self._mk().json()["id"]
        self.assertEqual(self.client.delete(f"/api/money/recurring/{rid}").status_code, 200)
        self.assertEqual(self.client.get("/api/money/recurring").json(), [])

    def test_post_due_creates_txn(self):
        self._mk(next_date=date.today().isoformat(), payee="Rent")
        posted = [t for t in self._txns() if t["payee"] == "Rent"]
        self.assertEqual(len(posted), 1)

    def test_post_due_idempotent(self):
        self._mk(next_date=date.today().isoformat(), payee="Rent")
        self._txns()  # first load posts
        self._txns()  # second load must not double-post
        posted = [t for t in self._txns() if t["payee"] == "Rent"]
        self.assertEqual(len(posted), 1)

    def test_post_due_advances_next_date(self):
        rid = self._mk(next_date=date.today().isoformat(), cycle="monthly").json()["id"]
        self._txns()  # trigger posting
        got = [x for x in self.client.get("/api/money/recurring").json() if x["id"] == rid][0]
        self.assertGreater(got["next_date"], date.today().isoformat())

    def test_post_catches_up_overdue(self):
        # weekly, starting 21 days ago → occurrences at -21,-14,-7,0 = 4 posts
        start = (date.today() - timedelta(days=21)).isoformat()
        self._mk(cycle="weekly", next_date=start, payee="Gym")
        posted = [t for t in self._txns() if t["payee"] == "Gym"]
        self.assertEqual(len(posted), 4)

    def test_inactive_not_posted(self):
        rid = self._mk(payee="Paused").json()["id"]
        self.client.patch(f"/api/money/recurring/{rid}", json={"active": False})
        posted = [t for t in self._txns() if t["payee"] == "Paused"]
        self.assertEqual(len(posted), 0)

    def test_posted_txn_has_fields(self):
        self._mk(next_date=date.today().isoformat(), amount=-123.45, category="rent", payee="LL")
        t = [t for t in self._txns() if t["payee"] == "LL"][0]
        self.assertEqual(t["amount"], -123.45)
        self.assertEqual(t["category"], "rent")
        self.assertEqual(t["date"], date.today().isoformat())

    def test_unknown_account_rejected(self):
        self.assertEqual(self._mk(account_id="nope").status_code, 400)

    def test_invalid_cycle_rejected(self):
        self.assertEqual(self._mk(cycle="hourly").status_code, 400)
