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

    def versioned_position(self, owner, sequence, position, base=""):
        item = self.client.get(self.path).json()
        return {
            "position": position,
            "content_hash": item["content_hash"],
            "position_revision": f"{owner}:{sequence}",
            "position_base": base,
        }

    def test_final_place_wins_in_either_delivery_order(self):
        from uuid import uuid4

        for newest_first in (False, True):
            with self.subTest(newest_first=newest_first):
                base = self.client.get(self.path).json()["position_revision"]
                owner = str(uuid4())
                first = self.versioned_position(owner, 1, 0.65, base)
                final = self.versioned_position(owner, 2, 0.75, base)
                for body in [final, first] if newest_first else [first, final]:
                    response = self.client.patch(self.path, json=body)
                    expected = 409 if newest_first and body is first else 200
                    self.assertEqual(response.status_code, expected, response.text)
                loaded = self.client.get(self.path).json()
                self.assertEqual(loaded["position"], 0.75)
                self.assertEqual(loaded["position_revision"], final["position_revision"])
                self.assertFalse(loaded["read"])

    def test_same_position_request_replays_but_cannot_change_its_value(self):
        from uuid import uuid4

        body = self.versioned_position(str(uuid4()), 1, 0.375)
        first = self.client.patch(self.path, json=body)
        self.assertEqual(first.status_code, 200)
        replay = self.client.patch(self.path, json=body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["position_revision"], first.json()["position_revision"])
        conflict = self.client.patch(self.path, json={**body, "position": 0.8, "fav": True})
        self.assertEqual(conflict.status_code, 409)
        loaded = self.client.get(self.path).json()
        self.assertEqual(loaded["position"], 0.375)
        self.assertFalse(loaded["fav"])

    def test_matching_base_cannot_roll_back_the_current_readers_sequence(self):
        from uuid import uuid4

        owner = str(uuid4())
        final = self.versioned_position(owner, 2, 0.75)
        self.assertEqual(self.client.patch(self.path, json=final).status_code, 200)
        older = self.versioned_position(owner, 1, 0.65, final["position_revision"])
        response = self.client.patch(self.path, json={**older, "fav": True, "read": True})
        self.assertEqual(response.status_code, 409, response.text)
        loaded = self.client.get(self.path).json()
        self.assertEqual(loaded["position"], 0.75)
        self.assertEqual(loaded["position_revision"], final["position_revision"])
        self.assertFalse(loaded["fav"])
        self.assertFalse(loaded["read"])

    def test_reopened_reader_prevents_previous_reader_from_overwriting(self):
        from uuid import uuid4

        original = str(uuid4())
        first = self.versioned_position(original, 1, 0.5)
        self.assertEqual(self.client.patch(self.path, json=first).status_code, 200)
        current = self.versioned_position(str(uuid4()), 1, 0.7, first["position_revision"])
        self.assertEqual(self.client.patch(self.path, json=current).status_code, 200)
        late = self.versioned_position(original, 2, 0.6)
        self.assertEqual(self.client.patch(self.path, json=late).status_code, 409)
        self.assertEqual(self.client.get(self.path).json()["position"], 0.7)

    def test_legacy_position_write_invalidates_an_older_versioned_reader(self):
        from uuid import uuid4

        owner = str(uuid4())
        first = self.versioned_position(owner, 1, 0.5)
        self.assertEqual(self.client.patch(self.path, json=first).status_code, 200)
        legacy = {"position": 0.8, "content_hash": first["content_hash"]}
        response = self.client.patch(self.path, json=legacy)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["position_revision"], first["position_revision"])
        late = self.versioned_position(owner, 2, 0.6)
        self.assertEqual(self.client.patch(self.path, json=late).status_code, 409)
        self.assertEqual(self.client.get(self.path).json()["position"], 0.8)

    def test_position_revision_metadata_is_paired_and_validated(self):
        from uuid import uuid4

        valid = self.versioned_position(str(uuid4()), 1, 0.5)
        for removed in ["position", "position_base", "position_revision"]:
            body = {k: v for k, v in valid.items() if k != removed}
            self.assertEqual(self.client.patch(self.path, json=body).status_code, 422)
        for revision in ["broken", str(uuid4()) + ":0", str(uuid4()) + ":-1"]:
            self.assertEqual(
                self.client.patch(
                    self.path, json={**valid, "position_revision": revision}
                ).status_code,
                422,
            )
        self.assertEqual(self.client.get(self.path).json()["position"], 0)


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


class ReadingPositionRevisionMigrationTests(unittest.TestCase):
    def test_migration_keeps_existing_position_and_text(self):
        from sqlalchemy import create_engine, text

        from core.migrations import m0067_reading_position_revision

        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE TABLE read_items (id TEXT PRIMARY KEY, text TEXT, read_position REAL)"
                    )
                )
                connection.execute(
                    text("INSERT INTO read_items VALUES ('fixture', 'exact local text', .625)")
                )
                m0067_reading_position_revision.up(connection)
                m0067_reading_position_revision.up(connection)
                row = connection.execute(
                    text("SELECT id, text, read_position, position_revision FROM read_items")
                ).one()
                self.assertEqual(tuple(row), ("fixture", "exact local text", 0.625, ""))
        finally:
            engine.dispose()
