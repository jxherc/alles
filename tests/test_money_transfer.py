from datetime import date

from tests._client import ApiTest


class MoneyTransferTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.a = self._acct("Checking", 1000)
        self.b = self._acct("Savings", 500)
        self.month = date.today().strftime("%Y-%m")

    def _acct(self, name, opening=0.0):
        return self.client.post(
            "/api/money/accounts", json={"name": name, "opening": opening}
        ).json()["id"]

    def _transfer(self, amount=200, frm=None, to=None, d=None):
        return self.client.post(
            "/api/money/transfer",
            json={
                "from_account": frm or self.a,
                "to_account": to or self.b,
                "amount": amount,
                "date": d or f"{self.month}-10",
            },
        )

    def _bal(self, aid):
        accts = self.client.get("/api/money/accounts").json()
        return [x for x in accts if x["id"] == aid][0]["balance"]

    def test_creates_two_legs(self):
        r = self._transfer(200).json()
        txns = self.client.get("/api/money/transactions").json()
        legs = [t for t in txns if t.get("transfer_id") == r["transfer_id"]]
        self.assertEqual(len(legs), 2)

    def test_legs_share_transfer_id(self):
        r = self._transfer(200).json()
        self.assertTrue(r["transfer_id"])
        self.assertEqual(r["from"]["transfer_id"], r["to"]["transfer_id"])

    def test_from_negative_to_positive(self):
        r = self._transfer(150).json()
        self.assertEqual(r["from"]["amount"], -150)
        self.assertEqual(r["to"]["amount"], 150)

    def test_category_is_transfer(self):
        r = self._transfer(50).json()
        self.assertEqual(r["from"]["category"], "transfer")
        self.assertEqual(r["to"]["category"], "transfer")

    def test_balances_move_between_accounts(self):
        self._transfer(200)
        self.assertEqual(self._bal(self.a), 800)  # 1000 - 200
        self.assertEqual(self._bal(self.b), 700)  # 500 + 200

    def test_net_worth_unchanged(self):
        before = self.client.get(f"/api/money/summary?month={self.month}").json()["net_worth"]
        self._transfer(300)
        after = self.client.get(f"/api/money/summary?month={self.month}").json()["net_worth"]
        self.assertEqual(before, after)

    def test_summary_excludes_transfer_income_expense(self):
        self._transfer(400)
        s = self.client.get(f"/api/money/summary?month={self.month}").json()
        self.assertEqual(s["income"], 0)
        self.assertEqual(s["expense"], 0)

    def test_summary_excludes_transfer_by_category(self):
        self._transfer(400)
        s = self.client.get(f"/api/money/summary?month={self.month}").json()
        cats = [c[0] for c in s["by_category"]]
        self.assertNotIn("transfer", cats)

    def test_real_expense_still_counts_alongside_transfer(self):
        self.client.post(
            "/api/money/transactions",
            json={
                "account_id": self.a,
                "date": f"{self.month}-11",
                "amount": -75,
                "category": "food",
            },
        )
        self._transfer(200)
        s = self.client.get(f"/api/money/summary?month={self.month}").json()
        self.assertEqual(s["expense"], 75)

    def test_same_account_rejected(self):
        r = self._transfer(100, frm=self.a, to=self.a)
        self.assertEqual(r.status_code, 400)

    def test_unknown_account_rejected(self):
        r = self._transfer(100, to="does-not-exist")
        self.assertEqual(r.status_code, 400)

    def test_nonpositive_amount_rejected(self):
        self.assertEqual(self._transfer(0).status_code, 400)
        self.assertEqual(self._transfer(-50).status_code, 400)

    def test_delete_removes_both_legs(self):
        tid = self._transfer(200).json()["transfer_id"]
        r = self.client.delete(f"/api/money/transfer/{tid}")
        self.assertEqual(r.status_code, 200)
        txns = self.client.get("/api/money/transactions").json()
        self.assertEqual([t for t in txns if t.get("transfer_id") == tid], [])

    def test_delete_unknown_404(self):
        self.assertEqual(self.client.delete("/api/money/transfer/nope").status_code, 404)
