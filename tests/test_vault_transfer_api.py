import tempfile
from pathlib import Path
from unittest import mock

from services import document_safety, vault_transfer
from tests._client import VaultApiTest


class VaultTransferApiTests(VaultApiTest):
    def setUp(self):
        super().setUp()
        self.source = Path(self._vault_tmp).resolve()
        self.destination_tmp = tempfile.TemporaryDirectory(prefix="alles-vault-api-destination-")
        self.state_tmp = tempfile.TemporaryDirectory(prefix="alles-vault-api-state-")
        self.destination = Path(self.destination_tmp.name) / "moved"
        self.active = self.source
        (self.source / "note.md").write_text("# isolated vault\n", "utf-8")
        self.state_patch = mock.patch.object(
            document_safety, "_state_root", lambda: Path(self.state_tmp.name)
        )
        self.active_patch = mock.patch.object(vault_transfer, "_active_vault", lambda: self.active)
        self.switch_patch = mock.patch.object(vault_transfer, "_set_active_vault", self._set_active)
        self.data_patch = mock.patch.object(
            vault_transfer, "data_dir", lambda: Path(self.destination_tmp.name)
        )
        self.state_patch.start()
        self.active_patch.start()
        self.switch_patch.start()
        self.data_patch.start()

    def tearDown(self):
        self.data_patch.stop()
        self.switch_patch.stop()
        self.active_patch.stop()
        self.state_patch.stop()
        self.state_tmp.cleanup()
        self.destination_tmp.cleanup()
        super().tearDown()

    def _set_active(self, path: Path):
        self.active = Path(path).resolve()

    def test_prepare_resume_delete_and_restore_are_separate_calls(self):
        prepared = self.client.post(
            "/api/vault-transfer/move", json={"destination": str(self.destination)}
        )
        self.assertEqual(prepared.status_code, 200)
        body = prepared.json()
        self.assertEqual(body["state"], "backed_up")
        self.assertEqual(body["source_files"], 1)
        self.assertNotIn("source_inventory", body)
        operation_id = body["id"]

        pending = self.client.get("/api/vault-transfer/pending").json()["transfers"]
        self.assertIn(operation_id, {item["id"] for item in pending})

        resumed = self.client.post(f"/api/vault-transfer/{operation_id}/resume")
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["state"], "complete")
        self.assertEqual(self.active, self.destination.resolve())
        self.assertTrue(self.source.is_dir())

        rejected = self.client.post(
            f"/api/vault-transfer/{operation_id}/delete-old",
            json={"confirmation": "delete it"},
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertTrue(self.source.is_dir())

        deleted = self.client.post(
            f"/api/vault-transfer/{operation_id}/delete-old",
            json={"confirmation": resumed.json()["delete_confirmation"]},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["old_deleted"])
        self.assertFalse(self.source.exists())

        restored = self.client.post(f"/api/vault-transfer/{operation_id}/rollback")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["state"], "rolled_back")
        self.assertFalse(restored.json()["old_deleted"])
        self.assertEqual(self.active, self.source)
        self.assertEqual((self.source / "note.md").read_text("utf-8"), "# isolated vault\n")

    def test_resume_reports_reindex_failure_and_can_retry(self):
        prepared = self.client.post(
            "/api/vault-transfer/move", json={"destination": str(self.destination)}
        ).json()
        operation_id = prepared["id"]

        with mock.patch(
            "services.personal_index.reindex_source", side_effect=RuntimeError("index failed")
        ):
            failed = self.client.post(f"/api/vault-transfer/{operation_id}/resume")

        self.assertEqual(failed.status_code, 500, failed.text)
        self.assertEqual(failed.json()["code"], "vault_reindex_failed")
        self.assertIn("search indexing failed", failed.json()["detail"])
        self.assertEqual(self.active, self.destination.resolve())

        retried = self.client.post(f"/api/vault-transfer/{operation_id}/resume")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["state"], "complete")

    def test_external_vault_preview_copy_and_move_are_explicit(self):
        external_copy = Path(self.destination_tmp.name) / "external-copy"
        external_copy.mkdir()
        (external_copy / "linked.md").write_text("[[note]]\n", "utf-8")
        preview = self.client.post(
            "/api/vault-transfer/import/preview",
            json={"source": str(external_copy), "name": "copy target", "workflow": "copy"},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["can_import"])
        self.assertTrue(preview.json()["links_preserved"])
        copied = self.client.post(
            "/api/vault-transfer/import",
            json={"source": str(external_copy), "name": "copy target", "workflow": "copy"},
        )
        self.assertEqual(copied.status_code, 200, copied.text)
        self.assertTrue(external_copy.is_dir())
        self.assertEqual(self.active, Path(copied.json()["destination"]))

        self.client.post(f"/api/vault-transfer/{copied.json()['id']}/rollback")
        external_move = Path(self.destination_tmp.name) / "external-move"
        external_move.mkdir()
        (external_move / "move.md").write_text("owner\n", "utf-8")
        moved = self.client.post(
            "/api/vault-transfer/import",
            json={"source": str(external_move), "name": "move target", "workflow": "move"},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertTrue(moved.json()["old_deleted"])
        self.assertFalse(external_move.exists())
        restored = self.client.post(f"/api/vault-transfer/{moved.json()['id']}/rollback")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertTrue(external_move.is_dir())


if __name__ == "__main__":
    import unittest

    unittest.main()
