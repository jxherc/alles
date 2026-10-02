import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date, datetime, timedelta
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Account, Base, FinanceCreateReceipt, SubPayment, Subscription, Transaction
from routes import subscriptions
from services import finance_requests
from tests._client import ApiTest


class SubscriptionRequestTests(ApiTest):
    def seed(self):
        with self.db() as db:
            sub = Subscription(
                name="renewal",
                price=10,
                currency="CAD",
                cycle="monthly",
                next_due=(date.today() + timedelta(days=30)).isoformat(),
                active=True,
                original_price_text="10",
                original_currency_code="CAD",
                base_price_text="10",
                base_currency_code="CAD",
                fx_rate_text="1",
                fx_source="test_identity",
            )
            db.add(sub)
            db.flush()
            older = SubPayment(
                sub_id=sub.id,
                date=(date.today() - timedelta(days=30)).isoformat(),
                amount=10,
                created_at=datetime(2026, 9, 1),
            )
            recent = SubPayment(
                sub_id=sub.id,
                date=date.today().isoformat(),
                amount=10,
                created_at=datetime(2026, 10, 1),
            )
            db.add_all([older, recent])
            db.commit()
            return sub.id, older.id, recent.id

    def test_retry_undo_keeps_older_payment(self):
        sid, older, recent = self.seed()
        url = f"/api/subscriptions/{sid}/payments/undo"
        first = self.client.post(url, json={"payment_id": recent})
        self.assertEqual(first.status_code, 200)
        self.client.post(url, json={"payment_id": recent})
        ids = [p["id"] for p in self.client.get(f"/api/subscriptions/{sid}/payments").json()]
        self.assertEqual(ids, [older], "same undo retry removed an unrelated older payment")

    def test_stale_history_does_not_undo_newer_payment(self):
        sid, older, recent = self.seed()
        response = self.client.post(
            f"/api/subscriptions/{sid}/payments/undo", json={"payment_id": older}
        )
        self.assertEqual(
            response.status_code, 409, "stale history undo targeted newest payment instead"
        )
        self.assertEqual(len(self.client.get(f"/api/subscriptions/{sid}/payments").json()), 2)

    def test_uncertain_subscription_create_retries_one_record(self):
        body = {
            "name": "retry fixture",
            "price": 10,
            "currency": "CAD",
            "cycle": "monthly",
            "next_due": date.today().isoformat(),
            "request_id": "f41bfb17-f3b2-4105-a304-2ff5ebe81328",
        }
        first = self.client.post("/api/subscriptions", json=body)
        retry = self.client.post("/api/subscriptions", json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(
            first.json()["id"],
            retry.json()["id"],
            "uncertain create retry produced two subscriptions",
        )

    def body(self, **extra):
        return {
            "name": "retry fixture",
            "price": 10,
            "currency": "CAD",
            "cycle": "monthly",
            "next_due": date.today().isoformat(),
            "request_id": str(uuid.uuid4()),
            **extra,
        }

    def test_changed_create_retry_conflicts_and_deleted_receipt_stays_deleted(self):
        body = self.body()
        saved = self.client.post("/api/subscriptions", json=body).json()
        self.assertEqual(
            self.client.post("/api/subscriptions", json=body | {"name": "changed"}).status_code, 409
        )
        self.assertEqual(self.client.delete("/api/subscriptions/" + saved["id"]).status_code, 200)
        self.assertEqual(self.client.post("/api/subscriptions", json=body).status_code, 410)
        with self.db() as db:
            self.assertEqual(db.query(Subscription).count(), 0)
            receipt = db.query(FinanceCreateReceipt).one()
            self.assertEqual(receipt.response_json, "null")

    def test_legacy_and_new_request_ids_allow_intentional_repeats(self):
        body = self.body()
        for candidate in [
            body,
            body | {"request_id": str(uuid.uuid4())},
            body | {"request_id": ""},
            body | {"request_id": ""},
        ]:
            self.assertEqual(
                self.client.post("/api/subscriptions", json=candidate).status_code, 200
            )
        with self.db() as db:
            self.assertEqual(db.query(Subscription).count(), 4)

    def test_invalid_request_does_not_write(self):
        self.assertEqual(
            self.client.post(
                "/api/subscriptions", json=self.body(request_id="invalid")
            ).status_code,
            400,
        )
        with self.db() as db:
            self.assertEqual(db.query(Subscription).count(), 0)

    def test_receipt_failure_rolls_back_subscription(self):
        with mock.patch.object(
            finance_requests, "finish", side_effect=RuntimeError("fixture rollback")
        ):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/subscriptions", json=self.body())
        with self.db() as db:
            self.assertEqual(db.query(Subscription).count(), 0)
            self.assertEqual(db.query(FinanceCreateReceipt).count(), 0)

    def test_paid_retry_does_not_pay_a_second_still_due_cycle(self):
        today = date.today().isoformat()
        due = (date.today() - timedelta(days=1)).isoformat()
        sub = self.client.post(
            "/api/subscriptions", json=self.body(next_due=due, cycle="custom", cycle_days=1)
        ).json()
        body = {"request_id": str(uuid.uuid4()), "next_due": due}
        url = "/api/subscriptions/" + sub["id"] + "/paid"
        first = self.client.post(url, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["next_due"], today)
        retry = self.client.post(url, json=body)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json(), first.json())
        payments = self.client.get("/api/subscriptions/" + sub["id"] + "/payments").json()
        self.assertEqual(len(payments), 1)
        self.assertEqual(
            self.client.post(
                url, json={"request_id": str(uuid.uuid4()), "next_due": due}
            ).status_code,
            409,
        )
        self.assertEqual(
            len(self.client.get("/api/subscriptions/" + sub["id"] + "/payments").json()), 1
        )

    def test_paused_subscription_cannot_be_paid(self):
        sub = self.client.post("/api/subscriptions", json=self.body()).json()
        url = "/api/subscriptions/" + sub["id"]
        self.client.patch(url, json={"active": False})
        self.assertEqual(
            self.client.post(
                url + "/paid", json={"next_due": sub["next_due"], "request_id": str(uuid.uuid4())}
            ).status_code,
            409,
        )
        self.assertEqual(self.client.get(url + "/payments").json(), [])

    def test_backfilled_latest_payment_is_identified_for_undo(self):
        sid, older, recent = self.seed()
        with self.db() as db:
            db.get(SubPayment, recent).date = (date.today() - timedelta(days=60)).isoformat()
            db.commit()
        rows = self.client.get(f"/api/subscriptions/{sid}/payments").json()
        self.assertEqual(rows[0]["id"], older)
        self.assertEqual([p["id"] for p in rows if p.get("can_undo")], [recent])

    def test_wrong_subscription_payment_is_not_removed(self):
        sid, older, recent = self.seed()
        other = self.client.post("/api/subscriptions", json=self.body()).json()["id"]
        self.assertEqual(
            self.client.post(
                f"/api/subscriptions/{other}/payments/undo", json={"payment_id": recent}
            ).status_code,
            404,
        )
        self.assertEqual(len(self.client.get(f"/api/subscriptions/{sid}/payments").json()), 2)

    def test_paid_undo_retry_keeps_money_balance_and_tombstones_paid_request(self):
        with self.db() as db:
            account = Account(
                name="checking",
                opening=100,
                currency="CAD",
                currency_code="CAD",
                base_currency_code="CAD",
            )
            db.add(account)
            db.commit()
            aid = account.id
        sub = self.client.post("/api/subscriptions", json=self.body(account_id=aid)).json()
        url = "/api/subscriptions/" + sub["id"]
        body = {"request_id": str(uuid.uuid4()), "next_due": sub["next_due"]}
        paid = self.client.post(url + "/paid", json=body)
        self.assertEqual(paid.status_code, 200, paid.text)
        payment = self.client.get(url + "/payments").json()[0]
        with self.db() as db:
            self.assertEqual(db.query(Transaction).filter_by(account_id=aid).count(), 1)
        self.assertEqual(
            self.client.post(
                url + "/payments/undo", json={"payment_id": payment["id"]}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                url + "/payments/undo", json={"payment_id": payment["id"]}
            ).status_code,
            404,
        )
        self.assertEqual(self.client.post(url + "/paid", json=body).status_code, 410)
        with self.db() as db:
            self.assertEqual(db.query(Transaction).filter_by(account_id=aid).count(), 0)
        self.assertEqual(
            self.client.post(
                url + "/paid", json=body | {"request_id": str(uuid.uuid4())}
            ).status_code,
            200,
        )
        with self.db() as db:
            self.assertEqual(db.query(Transaction).filter_by(account_id=aid).count(), 1)

    def test_independent_connections_serialize_create_paid_and_exact_undo(self):
        with tempfile.TemporaryDirectory(prefix="alles-subscription-race-") as directory:
            engine = create_engine(f"sqlite:///{directory}/ledger.db", connect_args={"timeout": 10})
            try:
                Base.metadata.create_all(engine)
                factory = sessionmaker(bind=engine, autoflush=False)
                barrier = threading.Barrier(3)
                body = self.body()

                def create():
                    barrier.wait(timeout=8)
                    with factory() as db:
                        return subscriptions.create_subscription.__wrapped__(
                            subscriptions.SubBody(**body), db
                        )

                with ThreadPoolExecutor(max_workers=3) as pool:
                    created = list(pool.map(lambda _: create(), range(3)))
                self.assertEqual(created, [created[0]] * 3)
                sid = created[0]["id"]
                barrier.reset()
                paid_body = subscriptions.PaidBody(
                    request_id=str(uuid.uuid4()), next_due=body["next_due"]
                )

                def pay():
                    barrier.wait(timeout=8)
                    with factory() as db:
                        return subscriptions.mark_paid.__wrapped__(sid, db, paid_body)

                with ThreadPoolExecutor(max_workers=3) as pool:
                    paid = list(pool.map(lambda _: pay(), range(3)))
                self.assertEqual(paid, [paid[0]] * 3)
                with factory() as db:
                    self.assertEqual(db.query(Subscription).count(), 1)
                    self.assertEqual(db.query(SubPayment).count(), 1)
                    target = db.query(SubPayment).one().id
                    earlier = SubPayment(
                        sub_id=sid,
                        date=(date.today() - timedelta(days=30)).isoformat(),
                        amount=10,
                        created_at=datetime(2000, 1, 1),
                    )
                    db.add(earlier)
                    db.commit()
                    older = earlier.id
                barrier.reset()

                def undo():
                    barrier.wait(timeout=8)
                    with factory() as db:
                        try:
                            subscriptions.undo_payment.__wrapped__(
                                sid, db, subscriptions.UndoBody(payment_id=target)
                            )
                            return 200
                        except HTTPException as error:
                            return error.status_code

                with ThreadPoolExecutor(max_workers=3) as pool:
                    statuses = list(pool.map(lambda _: undo(), range(3)))
                self.assertEqual(sorted(statuses), [200, 404, 404])
                with factory() as db:
                    self.assertEqual([p.id for p in db.query(SubPayment).all()], [older])
            finally:
                engine.dispose()

    def test_delete_serializes_new_payment_before_tombstoning_receipts(self):
        with tempfile.TemporaryDirectory(prefix="alles-subscription-delete-race-") as directory:
            engine = create_engine(f"sqlite:///{directory}/ledger.db", connect_args={"timeout": 10})
            try:
                Base.metadata.create_all(engine)
                factory = sessionmaker(bind=engine, autoflush=False)
                with factory() as db:
                    sub = subscriptions.create_subscription.__wrapped__(
                        subscriptions.SubBody(**self.body()), db
                    )
                sid = sub["id"]
                paid_body = subscriptions.PaidBody(
                    request_id=str(uuid.uuid4()), next_due=sub["next_due"]
                )
                original_forget = finance_requests.forget
                attempts = []

                def pay():
                    with factory() as db:
                        try:
                            subscriptions.mark_paid.__wrapped__(sid, db, paid_body)
                            return 200
                        except HTTPException as error:
                            return error.status_code

                with ThreadPoolExecutor(max_workers=1) as pool:

                    def concurrent_payment(db, ids):
                        pending = pool.submit(pay)
                        attempts.append(pending)
                        # An unreserved deletion lets another connection finish here.
                        # A reserved deletion holds it until this transaction commits.
                        try:
                            pending.result(timeout=0.3)
                        except TimeoutError:
                            pass
                        return original_forget(db, ids)

                    with mock.patch.object(
                        finance_requests, "forget", side_effect=concurrent_payment
                    ):
                        with factory() as db:
                            subscriptions.delete_subscription.__wrapped__(sid, db)
                    self.assertIn(attempts[0].result(timeout=10), [200, 404])
                self.assertIn(
                    pay(), [404, 410], "deleted subscription returned a live paid receipt"
                )
                with factory() as db:
                    self.assertEqual(db.query(Subscription).count(), 0)
                    self.assertTrue(
                        all(r.response_json == "null" for r in db.query(FinanceCreateReceipt))
                    )
            finally:
                engine.dispose()
