from tests._client import ApiTest


class MoneyRuleTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.acct = self.client.post(
            "/api/money/accounts", json={"name": "Checking", "opening": 0}
        ).json()["id"]

    def _rule(self, match, category):
        return self.client.post("/api/money/rules", json={"match": match, "category": category})

    def _txn(self, payee, category="", amount=-10, date="2026-06-01"):
        return self.client.post(
            "/api/money/transactions",
            json={
                "account_id": self.acct,
                "date": date,
                "amount": amount,
                "category": category,
                "payee": payee,
            },
        ).json()

    def test_rule_create_list_delete(self):
        rid = self._rule("netflix", "subscriptions").json()["id"]
        self.assertIn("netflix", [r["match"] for r in self.client.get("/api/money/rules").json()])
        self.assertEqual(self.client.delete(f"/api/money/rules/{rid}").status_code, 200)
        self.assertEqual(self.client.get("/api/money/rules").json(), [])

    def test_blank_match_rejected(self):
        self.assertEqual(self._rule("  ", "x").status_code, 400)

    def test_create_autocategorizes_when_blank(self):
        self._rule("whole foods", "groceries")
        t = self._txn("Whole Foods Market")
        self.assertEqual(t["category"], "groceries")

    def test_match_is_case_insensitive(self):
        self._rule("STARBUCKS", "coffee")
        t = self._txn("morning starbucks run")
        self.assertEqual(t["category"], "coffee")

    def test_create_keeps_explicit_category(self):
        self._rule("whole foods", "groceries")
        t = self._txn("Whole Foods", category="food")
        self.assertEqual(t["category"], "food")

    def test_no_match_stays_blank(self):
        self._rule("netflix", "subscriptions")
        t = self._txn("Random Vendor")
        self.assertEqual(t["category"], "")

    def test_first_rule_wins(self):
        self._rule("market", "shopping")
        self._rule("whole foods", "groceries")
        t = self._txn("Whole Foods Market")  # matches both; first created wins
        self.assertEqual(t["category"], "shopping")

    def test_empty_payee_no_category(self):
        self._rule("netflix", "subscriptions")
        t = self._txn("")
        self.assertEqual(t["category"], "")

    def test_import_autocategorizes(self):
        self._rule("uber", "transport")
        csv = "date,amount,payee\n2026-06-02,-18.50,Uber Trip\n2026-06-03,-9.00,Unknown\n"
        self.client.post(
            "/api/money/transactions/import.csv", json={"csv": csv, "account_id": self.acct}
        )
        txns = self.client.get("/api/money/transactions").json()
        uber = [t for t in txns if t["payee"] == "Uber Trip"][0]
        self.assertEqual(uber["category"], "transport")

    def test_apply_recategorizes_blank(self):
        self._txn("Netflix")  # no rule yet → blank
        self._rule("netflix", "subscriptions")
        r = self.client.post("/api/money/rules/apply").json()
        self.assertEqual(r["updated"], 1)
        t = self.client.get("/api/money/transactions").json()[0]
        self.assertEqual(t["category"], "subscriptions")

    def test_apply_skips_already_categorized(self):
        self._rule("netflix", "subscriptions")
        self._txn("Netflix", category="entertainment")  # explicit
        r = self.client.post("/api/money/rules/apply").json()
        self.assertEqual(r["updated"], 0)

    def test_apply_returns_count(self):
        self._txn("Netflix")
        self._txn("Netflix monthly")
        self._txn("Spotify")
        self._rule("netflix", "subscriptions")
        r = self.client.post("/api/money/rules/apply").json()
        self.assertEqual(r["updated"], 2)
