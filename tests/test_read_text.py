"""Explicit article retrieval preserves saved records through failure and retry."""

import hashlib
import unittest
from unittest import mock

from sqlalchemy import create_engine, text

from core.database import ReadItem
from core.migrations import m0065_reading_text_state
from services.read_items import fetch_saved_text
from tests._client import ApiTest

EXTRACTED = {
    "success": True,
    "title": "Publisher title",
    "content": "Local full article paragraph.\n\n" + "More local article text. " * 80,
    "og_image": "",
}


class ReadTextTests(ApiTest):
    def setUp(self):
        super().setUp()
        response = self.client.post(
            "/api/read/save-news",
            json={
                "url": "http://127.0.0.1:1/local-synthetic-article",
                "title": "Saved headline",
                "excerpt": "Original summary.",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.item_id = response.json()["item"]["id"]
        self.path = "/api/read/" + self.item_id

    def current(self):
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def fetch(self, content_hash=None, **body):
        if content_hash is None:
            content_hash = self.current()["content_hash"]
        return self.client.post(
            self.path + "/fetch-text", json={"content_hash": content_hash, **body}
        )

    def test_news_save_stays_excerpt_until_explicit_fetch(self):
        before = self.current()
        self.assertEqual(before["text_state"], "excerpt")
        with mock.patch(
            "services.read_items.fetch_webpage_content", return_value=EXTRACTED
        ) as fetch:
            response = self.fetch()
        self.assertEqual(response.status_code, 200, response.text)
        fetch.assert_called_once_with(before["url"])
        result = response.json()
        self.assertEqual(result["id"], self.item_id)
        self.assertEqual(result["text"], EXTRACTED["content"])
        self.assertEqual(result["text_state"], "extracted")
        for field in ("title", "url", "tags", "source_kind", "added_at"):
            self.assertEqual(result[field], before[field])
        self.assertEqual(
            result["content_hash"], hashlib.sha256(EXTRACTED["content"].encode()).hexdigest()
        )

    def test_failed_or_empty_extraction_preserves_all_saved_fields(self):
        before = self.current()
        for result in (
            None,
            {"success": False, "content": "error page"},
            {"success": True, "content": " \n"},
        ):
            with (
                self.subTest(result=result),
                mock.patch("services.read_items.fetch_webpage_content", return_value=result),
            ):
                response = self.fetch()
            self.assertEqual(response.status_code, 502)
            self.assertEqual(self.current(), before)
        with mock.patch(
            "services.read_items.fetch_webpage_content", side_effect=OSError("local failure")
        ):
            self.assertEqual(self.fetch().status_code, 502)
        self.assertEqual(self.current(), before)

    def test_lost_response_retry_returns_current_text_without_refetch(self):
        original_hash = self.current()["content_hash"]
        with mock.patch(
            "services.read_items.fetch_webpage_content", return_value=EXTRACTED
        ) as fetch:
            first = self.fetch(original_hash)
            self.assertEqual(first.status_code, 200)
            updated = self.client.patch(
                self.path, json={"read": True, "fav": True, "tags": "source:news, later"}
            )
            self.assertEqual(updated.status_code, 200)
            second = self.fetch(original_hash)
        self.assertEqual(second.status_code, 200)
        fetch.assert_called_once()
        self.assertTrue(second.json()["read"])
        self.assertTrue(second.json()["fav"])
        self.assertEqual(second.json()["tags"], "source:news, later")
        self.assertEqual(second.json()["text"], first.json()["text"])

    def test_fetch_preserves_concurrent_metadata_changes_and_resets_changed_text_place(self):
        before = self.current()
        self.assertEqual(
            self.client.patch(
                self.path, json={"position": 0.6, "content_hash": before["content_hash"]}
            ).status_code,
            200,
        )

        def extract(_url):
            with self.db() as db:
                row = db.get(ReadItem, self.item_id)
                row.read_at = "2026-01-02T03:04:05"
                row.fav = True
                row.archived = True
                row.tags = "source:news, changed during fetch"
                db.commit()
            return EXTRACTED

        with mock.patch("services.read_items.fetch_webpage_content", side_effect=extract):
            result = self.fetch().json()
        self.assertEqual(result["position"], 0)
        self.assertTrue(result["read"] and result["fav"] and result["archived"])
        self.assertEqual(result["read_at"], "2026-01-02T03:04:05")
        self.assertEqual(result["tags"], "source:news, changed during fetch")

    def test_identical_extracted_text_keeps_reading_place(self):
        before = self.current()
        self.assertEqual(
            self.client.patch(
                self.path, json={"position": 0.6, "content_hash": before["content_hash"]}
            ).status_code,
            200,
        )
        with mock.patch(
            "services.read_items.fetch_webpage_content",
            return_value=EXTRACTED | {"content": before["text"]},
        ):
            result = self.fetch().json()
        self.assertEqual(result["position"], 0.6)
        self.assertEqual(result["text_state"], "extracted")
        self.assertEqual(result["content_hash"], before["content_hash"])

    def test_changed_version_rejects_before_fetch(self):
        with mock.patch("services.read_items.fetch_webpage_content") as fetch:
            response = self.fetch("0" * 64)
        self.assertEqual(response.status_code, 409)
        fetch.assert_not_called()

    def test_legacy_text_needs_explicit_replacement_and_is_not_inferred_from_tags(self):
        with self.db() as db:
            row = db.get(ReadItem, self.item_id)
            row.text_state = "unknown"
            db.commit()
        self.assertEqual(self.current()["text_state"], "unknown")
        with mock.patch(
            "services.read_items.fetch_webpage_content", return_value=EXTRACTED
        ) as fetch:
            self.assertEqual(self.fetch().status_code, 409)
            fetch.assert_not_called()
            response = self.fetch(replace_saved_text=True)
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once()

    def test_deletion_or_replacement_during_fetch_is_not_overwritten(self):
        for change in ("delete", "text", "url"):
            with self.subTest(change=change):
                with self.db() as db:
                    row = db.get(ReadItem, self.item_id)
                    if row is None:
                        row = ReadItem(
                            id=self.item_id,
                            url="http://127.0.0.1:1/local",
                            text="summary",
                            text_state="excerpt",
                        )
                        db.add(row)
                        db.commit()
                before = self.current()

                def extract(_url):
                    with self.db() as db:
                        row = db.get(ReadItem, self.item_id)
                        if change == "delete":
                            db.delete(row)
                        else:
                            setattr(row, change, "new saved value")
                        db.commit()
                    return EXTRACTED

                with mock.patch("services.read_items.fetch_webpage_content", side_effect=extract):
                    response = self.fetch(before["content_hash"])
                self.assertEqual(response.status_code, 404 if change == "delete" else 409)
                if change == "delete":
                    self.assertEqual(self.client.get(self.path).status_code, 404)
                else:
                    self.assertEqual(self.current()[change], "new saved value")

    def test_a_concurrent_completed_fetch_wins_without_overwriting_it(self):
        def extract(_url):
            with self.db() as db:
                row = db.get(ReadItem, self.item_id)
                row.text = "Already extracted by the other request."
                row.text_state = "extracted"
                row.read_position = 0.4
                db.commit()
            return EXTRACTED

        with mock.patch("services.read_items.fetch_webpage_content", side_effect=extract):
            response = self.fetch()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Already extracted by the other request.")
        self.assertEqual(response.json()["position"], 0.4)

    def test_commit_failure_keeps_the_original_record(self):
        before = self.current()
        with self.db() as db:
            with (
                mock.patch("services.read_items.fetch_webpage_content", return_value=EXTRACTED),
                mock.patch.object(
                    db, "commit", side_effect=RuntimeError("synthetic write failure")
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
                    fetch_saved_text(db, self.item_id, before["content_hash"])
        self.assertEqual(self.current(), before)

    def test_new_url_saves_mark_extraction_and_news_duplicate_keeps_that_state(self):
        for success, expected in ((True, "extracted"), (False, "empty")):
            url = f"http://127.0.0.1:1/local-{success}"
            with mock.patch(
                "services.read_items.fetch_webpage_content",
                return_value=EXTRACTED | {"success": success},
            ):
                saved = self.client.post("/api/read", json={"url": url})
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["text_state"], expected)
            result = self.client.post(
                "/api/read/save-news", json={"url": url, "excerpt": "new summary"}
            )
            self.assertEqual(result.json()["item"]["text_state"], expected)


class ReadTextMigrationTests(unittest.TestCase):
    def test_repeat_migration_marks_legacy_text_unknown_without_changing_it(self):
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE read_items (id TEXT PRIMARY KEY, text TEXT, read_position REAL, tags TEXT)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO read_items VALUES ('old', 'Exact legacy text.\n', 0.7, 'source:news')"
                    )
                )
                m0065_reading_text_state.up(connection)
                m0065_reading_text_state.up(connection)
                self.assertEqual(
                    connection.execute(
                        text("SELECT text,read_position,tags,text_state FROM read_items")
                    ).one(),
                    ("Exact legacy text.\n", 0.7, "source:news", "unknown"),
                )
        finally:
            engine.dispose()
