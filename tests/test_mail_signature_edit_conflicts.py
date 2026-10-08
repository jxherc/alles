"""Conditional edits cannot overwrite newer text after an uncertain earlier save."""

import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cfg
from tests._client import ApiTest


class SignatureEditConflicts(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="alles-signature-edit-")
        self.patch = mock.patch.object(
            cfg, "_SETTINGS_FILE", Path(self.temp.name) / "settings.json"
        )
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()
        super().tearDown()

    def save(self, revision, body, expected=None):
        data = {"id": "owned-signature", "name": "work", "body": body, "revision": revision}
        if expected is not None:
            data["expected_revision"] = expected
        return self.client.post("/api/mail/signatures", json=data)

    def test_stale_expected_revision_cannot_overwrite_a_newer_save_even_with_higher_local_revision(
        self,
    ):
        self.assertEqual(self.save(1, "initial").status_code, 200)
        self.assertEqual(self.save(2, "other editor").status_code, 200)
        self.assertEqual(self.save(3, "stale changed retry", 1).status_code, 409)
        self.assertEqual(
            self.client.get("/api/mail/signatures").json()["signatures"][0]["body"], "other editor"
        )

    def test_missing_previously_read_signature_is_not_recreated(self):
        self.assertEqual(self.save(2, "previously read text", 1).status_code, 409)
        self.assertEqual(self.client.get("/api/mail/signatures").json()["signatures"], [])

    def test_conditional_edit_requires_a_stable_id_and_proposed_revision(self):
        for data in [
            {"name": "x", "body": "x", "revision": 1, "expected_revision": 0},
            {"id": "known", "name": "x", "body": "x", "expected_revision": 0},
        ]:
            self.assertEqual(self.client.post("/api/mail/signatures", json=data).status_code, 422)

    def test_current_edit_and_identical_lost_reply_retry_share_one_saved_version(self):
        self.assertEqual(self.save(1, "initial").status_code, 200)
        first = self.save(2, "edited", 1)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.save(2, "edited", 1).json(), first.json())
        self.assertEqual(first.json()["revision"], 2)

    def test_later_identical_state_can_confirm_an_older_retry(self):
        self.save(1, "initial")
        self.save(2, "edited", 1)
        self.save(3, "edited", 2)
        retry = self.save(2, "edited", 1)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["revision"], 3)

    def test_wrong_expected_revision_cannot_claim_a_newer_revision_with_identical_text(self):
        self.save(1, "initial")
        response = self.save(2, "initial", 0)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.client.get("/api/mail/signatures").json()["signatures"][0]["revision"], 1
        )

    def test_legacy_unversioned_edit_invalidates_a_previously_read_version(self):
        self.save(1, "initial")
        self.assertEqual(self.save(None, "legacy edit").status_code, 200)
        self.assertEqual(self.save(3, "stale editor", 1).status_code, 409)
        self.assertEqual(
            self.client.get("/api/mail/signatures").json()["signatures"][0]["body"], "legacy edit"
        )

    def test_legacy_signature_without_revision_can_be_edited_at_zero(self):
        self.save(None, "legacy")
        response = self.save(1, "edited", 0)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision"], 1)

    def test_new_signature_can_claim_zero(self):
        self.assertEqual(self.save(1, "new", 0).status_code, 200)
        self.assertEqual(len(self.client.get("/api/mail/signatures").json()["signatures"]), 1)

    def test_conditional_save_cannot_restore_a_removed_signature(self):
        self.save(1, "initial")
        self.assertEqual(
            self.client.delete("/api/mail/signatures/owned-signature").status_code, 200
        )
        self.assertEqual(self.save(2, "removed edit", 1).status_code, 410)

    def test_expected_revision_is_strict_and_nonnegative(self):
        self.save(1, "initial")
        for expected in [-1, True, "1", 1.5]:
            self.assertEqual(self.save(2, "edited", expected).status_code, 422, expected)
        self.assertEqual(
            self.client.get("/api/mail/signatures").json()["signatures"][0]["body"], "initial"
        )

    def test_failed_conditional_save_preserves_existing_text_and_revision(self):
        self.save(1, "initial")
        with mock.patch.object(cfg, "save_settings", side_effect=OSError("owned write failure")):
            with self.assertRaises(OSError):
                self.save(2, "edited", 1)
        row = self.client.get("/api/mail/signatures").json()["signatures"][0]
        self.assertEqual((row["body"], row["revision"]), ("initial", 1))
