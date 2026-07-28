import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import document_safety, file_operations, vault_md, vault_transfer


class VaultTransferTests(unittest.TestCase):
    """Vault moves use only disposable source, destination, and recovery roots."""

    def setUp(self):
        self.source_tmp = tempfile.TemporaryDirectory(prefix="alles-vault-source-")
        self.destination_tmp = tempfile.TemporaryDirectory(prefix="alles-vault-destination-")
        self.state_tmp = tempfile.TemporaryDirectory(prefix="alles-vault-transfer-state-")
        self.source = Path(self.source_tmp.name).resolve()
        self.destination_parent = Path(self.destination_tmp.name).resolve()
        self.destination = self.destination_parent / "moved-vault"
        self.state = Path(self.state_tmp.name).resolve()
        self.active = self.source

        self.patches = [
            mock.patch.object(vault_md, "vault_dir", lambda: self.source),
            mock.patch.object(document_safety, "_state_root", lambda: self.state),
            mock.patch.object(vault_transfer, "_active_vault", lambda: self.active),
            mock.patch.object(vault_transfer, "_set_active_vault", self._set_active),
        ]
        for patch in self.patches:
            patch.start()

        (self.source / "folder" / "empty").mkdir(parents=True)
        (self.source / "readme.md").write_bytes(b"# owner vault\r\n\r\n[[folder/note]]")
        (self.source / "folder" / "note.md").write_bytes(b"---\ntags: [safe]\n---\nbody\n")
        (self.source / ".obsidian").mkdir()
        (self.source / ".obsidian" / "workspace.json").write_bytes(b'{"layout":"owner"}')
        (self.source / "asset.bin").write_bytes(bytes(range(256)))
        self.original = vault_transfer._inventory(self.source)

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.state_tmp.cleanup()
        self.destination_tmp.cleanup()
        self.source_tmp.cleanup()

    def _set_active(self, path: Path):
        self.active = Path(path).resolve()

    def test_move_copies_verifies_switches_and_keeps_old_vault(self):
        result = vault_transfer.move_vault(str(self.destination))

        self.assertEqual(result["state"], "complete")
        self.assertEqual(self.active, self.destination)
        self.assertTrue(self.source.is_dir())
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(self.source))
        )
        self.assertTrue(
            vault_transfer._same_inventory(
                self.original, vault_transfer._inventory(self.destination)
            )
        )
        backup = self.state / "vault-transfers" / result["id"] / "backup"
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(backup))
        )

    @unittest.skipIf(os.name == "nt", "POSIX directory modes are not enforced on Windows")
    def test_move_and_backup_preserve_private_directory_modes(self):
        os.chmod(self.source, 0o700)
        os.chmod(self.source / "folder", 0o710)

        result = vault_transfer.move_vault(str(self.destination))
        backup = self.state / "vault-transfers" / result["id"] / "backup"

        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.destination / "folder").stat().st_mode), 0o710)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((backup / "folder").stat().st_mode), 0o710)

    @unittest.skipIf(os.name == "nt", "POSIX directory modes are not enforced on Windows")
    def test_copy_populates_read_only_directories_before_restoring_their_modes(self):
        target = self.destination_parent / "read-only-copy"
        os.chmod(self.source / "folder", 0o555)
        expected = vault_transfer._inventory(self.source)

        try:
            vault_transfer._copy_snapshot(self.source, target, expected)

            self.assertEqual(
                (target / "folder" / "note.md").read_bytes(),
                (self.source / "folder" / "note.md").read_bytes(),
            )
            self.assertEqual(stat.S_IMODE((target / "folder").stat().st_mode), 0o555)
        finally:
            os.chmod(self.source / "folder", 0o700)
            if (target / "folder").exists():
                os.chmod(target / "folder", 0o700)

    def test_cross_device_guard_proves_the_source_is_never_renamed(self):
        real_rename = file_operations._rename_no_replace
        renamed = []

        def reject_source_rename(path, target):
            resolved = Path(path).resolve(strict=False)
            if vault_transfer._is_within(resolved, self.source):
                raise OSError("cross-device source rename is forbidden")
            renamed.append((resolved, Path(target).resolve(strict=False)))
            return real_rename(path, target)

        with mock.patch.object(file_operations, "_rename_no_replace", reject_source_rename):
            result = vault_transfer.move_vault(str(self.destination))

        self.assertEqual(result["state"], "complete")
        self.assertTrue(self.source.is_dir())
        self.assertEqual(len(renamed), 1)
        self.assertEqual(renamed[0][1], self.destination)
        self.assertTrue(
            vault_transfer._same_inventory(
                self.original, vault_transfer._inventory(self.destination)
            )
        )

    def test_move_never_replaces_a_destination_created_during_publication(self):
        original = file_operations._rename_no_replace

        def publish_after_race(stage, destination):
            destination.mkdir()
            (destination / "owner.txt").write_text("keep", "utf-8")
            return original(stage, destination)

        prepared = vault_transfer.prepare_vault_move(str(self.destination))
        with (
            mock.patch.object(file_operations, "_rename_no_replace", publish_after_race),
            self.assertRaisesRegex(vault_transfer.TransferConflict, "destination appeared"),
        ):
            vault_transfer.resume_vault_transfer(prepared["id"])

        self.assertEqual((self.destination / "owner.txt").read_text("utf-8"), "keep")
        self.assertEqual(self.active, self.source)

    def test_old_location_requires_separate_exact_confirmation(self):
        result = vault_transfer.move_vault(str(self.destination))
        with self.assertRaises(ValueError):
            vault_transfer.delete_old_vault(result["id"], "delete it")
        self.assertTrue(self.source.is_dir())

        deleted = vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])
        self.assertTrue(deleted["old_deleted"])
        self.assertFalse(self.source.exists())
        self.assertTrue(
            vault_transfer._same_inventory(
                self.original, vault_transfer._inventory(self.destination)
            )
        )
        backup = self.state / "vault-transfers" / result["id"] / "backup"
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(backup))
        )

    def test_rollback_restores_deleted_source_from_verified_backup(self):
        result = vault_transfer.move_vault(str(self.destination))
        vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])

        rolled_back = vault_transfer.rollback_vault_transfer(result["id"])
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertEqual(self.active, self.source)
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(self.source))
        )
        self.assertTrue(self.destination.is_dir())

    def test_rollback_never_replaces_a_recreated_old_location(self):
        result = vault_transfer.move_vault(str(self.destination))
        vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])
        original = file_operations._rename_no_replace

        def publish_after_race(stage, source):
            source.mkdir()
            (source / "owner.txt").write_text("keep", "utf-8")
            return original(stage, source)

        with (
            mock.patch.object(file_operations, "_rename_no_replace", publish_after_race),
            self.assertRaisesRegex(vault_transfer.TransferConflict, "appeared during rollback"),
        ):
            vault_transfer.rollback_vault_transfer(result["id"])

        self.assertEqual((self.source / "owner.txt").read_text("utf-8"), "keep")
        self.assertEqual(self.active, self.destination)

    def test_rollback_preserves_an_unowned_existing_staging_directory(self):
        result = vault_transfer.move_vault(str(self.destination))
        vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])
        stage = self.source.parent / f".{self.source.name}.alles-rollback-{result['id']}"
        stage.mkdir()
        marker = stage / "owner.txt"
        marker.write_text("keep", "utf-8")

        with self.assertRaisesRegex(vault_transfer.TransferConflict, "identity"):
            vault_transfer.rollback_vault_transfer(result["id"])

        self.assertEqual(marker.read_text("utf-8"), "keep")
        self.assertEqual(self.active, self.destination)

    def test_rollback_resumes_only_its_recorded_partial_staging_directory(self):
        result = vault_transfer.move_vault(str(self.destination))
        vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])
        original_copy = vault_transfer._copy_file
        interrupted = False

        def interrupt_once(source, destination):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise SystemExit("simulated rollback interruption")
            return original_copy(source, destination)

        with (
            mock.patch.object(vault_transfer, "_copy_file", side_effect=interrupt_once),
            self.assertRaisesRegex(SystemExit, "simulated rollback interruption"),
        ):
            vault_transfer.rollback_vault_transfer(result["id"])

        recovered = vault_transfer.rollback_vault_transfer(result["id"])
        self.assertEqual(recovered["state"], "rolled_back")
        self.assertEqual(self.active, self.source)
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(self.source))
        )

    def test_rollback_rejects_owner_edits_in_the_active_destination(self):
        result = vault_transfer.move_vault(str(self.destination))
        (self.destination / "new-owner-note.md").write_text("keep", "utf-8")

        with self.assertRaisesRegex(vault_transfer.TransferConflict, "destination changed"):
            vault_transfer.rollback_vault_transfer(result["id"])

        self.assertEqual(self.active, self.destination)
        self.assertEqual((self.destination / "new-owner-note.md").read_text("utf-8"), "keep")

    def test_rollback_rejects_an_operation_that_is_no_longer_active(self):
        result = vault_transfer.move_vault(str(self.destination))
        newer = self.destination_parent / "newer-vault"
        newer.mkdir()
        self.active = newer

        with self.assertRaisesRegex(vault_transfer.TransferConflict, "no longer the active"):
            vault_transfer.rollback_vault_transfer(result["id"])

        self.assertEqual(self.active, newer)

    def test_rollback_uses_the_same_transfer_lock_as_old_vault_deletion(self):
        lock = mock.MagicMock()
        expected = {"state": "rolled_back"}
        with (
            mock.patch.object(vault_transfer, "_TRANSFER_LOCK", lock),
            mock.patch.object(vault_transfer, "_rollback_vault_transfer", return_value=expected),
        ):
            result = vault_transfer.rollback_vault_transfer("operation")

        self.assertIs(result, expected)
        lock.__enter__.assert_called_once_with()
        lock.__exit__.assert_called_once()

    def test_direct_resume_uses_the_transfer_lock(self):
        lock = mock.MagicMock()
        expected = {"state": "complete"}
        with (
            mock.patch.object(vault_transfer, "_TRANSFER_LOCK", lock),
            mock.patch.object(vault_transfer, "_resume_vault_transfer", return_value=expected),
        ):
            result = vault_transfer.resume_vault_transfer("operation")

        self.assertIs(result, expected)
        lock.__enter__.assert_called_once_with()
        lock.__exit__.assert_called_once()

    def test_stale_prepared_transfer_cannot_replace_a_new_active_vault(self):
        other = self.destination_parent / "other"
        prepared = vault_transfer.prepare_vault_move(str(self.destination))
        other.mkdir()
        self.active = other.resolve()

        with self.assertRaisesRegex(vault_transfer.TransferConflict, "another vault transfer"):
            vault_transfer.resume_vault_transfer(prepared["id"])

        self.assertFalse(self.destination.exists())

    def test_delete_quarantines_and_restores_a_source_changed_at_the_boundary(self):
        result = vault_transfer.move_vault(str(self.destination))
        original_inventory = vault_transfer._inventory

        def inventory(path):
            path = Path(path)
            if ".alles-delete-" in path.name:
                (path / "late.md").write_text("late owner write", "utf-8")
            return original_inventory(path)

        with mock.patch.object(vault_transfer, "_inventory", side_effect=inventory):
            with self.assertRaisesRegex(vault_transfer.TransferConflict, "changed during deletion"):
                vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])

        self.assertTrue(self.source.is_dir())
        self.assertEqual((self.source / "late.md").read_text("utf-8"), "late owner write")
        quarantine = self.source.with_name(f".{self.source.name}.alles-delete-{result['id']}")
        self.assertFalse(quarantine.exists())

    def test_restart_with_a_complete_stage_resumes_without_recopying_source(self):
        prepared = vault_transfer.prepare_vault_move(str(self.destination))
        operation_dir = self.state / "vault-transfers" / prepared["id"]
        backup = operation_dir / "backup"
        stage = self.destination.parent / (f".{self.destination.name}.alles-stage-{prepared['id']}")
        vault_transfer._copy_snapshot(backup, stage, self.original)

        recovered = vault_transfer.resume_vault_transfer(prepared["id"])
        self.assertEqual(recovered["state"], "complete")
        self.assertEqual(self.active, self.destination)
        self.assertFalse(stage.exists())
        self.assertTrue(
            vault_transfer._same_inventory(
                self.original, vault_transfer._inventory(self.destination)
            )
        )

    def test_external_edit_during_backup_stops_before_switch(self):
        original_copy = vault_transfer._copy_snapshot

        def copy_then_edit(source, destination, inventory, *, on_create=None):
            original_copy(source, destination, inventory, on_create=on_create)
            (self.source / "readme.md").write_bytes(b"external edit during backup")

        with mock.patch.object(vault_transfer, "_copy_snapshot", side_effect=copy_then_edit):
            with self.assertRaises(vault_transfer.TransferConflict):
                vault_transfer.prepare_vault_move(str(self.destination))

        self.assertEqual(self.active, self.source)
        self.assertFalse(self.destination.exists())
        self.assertEqual((self.source / "readme.md").read_bytes(), b"external edit during backup")

    def test_source_edit_during_final_switch_restores_the_old_active_vault(self):
        def switch_then_edit(path):
            self._set_active(path)
            if self.active == self.destination:
                (self.source / "late-owner-note.md").write_text("keep", "utf-8")

        with mock.patch.object(vault_transfer, "_set_active_vault", side_effect=switch_then_edit):
            with self.assertRaisesRegex(vault_transfer.TransferConflict, "final vault switch"):
                vault_transfer.move_vault(str(self.destination))

        self.assertEqual(self.active, self.source)
        self.assertEqual((self.source / "late-owner-note.md").read_text("utf-8"), "keep")

    def test_completed_old_vault_deletion_retry_is_idempotent(self):
        result = vault_transfer.move_vault(str(self.destination))
        first = vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])
        second = vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])

        self.assertTrue(first["old_deleted"])
        self.assertTrue(second["old_deleted"])
        self.assertFalse(self.source.exists())

    def test_partial_quarantine_deletion_resumes_without_restoring_a_partial_vault(self):
        result = vault_transfer.move_vault(str(self.destination))
        original_rmtree = vault_transfer.shutil.rmtree
        failed_once = False

        def partially_remove(path, *args, **kwargs):
            nonlocal failed_once
            path = Path(path)
            if ".alles-delete-" in path.name and not failed_once:
                failed_once = True
                (path / "readme.md").unlink()
                raise OSError("interrupted recursive delete")
            return original_rmtree(path, *args, **kwargs)

        with mock.patch.object(vault_transfer.shutil, "rmtree", side_effect=partially_remove):
            with self.assertRaisesRegex(OSError, "interrupted recursive delete"):
                vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])

        self.assertFalse(self.source.exists())
        quarantine = Path(vault_transfer.transfer_status(result["id"])["delete_quarantine"])
        self.assertFalse((quarantine / "readme.md").exists())
        resumed = vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])
        self.assertTrue(resumed["old_deleted"])
        self.assertFalse(quarantine.exists())

    def test_partial_deletion_refuses_a_replaced_quarantine_directory(self):
        result = vault_transfer.move_vault(str(self.destination))
        original_rmtree = vault_transfer.shutil.rmtree
        failed_once = False

        def interrupt_delete(path, *args, **kwargs):
            nonlocal failed_once
            path = Path(path)
            if ".alles-delete-" in path.name and not failed_once:
                failed_once = True
                (path / "readme.md").unlink()
                raise OSError("interrupted recursive delete")
            return original_rmtree(path, *args, **kwargs)

        with mock.patch.object(vault_transfer.shutil, "rmtree", side_effect=interrupt_delete):
            with self.assertRaisesRegex(OSError, "interrupted recursive delete"):
                vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])

        quarantine = Path(vault_transfer.transfer_status(result["id"])["delete_quarantine"])
        preserved_partial = quarantine.with_name(quarantine.name + "-preserved")
        quarantine.rename(preserved_partial)
        quarantine.mkdir()
        self.addCleanup(original_rmtree, preserved_partial, ignore_errors=True)
        self.addCleanup(original_rmtree, quarantine, ignore_errors=True)
        replacement = quarantine / "replacement.md"
        replacement.write_text("do not delete", "utf-8")

        with self.assertRaisesRegex(vault_transfer.TransferConflict, "identity"):
            vault_transfer.delete_old_vault(result["id"], result["delete_confirmation"])

        self.assertEqual(replacement.read_text("utf-8"), "do not delete")
        self.assertTrue(preserved_partial.is_dir())

    def test_external_edit_during_destination_stage_stops_before_install(self):
        prepared = vault_transfer.prepare_vault_move(str(self.destination))
        original_copy = vault_transfer._copy_snapshot

        def copy_then_edit(source, destination, inventory, *, on_create=None):
            original_copy(source, destination, inventory, on_create=on_create)
            if source.name == "backup":
                (self.source / "readme.md").write_bytes(b"external edit during stage")

        with mock.patch.object(vault_transfer, "_copy_snapshot", side_effect=copy_then_edit):
            with self.assertRaises(vault_transfer.TransferConflict):
                vault_transfer.resume_vault_transfer(prepared["id"])

        self.assertEqual(self.active, self.source)
        self.assertFalse(self.destination.exists())
        self.assertEqual((self.source / "readme.md").read_bytes(), b"external edit during stage")

    def test_resume_rebuilds_its_owned_partial_destination_stage(self):
        prepared = vault_transfer.prepare_vault_move(str(self.destination))
        original_copy_file = vault_transfer._copy_file
        interrupted = False

        def interrupt_copy(source, destination):
            nonlocal interrupted
            original_copy_file(source, destination)
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt("simulated process exit")

        with mock.patch.object(vault_transfer, "_copy_file", side_effect=interrupt_copy):
            with self.assertRaisesRegex(KeyboardInterrupt, "process exit"):
                vault_transfer.resume_vault_transfer(prepared["id"])

        status = vault_transfer.transfer_status(prepared["id"])
        stage = self.destination_parent / f".{self.destination.name}.alles-stage-{prepared['id']}"
        self.assertTrue(stage.is_dir())
        self.assertIn("stage_identity", status)

        resumed = vault_transfer.resume_vault_transfer(prepared["id"])

        self.assertEqual(resumed["state"], "complete")
        self.assertNotIn("stage_identity", resumed)
        self.assertFalse(stage.exists())
        self.assertTrue(
            vault_transfer._same_inventory(
                self.original, vault_transfer._inventory(self.destination)
            )
        )

    def test_failed_snapshot_verification_removes_the_incomplete_destination(self):
        target = self.destination_parent / "failed-snapshot"
        with mock.patch.object(vault_transfer, "_same_inventory", return_value=False):
            with self.assertRaises(vault_transfer.TransferConflict):
                vault_transfer._copy_snapshot(self.source, target, self.original)
        self.assertFalse(target.exists())

    def test_snapshot_rejects_an_identical_root_substitution_during_verification(self):
        target = self.destination_parent / "substituted-snapshot"
        preserved = self.destination_parent / "preserved-snapshot"
        original_inventory = vault_transfer._inventory
        substituted = False

        def inventory(path):
            nonlocal substituted
            path = Path(path)
            if path == target and not substituted:
                substituted = True
                target.rename(preserved)
                vault_transfer.shutil.copytree(preserved, target)
            return original_inventory(path)

        with mock.patch.object(vault_transfer, "_inventory", side_effect=inventory):
            with self.assertRaisesRegex(vault_transfer.TransferConflict, "identity changed"):
                vault_transfer._copy_snapshot(self.source, target, self.original)

        self.assertTrue(target.is_dir())
        self.assertTrue(preserved.is_dir())

    def test_move_rechecks_the_stage_identity_immediately_before_publication(self):
        prepared = vault_transfer.prepare_vault_move(str(self.destination))
        stage = self.destination_parent / f".{self.destination.name}.alles-stage-{prepared['id']}"
        preserved = stage.with_name(stage.name + "-preserved")
        original_same = vault_transfer._same_directory_identity
        checks = 0

        def replace_before_publication(path, expected):
            nonlocal checks
            checks += 1
            path = Path(path)
            if checks == 3 and path == stage:
                stage.rename(preserved)
                vault_transfer.shutil.copytree(preserved, stage)
            return original_same(path, expected)

        with mock.patch.object(
            vault_transfer,
            "_same_directory_identity",
            side_effect=replace_before_publication,
        ):
            with self.assertRaisesRegex(vault_transfer.TransferConflict, "before publication"):
                vault_transfer.resume_vault_transfer(prepared["id"])

        self.assertFalse(self.destination.exists())
        self.assertTrue(stage.is_dir())
        self.assertTrue(preserved.is_dir())

    def test_no_space_for_backup_fails_without_writing_destination(self):
        with mock.patch.object(vault_transfer, "_available_bytes", return_value=0):
            with self.assertRaises(vault_transfer.InsufficientSpace):
                vault_transfer.prepare_vault_move(str(self.destination))
        self.assertEqual(self.active, self.source)
        self.assertFalse(self.destination.exists())
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(self.source))
        )

    def test_no_space_for_destination_keeps_verified_backup_and_source(self):
        prepared = vault_transfer.prepare_vault_move(str(self.destination))
        with mock.patch.object(vault_transfer, "_available_bytes", return_value=0):
            with self.assertRaises(vault_transfer.InsufficientSpace):
                vault_transfer.resume_vault_transfer(prepared["id"])
        backup = self.state / "vault-transfers" / prepared["id"] / "backup"
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(backup))
        )
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(self.source))
        )
        self.assertEqual(self.active, self.source)
        self.assertFalse(self.destination.exists())

    def test_permission_failure_keeps_source_and_active_setting(self):
        with mock.patch.object(
            vault_transfer, "_copy_file", side_effect=PermissionError("read denied")
        ):
            with self.assertRaises(PermissionError):
                vault_transfer.prepare_vault_move(str(self.destination))
        self.assertEqual(self.active, self.source)
        self.assertFalse(self.destination.exists())
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(self.source))
        )

    def test_relink_verifies_existing_vault_and_can_roll_back(self):
        existing = self.destination_parent / "existing-vault"
        existing.mkdir()
        (existing / "external.md").write_bytes(b"# existing Obsidian vault\n")
        existing_before = vault_transfer._inventory(existing)

        relinked = vault_transfer.relink_vault(str(existing))
        self.assertEqual(relinked["state"], "complete")
        self.assertEqual(self.active, existing)
        self.assertTrue(
            vault_transfer._same_inventory(existing_before, vault_transfer._inventory(existing))
        )
        self.assertTrue(
            vault_transfer._same_inventory(self.original, vault_transfer._inventory(self.source))
        )

        rolled_back = vault_transfer.rollback_vault_transfer(relinked["id"])
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertEqual(self.active, self.source)
        self.assertTrue(
            vault_transfer._same_inventory(existing_before, vault_transfer._inventory(existing))
        )

    def test_external_copy_uses_managed_destination_and_keeps_source(self):
        external = self.destination_parent / "external-copy"
        external.mkdir()
        (external / "note.md").write_text("[[linked-note]]\n", "utf-8")
        expected = vault_transfer._inventory(external)
        with mock.patch.object(vault_transfer, "data_dir", return_value=self.destination_parent):
            preview = vault_transfer.preview_external_vault(str(external), "imported copy")
            self.assertTrue(preview["can_import"])
            self.assertTrue(preview["links_preserved"])
            result = vault_transfer.import_external_vault(str(external), "imported copy")
        destination = Path(result["destination"])
        self.assertEqual(self.active, destination)
        self.assertTrue(vault_transfer._same_inventory(expected, vault_transfer._inventory(external)))
        self.assertTrue(vault_transfer._same_inventory(expected, vault_transfer._inventory(destination)))
        rolled_back = vault_transfer.rollback_vault_transfer(result["id"])
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertEqual(self.active, self.source)

    def test_external_move_deletes_only_after_verified_copy_and_can_restore(self):
        external = self.destination_parent / "external-move"
        external.mkdir()
        (external / "note.md").write_text("owner data\n", "utf-8")
        expected = vault_transfer._inventory(external)
        with mock.patch.object(vault_transfer, "data_dir", return_value=self.destination_parent):
            result = vault_transfer.import_external_vault(str(external), "imported move", move=True)
        self.assertTrue(result["old_deleted"])
        self.assertFalse(external.exists())
        self.assertTrue(vault_transfer._same_inventory(expected, vault_transfer._inventory(Path(result["destination"]))))
        vault_transfer.rollback_vault_transfer(result["id"])
        self.assertEqual(self.active, self.source)
        self.assertTrue(vault_transfer._same_inventory(expected, vault_transfer._inventory(external)))

    def test_external_preview_reports_destination_conflict_and_space(self):
        external = self.destination_parent / "external-conflict"
        external.mkdir()
        (external / "note.md").write_text("x", "utf-8")
        managed = self.destination_parent / "vaults" / "same-name"
        managed.mkdir(parents=True)
        with mock.patch.object(vault_transfer, "data_dir", return_value=self.destination_parent):
            preview = vault_transfer.preview_external_vault(str(external), "same-name")
        self.assertEqual(preview["conflicts"], ["same-name"])
        self.assertFalse(preview["can_import"])
        self.assertGreater(preview["required_bytes"], preview["source_bytes"])

    def test_symlink_is_rejected_without_copying_its_target(self):
        outside_tmp = tempfile.TemporaryDirectory(prefix="alles-vault-outside-")
        try:
            outside = Path(outside_tmp.name)
            (outside / "secret.md").write_text("outside owner data", "utf-8")
            try:
                (self.source / "linked-outside").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            with self.assertRaises(vault_transfer.TransferConflict):
                vault_transfer.prepare_vault_move(str(self.destination))
            self.assertFalse(self.destination.exists())
        finally:
            outside_tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
