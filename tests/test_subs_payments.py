from datetime import date, timedelta
from unittest import mock

from core.database import Account, MoneyFxEvidence, Subscription, Transaction
from routes import subscriptions as subscription_routes
from routes.subscriptions import _advance, _prepare_renewals
from tests._client import ApiTest


class SubPaymentTests(ApiTest):
    def _sub(self, **kw):
        d = self.db()
        s = Subscription(
            name=kw.get("name", "Sub"),
            price=kw.get("price", 10.0),
            currency="CAD",
            cycle=kw.get("cycle", "monthly"),
            cycle_days=kw.get("cycle_days", 30),
            next_due=kw["next_due"],
            account_id=kw.get("account_id", ""),
            active=True,
            original_price_text=str(kw.get("price", 10.0)),
            original_currency_code="CAD",
            base_price_text=str(kw.get("price", 10.0)),
            base_currency_code="CAD",
            fx_rate_text="1",
            fx_source="test_identity",
        )
        d.add(s)
        d.commit()
        sid = s.id
        d.close()
        return sid

    def _acct(self, currency="CAD"):
        d = self.db()
        a = Account(
            name="Checking",
            opening=100.0,
            currency=currency,
            currency_code=currency,
            base_currency_code=currency,
        )
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

    def test_background_renewal_pass_processes_every_overdue_subscription(self):
        old = (date.today() - timedelta(days=40)).isoformat()
        first = self._sub(cycle="monthly", next_due=old)
        second = self._sub(cycle="monthly", next_due=old)

        _prepare_renewals(date.today())

        db = self.db()
        self.assertGreaterEqual(
            date.fromisoformat(db.get(Subscription, first).next_due), date.today()
        )
        self.assertGreaterEqual(
            date.fromisoformat(db.get(Subscription, second).next_due), date.today()
        )
        db.close()

    def test_unreviewed_renewal_does_not_block_other_background_renewals(self):
        aid = self._acct()
        old = (date.today() - timedelta(days=40)).isoformat()
        blocked = self._sub(cycle="monthly", next_due=old, account_id=aid, price=9.0)
        healthy = self._sub(cycle="monthly", next_due=old)
        db = self.db()
        sub = db.get(Subscription, blocked)
        sub.original_currency_code = "XXX"
        sub.base_price_text = ""
        sub.base_currency_code = ""
        sub.fx_rate_text = ""
        db.commit()
        db.close()

        _prepare_renewals(date.today())

        db = self.db()
        self.assertEqual(db.get(Subscription, blocked).next_due, old)
        self.assertGreaterEqual(
            date.fromisoformat(db.get(Subscription, healthy).next_due), date.today()
        )
        self.assertEqual(db.query(Transaction).filter_by(account_id=aid).count(), 0)
        db.close()

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

    def test_read_only_group_overview_does_not_advance_or_post_an_overdue_subscription(self):
        aid = self._acct()
        old = (date.today() - timedelta(days=40)).isoformat()
        sid = self._sub(cycle="monthly", next_due=old, account_id=aid, price=9.0)
        response = self.client.get("/api/subscriptions?advance=false")
        self.assertEqual(response.status_code, 200, response.text)
        row = next(item for item in response.json()["subscriptions"] if item["id"] == sid)
        self.assertEqual(row["next_due"], old)
        db = self.db()
        self.assertEqual(db.get(Subscription, sid).next_due, old)
        self.assertEqual(db.query(Transaction).filter(Transaction.account_id == aid).count(), 0)
        db.close()

    def test_unreviewed_linked_renewal_keeps_the_list_available_without_posting(self):
        aid = self._acct()
        old = (date.today() - timedelta(days=40)).isoformat()
        sid = self._sub(cycle="monthly", next_due=old, account_id=aid, price=9.0)
        db = self.db()
        sub = db.get(Subscription, sid)
        sub.currency = "$"
        sub.original_currency_code = "XXX"
        sub.base_price_text = ""
        sub.base_currency_code = ""
        sub.fx_rate_text = ""
        sub.fx_source = ""
        db.commit()
        db.close()

        response = self.client.get("/api/subscriptions")

        self.assertEqual(response.status_code, 200, response.text)
        row = next(item for item in response.json()["subscriptions"] if item["id"] == sid)
        self.assertTrue(row["renewal_review_required"])
        self.assertEqual(row["next_due"], old)
        db = self.db()
        self.assertEqual(db.query(Transaction).filter_by(account_id=aid).count(), 0)
        db.close()

    def test_subscription_authority_rows_are_selected_while_cutover_lock_is_held(self):
        class TrackingLock:
            def __init__(self):
                self.depth = 0

            def __enter__(self):
                self.depth += 1

            def __exit__(self, *_args):
                self.depth -= 1

        lock = TrackingLock()
        original = subscription_routes._subscription_rows

        def select_rows(db):
            self.assertGreater(lock.depth, 0)
            return original(db)

        with (
            mock.patch.object(subscription_routes.actual_finance, "AUTHORITY_LOCK", lock),
            mock.patch.object(subscription_routes, "_subscription_rows", side_effect=select_rows),
        ):
            response = self.client.get("/api/subscriptions?advance=false")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(lock.depth, 0)

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

    def test_foreign_subscription_posts_the_reviewed_account_native_amount(self):
        aid = self._acct("CAD")
        due = date.today().isoformat()
        sid = self._sub(price=10.0, next_due=due, account_id=aid)
        db = self.db()
        sub = db.get(Subscription, sid)
        sub.currency = "USD"
        sub.original_currency_code = "USD"
        sub.original_price_text = "10.00"
        sub.base_currency_code = "CAD"
        sub.base_price_text = "13.50"
        sub.fx_rate_text = "1.35"
        sub.fx_rate_date = "2026-07-18"
        sub.fx_source = "owner_review"
        db.commit()
        db.close()

        response = self._pay(sid)
        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        txn = db.query(Transaction).filter_by(account_id=aid).one()
        self.assertEqual(txn.amount, -13.5)
        self.assertEqual(txn.original_amount_text, "-10.00")
        self.assertEqual(txn.original_currency_code, "USD")
        self.assertEqual(txn.base_amount_text, "-13.50")
        self.assertEqual(txn.base_currency_code, "CAD")
        evidence = db.query(MoneyFxEvidence).filter_by(transaction_id=txn.id).one()
        self.assertEqual(evidence.rate_text, "1.35")
        self.assertEqual(evidence.source, "subscription_reviewed")
        db.close()

    def test_subscription_rejects_an_unsupported_account_currency_without_advancing(self):
        aid = self._acct("EUR")
        due = date.today().isoformat()
        sid = self._sub(price=10.0, next_due=due, account_id=aid)
        response = self._pay(sid)
        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertEqual(db.get(Subscription, sid).next_due, due)
        self.assertEqual(db.query(Transaction).filter_by(account_id=aid).count(), 0)
        db.close()

    def test_undo_does_not_wipe_idempotency_marker(self):
        # undo set last_posted_due="" which made the next roll re-post already-charged renewals.
        # it must stay non-empty, but stay < the undone cycle so a re-pay can re-post that one.
        from core.database import Subscription

        aid = self._acct()
        due = (date.today() - timedelta(days=40)).isoformat()
        sid = self._sub(cycle="monthly", next_due=due, account_id=aid, price=9.0)
        self._pay(sid)
        self.client.post(f"/api/subscriptions/{sid}/payments/undo")
        d = self.db()
        sub = d.get(Subscription, sid)
        self.assertNotEqual(sub.last_posted_due, "")
        self.assertLess(sub.last_posted_due, due)
        d.close()

    def test_pay_unknown_404(self):
        self.assertEqual(self.client.post("/api/subscriptions/nope/paid").status_code, 404)

    def test_payments_unknown_404(self):
        self.assertEqual(self.client.get("/api/subscriptions/nope/payments").status_code, 404)

    def test_advance_still_correct(self):
        self.assertEqual(_advance(date(2026, 6, 18), "yearly", 30), date(2027, 6, 18))
