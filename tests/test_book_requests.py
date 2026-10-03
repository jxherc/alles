"""Book creation keeps one identity through retries, edits and deletion."""

import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import httpx
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from core.database import Book, BookCreateReceipt
from core.migrations import m0064_book_create_receipts
from services.book_items import save_book
from tests._client import ApiTest


class BookRequestTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.payload = {
            "title": "Local book",
            "author": "Local writer",
            "request_id": str(uuid.uuid4()),
        }

    def save(self, **changes):
        return self.client.post("/api/books", json=self.payload | changes)

    def recover(self, **params):
        return self.client.get("/api/books/requests/" + self.payload["request_id"], params=params)

    def test_retry_and_read_only_lookup_return_same_book(self):
        first = self.save()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.save().json(), first.json())
        self.assertEqual(self.recover().json(), first.json())
        with self.db() as db:
            self.assertEqual(db.query(Book).count(), 1)
            self.assertEqual(db.query(BookCreateReceipt).count(), 1)

    def test_unknown_request_lookup_does_not_create(self):
        self.assertEqual(self.recover().status_code, 404)
        self.assertEqual(self.client.get("/api/books/overview").json()["total"], 0)

    def test_replay_releases_write_transaction_for_another_save_in_same_session(self):
        first = self.save().json()
        with self.db() as db:
            replay = save_book(db, **self.payload)
            self.assertEqual(replay.id, first["id"])
            second = save_book(db, title="Another local book", request_id=str(uuid.uuid4()))
            self.assertNotEqual(second.id, replay.id)
        self.assertEqual(self.client.get("/api/books/overview").json()["total"], 2)

    def test_deleted_book_cannot_be_recreated_by_retry(self):
        first = self.save().json()
        self.assertEqual(self.client.delete("/api/books/" + first["id"]).status_code, 200)
        self.assertEqual(self.save().status_code, 410)
        self.assertEqual(self.recover().status_code, 410)
        with self.db() as db:
            self.assertEqual(db.query(Book).count(), 0)
            self.assertEqual(
                db.get(BookCreateReceipt, self.payload["request_id"]).book_id, first["id"]
            )

    def test_changed_fields_cannot_reuse_the_request(self):
        first = self.save().json()
        for field, value in {
            "title": "changed",
            "author": "someone",
            "notes": "new",
            "status": "done",
            "year": 2020,
            "isbn": "1",
            "cover": "local.png",
            "rating": 3,
        }.items():
            with self.subTest(field=field):
                self.assertEqual(self.save(**{field: value}).status_code, 409)
        self.assertEqual(self.recover().json(), first)

    def test_normalized_equivalent_payload_replays(self):
        first = self.save(
            title="  Local book  ", author=" Local writer ", rating=8, cover=" local ", isbn=" 123 "
        ).json()
        second = self.save(rating=5, cover="local", isbn="123").json()
        self.assertEqual(first["id"], second["id"])

    def test_replay_preserves_later_edits(self):
        first = self.save().json()
        patch = {
            "title": "Edited book",
            "status": "done",
            "notes": "Exact edited notes",
            "rating": 4,
        }
        updated = self.client.patch("/api/books/" + first["id"], json=patch)
        self.assertEqual(updated.status_code, 200)
        replay = self.save().json()
        for key, value in patch.items():
            self.assertEqual(replay[key], value)
        self.assertTrue(replay["finished"])
        self.assertEqual(replay, self.recover().json())

    def test_legacy_and_separate_requests_can_save_another_copy(self):
        one = self.save(request_id="").json()
        two = self.save(request_id="").json()
        self.assertNotEqual(one["id"], two["id"])
        self.assertNotIn("request_id", one)
        three = self.save().json()
        four = self.save(request_id=str(uuid.uuid4())).json()
        self.assertNotEqual(three["id"], four["id"])
        with self.db() as db:
            self.assertEqual(db.query(BookCreateReceipt).count(), 2)

    def test_invalid_identity_cannot_create(self):
        for identity in ("invalid", uuid.uuid4().hex, str(uuid.uuid4()).upper()):
            self.assertEqual(self.save(request_id=identity).status_code, 400)
            self.assertEqual(self.client.get("/api/books/requests/" + identity).status_code, 400)
        self.assertEqual(self.client.get("/api/books/overview").json()["total"], 0)

    def test_recovery_scope_is_required_to_match_when_supplied(self):
        scopes = self.client.get("/api/books/overview").json()["recovery_scopes"]
        self.assertTrue(scopes)
        self.assertEqual(self.save(recovery_scope="wrong").status_code, 409)
        self.assertEqual(self.save(recovery_scope=scopes[0]).status_code, 200)
        self.assertEqual(self.recover(recovery_scope="wrong").status_code, 409)
        self.assertEqual(self.recover(recovery_scope=scopes[0]).status_code, 200)

    def test_failed_commit_keeps_neither_book_nor_receipt(self):
        with self.db() as db:
            with mock.patch.object(
                db, "commit", side_effect=RuntimeError("synthetic commit failure")
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    save_book(db, **self.payload)
            db.rollback()
            self.assertEqual(db.query(Book).count(), 0)
            self.assertEqual(db.query(BookCreateReceipt).count(), 0)
        self.assertEqual(self.save().status_code, 200)

    def test_lookup_distinguishes_empty_from_failed_results(self):
        request = httpx.Request("GET", "https://example.invalid/lookup")
        for response, expected in [
            (httpx.Response(200, json={"docs": []}, request=request), 200),
            (httpx.Response(503, json={"docs": []}, request=request), 503),
            (httpx.Response(200, json={"bad": []}, request=request), 503),
            (httpx.Response(200, text="invalid", request=request), 503),
        ]:
            with (
                self.subTest(status=response.status_code, body=response.text),
                mock.patch("httpx.get", return_value=response),
            ):
                result = self.client.get("/api/books/lookup", params={"q": "Local search"})
                self.assertEqual(result.status_code, expected)
        with mock.patch("httpx.get", side_effect=httpx.ConnectError("synthetic offline")):
            self.assertEqual(
                self.client.get("/api/books/lookup", params={"q": "Local search"}).status_code, 503
            )


class BookRequestConcurrencyTests(unittest.TestCase):
    def test_concurrent_same_identity_creates_one_book(self):
        with tempfile.TemporaryDirectory(prefix="alles-book-create-") as folder:
            engine = create_engine("sqlite:///" + str(Path(folder) / "fixture.db"))
            factory = sessionmaker(bind=engine)
            try:
                Book.__table__.create(engine)
                BookCreateReceipt.__table__.create(engine)
                barrier = threading.Barrier(2)
                identity = str(uuid.uuid4())

                def save():
                    with factory() as db:
                        barrier.wait(timeout=5)
                        return save_book(db, title="Local concurrent book", request_id=identity).id

                with (
                    mock.patch("services.personal_index.index_record"),
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    results = list(pool.map(lambda _: save(), range(2)))
                self.assertEqual(results[0], results[1])
                with factory() as db:
                    self.assertEqual(db.query(Book).count(), 1)
                    self.assertEqual(db.query(BookCreateReceipt).count(), 1)
            finally:
                engine.dispose()

    def test_migration_is_repeatable_and_preserves_existing_books(self):
        engine = create_engine("sqlite://")
        try:
            Book.__table__.create(engine)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO books(id,title,notes) VALUES ('local','Existing book','Exact notes')"
                    )
                )
                m0064_book_create_receipts.up(connection)
                m0064_book_create_receipts.up(connection)
                self.assertEqual(
                    connection.execute(text("SELECT title,notes FROM books")).one(),
                    ("Existing book", "Exact notes"),
                )
                self.assertEqual(
                    connection.execute(text("SELECT count(*) FROM book_create_receipts")).scalar(),
                    0,
                )
            self.assertIn(
                "ix_book_create_receipts_book_id",
                [row["name"] for row in inspect(engine).get_indexes("book_create_receipts")],
            )
        finally:
            engine.dispose()
