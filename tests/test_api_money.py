from tests._client import ApiTest


class MoneyApiTest(ApiTest):
    def test_tag_budget_reports_tag_spend(self):
        from datetime import date

        a = self.client.post("/api/money/accounts", json={"name": "chk"}).json()
        today = date.today().isoformat()
        self.client.post(
            "/api/money/transactions",
            json={"account_id": a["id"], "date": today, "amount": -24.0, "tags": "coffee"},
        )
        self.client.post("/api/money/budgets", json={"tag": "coffee", "limit_amt": 40})
        s = self.client.get("/api/money/summary").json()
        b = next(x for x in s["budgets"] if x.get("tag") == "coffee")
        self.assertEqual(b["spent"], 24.0)  # was 0.0 with a blank label
        self.assertEqual(b["category"], "coffee")

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

    def test_patch_txn_rejects_non_finite_amount(self):
        # update_txn must reject inf/nan like create does, else the amount silently becomes $0
        a = self.client.post("/api/money/accounts", json={"name": "chk"}).json()
        t = self.client.post(
            "/api/money/transactions",
            json={"account_id": a["id"], "date": "2026-06-01", "amount": -20.0},
        ).json()
        r = self.client.patch(
            f"/api/money/transactions/{t['id']}",
            content='{"amount": 1e999}',  # parses to inf
            headers={"content-type": "application/json"},
        )
        self.assertEqual(r.status_code, 400)

    def test_patch_txn_rejects_unknown_account(self):
        a = self.client.post("/api/money/accounts", json={"name": "chk2"}).json()
        t = self.client.post(
            "/api/money/transactions",
            json={"account_id": a["id"], "date": "2026-06-01", "amount": -5.0},
        ).json()
        r = self.client.patch(
            f"/api/money/transactions/{t['id']}", json={"account_id": "ghost"}
        )
        self.assertEqual(r.status_code, 400)

    def test_summary_and_delete(self):
        a = self.client.post("/api/money/accounts", json={"name": "x"}).json()
        self.assertEqual(self.client.get("/api/money/summary").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/money/accounts/{a['id']}").status_code, 200)

    def test_delete_account_removes_it_from_list(self):
        a = self.client.post("/api/money/accounts", json={"name": "temp"}).json()
        self.client.delete(f"/api/money/accounts/{a['id']}")
        ids = [acc["id"] for acc in self.client.get("/api/money/accounts").json()]
        self.assertNotIn(a["id"], ids)

    def test_delete_unknown_account_404(self):
        r = self.client.delete("/api/money/accounts/doesnotexist")
        self.assertEqual(r.status_code, 404)

    def test_update_account_name(self):
        a = self.client.post("/api/money/accounts", json={"name": "old"}).json()
        r = self.client.patch(f"/api/money/accounts/{a['id']}", json={"name": "new"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "new")

    def test_transfer_creates_two_linked_legs(self):
        a = self.client.post("/api/money/accounts", json={"name": "src", "opening": 500.0}).json()
        b = self.client.post("/api/money/accounts", json={"name": "dst"}).json()
        r = self.client.post(
            "/api/money/transfer",
            json={
                "from_account": a["id"],
                "to_account": b["id"],
                "amount": 100.0,
                "date": "2026-06-01",
            },
        )
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("transfer_id", d)
        self.assertEqual(d["from"]["amount"], -100.0)
        self.assertEqual(d["to"]["amount"], 100.0)

    def test_transfer_same_account_400(self):
        a = self.client.post("/api/money/accounts", json={"name": "only"}).json()
        r = self.client.post(
            "/api/money/transfer",
            json={
                "from_account": a["id"],
                "to_account": a["id"],
                "amount": 10.0,
                "date": "2026-06-01",
            },
        )
        self.assertEqual(r.status_code, 400)

    def test_category_rule_auto_applied(self):
        a = self.client.post("/api/money/accounts", json={"name": "bank"}).json()
        self.client.post("/api/money/rules", json={"match": "starbucks", "category": "coffee"})
        t = self.client.post(
            "/api/money/transactions",
            json={
                "account_id": a["id"],
                "date": "2026-06-01",
                "amount": -5.0,
                "payee": "Starbucks Downtown",
            },
        ).json()
        self.assertEqual(t["category"], "coffee")

    def test_reconcile_shows_difference(self):
        a = self.client.post("/api/money/accounts", json={"name": "chk", "opening": 200.0}).json()
        aid = a["id"]
        self.client.post(
            "/api/money/transactions",
            json={"account_id": aid, "date": "2026-06-01", "amount": -50.0, "cleared": True},
        )
        r = self.client.get(f"/api/money/accounts/{aid}/reconcile?statement=150.0")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["cleared_balance"], 150.0)
        self.assertTrue(d["reconciled"])
