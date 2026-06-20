from core.database import Account, RecurringTxn
from tests._client import ApiTest


class MoneyInvestTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        self.acct = Account(name="Checking", kind="checking", currency="$", opening=1000.0)
        db.add(self.acct)
        db.commit()
        self.aid = self.acct.id
        db.close()

    def _txn(self, amount, category="", payee="", date="2026-06-10"):
        return self.client.post(
            "/api/money/transactions",
            json={
                "account_id": self.aid,
                "date": date,
                "amount": amount,
                "category": category,
                "payee": payee,
            },
        ).json()

    def _recurring(self, amount, cycle="monthly", next_date="2026-06-20"):
        db = self.db()
        r = RecurringTxn(
            account_id=self.aid,
            amount=amount,
            cycle=cycle,
            next_date=next_date,
            active=True,
            payee="rent",
        )
        db.add(r)
        db.commit()
        db.close()

    # ---- forecast ----
    def test_forecast_projects_recurring(self):
        self._recurring(-200, "monthly", "2026-06-20")
        d = self.client.get(
            "/api/money/forecast", params={"month": "2026-06", "as_of": "2026-06-01"}
        ).json()
        self.assertEqual(d["start_balance"], 1000.0)
        self.assertEqual(d["projected"], 800.0)

    def test_forecast_no_recurring_flat(self):
        d = self.client.get(
            "/api/money/forecast", params={"month": "2026-06", "as_of": "2026-06-01"}
        ).json()
        self.assertEqual(d["projected"], d["start_balance"])

    def test_forecast_line_reaches_month_end(self):
        self._recurring(-200, "monthly", "2026-06-20")
        d = self.client.get(
            "/api/money/forecast", params={"month": "2026-06", "as_of": "2026-06-01"}
        ).json()
        self.assertEqual(d["line"][-1]["date"], "2026-06-30")
        self.assertEqual(d["line"][-1]["balance"], 800.0)

    # ---- net-worth history ----
    def test_networth_history_length(self):
        d = self.client.get(
            "/api/money/networth-history", params={"months": 6, "as_of": "2026-06-15"}
        ).json()
        self.assertEqual(len(d), 6)

    def test_networth_history_rises_with_income(self):
        self._txn(500, "salary", date="2026-04-10")
        d = self.client.get(
            "/api/money/networth-history", params={"months": 6, "as_of": "2026-06-15"}
        ).json()
        by = {x["month"]: x["net_worth"] for x in d}
        self.assertEqual(by["2026-03"], 1000.0)
        self.assertEqual(by["2026-04"], 1500.0)
        self.assertGreaterEqual(d[-1]["net_worth"], d[0]["net_worth"])

    # ---- holdings ----
    def test_holding_value_and_gain(self):
        h = self.client.post(
            "/api/money/holdings",
            json={"symbol": "AAPL", "qty": 10, "cost_basis": 100, "price": 150},
        ).json()
        self.assertEqual(h["value"], 1500.0)
        self.assertEqual(h["cost"], 1000.0)
        self.assertEqual(h["gain"], 500.0)

    def test_holding_crud(self):
        h = self.client.post(
            "/api/money/holdings",
            json={"symbol": "MSFT", "qty": 5, "cost_basis": 200, "price": 200},
        ).json()
        self.assertTrue(
            any(
                x["symbol"] == "MSFT"
                for x in self.client.get("/api/money/holdings").json()["holdings"]
            )
        )
        self.client.patch(f"/api/money/holdings/{h['id']}", json={"price": 250})
        rows = self.client.get("/api/money/holdings").json()["holdings"]
        self.assertEqual(next(x for x in rows if x["id"] == h["id"])["gain"], 250.0)
        self.client.delete(f"/api/money/holdings/{h['id']}")
        self.assertFalse(self.client.get("/api/money/holdings").json()["holdings"])

    def test_holdings_totals(self):
        self.client.post(
            "/api/money/holdings", json={"symbol": "A", "qty": 1, "cost_basis": 10, "price": 20}
        )
        self.client.post(
            "/api/money/holdings", json={"symbol": "B", "qty": 2, "cost_basis": 5, "price": 5}
        )
        d = self.client.get("/api/money/holdings").json()
        self.assertEqual(d["totals"]["value"], 30.0)  # 20 + 10
        self.assertEqual(d["totals"]["cost"], 20.0)  # 10 + 10
        self.assertEqual(d["totals"]["gain"], 10.0)

    # ---- watches + alerts ----
    def test_watch_crud(self):
        w = self.client.post(
            "/api/money/watches", json={"kind": "category", "value": "food"}
        ).json()
        self.assertTrue(self.client.get("/api/money/watches").json()["watches"])
        self.client.delete(f"/api/money/watches/{w['id']}")
        self.assertFalse(self.client.get("/api/money/watches").json()["watches"])

    def test_alerts_large_purchase(self):
        self._txn(-500, "shopping", "TV", date="2026-06-10")
        d = self.client.get(
            "/api/money/alerts", params={"month": "2026-06", "big": 100, "as_of": "2026-06-15"}
        ).json()
        self.assertTrue(any(a["payee"] == "TV" for a in d["large_purchases"]))

    def test_alerts_upcoming_bill(self):
        self._recurring(-100, "monthly", "2026-06-18")
        d = self.client.get(
            "/api/money/alerts", params={"month": "2026-06", "as_of": "2026-06-15"}
        ).json()
        self.assertTrue(d["upcoming_bills"])

    def test_alerts_watch_hit(self):
        self.client.post("/api/money/watches", json={"kind": "category", "value": "food"})
        self._txn(-50, "food", "Cafe", date="2026-06-10")
        d = self.client.get(
            "/api/money/alerts", params={"month": "2026-06", "as_of": "2026-06-15"}
        ).json()
        self.assertTrue(any(a["payee"] == "Cafe" for a in d["watch_hits"]))
