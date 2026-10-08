"""Ordinary URL saves keep one durable identity through retries and deletion."""

import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.database import ReadCreateReceipt, ReadItem
from core.migrations import m0063_read_create_receipts
from services.read_items import save_url
from tests._client import ApiTest

EXTRACTED = {
    "success": True,
    "title": "synthetic saved source",
    "content": "Exact local fixture text.",
    "og_image": "",
}


class ReadRequestTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.payload = {
            "url": "https://example.invalid/local-save-retry",
            "request_id": str(uuid.uuid4()),
        }
        self.extractor = mock.patch(
            "services.read_items.fetch_webpage_content", return_value=EXTRACTED
        ).start()
        self.addCleanup(mock.patch.stopall)

    def save(self, **changes):
        return self.client.post("/api/read", json=self.payload | changes)

    def recover(self, **params):
        return self.client.get("/api/read/requests/" + self.payload["request_id"], params=params)

    def test_retry_returns_original_without_extracting_again(self):
        first = self.save()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.save().json(), first.json())
        self.assertEqual(self.recover().json(), first.json())
        self.extractor.assert_called_once_with(self.payload["url"])
        with self.db() as db:
            self.assertEqual(db.query(ReadItem).count(), 1)
            self.assertEqual(db.query(ReadCreateReceipt).count(), 1)

    def test_missing_request_lookup_does_not_fetch_or_save(self):
        self.assertEqual(self.recover().status_code, 404)
        self.extractor.assert_not_called()
        self.assertEqual(self.client.get("/api/read").json()["items"], [])

    def test_deleted_save_cannot_be_recreated(self):
        item = self.save().json()
        self.assertEqual(self.client.delete("/api/read/" + item["id"]).status_code, 200)
        self.assertEqual(self.save().status_code, 410)
        self.assertEqual(self.recover().status_code, 410)
        self.assertEqual(self.client.get("/api/read").json()["items"], [])
        self.extractor.assert_called_once()
        with self.db() as db:
            receipt = db.get(ReadCreateReceipt, self.payload["request_id"])
            self.assertEqual(receipt.item_id, item["id"])

    def test_changed_url_conflicts_before_extraction(self):
        item = self.save().json()
        self.assertEqual(self.save(url="https://example.invalid/different").status_code, 409)
        self.assertEqual(self.recover().json()["id"], item["id"])
        self.extractor.assert_called_once()

    def test_normalized_url_replays_the_same_intent(self):
        first = self.save(url=" example.invalid/path ").json()
        second = self.save(url="https://example.invalid/path").json()
        self.assertEqual(first["id"], second["id"])
        self.extractor.assert_called_once_with("https://example.invalid/path")

    def test_replay_preserves_current_reading_metadata(self):
        item = self.save().json()
        path = "/api/read/" + item["id"]
        full = self.client.get(path).json()
        patch = {
            "read": True,
            "fav": True,
            "archived": True,
            "tags": "keep",
            "position": 0.6,
            "content_hash": full["content_hash"],
        }
        self.assertEqual(self.client.patch(path, json=patch).status_code, 200)
        replay = self.save().json()
        for key in ("read", "fav", "archived", "tags", "position"):
            self.assertEqual(replay[key], patch[key])
        self.assertEqual(self.client.get(path).json()["text"], EXTRACTED["content"])
        self.extractor.assert_called_once()

    def test_invalid_request_identity_cannot_write(self):
        for identity in ("invalid", uuid.uuid4().hex, str(uuid.uuid4()).upper()):
            self.assertEqual(self.save(request_id=identity).status_code, 400)
            self.assertEqual(self.client.get("/api/read/requests/" + identity).status_code, 400)
        self.extractor.assert_not_called()

    def test_legacy_callers_can_intentionally_save_again(self):
        first = self.save(request_id="").json()
        second = self.save(request_id="").json()
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotIn("request_id", first)
        with self.db() as db:
            self.assertEqual(db.query(ReadCreateReceipt).count(), 0)

    def test_another_request_can_intentionally_save_same_url(self):
        first = self.save().json()
        second = self.save(request_id=str(uuid.uuid4())).json()
        self.assertNotEqual(first["id"], second["id"])

    def test_failed_extraction_keeps_link_without_duplicate_on_retry(self):
        self.extractor.return_value = {"success": False, "content": ""}
        first = self.save().json()
        self.assertEqual(self.save().json()["id"], first["id"])
        self.assertEqual(self.client.get("/api/read/" + first["id"]).json()["text"], "")
        self.extractor.assert_called_once()

    def test_storage_scope_is_checked_before_mutation_or_recovery(self):
        with mock.patch("routes.read._recovery_scopes", return_value=["a" * 64]):
            self.assertEqual(self.client.get("/api/read").json()["recovery_scopes"], ["a" * 64])
            self.assertEqual(self.save(recovery_scope="b" * 64).status_code, 409)
            self.assertEqual(self.recover(recovery_scope="b" * 64).status_code, 409)
            self.extractor.assert_not_called()
            self.assertEqual(self.save(recovery_scope="a" * 64).status_code, 200)
            self.assertEqual(self.recover(recovery_scope="a" * 64).status_code, 200)

    def test_receipt_and_article_share_one_transaction(self):
        with self.db() as db:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("synthetic outage")):
                with self.assertRaisesRegex(RuntimeError, "synthetic outage"):
                    save_url(db, self.payload["url"], self.payload["request_id"])
            db.rollback()
        with self.db() as db:
            self.assertEqual(db.query(ReadItem).count(), 0)
            self.assertEqual(db.query(ReadCreateReceipt).count(), 0)
        self.assertEqual(self.save().status_code, 200)


