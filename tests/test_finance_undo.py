"""Owned local saves can be reversed only while their original evidence is unchanged."""

import json
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import mock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from core.database import (
    Base,
    FinanceCreateReceipt,
    MoneyFxEvidence,
    Transaction,
    TxnSplit,
)
from routes import money
from services import finance_undo
from tests._client import ApiTest


class FinanceUndoTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.account = self.client.post(
            "/api/money/accounts",
            json={"name": "owned checking", "currency": "CAD", "opening": 100},
        ).json()["id"]

    def save(self, **changes):
        payload = {
            "account_id": self.account,
            "amount": -12.5,
            "date": "2026-10-01",
            "payee": "owned expense",
            "request_id": str(uuid.uuid4()),
            **changes,
        }
        response = self.client.post("/api/money/transactions", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), payload

    def undo(self, saved, **changes):
        return self.client.post(
            f"/api/money/transactions/{saved['id']}/undo",
            json={"request_id": saved["undo"]["request_id"], **changes},
        )

    def test_exact_save_reversal_balances_proof_and_lost_reply_retry(self):
        saved, payload = self.save()
        other, _ = self.save(payee="keep this", amount=-5)
        response = self.undo(saved)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True, "outcome": "undone"})
        self.assertEqual(self.undo(saved).json(), {"ok": True, "outcome": "already_removed"})
        rows = self.client.get("/api/money/transactions").json()
        self.assertEqual([row["id"] for row in rows], [other["id"]])
        self.assertEqual(self.client.get("/api/money/accounts").json()[0]["balance"], 95)
        self.assertEqual(self.client.post("/api/money/transactions", json=payload).status_code, 410)
        with self.db() as db:
            self.assertIsNone(
                db.query(MoneyFxEvidence).filter_by(transaction_id=saved["id"]).first()
            )
            receipt = db.get(FinanceCreateReceipt, f"transaction:{payload['request_id']}")
            self.assertEqual(receipt.response_json, "null")

    def test_changed_record_is_never_deleted(self):
        for change in (
            {"amount": -11},
            {"date": "2026-10-02"},
            {"notes": "new note"},
            {"category": "changed category"},
            {"payee": "changed payee"},
            {"tags": "new-tag"},
            {"receipt_id": "new-attachment"},
            {"cleared": True},
        ):
            with self.subTest(change=change):
                saved, _ = self.save()
                url = f"/api/money/transactions/{saved['id']}"
                self.assertEqual(self.client.patch(url, json=change).status_code, 200)
                before = self.client.get("/api/money/transactions").json()
                response = self.undo(saved)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.client.get("/api/money/transactions").json(), before)

    def test_non_display_proof_import_timestamp_split_or_transfer_changes_refuse(self):
        def mutate(db, saved, kind):
            transaction = db.get(Transaction, saved["id"])
            if kind == "fx":
                db.query(MoneyFxEvidence).filter_by(
                    transaction_id=saved["id"]
                ).one().source_hash = "new evidence"
            elif kind == "split":
                db.add(TxnSplit(txn_id=saved["id"], category="food", amount=-12.5))
            elif kind == "timestamp":
                transaction.created_at += timedelta(seconds=1)
            elif kind == "import":
                transaction.import_receipt_json = '{"review":"new"}'
            elif kind == "rate":
                transaction.fx_rate_date = "2026-09-01"
            else:
                transaction.transfer_id = "different transfer"

        for kind in ("fx", "split", "timestamp", "import", "rate", "transfer"):
            with self.subTest(kind=kind):
                saved, _ = self.save()
                with self.db() as db:
                    mutate(db, saved, kind)
                    db.commit()
                self.assertEqual(self.undo(saved).status_code, 409)
                with self.db() as db:
                    self.assertIsNotNone(db.get(Transaction, saved["id"]))
                    self.assertNotEqual(
                        db.get(
                            FinanceCreateReceipt, f"transaction:{saved['undo']['request_id']}"
                        ).response_json,
                        "null",
                    )

    def test_wrong_identity_and_legacy_receipts_cannot_reverse(self):
        saved, _ = self.save()
        for identity, status in (("bad", 400), (str(uuid.uuid4()), 409)):
            self.assertEqual(self.undo(saved, request_id=identity).status_code, status)
        with self.db() as db:
            receipt = db.get(FinanceCreateReceipt, f"transaction:{saved['undo']['request_id']}")
            values = json.loads(receipt.response_json)
            del values["undo"]
            receipt.response_json = json.dumps(values)
            db.commit()
        self.assertEqual(self.undo(saved).status_code, 409)
        self.assertEqual(len(self.client.get("/api/money/transactions").json()), 1)

    def test_saved_result_is_read_only_original_ack_and_canonical_undo_is_unavailable(self):
        saved, _ = self.save()
        url = f"/api/money/transactions/{saved['id']}/undo"
        self.client.patch(f"/api/money/transactions/{saved['id']}", json={"payee": "newer payee"})
        result = self.client.get(url, params={"request_id": saved["undo"]["request_id"]})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), saved)
        self.assertEqual(self.undo(saved).status_code, 409)
        with (
            mock.patch("services.actual_finance.is_canonical", return_value=True),
            mock.patch.object(finance_undo, "reverse") as reverse,
        ):
            self.assertEqual(self.undo(saved).status_code, 409)
            self.assertEqual(
                self.client.get(
                    url, params={"request_id": saved["undo"]["request_id"]}
                ).status_code,
                409,
            )
            reverse.assert_not_called()

    def test_failed_commit_rolls_back_transaction_proof_and_tombstone_together(self):
        saved, _ = self.save()
        from sqlalchemy.orm import Session

        with mock.patch.object(Session, "commit", side_effect=RuntimeError("owned interruption")):
            with self.assertRaisesRegex(RuntimeError, "owned interruption"):
                self.undo(saved)
        with self.db() as db:
            self.assertIsNotNone(db.get(Transaction, saved["id"]))
            self.assertIsNotNone(
                db.query(MoneyFxEvidence).filter_by(transaction_id=saved["id"]).first()
            )
            self.assertNotEqual(
                db.get(
                    FinanceCreateReceipt, f"transaction:{saved['undo']['request_id']}"
                ).response_json,
                "null",
            )
        self.assertEqual(self.undo(saved).json()["outcome"], "undone")

    def test_original_request_cannot_remove_another_save_or_resurrect_manual_deletion(self):
        first, _ = self.save()
        second, _ = self.save()
        self.assertEqual(self.undo(second, request_id=first["undo"]["request_id"]).status_code, 409)
        self.assertEqual(
            self.client.delete(f"/api/money/transactions/{first['id']}").status_code, 200
        )
        self.assertEqual(self.undo(first).json(), {"ok": True, "outcome": "already_removed"})
        self.assertEqual(
            [row["id"] for row in self.client.get("/api/money/transactions").json()], [second["id"]]
        )

    def test_separate_connections_cannot_write_between_compare_and_delete(self):
        with tempfile.TemporaryDirectory(prefix="alles-finance-undo-race-") as directory:
            engine = create_engine(f"sqlite:///{directory}/ledger.db", connect_args={"timeout": 10})
            factory = sessionmaker(bind=engine, autoflush=False)
            try:
                Base.metadata.create_all(engine)
                with factory() as db:
                    account = money.create_account(
                        money.AccountBody(name="race", currency="CAD", opening=100), db
                    )
                    saved = money.create_txn(
                        money.TxnBody(
                            account_id=account["id"],
                            date="2026-10-01",
                            amount=-12.5,
                            request_id=str(uuid.uuid4()),
                        ),
                        db,
                    )
                reserved, release, attempted, completed = (threading.Event() for _ in range(4))
                editing_thread = []
                original = finance_undo._fingerprint

                def compare(db, transaction):
                    reserved.set()
                    self.assertTrue(release.wait(15))
                    return original(db, transaction)

                def observe_before(conn, cursor, statement, parameters, context, executemany):
                    if editing_thread == [threading.get_ident()] and statement.startswith(
                        ("UPDATE ", "INSERT ")
                    ):
                        attempted.set()

                def observe_after(conn, cursor, statement, parameters, context, executemany):
                    if editing_thread == [threading.get_ident()] and statement.startswith(
                        ("UPDATE ", "INSERT ")
                    ):
                        completed.set()

                event.listen(engine, "before_cursor_execute", observe_before)
                event.listen(engine, "after_cursor_execute", observe_after)

                def reverse():
                    with factory() as db:
                        return finance_undo.reverse(db, saved["id"], saved["undo"]["request_id"])

                def edit():
                    editing_thread.append(threading.get_ident())
                    with factory() as db:
                        row = db.get(Transaction, saved["id"])
                        row.notes = "concurrent newer note"
                        db.commit()

                with (
                    mock.patch.object(finance_undo, "_fingerprint", side_effect=compare),
                    ThreadPoolExecutor(max_workers=2) as workers,
                ):
                    undo = workers.submit(reverse)
                    self.assertTrue(reserved.wait(5))
                    editing = workers.submit(edit)
                    try:
                        self.assertTrue(attempted.wait(3))
                        self.assertFalse(completed.wait(0.1))
                    finally:
                        release.set()
                    self.assertEqual(undo.result(timeout=5), {"ok": True, "outcome": "undone"})
                    with self.assertRaises(StaleDataError):
                        editing.result(timeout=5)
                with factory() as db:
                    self.assertEqual(db.query(Transaction).count(), 0)
                    self.assertEqual(db.query(MoneyFxEvidence).count(), 0)
            finally:
                engine.dispose()
