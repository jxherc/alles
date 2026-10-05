"""Local Finance create retries share a durable acknowledgment and one ledger commit."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, event, func
from sqlalchemy.orm import sessionmaker

from core.database import Account, Base, FinanceCreateReceipt, Transaction
from routes import money
from tests._client import ApiTest


class FinanceLocalRequestTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.a = self.client.post(
            "/api/money/accounts", json={"name": "A", "currency": "CAD", "opening": 100}
        ).json()["id"]
        self.b = self.client.post(
            "/api/money/accounts", json={"name": "B", "currency": "CAD", "opening": 50}
        ).json()["id"]

    def cases(self):
        return [
            ("accounts", {"name": "request fixture", "opening": 12.34}, "opening", 99),
            (
                "transactions",
                {"account_id": self.a, "date": "2026-09-25", "amount": -23.45, "payee": "fixture"},
                "amount",
                -99,
            ),
            (
                "transfer",
                {
                    "from_account": self.a,
                    "to_account": self.b,
                    "date": "2026-09-25",
                    "amount": 12.34,
                },
                "amount",
                99,
            ),
        ]

    def test_matching_retry_and_conflicting_reuse_for_all_local_creates(self):
        for path, payload, field, conflicting in self.cases():
            with self.subTest(path=path):
                payload["request_id"] = str(uuid.uuid4())
                url = f"/api/money/{path}"
                first = self.client.post(url, json=payload)
                self.assertEqual(first.status_code, 200, first.text)
                replay = self.client.post(url, json=payload)
                self.assertEqual(replay.status_code, 200, replay.text)
                self.assertEqual(replay.json(), first.json())
                conflict = self.client.post(url, json={**payload, field: conflicting})
                self.assertEqual(conflict.status_code, 409, conflict.text)
        with self.db() as db:
            self.assertEqual(db.query(Account).count(), 3)
            self.assertEqual(db.query(Transaction).count(), 3)
            self.assertEqual(db.query(FinanceCreateReceipt).count(), 3)
        balances = {r["id"]: r["balance"] for r in self.client.get("/api/money/accounts").json()}
        self.assertEqual(balances[self.a], 64.21)
        self.assertEqual(balances[self.b], 62.34)

    def test_retry_replays_original_response_after_edit_and_does_not_recreate_deleted_rows(self):
        payload = self.cases()[1][1] | {"request_id": str(uuid.uuid4())}
        url = "/api/money/transactions"
        original = self.client.post(url, json=payload).json()
        self.client.patch(f"{url}/{original['id']}", json={"amount": -3})
        self.assertEqual(self.client.post(url, json=payload).json(), original)
        self.assertEqual(self.client.get(url).json()[0]["amount"], -3)
        self.client.delete(f"{url}/{original['id']}")
        self.assertEqual(self.client.post(url, json=payload).status_code, 410)
        self.assertEqual(self.client.get(url).json(), [])
        with self.db() as db:
            self.assertEqual(db.query(FinanceCreateReceipt).one().response_json, "null")

    def test_account_deletion_forgets_content_in_all_affected_receipts(self):
        account_body = {
            "name": "private account",
            "currency": "CAD",
            "request_id": str(uuid.uuid4()),
        }
        account = self.client.post("/api/money/accounts", json=account_body).json()
        transaction_body = self.cases()[1][1] | {
            "account_id": account["id"],
            "request_id": str(uuid.uuid4()),
            "notes": "private note",
        }
        self.client.post("/api/money/transactions", json=transaction_body)
        transfer_body = self.cases()[2][1] | {
            "from_account": account["id"],
            "request_id": str(uuid.uuid4()),
            "notes": "private transfer",
        }
        self.client.post("/api/money/transfer", json=transfer_body)
        response = self.client.delete(f"/api/money/accounts/{account['id']}")
        self.assertEqual(response.status_code, 200)
        for path, body in (
            ("accounts", account_body),
            ("transactions", transaction_body),
            ("transfer", transfer_body),
        ):
            self.assertEqual(self.client.post(f"/api/money/{path}", json=body).status_code, 410)
        with self.db() as db:
            self.assertEqual(
                [r.response_json for r in db.query(FinanceCreateReceipt)], ["null"] * 3
            )
            self.assertEqual(db.query(Account).count(), 2)
            # The existing account-deletion contract preserves the other transfer leg as a plain txn.
            self.assertEqual(db.query(Transaction).count(), 1)
            self.assertEqual(db.query(Transaction).one().transfer_id, "")

    def test_transfer_or_one_leg_deletion_forgets_acknowledgment_and_never_reapplies(self):
        for delete_one_leg in (False, True):
            with self.subTest(delete_one_leg=delete_one_leg):
                body = self.cases()[2][1] | {
                    "request_id": str(uuid.uuid4()),
                    "notes": "private transfer",
                }
                result = self.client.post("/api/money/transfer", json=body).json()
                endpoint = (
                    f"transactions/{result['from']['id']}"
                    if delete_one_leg
                    else f"transfer/{result['transfer_id']}"
                )
                self.assertEqual(self.client.delete(f"/api/money/{endpoint}").status_code, 200)
                before = self.client.get("/api/money/accounts").json()
                self.assertEqual(
                    self.client.post("/api/money/transfer", json=body).status_code, 410
                )
                self.assertEqual(self.client.get("/api/money/accounts").json(), before)
                with self.db() as db:
                    receipt = db.get(FinanceCreateReceipt, f"transfer:{body['request_id']}")
                    self.assertEqual(receipt.response_json, "null")

    def test_failed_validation_does_not_consume_request_id(self):
        request_id = str(uuid.uuid4())
        payload = self.cases()[1][1] | {"request_id": request_id, "account_id": "missing"}
        response = self.client.post("/api/money/transactions", json=payload)
        self.assertEqual(response.status_code, 400)
        with self.db() as db:
            self.assertEqual(db.query(FinanceCreateReceipt).count(), 0)
        payload["account_id"] = self.a
        self.assertEqual(self.client.post("/api/money/transactions", json=payload).status_code, 200)

    def test_failure_after_ledger_flush_rolls_back_ledger_and_receipt(self):
        payload = self.cases()[1][1] | {"request_id": str(uuid.uuid4())}
        with mock.patch(
            "services.finance_requests.finish", side_effect=RuntimeError("fixture interruption")
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
                self.client.post("/api/money/transactions", json=payload)
        with self.db() as db:
            self.assertEqual(db.query(Transaction).count(), 0)
            self.assertEqual(db.query(FinanceCreateReceipt).count(), 0)
        self.assertEqual(self.client.post("/api/money/transactions", json=payload).status_code, 200)

    def test_invalid_identity_rejected_without_rows(self):
        for path, payload, *_ in self.cases():
            with self.subTest(path=path):
                response = self.client.post(
                    f"/api/money/{path}", json={**payload, "request_id": "not-a-uuid"}
                )
                self.assertEqual(response.status_code, 400, response.text)
        with self.db() as db:
            self.assertEqual(db.query(FinanceCreateReceipt).count(), 0)
            self.assertEqual(db.query(Transaction).count(), 0)
            self.assertEqual(db.query(Account).count(), 2)

    def test_create_without_identity_remains_independent(self):
        payload = self.cases()[1][1]
        first = self.client.post("/api/money/transactions", json=payload).json()
        second = self.client.post("/api/money/transactions", json=payload).json()
        self.assertNotEqual(first["id"], second["id"])

    def test_concurrent_connections_create_one_transaction_and_one_balance_delta(self):
        with tempfile.TemporaryDirectory(prefix="alles-finance-race-") as directory:
            engine = create_engine(f"sqlite:///{directory}/ledger.db", connect_args={"timeout": 10})
            try:
                Base.metadata.create_all(engine)
                factory = sessionmaker(bind=engine, autoflush=False)
                with factory() as db:
                    account = money.create_account(
                        money.AccountBody(name="race fixture", opening=100), db
                    )
                payload = {
                    "account_id": account["id"],
                    "date": "2026-09-25",
                    "amount": -23.45,
                    "request_id": str(uuid.uuid4()),
                }
                barrier = threading.Barrier(4)

                def before_receipt_insert(*_args):
                    barrier.wait(timeout=8)

                def create():
                    with factory() as db:
                        # Direct route calls deliberately bypass the process-local API lock.
                        return money.create_txn(money.TxnBody(**payload), db)

                event.listen(FinanceCreateReceipt, "before_insert", before_receipt_insert)
                try:
                    with ThreadPoolExecutor(max_workers=4) as workers:
                        results = list(workers.map(lambda _: create(), range(4)))
                finally:
                    event.remove(FinanceCreateReceipt, "before_insert", before_receipt_insert)
                self.assertTrue(all(result == results[0] for result in results))
                with factory() as db:
                    self.assertEqual(db.query(Transaction).count(), 1)
                    self.assertEqual(db.query(FinanceCreateReceipt).count(), 1)
                    self.assertEqual(db.query(func.sum(Transaction.amount)).scalar(), -23.45)
                    self.assertEqual(money.list_accounts(db)[0]["balance"], 76.55)
            finally:
                engine.dispose()

    def test_identity_survives_new_process(self):
        with tempfile.TemporaryDirectory(prefix="alles-finance-restart-") as directory:
            database = str(Path(directory) / "ledger.db")
            script = """import json,sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import init_db
