from tests._client import ApiTest
from core.database import Account, Transaction


class MoneyCsvTest(ApiTest):
    def _account(self):
        d = self.db(); a = Account(name="checking", opening=0.0); d.add(a); d.commit(); aid = a.id; d.close()
        return aid

    def test_export_then_import_roundtrip(self):
        aid = self._account()
        self.client.post("/api/money/transactions", json={"account_id": aid, "date": "2026-06-01", "amount": -12.5, "category": "food", "payee": "cafe"})
        self.client.post("/api/money/transactions", json={"account_id": aid, "date": "2026-06-02", "amount": 100.0, "category": "income"})
        csv = self.client.get("/api/money/transactions/export.csv")
        self.assertEqual(csv.status_code, 200)
        self.assertIn("text/csv", csv.headers["content-type"])
        self.assertIn("cafe", csv.text)
        # import into a fresh account
        aid2 = self._account()
        r = self.client.post("/api/money/import.csv".replace("import.csv", "transactions/import.csv"),
                             json={"csv": csv.text, "account_id": aid2})
        self.assertEqual(r.json()["imported"], 2)

    def test_import_bank_style_csv(self):
        aid = self._account()
        csv_text = "Date,Amount,Description\n2026-06-03,-45.00,Grocery Store\n2026-06-04,2000,Paycheck\n"
        r = self.client.post("/api/money/transactions/import.csv", json={"csv": csv_text, "account_id": aid})
        self.assertEqual(r.json()["imported"], 2)
        # payee comes from the Description column; balance reflects both
        bal = self.client.get("/api/money/accounts").json()
        self.assertEqual(bal[0]["balance"], 1955.0)   # -45 + 2000

    def test_import_unknown_account_400(self):
        self.assertEqual(self.client.post("/api/money/transactions/import.csv",
                         json={"csv": "date,amount\n2026-06-01,5", "account_id": "nope"}).status_code, 400)

    def test_import_skips_bad_rows(self):
        aid = self._account()
        csv_text = "date,amount\n2026-06-01,10\n,5\n2026-06-02,notanumber\n2026-06-03,20\n"
        r = self.client.post("/api/money/transactions/import.csv", json={"csv": csv_text, "account_id": aid})
        self.assertEqual(r.json()["imported"], 2)   # only the two valid rows

    def test_import_skips_duplicates(self):
        aid = self._account()
        csv_text = "date,amount,payee\n2026-06-01,-10,cafe\n2026-06-02,-20,shop\n"
        first = self.client.post("/api/money/transactions/import.csv", json={"csv": csv_text, "account_id": aid}).json()
        self.assertEqual(first["imported"], 2)
        # re-import the same statement plus a new row → only the new one lands
        again = "date,amount,payee\n2026-06-01,-10,cafe\n2026-06-02,-20,shop\n2026-06-03,-5,newthing\n"
        second = self.client.post("/api/money/transactions/import.csv", json={"csv": again, "account_id": aid}).json()
        self.assertEqual(second["imported"], 1)
        self.assertEqual(second["skipped"], 2)
        # in-file duplicate rows are also collapsed
        dupfile = "date,amount,payee\n2026-07-01,-9,x\n2026-07-01,-9,x\n"
        aid2 = self._account()
        third = self.client.post("/api/money/transactions/import.csv", json={"csv": dupfile, "account_id": aid2}).json()
        self.assertEqual(third["imported"], 1)
        self.assertEqual(third["skipped"], 1)

    def test_export_neutralizes_formula_injection(self):
        aid = self._account()
        # a payee/notes that an attacker controls (e.g. via an imported statement)
        # must not become a live formula when the CSV is opened in a spreadsheet
        self.client.post("/api/money/transactions", json={
            "account_id": aid, "date": "2026-06-05", "amount": -1.0,
            "payee": "=cmd|'/c calc'!A0", "notes": "@SUM(1+1)", "category": "+x"})
        text = self.client.get("/api/money/transactions/export.csv").text
        self.assertNotIn(",=cmd", text)           # no cell begins with a bare formula
        self.assertIn(",'=cmd|", text)            # neutralized with a leading quote
        self.assertIn(",'@SUM(1+1)", text)
        self.assertIn(",'+x", text)
