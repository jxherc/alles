"""Owned synthetic search snapshots remain intact through retries and deletion."""

import os
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from core.database import AndromedaSavedSearch, AndromedaSaveReceipt
from core.migrations import m0066_andromeda_save_receipts
from routes.andromeda import SaveBody, save_search
from tests._client import ApiTest


class SavedSearchRequestTests(ApiTest):
    def setUp(self):
        flag = mock.patch.dict(os.environ, {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"})
        flag.start()
        self.addCleanup(flag.stop)
        super().setUp()
        self.payload = {
            "query": "owned query !ai",
            "request_id": str(uuid.uuid4()),
            "request": {"category": "all", "query": "owned query !ai"},
            "results": [{"title": "Local result", "url": "http://127.0.0.1:1/source"}],
        }

    def save(self, **changes):
        return self.client.post("/api/andromeda/saved", json=self.payload | changes)

    def recover(self, **params):
        return self.client.get(
            "/api/andromeda/saved/requests/" + self.payload["request_id"], params=params
        )

    def test_supported_result_counts_roundtrip_without_truncation(self):
        for count in (13, 20, 600):
            with self.subTest(count=count):
                results = [
                    {
                        "title": f"Synthetic result {i}",
                        "url": f"http://127.0.0.1:1/{i}",
                        "snippet": "日" * 2000,
                    }
                    for i in range(count)
                ]
                response = self.save(results=results, request_id=str(uuid.uuid4()))
                self.assertEqual(response.status_code, 200, response.text[:200])
                reopened = self.client.get("/api/andromeda/saved/" + response.json()["id"])
                self.assertEqual(reopened.json()["results"], results)

    def test_retry_and_read_only_recovery_return_exact_snapshot(self):
        first = self.save()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.save().json(), first.json())
        self.assertEqual(self.recover().json(), first.json())
        with self.db() as db:
            self.assertEqual(db.query(AndromedaSavedSearch).count(), 1)
            self.assertEqual(db.query(AndromedaSaveReceipt).count(), 1)

    def test_missing_request_recovery_never_creates(self):
        self.assertEqual(self.recover().status_code, 404)
        self.assertEqual(self.client.get("/api/andromeda/saved").json()["searches"], [])

    def test_different_payload_cannot_reuse_identity(self):
        first = self.save().json()
        for field, value in {
            "query": "changed",
            "request": {"category": "news"},
            "results": [],
            "overview": {"claims": ["different"]},
            "evidence": [{"quote": "changed"}],
            "model": {"model": "changed"},
            "verification": {"status": "changed"},
            "verifier_model": {"model": "changed"},
        }.items():
            with self.subTest(field=field):
                self.assertEqual(self.save(**{field: value}).status_code, 409)
        self.assertEqual(self.recover().json(), first)

    def test_equivalent_object_key_order_replays(self):
        first = self.save().json()
        self.assertEqual(
            self.save(request={"query": "owned query !ai", "category": "all"}).json(), first
        )

    def test_deleted_snapshot_stays_deleted_on_retry(self):
        first = self.save().json()
        self.assertEqual(self.client.delete("/api/andromeda/saved/" + first["id"]).status_code, 200)
        self.assertEqual(self.save().status_code, 410)
        self.assertEqual(self.recover().status_code, 410)
        with self.db() as db:
            self.assertEqual(db.query(AndromedaSavedSearch).count(), 0)
            self.assertEqual(db.query(AndromedaSaveReceipt).count(), 1)

    def test_legacy_and_new_identities_allow_intentional_separate_snapshots(self):
        first = self.save(request_id="").json()
        second = self.save(request_id="").json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotIn("request_id", first)
        self.assertNotEqual(
            self.save().json()["id"], self.save(request_id=str(uuid.uuid4())).json()["id"]
        )

    def test_invalid_identity_and_blank_query_never_write(self):
        for identity in ("invalid", uuid.uuid4().hex, str(uuid.uuid4()).upper()):
            self.assertEqual(self.save(request_id=identity).status_code, 400)
        self.assertEqual(self.save(query="   ").status_code, 400)
        self.assertEqual(self.client.get("/api/andromeda/saved").json()["searches"], [])

    def test_recovery_scope_matches_the_current_store(self):
        scopes = self.client.get("/api/andromeda/saved").json()["recovery_scopes"]
        self.assertTrue(scopes)
        self.assertEqual(self.save(recovery_scope="wrong").status_code, 409)
        self.assertEqual(self.save(recovery_scope=scopes[0]).status_code, 200)
        self.assertEqual(self.recover(recovery_scope="wrong").status_code, 409)
        self.assertEqual(self.recover(recovery_scope=scopes[0]).status_code, 200)

    def test_bounds_reject_whole_snapshot_without_writing(self):
        self.assertEqual(self.save(results=[{}] * 601).status_code, 422)
        self.assertEqual(self.save(results=[{"snippet": "x" * 20_000_000}]).status_code, 413)
        self.assertEqual(self.client.get("/api/andromeda/saved").json()["searches"], [])

    def test_receipt_and_snapshot_commit_atomically(self):
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("synthetic failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                    save_search(SaveBody(**self.payload), db)
            db.rollback()
            self.assertEqual(db.query(AndromedaSavedSearch).count(), 0)
            self.assertEqual(db.query(AndromedaSaveReceipt).count(), 0)
        self.assertEqual(self.save().status_code, 200)

    def test_replay_releases_transaction_for_later_save(self):
        first = self.save().json()
        with self.db() as db:
            self.assertEqual(save_search(SaveBody(**self.payload), db)["id"], first["id"])
            second = save_search(SaveBody(**(self.payload | {"request_id": str(uuid.uuid4())})), db)
            self.assertNotEqual(second["id"], first["id"])


class SavedSearchMigrationTests(unittest.TestCase):
    def test_receipt_migration_repeats_without_changing_old_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = create_engine("sqlite:///" + str(Path(folder) / "synthetic.db"))
            self.addCleanup(engine.dispose)
            AndromedaSavedSearch.__table__.create(engine)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO andromeda_saved_searches (id, query, results_json) VALUES ('old', 'exact old query', '[1,2]')"
                    )
                )
                m0066_andromeda_save_receipts.up(conn)
                m0066_andromeda_save_receipts.up(conn)
                self.assertEqual(
                    conn.execute(
                        text("SELECT query, results_json FROM andromeda_saved_searches")
                    ).one(),
                    ("exact old query", "[1,2]"),
                )
            self.assertIn("andromeda_save_receipts", inspect(engine).get_table_names())

    def test_concurrent_identical_requests_create_one_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            engine = create_engine("sqlite:///" + str(Path(folder) / "synthetic.db"))
            self.addCleanup(engine.dispose)
            AndromedaSavedSearch.__table__.create(engine)
            AndromedaSaveReceipt.__table__.create(engine)
            sessions = sessionmaker(bind=engine)
            body = SaveBody(query="owned concurrent query", request_id=str(uuid.uuid4()))
            barrier = threading.Barrier(2)

            def save():
                with sessions() as db:
                    barrier.wait(timeout=5)
                    return save_search(body, db)["id"]

            with mock.patch.dict(os.environ, {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"}):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(save) for _ in range(2)]
                    ids = [future.result(timeout=10) for future in futures]
            self.assertEqual(ids[0], ids[1])
            with sessions() as db:
                self.assertEqual(db.query(AndromedaSavedSearch).count(), 1)
