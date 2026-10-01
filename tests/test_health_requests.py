"""Health retries retain one reading without collapsing intentional repeated measurements."""

import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from core.database import Base, HealthCreateReceipt, HealthEntry
from core.migrations import m0049_health_create_receipts
from services.health_entries import HealthInputError, save_entry
from tests._client import ApiTest


class HealthRequestTests(ApiTest):
    def body(self, **values):
        return {
            "kind": "weight",
            "value": 74.25,
            "unit": "kg",
            "note": "reading",
            "date": "2026-10-01",
            "request_id": str(uuid.uuid4()),
        } | values

    def test_retry_conflict_and_intentional_repeat(self):
        body = self.body()
        first = self.client.post("/api/health", json=body)
        retry = self.client.post("/api/health", json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.json(), first.json())
        conflict = self.client.post("/api/health", json=body | {"value": 80})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["entry_id"], first.json()["id"])
        repeated = self.client.post("/api/health", json=body | {"request_id": str(uuid.uuid4())})
        self.assertNotEqual(repeated.json()["id"], first.json()["id"])
        self.assertEqual(len(self.client.get("/api/health").json()["entries"]), 2)

    def test_receipt_bound_correction_never_edits_a_reused_id(self):
        body = self.body()
        original = self.client.post("/api/health", json=body).json()
        self.client.delete(f"/api/health/{original['id']}")
        replacement = self.client.post("/api/health", json=self.body(kind="sleep", value=8)).json()
        self.assertEqual(replacement["id"], original["id"])
        response = self.client.patch(
            f"/api/health/{original['id']}",
            json={"value": 99, "create_request_id": body["request_id"]},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(self.client.get("/api/health").json()["entries"][0]["value"], 8)
        self.assertEqual(
            self.client.get(f"/api/health/requests/{body['request_id']}").status_code, 410
        )

    def test_recovery_and_correction_use_the_receipt_identity(self):
        body = self.body()
        original = self.client.post("/api/health", json=body).json()
        url = f"/api/health/requests/{body['request_id']}"
        self.assertEqual(self.client.get(url).json(), original)
        update = {"value": 73, "note": " corrected ", "create_request_id": body["request_id"]}
        corrected = self.client.patch(f"/api/health/{original['id']}", json=update)
        self.assertEqual(corrected.status_code, 200)
        self.assertEqual((corrected.json()["value"], corrected.json()["note"]), (73, "corrected"))
        self.assertEqual(self.client.get(url).json(), corrected.json())
        other = self.client.post("/api/health", json=self.body(value=81)).json()
        self.assertEqual(
            self.client.patch(f"/api/health/{other['id']}", json=update).status_code, 409
        )
        for identity, status in [("invalid", 400), (str(uuid.uuid4()), 404)]:
            self.assertEqual(
                self.client.get(f"/api/health/requests/{identity}").status_code, status
            )
            self.assertEqual(
                self.client.patch(
                    f"/api/health/{original['id']}",
                    json=update | {"create_request_id": identity},
                ).status_code,
                status,
            )

    def test_retry_returns_current_correction_and_does_not_resurrect_deleted_reading(self):
        body = self.body()
        original = self.client.post("/api/health", json=body).json()
        self.client.patch(f"/api/health/{original['id']}", json={"value": 72})
        retried = self.client.post("/api/health", json=body).json()
        self.assertEqual((retried["id"], retried["value"]), (original["id"], 72))
        self.client.delete(f"/api/health/{original['id']}")
        # SQLite may reuse the greatest deleted integer ID. The receipt must remain a tombstone.
        with self.db() as db:
            db.add(HealthEntry(id=original["id"], kind="sleep", value=8, date="2026-10-02"))
            db.commit()
        self.assertEqual(self.client.post("/api/health", json=body).status_code, 410)
        entries = self.client.get("/api/health").json()["entries"]
        self.assertEqual([(row["kind"], row["value"]) for row in entries], [("sleep", 8)])
        with self.db() as db:
            receipt = db.query(HealthCreateReceipt).one()
            self.assertIsNone(receipt.entry_id)
            self.assertEqual(receipt.payload_hash, "")

    def test_legacy_caller_can_intentionally_repeat_and_invalid_identity_writes_nothing(self):
        body = self.body(request_id="")
        self.client.post("/api/health", json=body)
        self.client.post("/api/health", json=body)
        for identity in ["bad", uuid.uuid4().hex]:
            self.assertEqual(
                self.client.post("/api/health", json=body | {"request_id": identity}).status_code,
                400,
            )
        self.assertEqual(len(self.client.get("/api/health").json()["entries"]), 2)
        with self.db() as db:
            self.assertEqual(db.query(HealthCreateReceipt).count(), 0)

    def test_same_default_date_retry_after_midnight_uses_original_day(self):
        body = self.body(date="")
        with mock.patch("services.health_entries.date") as clock:
            clock.today.return_value = date(2026, 10, 1)
            clock.fromisoformat.side_effect = date.fromisoformat
            first = self.client.post("/api/health", json=body)
            clock.today.return_value = date(2026, 10, 2)
            retry = self.client.post("/api/health", json=body)
        self.assertEqual(first.json(), retry.json())
        self.assertEqual(retry.json()["date"], "2026-10-01")

    def test_failed_commit_rolls_back_receipt_and_reading_together(self):
        identity = str(uuid.uuid4())
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("commit rejected")):
                with self.assertRaisesRegex(RuntimeError, "commit rejected"):
                    save_entry(db, kind="sleep", value=8, request_id=identity)
            db.rollback()
        with self.db() as db:
            self.assertEqual(db.query(HealthCreateReceipt).count(), 0)
            self.assertEqual(db.query(HealthEntry).count(), 0)
            entry = save_entry(db, kind="sleep", value=8, request_id=identity)
            self.assertEqual(db.query(HealthEntry).count(), 1)
            self.assertEqual(db.query(HealthCreateReceipt).one().entry_id, entry.id)

    def test_concurrent_connections_create_once_and_reopen_replays(self):
        with tempfile.TemporaryDirectory(prefix="alles-health-request-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'health.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            identity, barrier = str(uuid.uuid4()), threading.Barrier(2)

            def save():
                with sessions() as db:
                    barrier.wait(timeout=10)
                    return save_entry(db, kind="sleep", value=8, request_id=identity).id

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(save) for _ in range(2)]
                    ids = [future.result(timeout=20) for future in futures]
                self.assertEqual(ids[0], ids[1])
                engine.dispose()
                with sessions() as db:
                    self.assertEqual(
                        save_entry(db, kind="sleep", value=8, request_id=identity).id, ids[0]
                    )
                    self.assertEqual(db.query(HealthEntry).count(), 1)
                    self.assertEqual(db.query(HealthCreateReceipt).count(), 1)
            finally:
                engine.dispose()

    def test_migration_preserves_old_entries_and_is_repeatable(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("CREATE TABLE health_entries (id INTEGER PRIMARY KEY, value FLOAT)")
                )
                conn.execute(text("INSERT INTO health_entries VALUES (1,74.25)"))
                m0049_health_create_receipts.up(conn)
                m0049_health_create_receipts.up(conn)
                self.assertEqual(
                    conn.execute(text("SELECT value FROM health_entries")).scalar(), 74.25
                )
                self.assertEqual(
                    conn.execute(text("SELECT count(*) FROM health_create_receipts")).scalar(), 0
                )
        finally:
            engine.dispose()

    def test_retry_cannot_acknowledge_a_replacement_inserted_during_receipt_read(self):
        from routes.health import delete_entry

        with tempfile.TemporaryDirectory(prefix="alles-health-race-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'health.db'}")
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            identity = str(uuid.uuid4())
            try:
                with sessions() as db:
                    original_id = save_entry(db, kind="weight", value=74.25, request_id=identity).id
                raced = []
                with sessions() as db:

                    @event.listens_for(db, "loaded_as_persistent")
                    def replace_after_receipt_load(_session, row):
                        if not isinstance(row, HealthCreateReceipt) or raced:
                            return
                        raced.append(True)
                        with sessions() as other:
                            delete_entry(original_id, other)
                            other.add(
                                HealthEntry(
                                    id=original_id, kind="sleep", value=8, date="2026-10-01"
                                )
                            )
                            other.commit()

                    try:
                        replayed = save_entry(db, kind="weight", value=74.25, request_id=identity)
                    except HealthInputError as error:
                        self.assertEqual(error.status_code, 410)
                    else:
                        self.assertEqual((replayed.kind, replayed.value), ("weight", 74.25))
                self.assertTrue(raced)
                with sessions() as db:
                    self.assertEqual(db.get(HealthEntry, original_id).kind, "sleep")
            finally:
                engine.dispose()

    def test_correction_cannot_write_a_replacement_inserted_after_receipt_read(self):
        from fastapi import HTTPException

        from routes.health import EntryPatch, delete_entry, update_entry

        with tempfile.TemporaryDirectory(prefix="alles-health-correction-race-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'health.db'}")
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            identity = str(uuid.uuid4())
            try:
                with sessions() as db:
                    original_id = save_entry(db, kind="weight", value=74.25, request_id=identity).id
                raced = []
                with sessions() as db:

                    @event.listens_for(db, "loaded_as_persistent")
                    def replace_after_receipt_load(_session, row):
                        if not isinstance(row, HealthCreateReceipt) or raced:
                            return
                        raced.append(True)
                        with sessions() as other:
                            delete_entry(original_id, other)
                            other.add(
                                HealthEntry(
                                    id=original_id, kind="sleep", value=8, date="2026-10-01"
                                )
                            )
                            other.commit()

                    with self.assertRaises(HTTPException) as raised:
                        update_entry(
                            original_id, EntryPatch(value=99, create_request_id=identity), db
                        )
                    self.assertEqual(raised.exception.status_code, 410)
                self.assertTrue(raced)
                with sessions() as db:
                    replacement = db.get(HealthEntry, original_id)
                    self.assertEqual((replacement.kind, replacement.value), ("sleep", 8))
            finally:
                engine.dispose()

    def test_initial_acknowledgment_cannot_read_a_replacement_after_commit(self):
        from routes.health import delete_entry

        with tempfile.TemporaryDirectory(prefix="alles-health-ack-race-") as root:
            engine = create_engine(f"sqlite:///{Path(root) / 'health.db'}")
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            try:
                with sessions() as db:
                    commit = db.commit

                    def replace_after_commit():
                        commit()
                        with sessions() as other:
                            original_id = other.query(HealthEntry).one().id
                            delete_entry(original_id, other)
                            other.add(
                                HealthEntry(
                                    id=original_id, kind="sleep", value=8, date="2026-10-01"
                                )
                            )
                            other.commit()

                    with mock.patch.object(db, "commit", side_effect=replace_after_commit):
                        with self.assertRaises(HealthInputError) as raised:
                            save_entry(db, kind="weight", value=74.25, request_id=str(uuid.uuid4()))
                    self.assertEqual(raised.exception.status_code, 410)
                with sessions() as db:
                    replacement = db.query(HealthEntry).one()
                    self.assertEqual((replacement.kind, replacement.value), ("sleep", 8))
            finally:
                engine.dispose()
