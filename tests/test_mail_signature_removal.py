"""Removed signature IDs must stay removed when an old editor retries."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.settings as cfg
from tests._client import ApiTest


class SignatureRemovalRecovery(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="alles-signature-removal-")
        self.patch = mock.patch.object(
            cfg, "_SETTINGS_FILE", Path(self.temp.name) / "settings.json"
        )
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()
        super().tearDown()

    def test_retry_of_removed_creation_does_not_restore_it(self):
        body = {"id": "owned-signature", "name": "work", "body": "fixture signature", "revision": 1}
        self.assertEqual(self.client.post("/api/mail/signatures", json=body).status_code, 200)
        self.assertEqual(self.client.delete("/api/mail/signatures/" + body["id"]).status_code, 200)
        self.assertEqual(self.client.post("/api/mail/signatures", json=body).status_code, 410)
        self.assertEqual(self.client.get("/api/mail/signatures").json()["signatures"], [])

    def test_old_editor_cannot_restore_removed_signature_with_a_higher_revision(self):
        body = {"id": "owned-signature", "name": "work", "body": "fixture signature", "revision": 1}
        self.assertEqual(self.client.post("/api/mail/signatures", json=body).status_code, 200)
        self.assertEqual(self.client.delete("/api/mail/signatures/" + body["id"]).status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/mail/signatures",
                json={**body, "body": "edited before removal", "revision": 2},
            ).status_code,
            410,
        )
        self.assertEqual(self.client.get("/api/mail/signatures").json()["signatures"], [])

    def create(self, sid="owned-signature", revision=1, text="original"):
        body = {"id": sid, "name": "work", "body": text}
        if revision is not None:
            body["revision"] = revision
        return self.client.post("/api/mail/signatures", json=body)

    def remove(self, sid="owned-signature", expected="1"):
        return self.client.delete(
            "/api/mail/signatures/" + sid, params={"expected_revision": expected}
        )

    def rows(self):
        return self.client.get("/api/mail/signatures").json()["signatures"]

    def test_stale_removal_preserves_newer_signature(self):
        self.assertEqual(self.create().status_code, 200)
        self.assertEqual(self.create(revision=2, text="newer").status_code, 200)
        self.assertEqual(self.remove().status_code, 409)
        self.assertEqual(self.rows()[0]["body"], "newer")
        self.assertEqual(self.remove(expected="2").status_code, 200)

    def test_repeated_removal_after_lost_reply_remains_successful(self):
        self.create()
        self.assertEqual(self.remove().status_code, 200)
        self.assertEqual(self.remove().status_code, 200)
        self.assertEqual(self.rows(), [])
        self.assertEqual(cfg.load_settings()["mail_signature_deleted_ids"], ["owned-signature"])

    def test_legacy_signature_can_be_conditionally_removed_at_zero(self):
        self.create(revision=None)
        self.assertEqual(self.remove(expected="0").status_code, 200)
        self.assertEqual(self.create(revision=None).status_code, 410)

    def test_removal_before_delayed_creation_prevents_creation(self):
        self.assertEqual(self.remove(expected="0").status_code, 200)
        self.assertEqual(self.create().status_code, 410)

    def test_removed_identity_survives_reload_without_retaining_content(self):
        self.create(text="private fixture text")
        self.remove()
        cfg._clear_settings_cache()
        self.assertEqual(self.create(revision=99).status_code, 410)
        saved = cfg.load_settings()
        self.assertEqual(saved["mail_signature_deleted_ids"], ["owned-signature"])
        self.assertEqual(saved["mail_signatures"], [])
        self.assertNotIn(
            "private fixture text", (Path(self.temp.name) / "settings.json").read_text()
        )

    def test_other_signatures_and_new_ids_remain_available(self):
        self.create()
        self.create(sid="other", text="other")
        self.remove()
        self.assertEqual(self.create(sid="replacement").status_code, 200)
        self.assertEqual({r["id"] for r in self.rows()}, {"other", "replacement"})

    def test_invalid_revision_never_removes_signature(self):
        self.create()
        for value in ["-1", "1.0", "true", "", "01", "1e0", " 1", "1 "]:
            self.assertEqual(self.remove(expected=value).status_code, 422, value)
        self.assertEqual(len(self.rows()), 1)

    def test_failed_persistence_keeps_signature_and_does_not_record_removal(self):
        self.create()
        with mock.patch.object(cfg, "save_settings", side_effect=OSError("owned write failure")):
            with self.assertRaises(OSError):
                self.remove()
        self.assertEqual(len(self.rows()), 1)
        self.assertNotIn(
            "owned-signature", cfg.load_settings().get("mail_signature_deleted_ids", [])
        )
        self.assertEqual(self.create(revision=2, text="still editable").status_code, 200)

    def test_high_revision_remains_removable(self):
        value = 10**30
        self.assertEqual(self.create(revision=value).status_code, 200)
        self.assertEqual(self.remove(expected=str(value)).status_code, 200)


if __name__ == "__main__":
    unittest.main()
