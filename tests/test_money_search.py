from tests._client import ApiTest


class MoneySearchTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.a = self.client.post("/api/money/accounts", json={"name": "Checking"}).json()["id"]
        self.b = self.client.post("/api/money/accounts", json={"name": "Savings"}).json()["id"]
        self._mk(self.a, "2026-06-01", -82.50, "groceries", "Whole Foods", "weekly run")
        self._mk(self.a, "2026-06-05", -15.99, "subscriptions", "Netflix", "")
        self._mk(self.a, "2026-06-10", -250.00, "rent", "Landlord", "june rent")
        self._mk(self.b, "2026-05-20", 3000.00, "salary", "Acme Payroll", "")
        self._mk(self.a, "2026-06-15", -8.00, "dining", "Cafe", "espresso")

    def _mk(self, acct, date, amount, category, payee, notes):
        return self.client.post(
            "/api/money/transactions",
            json={
                "account_id": acct,
                "date": date,
                "amount": amount,
                "category": category,
                "payee": payee,
                "notes": notes,
            },
        )

    def _search(self, **params):
        return self.client.get("/api/money/transactions/search", params=params).json()

    def test_search_by_payee(self):
        r = self._search(q="netflix")
        self.assertEqual([t["payee"] for t in r], ["Netflix"])

    def test_search_by_category(self):
        r = self._search(q="rent")  # matches category "rent" and notes "june rent"
        payees = {t["payee"] for t in r}
        self.assertIn("Landlord", payees)

    def test_search_by_notes(self):
        r = self._search(q="espresso")
        self.assertEqual([t["payee"] for t in r], ["Cafe"])

    def test_search_case_insensitive(self):
        self.assertEqual(len(self._search(q="WHOLE FOODS")), 1)

    def test_min_amount_filters_by_magnitude(self):
        r = self._search(min_amt=100)
        amts = sorted(abs(t["amount"]) for t in r)
        self.assertEqual(amts, [250.0, 3000.0])

    def test_max_amount_filters_by_magnitude(self):
        r = self._search(max_amt=20)
        amts = sorted(abs(t["amount"]) for t in r)
        self.assertEqual(amts, [8.0, 15.99])

    def test_min_max_range(self):
        r = self._search(min_amt=10, max_amt=100)
        amts = sorted(abs(t["amount"]) for t in r)
        self.assertEqual(amts, [15.99, 82.5])

    def test_account_filter(self):
        r = self._search(account=self.b)
        self.assertEqual([t["payee"] for t in r], ["Acme Payroll"])

    def test_month_filter(self):
        r = self._search(month="2026-05")
        self.assertEqual([t["payee"] for t in r], ["Acme Payroll"])

    def test_empty_query_returns_all(self):
        self.assertEqual(len(self._search()), 5)

    def test_combined_filters(self):
        # account a, june, magnitude >= 50 → Whole Foods (82.50) + Landlord (250)
        r = self._search(account=self.a, month="2026-06", min_amt=50)
        self.assertEqual({t["payee"] for t in r}, {"Whole Foods", "Landlord"})

    def test_sorted_date_desc(self):
        dates = [t["date"] for t in self._search()]
        self.assertEqual(dates, sorted(dates, reverse=True))
