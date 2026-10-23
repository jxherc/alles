"""Versioned signature retries preserve the newest accepted text."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest


class SignatureVersions(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="alles-signature-versions-")
        self.settings = mock.patch.object(
            core.settings, "_SETTINGS_FILE", Path(self.temp.name) / "settings.json"
        )
        self.settings.start()

    def tearDown(self):
        self.settings.stop()
        self.temp.cleanup()
        super().tearDown()

    def save(self, revision, body="original"):
        payload = {"id": "owned-signature", "name": "work", "body": body}
        if revision is not None:
            payload["revision"] = revision
        return self.client.post("/api/mail/signatures", json=payload)

    def rows(self):
        return self.client.get("/api/mail/signatures").json()["signatures"]

    def test_delayed_older_save_cannot_replace_confirmed_newer_text(self):
        self.assertEqual(self.save(2, "newer").status_code, 200)
        self.assertEqual(self.save(1).status_code, 409)
        self.assertEqual(self.rows()[0]["body"], "newer")

    def test_same_revision_replay_is_one_identical_saved_signature(self):
        first = self.save(1)
        second = self.save(1)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(len(self.rows()), 1)

    def test_same_revision_cannot_be_reused_for_other_text(self):
        self.assertEqual(self.save(1).status_code, 200)
        self.assertEqual(self.save(1, "changed").status_code, 409)
        self.assertEqual(self.rows()[0]["body"], "original")

    def test_edited_retry_advances_without_duplicate(self):
        self.assertEqual(self.save(1).status_code, 200)
        self.assertEqual(self.save(2, "newer").status_code, 200)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["body"], "newer")
        self.assertEqual(self.save(1).status_code, 409)

    def test_legacy_update_remains_available_and_invalidates_old_version(self):
        self.assertEqual(self.save(2).status_code, 200)
        self.assertEqual(self.save(None, "legacy update").status_code, 200)
        self.assertEqual(self.rows()[0]["body"], "legacy update")
        self.assertEqual(self.save(2).status_code, 409)

    def test_versioned_saves_require_positive_integer_and_stable_id(self):
        for revision in [0, -1, True, "1", 1.5]:
            self.assertEqual(self.save(revision).status_code, 422, revision)
        self.assertEqual(
            self.client.post(
                "/api/mail/signatures", json={"revision": 1, "body": "missing id"}
            ).status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
