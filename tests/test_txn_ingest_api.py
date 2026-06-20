from datetime import date, timedelta

from core.database import Account, Subscription, Transaction
from tests._client import ApiTest

OFX = """<OFX>
<STMTTRN><DTPOSTED>20240115<TRNAMT>-15.99<NAME>NETFLIX<FITID>n1</STMTTRN>
<STMTTRN><DTPOSTED>20240116<TRNAMT>-9.99<NAME>SPOTIFY<FITID>s1</STMTTRN>
</OFX>"""


class TxnIngestApiTests(ApiTest):
    def _account(self):
        d = self.db()
        a = Account(name="Checking", kind="checking", opening=0.0)
        d.add(a)
        d.commit()
        aid = a.id
        d.close()
        return aid

    def _seed_recurring(self, aid, payee="Netflix", amount=-15.99, n=4, step=30):
        d = self.db()
        start = date(2024, 1, 15)
        for i in range(n):
            d.add(
                Transaction(
                    account_id=aid,
                    date=(start + timedelta(days=step * i)).isoformat(),
                    amount=amount,
                    payee=payee,
                    category="",
                )
            )
        d.commit()
        d.close()

    def test_import_ofx(self):
        aid = self._account()
        r = self.client.post(
            "/api/money/transactions/import-ofx", json={"account_id": aid, "ofx": OFX}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["imported"], 2)

    def test_import_ofx_dedup(self):
        aid = self._account()
        self.client.post("/api/money/transactions/import-ofx", json={"account_id": aid, "ofx": OFX})
        again = self.client.post(
            "/api/money/transactions/import-ofx", json={"account_id": aid, "ofx": OFX}
        ).json()
        self.assertEqual(again["imported"], 0)
        self.assertEqual(again["skipped"], 2)

    def test_import_ofx_unknown_account_400(self):
        r = self.client.post(
            "/api/money/transactions/import-ofx", json={"account_id": "nope", "ofx": OFX}
        )
        self.assertEqual(r.status_code, 400)

    def test_import_ofx_creates_real_txns(self):
        aid = self._account()
        self.client.post("/api/money/transactions/import-ofx", json={"account_id": aid, "ofx": OFX})
        payees = {t.payee for t in self.db().query(Transaction).all()}
        self.assertIn("NETFLIX", payees)

    def test_recurring_detect(self):
        aid = self._account()
        self._seed_recurring(aid)
        c = self.client.get("/api/money/transactions/recurring-detect").json()["candidates"]
        self.assertTrue(any(x["cycle"] == "monthly" and x["count"] == 4 for x in c))

    def test_recurring_detect_account_filter(self):
        aid = self._account()
        self._seed_recurring(aid)
        other = self._account()
        c = self.client.get(
            "/api/money/transactions/recurring-detect", params={"account_id": other}
        ).json()["candidates"]
        self.assertEqual(c, [])

    def test_recurring_detect_ignores_oneoffs(self):
        aid = self._account()
        d = self.db()
        d.add(
            Transaction(account_id=aid, date="2024-01-01", amount=-3.0, payee="Coffee", category="")
        )
        d.commit()
        c = self.client.get("/api/money/transactions/recurring-detect").json()["candidates"]
        self.assertEqual(c, [])

    def test_subs_detect_proposes(self):
        aid = self._account()
        self._seed_recurring(aid, payee="Netflix")
        c = self.client.get("/api/subscriptions/detect").json()["candidates"]
        self.assertTrue(any("netflix" in (x["payee"] or "").lower() for x in c))

    def test_subs_detect_excludes_tracked(self):
        aid = self._account()
        self._seed_recurring(aid, payee="Netflix")
        d = self.db()
        d.add(Subscription(name="Netflix", price=15.99, cycle="monthly", next_due="2025-01-01"))
        d.commit()
        d.close()
        c = self.client.get("/api/subscriptions/detect").json()["candidates"]
        self.assertFalse(any("netflix" == (x["payee"] or "").strip().lower() for x in c))
