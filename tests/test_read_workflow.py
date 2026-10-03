"""Saved reading changes are explicit and safe to repeat after an uncertain reply."""

import unittest
from unittest import mock

from tests._client import ApiTest


class ReadWorkflowTests(ApiTest):
    def setUp(self):
        super().setUp()
        with mock.patch(
            "services.read_items.fetch_webpage_content",
            side_effect=AssertionError("no network allowed"),
        ):
            response = self.client.post(
                "/api/read/save-news",
                json={
                    "url": "https://example.invalid/local-reading-fixture",
                    "title": "synthetic reading source",
                    "excerpt": "owned fixture passage",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()["item"]
        self.path = "/api/read/" + self.item["id"]

    def test_explicit_completion_is_idempotent_and_reversible(self):
        initial = self.client.get(self.path).json()
        self.assertFalse(initial["read"])
        first = self.client.patch(self.path, json={"read": True})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["read"])
        replay = self.client.patch(self.path, json={"read": True})
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["read_at"], first.json()["read_at"])
        self.assertTrue(self.client.get(self.path).json()["read"])
        undone = self.client.patch(self.path, json={"read": False})
        self.assertFalse(undone.json()["read"])
        self.assertEqual(undone.json()["read_at"], "")
        self.assertFalse(self.client.patch(self.path, json={"read": False}).json()["read"])

    def test_legacy_read_toggle_remains_compatible(self):
        self.assertTrue(self.client.post(self.path + "/read").json()["read"])
        self.assertFalse(self.client.post(self.path + "/read").json()["read"])

    def test_read_update_keeps_article_metadata(self):
        self.client.patch(self.path, json={"tags": "source:news, retained", "fav": True})
        self.client.patch(self.path, json={"read": True})
        result = self.client.get(self.path).json()
        self.assertTrue(result["read"])
        self.assertEqual(result["text"], "owned fixture passage")
        self.assertEqual(result["tags"], "source:news, retained")
        self.assertTrue(result["fav"])

    def test_reading_place_is_durable_idempotent_and_does_not_complete(self):
        item = self.client.get(self.path).json()
        self.assertEqual(item.get("position"), 0)
        body = {"position": 0.375, "content_hash": item["content_hash"]}
        first = self.client.patch(self.path, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["position"], 0.375)
        replay = self.client.patch(self.path, json=body)
        self.assertEqual(replay.json()["position"], 0.375)
        loaded = self.client.get(self.path).json()
        self.assertEqual(loaded["position"], 0.375)
        self.assertFalse(loaded["read"])
        self.assertEqual(loaded["text"], item["text"])

    def test_stale_text_cannot_save_position_or_partially_change_metadata(self):
        from core.database import ReadItem

        original = self.client.get(self.path).json()
        with self.db() as session:
            session.get(ReadItem, self.item["id"]).text = "replacement local text"
            session.commit()
        response = self.client.patch(
            self.path,
            json={
                "position": 0.5,
                "content_hash": original.get("content_hash", ""),
                "fav": True,
                "read": True,
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        fresh = self.client.get(self.path).json()
        self.assertEqual(fresh["position"], 0)
        self.assertFalse(fresh["fav"])
        self.assertFalse(fresh["read"])

    def test_reading_place_requires_bounds_and_matching_content(self):
        item = self.client.get(self.path).json()
        for position in (-0.1, 1.1, "nan", "inf"):
            response = self.client.patch(
                self.path, json={"position": position, "content_hash": item.get("content_hash", "")}
            )
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.patch(self.path, json={"position": 0.5})
        self.assertEqual(response.status_code, 409, response.text)


class ReadingPositionMigrationTests(unittest.TestCase):
    def test_existing_records_receive_zero_without_losing_data_and_reapply_is_safe(self):
        from sqlalchemy import create_engine, text

        from core.migrations import m0062_reading_position

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE read_items (id TEXT PRIMARY KEY, text TEXT)"))
                connection.execute(
                    text("INSERT INTO read_items (id, text) VALUES ('fixture', 'exact local text')")
                )
                m0062_reading_position.up(connection)
                m0062_reading_position.up(connection)
                row = connection.execute(
                    text("SELECT id, text, read_position FROM read_items")
                ).one()
                self.assertEqual(tuple(row), ("fixture", "exact local text", 0))
        finally:
            engine.dispose()
