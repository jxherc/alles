from datetime import datetime

from core.database import Account, Transaction
from tests._client import ApiTest


class MoneyEnvelopeTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        self.acct = Account(name="Checking", kind="checking", currency="$", opening=0.0)
        db.add(self.acct)
        db.commit()
        self.aid = self.acct.id
        db.close()

    def _txn(self, amount, category="", date="2026-06-10"):
        return self.client.post(
            "/api/money/transactions",
            json={"account_id": self.aid, "date": date, "amount": amount, "category": category},
        ).json()

    def _assign(self, category, amount, month="2026-06"):
        body = {"category": category, "amount": amount}
        if month is not None:
            body["month"] = month
        return self.client.put("/api/money/envelope/assign", json=body)

    def _env(self, month="2026-06"):
        return self.client.get("/api/money/envelope", params={"month": month}).json()

    def _cat(self, env, name):
        return next((c for c in env["categories"] if c["category"] == name), None)

    def test_assign_upserts(self):
        self._assign("food", 200)
        c = self._cat(self._env(), "food")
        self.assertIsNotNone(c)
        self.assertEqual(c["assigned"], 200.0)

    def test_assign_replaces_same_month(self):
        self._assign("food", 200)
        self._assign("food", 150)
        self.assertEqual(self._cat(self._env(), "food")["assigned"], 150.0)

    def test_envelope_lists_categories(self):
        self._txn(-50, "food")
        self._assign("rent", 300)
        env = self._env()
        names = {c["category"] for c in env["categories"]}
        self.assertIn("food", names)
        self.assertIn("rent", names)

    def test_available_includes_assignment_minus_spent(self):
        self._assign("food", 200)
        self._txn(-50, "food")
        self.assertEqual(self._cat(self._env(), "food")["available"], 150.0)

    def test_available_rolls_over_prev_month(self):
        self._assign("food", 100, month="2026-05")
        self._assign("food", 50, month="2026-06")
        self.assertEqual(self._cat(self._env("2026-06"), "food")["available"], 150.0)

    def test_to_be_budgeted_is_income_minus_assigned(self):
        self._txn(1000, "salary", date="2026-06-05")
        self._assign("food", 200)
        self._assign("rent", 300)
        env = self._env()
        self.assertEqual(env["to_be_budgeted"], 500.0)

    def test_target_upsert_and_funded(self):
        self.client.put(
            "/api/money/envelope/target",
            json={"category": "vacation", "amount": 1000, "target_date": "2026-12-01"},
        )
        self._assign("vacation", 250)
        c = self._cat(self._env(), "vacation")
        self.assertIsNotNone(c["target"])
        self.assertEqual(c["target"]["amount"], 1000.0)
        self.assertAlmostEqual(c["target"]["funded"], 0.25, places=2)

    def test_target_delete_on_zero(self):
        self.client.put("/api/money/envelope/target", json={"category": "vacation", "amount": 500})
        self.client.put("/api/money/envelope/target", json={"category": "vacation", "amount": 0})
        self._assign("vacation", 10)
        self.assertIsNone(self._cat(self._env(), "vacation")["target"])

    def test_age_of_money_simple_gap(self):
        self._txn(100, "salary", date="2026-06-01")
        self._txn(-50, "food", date="2026-06-11")
        d = self.client.get("/api/money/age-of-money").json()
        self.assertEqual(d["age"], 10)

    def test_age_of_money_none_when_no_income(self):
        self._txn(-50, "food", date="2026-06-11")
        d = self.client.get("/api/money/age-of-money").json()
        self.assertIsNone(d["age"])

    def test_age_of_money_survives_junk_date(self):
        # a transaction with a junk date (e.g. from a sloppy ofx/csv import) used to
        # 500 the endpoint via an unguarded date.fromisoformat — now it's skipped
        self._txn(100, "salary", date="2026-06-01")
        self._txn(-50, "food", date="2026-06-11")
        db = self.db()
        db.add(Transaction(account_id=self.aid, date="2026-13-99", amount=-9.0, category="x"))
        db.commit()
        db.close()
        r = self.client.get("/api/money/age-of-money")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["age"], 10)  # the valid pair still computes

    def test_envelope_spent_honors_splits(self):
        t = self._txn(-100, "shopping")
        self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={"splits": [{"category": "groceries", "amount": 60}]},
        )
        c = self._cat(self._env(), "groceries")
        self.assertIsNotNone(c)
        self.assertEqual(c["spent"], 60.0)

    def test_assign_unknown_month_defaults_current(self):
        month = datetime.utcnow().strftime("%Y-%m")
        self._assign("misc", 42, month=None)
        c = self._cat(self._env(month), "misc")
        self.assertIsNotNone(c)
        self.assertEqual(c["assigned"], 42.0)
