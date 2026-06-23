from core.database import Account, TxnSplit
from tests._client import ApiTest


class MoneyDepthTests(ApiTest):
    def setUp(self):
        super().setUp()
        db = self.db()
        self.acct = Account(name="Checking", kind="checking", currency="$", opening=100.0)
        db.add(self.acct)
        db.commit()
        self.aid = self.acct.id
        db.close()

    def _txn(self, amount, category="", payee="", date="2026-06-10", cleared=False, tags=""):
        return self.client.post(
            "/api/money/transactions",
            json={
                "account_id": self.aid,
                "date": date,
                "amount": amount,
                "category": category,
                "payee": payee,
                "tags": tags,
                "cleared": cleared,
            },
        ).json()

    # ---- splits ----
    def test_put_splits_creates_rows(self):
        t = self._txn(-50, "shopping", "Target")
        r = self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={
                "splits": [
                    {"category": "groceries", "amount": 30},
                    {"category": "household", "amount": 20},
                ]
            },
        )
        self.assertEqual(r.status_code, 200)
        db = self.db()
        self.assertEqual(db.query(TxnSplit).filter_by(txn_id=t["id"]).count(), 2)
        db.close()

    def test_put_splits_rejects_income(self):
        # splits only model how an EXPENSE divides across categories; _spending_by_cat
        # skips income (amount >= 0), so splits saved on an income row are dead data.
        t = self._txn(500, "salary", "Acme")  # positive = income
        r = self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={"splits": [{"category": "a", "amount": 100}]},
        )
        self.assertEqual(r.status_code, 400)
        db = self.db()
        self.assertEqual(db.query(TxnSplit).filter_by(txn_id=t["id"]).count(), 0)
        db.close()

    def test_get_splits_lists(self):
        t = self._txn(-50, "shopping")
        self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={"splits": [{"category": "a", "amount": 20}, {"category": "b", "amount": 10}]},
        )
        d = self.client.get(f"/api/money/transactions/{t['id']}/splits").json()
        cats = {s["category"]: s["amount"] for s in d["splits"]}
        self.assertEqual(cats, {"a": 20.0, "b": 10.0})

    def test_put_splits_replaces(self):
        t = self._txn(-50)
        self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={"splits": [{"category": "a", "amount": 50}]},
        )
        self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={"splits": [{"category": "b", "amount": 25}]},
        )
        d = self.client.get(f"/api/money/transactions/{t['id']}/splits").json()
        self.assertEqual(len(d["splits"]), 1)
        self.assertEqual(d["splits"][0]["category"], "b")

    def test_splits_reject_over_amount(self):
        t = self._txn(-50)
        r = self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={"splits": [{"category": "a", "amount": 40}, {"category": "b", "amount": 30}]},
        )
        self.assertEqual(r.status_code, 400)

    def test_summary_distributes_splits(self):
        t = self._txn(-100, "shopping")
        self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={
                "splits": [
                    {"category": "groceries", "amount": 60},
                    {"category": "household", "amount": 40},
                ]
            },
        )
        d = self.client.get("/api/money/summary", params={"month": "2026-06"}).json()
        cats = {c[0]: c[1] for c in d["by_category"]}
        self.assertEqual(cats.get("groceries"), 60.0)
        self.assertEqual(cats.get("household"), 40.0)
        self.assertNotIn("shopping", cats)

    def test_summary_split_remainder_to_own_category(self):
        t = self._txn(-100, "shopping")
        self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={"splits": [{"category": "groceries", "amount": 60}]},
        )
        d = self.client.get("/api/money/summary", params={"month": "2026-06"}).json()
        cats = {c[0]: c[1] for c in d["by_category"]}
        self.assertEqual(cats.get("groceries"), 60.0)
        self.assertEqual(cats.get("shopping"), 40.0)  # uncovered remainder

    def test_summary_unsplit_unchanged(self):
        self._txn(-25, "coffee")
        d = self.client.get("/api/money/summary", params={"month": "2026-06"}).json()
        cats = {c[0]: c[1] for c in d["by_category"]}
        self.assertEqual(cats.get("coffee"), 25.0)

    def test_delete_txn_cascades_splits(self):
        t = self._txn(-50)
        self.client.put(
            f"/api/money/transactions/{t['id']}/splits",
            json={"splits": [{"category": "a", "amount": 50}]},
        )
        self.client.delete(f"/api/money/transactions/{t['id']}")
        db = self.db()
        self.assertEqual(db.query(TxnSplit).filter_by(txn_id=t["id"]).count(), 0)
        db.close()

    # ---- tags ----
    def test_tags_normalized_on_create(self):
        t = self._txn(-10, payee="x", tags="Food, FOOD,  travel ")
        self.assertEqual(t["tags"], "food,travel")

    def test_transactions_tag_filter(self):
        self._txn(-10, payee="a", tags="food")
        self._txn(-20, payee="b", tags="travel")
        rows = self.client.get("/api/money/transactions", params={"tag": "food"}).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payee"], "a")

    def test_patch_sets_tags(self):
        t = self._txn(-10)
        self.client.patch(f"/api/money/transactions/{t['id']}", json={"tags": "A, b"})
        d = self.client.get("/api/money/transactions").json()
        self.assertEqual(d[0]["tags"], "a,b")

    def test_patch_sets_receipt_id(self):
        t = self._txn(-10)
        self.client.patch(f"/api/money/transactions/{t['id']}", json={"receipt_id": "up123"})
        d = self.client.get("/api/money/transactions").json()
        self.assertEqual(d[0]["receipt_id"], "up123")

    # ---- cleared / reconcile ----
    def test_patch_toggles_cleared(self):
        t = self._txn(-10)
        self.assertFalse(t["cleared"])
        self.client.patch(f"/api/money/transactions/{t['id']}", json={"cleared": True})
        d = self.client.get("/api/money/transactions").json()
        self.assertTrue(d[0]["cleared"])

    def test_reconcile_cleared_balance(self):
        self._txn(200, "salary", cleared=True)  # cleared income
        self._txn(-30, "food", cleared=True)  # cleared expense
        self._txn(-99, "pending", cleared=False)  # not cleared → excluded
        d = self.client.get(
            f"/api/money/accounts/{self.aid}/reconcile", params={"statement": 270}
        ).json()
        # opening 100 + 200 - 30 = 270
        self.assertEqual(d["cleared_balance"], 270.0)
        self.assertEqual(d["difference"], 0.0)
        self.assertTrue(d["reconciled"])

    def test_reconcile_flags_mismatch(self):
        self._txn(50, cleared=True)
        d = self.client.get(
            f"/api/money/accounts/{self.aid}/reconcile", params={"statement": 200}
        ).json()
        # cleared balance 150, statement 200 → diff 50
        self.assertEqual(d["difference"], 50.0)
        self.assertFalse(d["reconciled"])

    def test_reconcile_unknown_account_404(self):
        r = self.client.get("/api/money/accounts/nope/reconcile", params={"statement": 0})
        self.assertEqual(r.status_code, 404)
