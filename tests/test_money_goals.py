from core.database import Account
from tests._client import ApiTest


class MoneyGoalsTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        self.usd = Account(name="US", kind="checking", currency="USD", opening=100.0)
        self.eur = Account(name="EU", kind="savings", currency="EUR", opening=100.0)
        db.add_all([self.usd, self.eur])
        db.commit()
        self.usd_id = self.usd.id
        db.close()

    def _txn(self, amount, category="", payee="", date="2026-06-10"):
        return self.client.post(
            "/api/money/transactions",
            json={
                "account_id": self.usd_id,
                "date": date,
                "amount": amount,
                "category": category,
                "payee": payee,
            },
        ).json()

    # ---- goals ----
    def test_goal_crud(self):
        g = self.client.post(
            "/api/money/goals",
            json={"name": "Emergency", "kind": "savings", "target": 1000, "current": 0},
        ).json()
        self.assertTrue(
            any(
                x["name"] == "Emergency"
                for x in self.client.get("/api/money/goals").json()["goals"]
            )
        )
        self.client.patch(f"/api/money/goals/{g['id']}", json={"current": 500})
        rows = self.client.get("/api/money/goals").json()["goals"]
        self.assertEqual(next(x for x in rows if x["id"] == g["id"])["current"], 500.0)
        self.client.delete(f"/api/money/goals/{g['id']}")
        self.assertFalse(self.client.get("/api/money/goals").json()["goals"])

    def test_goal_savings_progress(self):
        g = self.client.post(
            "/api/money/goals",
            json={"name": "S", "kind": "savings", "target": 1000, "current": 250},
        ).json()
        self.assertAlmostEqual(g["progress"], 0.25, places=3)

    def test_goal_debt_progress(self):
        g = self.client.post(
            "/api/money/goals",
            json={"name": "Loan", "kind": "debt", "target": 1000, "current": 400},
        ).json()
        # paid down 600 of 1000
        self.assertAlmostEqual(g["progress"], 0.6, places=3)

    def test_goal_eta_months(self):
        g = self.client.post(
            "/api/money/goals",
            json={"name": "S", "kind": "savings", "target": 1000, "current": 250, "monthly": 150},
        ).json()
        self.assertEqual(g["eta_months"], 5)  # ceil(750/150)

    # ---- reports ----
    def test_report_range_totals(self):
        self._txn(1000, "salary", date="2026-06-05")
        self._txn(-200, "food", date="2026-06-12")
        d = self.client.get(
            "/api/money/report", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()
        self.assertEqual(d["income"], 1000.0)
        self.assertEqual(d["expense"], 200.0)
        self.assertEqual(d["net"], 800.0)

    def test_report_by_category(self):
        self._txn(-50, "food", date="2026-06-12")
        self._txn(-30, "food", date="2026-06-14")
        self._txn(-20, "fun", date="2026-06-15")
        d = self.client.get(
            "/api/money/report", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()
        cats = {c[0]: c[1] for c in d["by_category"]}
        self.assertEqual(cats["food"], 80.0)
        self.assertEqual(cats["fun"], 20.0)

    def test_report_excludes_out_of_range(self):
        self._txn(-50, "food", date="2026-05-30")
        self._txn(-99, "food", date="2026-06-10")
        d = self.client.get(
            "/api/money/report", params={"start": "2026-06-01", "end": "2026-06-30"}
        ).json()
        self.assertEqual(d["expense"], 99.0)

    def test_report_csv_export(self):
        self._txn(-50, "food", payee="Cafe", date="2026-06-10")
        r = self.client.get(
            "/api/money/report/export.csv", params={"start": "2026-06-01", "end": "2026-06-30"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers.get("content-type", ""))
        self.assertIn("Cafe", r.text)

    # ---- multi-currency net worth ----
    def test_networth_base_rollup(self):
        d = self.client.get("/api/money/networth-base", params={"base": "USD"}).json()
        self.assertEqual(d["base"], "USD")
        # 100 USD + 100 EUR→USD (100/0.92 = 108.70) = 208.70
        self.assertAlmostEqual(d["net_worth"], 208.70, delta=0.05)