class ReadRequestConcurrencyTests(unittest.TestCase):
    def test_two_workers_resolve_one_request_to_one_record(self):
        with tempfile.TemporaryDirectory(prefix="alles-read-request-") as directory:
            engine = create_engine("sqlite:///" + str(Path(directory) / "fixture.db"))
            try:
                ReadItem.__table__.create(engine)
                ReadCreateReceipt.__table__.create(engine)
                session = sessionmaker(bind=engine)
                barrier = threading.Barrier(2)
                identity = str(uuid.uuid4())

                def extract(_url):
                    barrier.wait(timeout=10)
                    return EXTRACTED

                def create():
                    with session() as db:
                        return save_url(db, "https://example.invalid/concurrent", identity).id

                with (
                    mock.patch("services.read_items.fetch_webpage_content", side_effect=extract),
                    mock.patch("services.personal_index.index_record"),
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    one, two = [
                        future.result(timeout=15)
                        for future in [pool.submit(create), pool.submit(create)]
                    ]
                self.assertEqual(one, two)
                with session() as db:
                    self.assertEqual(db.query(ReadItem).count(), 1)
                    self.assertEqual(db.query(ReadCreateReceipt).count(), 1)
            finally:
                engine.dispose()


class ReadRequestMigrationTests(unittest.TestCase):
    def test_migration_preserves_existing_reading_and_is_repeatable(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE read_items (id TEXT PRIMARY KEY, text TEXT)"))
                connection.execute(
                    text("INSERT INTO read_items VALUES ('fixture','keep exact text')")
                )
                m0063_read_create_receipts.up(connection)
                connection.execute(
                    text(
                        "INSERT INTO read_create_receipts (id,payload_hash,item_id) VALUES ('request','hash','fixture')"
                    )
                )
                m0063_read_create_receipts.up(connection)
                self.assertEqual(
                    tuple(connection.execute(text("SELECT * FROM read_items")).one()),
                    ("fixture", "keep exact text"),
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT item_id FROM read_create_receipts")
                    ).scalar_one(),
                    "fixture",
                )
        finally:
            engine.dispose()