from routes import money
init_db()
engine=create_engine('sqlite:///'+sys.argv[1])
with sessionmaker(bind=engine,autoflush=False)() as db:
 print(json.dumps(money.create_account(money.AccountBody(**json.loads(sys.argv[2])),db)))
engine.dispose()
"""
            payload = {"name": "restart fixture", "opening": 12.34, "request_id": str(uuid.uuid4())}
            env = {
                **{
                    key: os.environ[key]
                    for key in (
                        "PATH",
                        "HOME",
                        "USER",
                        "LOGNAME",
                        "TMPDIR",
                        "TEMP",
                        "TMP",
                        "SYSTEMROOT",
                    )
                    if key in os.environ
                },
                "ALLES_DATA": directory,
                "ALLES_DB": database,
                "PYTHON_DOTENV_DISABLED": "1",
                "HF_HUB_OFFLINE": "1",
                "HF_HOME": str(Path(directory) / "model-cache" / "huggingface"),
                "FASTEMBED_CACHE_PATH": str(Path(directory) / "model-cache" / "fastembed"),
            }
            command = [sys.executable, "-B", "-c", script, database, json.dumps(payload)]
            # Simulate an existing installation without this additive table.
            engine = create_engine(f"sqlite:///{database}")
            Base.metadata.create_all(
                engine,
                tables=[
                    table
                    for table in Base.metadata.sorted_tables
                    if table.name != "finance_create_receipts"
                ],
            )
            with sessionmaker(bind=engine)() as db:
                db.add(Account(name="existing account", opening=25))
                db.commit()
            engine.dispose()
            first = subprocess.run(
                command, env=env, check=True, capture_output=True, text=True, timeout=30
            )
            second = subprocess.run(
                command, env=env, check=True, capture_output=True, text=True, timeout=30
            )
            self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
            engine = create_engine(f"sqlite:///{database}")
            try:
                with sessionmaker(bind=engine)() as db:
                    self.assertEqual(db.query(Account).count(), 2)
                    self.assertEqual(db.query(FinanceCreateReceipt).count(), 1)
                    self.assertEqual(
                        db.query(Account).filter_by(name="existing account").one().opening, 25
                    )
            finally:
                engine.dispose()
            from services.backup_recovery import snapshot_sqlite

            snapshot = Path(directory) / "snapshot.db"
            snapshot_sqlite(Path(database), snapshot)
            engine = create_engine(f"sqlite:///{snapshot}")
            try:
                with sessionmaker(bind=engine)() as db:
                    replay = money.create_account(money.AccountBody(**payload), db)
                    self.assertEqual(replay, json.loads(first.stdout))
                    self.assertEqual(db.query(Account).count(), 2)
            finally:
                engine.dispose()
