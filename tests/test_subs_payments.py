from datetime import date, timedelta

from core.database import Account, Subscription, Transaction
from routes.subscriptions import _advance
from tests._client import ApiTest


class SubPaymentTests(ApiTest):
    def _sub(self, **kw):
        d = self.db()
        s = Subscription(
            name=kw.get("name", "Sub"),
            price=kw.get("price", 10.0),
            cycle=kw.get("cycle", "monthly"),
            cycle_days=kw.get("cycle_days", 30),
            next_due=kw["next_due"],
            account_id=kw.get("account_id", ""),
            active=True,
        )
        d.add(s)
        d.commit()
        sid = s.id
        d.close()
        return sid

    def _acct(self):
        d = self.db()
        a = Account(name="Checking", opening=100.0)
        d.add(a)
        d.commit()
        aid = a.id
        d.close()
        return aid

    def _pay(self, sid):
        return self.client.post(f"/api/subscriptions/{sid}/paid")

    # ── due-guard (the reported bug) ─────────────────────────────────────────
    def test_pay_when_due_advances(self):
        sid = self._sub(cycle="monthly", next_due=date.today().isoformat())
        r = self._pay(sid)
        self.assertEqual(r.status_code, 200)
        self.assertGreater(date.fromisoformat(r.json()["next_due"]), date.today())

    def test_pay_not_due_rejected(self):
        due = (date.today() + timedelta(days=5)).isoformat()
        sid = self._sub(cycle="monthly", next_due=due)
        r = self._pay(sid)
        self.assertEqual(r.status_code, 400)
        # next_due must be untouched — no infinite advancing
        rows = self.client.get("/api/subscriptions").json()["subscriptions"]
        self.assertEqual([s for s in rows if s["id"] == sid][0]["next_due"], due)

    def test_pay_not_due_is_idempotent_no_drift(self):
        due = (date.today() + timedelta(days=10)).isoformat()
        sid = self._sub(next_due=due)
        for _ in range(5):
            self._pay(sid)
        rows = self.client.get("/api/subscriptions").json()["subscriptions"]
        self.assertEqual([s for s in rows if s["id"] == sid][0]["next_due"], due)

    def test_overdue_rolls_future_and_records_payment(self):
        old = (date.today() - timedelta(days=95)).isoformat()
        sid = self._sub(cycle="monthly", next_due=old)
        r = self._pay(sid)
        self.assertGreater(date.fromisoformat(r.json()["next_due"]), date.today())
        pays = self.client.get(f"/api/subscriptions/{sid}/payments").json()
        self.assertEqual(len(pays), 1)
        self.assertEqual(pays[0]["date"], old)  # the cycle that was paid

    # ── payment log + undo ───────────────────────────────────────────────────
    def test_pay_records_payment(self):
        sid = self._sub(price=12.5, next_due=date.today().isoformat())
        self._pay(sid)
        pays = self.client.get(f"/api/subscriptions/{sid}/payments").json()
        self.assertEqual(len(pays), 1)
        self.assertEqual(pays[0]["amount"], 12.5)

    def test_undo_restores_next_due_and_removes_payment(self):
        due = date.today().isoformat()
        sid = self._sub(next_due=due)
        self._pay(sid)
        r = self.client.post(f"/api/subscriptions/{sid}/payments/undo")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["next_due"], due)  # back to the paid date
        self.assertEqual(self.client.get(f"/api/subscriptions/{sid}/payments").json(), [])

    def test_undo_no_payment_400(self):
        sid = self._sub(next_due=date.today().isoformat())
        r = self.client.post(f"/api/subscriptions/{sid}/payments/undo")
        self.assertEqual(r.status_code, 400)

    def test_payable_flag(self):
        due_sid = self._sub(next_due=date.today().isoformat())
        future_sid = self._sub(next_due=(date.today() + timedelta(days=9)).isoformat())
        rows = {s["id"]: s for s in self.client.get("/api/subscriptions").json()["subscriptions"]}
        self.assertTrue(rows[due_sid]["payable"])
        self.assertFalse(rows[future_sid]["payable"])

    def test_pay_posts_txn_and_undo_removes_it(self):
        aid = self._acct()
        sid = self._sub(price=9.0, next_due=date.today().isoformat(), account_id=aid)
        self._pay(sid)
        d = self.db()
        self.assertEqual(d.query(Transaction).filter(Transaction.account_id == aid).count(), 1)
        d.close()
        self.client.post(f"/api/subscriptions/{sid}/payments/undo")
        d = self.db()
        self.assertEqual(d.query(Transaction).filter(Transaction.account_id == aid).count(), 0)
        d.close()

    def test_pay_unknown_404(self):
        self.assertEqual(self.client.post("/api/subscriptions/nope/paid").status_code, 404)

    def test_payments_unknown_404(self):
        self.assertEqual(self.client.get("/api/subscriptions/nope/payments").status_code, 404)

    def test_advance_still_correct(self):
        self.assertEqual(_advance(date(2026, 6, 18), "yearly", 30), date(2027, 6, 18))
