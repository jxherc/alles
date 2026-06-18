from tests._client import ApiTest


class MoneyApiTest(ApiTest):
    def test_account_balance_reflects_transactions(self):
        a = self.client.post(
            "/api/money/accounts", json={"name": "checking", "opening": 100.0}
        ).json()
        self.assertEqual(a["balance"], 100.0)
        aid = a["id"]
        self.client.post(
            "/api/money/transactions",
            json={"account_id": aid, "date": "2026-06-01", "amount": 50.0},
        )
        self.client.post(
            "/api/money/transactions",
            json={"account_id": aid, "date": "2026-06-02", "amount": -30.0},
        )
        accts = self.client.get("/api/money/accounts").json()
        self.assertEqual(accts[0]["balance"], 120.0)  # 100 + 50 - 30

    def test_txn_unknown_account_400(self):
        r = self.client.post(
            "/api/money/transactions",
            json={"account_id": "nope", "date": "2026-06-01", "amount": 5},
        )
        self.assertEqual(r.status_code, 400)

    def test_summary_and_delete(self):
        a = self.client.post("/api/money/accounts", json={"name": "x"}).json()
        self.assertEqual(self.client.get("/api/money/summary").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/money/accounts/{a['id']}").status_code, 200)
