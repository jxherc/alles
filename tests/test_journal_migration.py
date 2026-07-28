import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings as settings
from core.database import JournalEntry
from services import journal_migration, vault_md
from tests._client import VaultApiTest


class JournalMigrationTests(VaultApiTest):
    def test_path_parent_handle_keeps_sidecars_under_the_target_parent(self):
        parent = Path(self._vault_tmp) / "windows-parent-handle"
        parent.mkdir()
        seed = parent / "note.seed"
        seed.write_bytes(b"private")

        journal_migration._link_at(parent, seed.name, "note.installing")
        self.assertEqual((parent / "note.installing").read_bytes(), b"private")
        journal_migration._rename_at_no_replace(parent, "note.installing", "note.rollback")
        self.assertFalse((parent / "note.installing").exists())
        self.assertEqual((parent / "note.rollback").read_bytes(), b"private")
        journal_migration._unlink_at(parent, "note.rollback")
        self.assertFalse((parent / "note.rollback").exists())

    def setUp(self):
        super().setUp()
        self.settings_tmp = tempfile.TemporaryDirectory()
        self.operations_tmp = tempfile.TemporaryDirectory()
        self.settings_patch = mock.patch.object(
            settings, "_SETTINGS_FILE", Path(self.settings_tmp.name) / "settings.json"
        )
        self.data_patch = mock.patch.object(
            journal_migration, "data_dir", lambda: Path(self.operations_tmp.name)
        )
        self.settings_patch.start()
        self.data_patch.start()
        settings._SETTINGS_CACHE = None
        settings._SETTINGS_CACHE_SIG = None

    def tearDown(self):
        settings._SETTINGS_CACHE = None
        settings._SETTINGS_CACHE_SIG = None
        self.data_patch.stop()
        self.settings_patch.stop()
        self.operations_tmp.cleanup()
        self.settings_tmp.cleanup()
        super().tearDown()

    def _entry(self, day: str, content: str):
        response = self.client.put(
            f"/api/journal/{day}",
            json={"content": content, "mood": "calm", "tags": "work"},
        )
        self.assertEqual(response.status_code, 200)

    def _prepare(self):
        plan = self.client.get("/api/journal-migration/plan")
        self.assertEqual(plan.status_code, 200)
        response = self.client.post(
            "/api/journal-migration/prepare",
            json={"confirmation": plan.json()["confirmation"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["operation_id"]

    def test_preview_apply_and_rollback_are_separate_and_lossless(self):
        self._entry("2026-07-01", "first")
        self._entry("2026-07-02", "second")

        operation_id = self._prepare()
        self.assertFalse((vault_md.vault_dir() / "Journal" / "2026-07-01.md").exists())

        applied = self.client.post(f"/api/journal-migration/{operation_id}/apply")
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertEqual(applied.json()["state"], "applied")
        self.assertEqual(applied.json()["installed"], 2)
        self.assertEqual(
            applied.json()["source_of_truth"], "database until the approved Docs cutover"
        )
        self.assertIn(
            "first",
            (vault_md.vault_dir() / "Journal" / "2026-07-01.md").read_text("utf-8"),
        )
        db = self.db()
        try:
            self.assertEqual(db.query(JournalEntry).count(), 2)
        finally:
            db.close()

        rolled_back = self.client.post(f"/api/journal-migration/{operation_id}/rollback")
        self.assertEqual(rolled_back.status_code, 200, rolled_back.text)
        self.assertEqual(rolled_back.json()["state"], "rolled_back")
        self.assertFalse((vault_md.vault_dir() / "Journal" / "2026-07-01.md").exists())
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        self.assertFalse((operation / "stage").exists())

    def test_migration_preserves_every_content_character(self):
        content = "  leading\r\n---\r\nunknown: syntax\r\n---\r\ntrailing  \r\n\r\n"
        db = self.db()
        try:
            db.add(JournalEntry(date="2026-07-03", content=content, mood="calm", tags="work"))
            db.commit()
        finally:
            db.close()
        operation_id = self._prepare()

        applied = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(applied.status_code, 200, applied.text)
        target = vault_md.vault_dir() / "Journal" / "2026-07-03.md"
        expected = content.encode("utf-8")
        self.assertEqual(target.read_bytes()[-len(expected) :], expected)
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        self.assertFalse((operation / "stage").exists())
        repeated = self.client.post(f"/api/journal-migration/{operation_id}/apply")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["state"], "applied")

    def test_prepare_failure_removes_partially_staged_plaintext(self):
        self._entry("2026-07-01", "first")
        self._entry("2026-07-02", "second")
        db = self.db()
        plan = journal_migration.migration_plan(db)
        original = Path.write_bytes
        staged_writes = 0

        def fail_second_staged_write(path, content):
            nonlocal staged_writes
            if "journal-migrations" in path.parts and "stage" in path.parts:
                staged_writes += 1
                if staged_writes == 2:
                    raise OSError("simulated staging failure")
            return original(path, content)

        try:
            with (
                mock.patch.object(Path, "write_bytes", fail_second_staged_write),
                self.assertRaisesRegex(OSError, "staging failure"),
            ):
                journal_migration.prepare(db, plan["confirmation"])
        finally:
            db.close()

        operation_root = Path(self.operations_tmp.name) / "journal-migrations"
        self.assertEqual(list(operation_root.iterdir()), [])

    def test_existing_different_daily_note_blocks_prepare(self):
        self._entry("2026-07-01", "database copy")
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        target.write_text("external copy", "utf-8")

        plan = self.client.get("/api/journal-migration/plan").json()
        self.assertEqual(plan["conflicts"], ["Journal/2026-07-01.md"])
        response = self.client.post(
            "/api/journal-migration/prepare",
            json={"confirmation": plan["confirmation"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(target.read_text("utf-8"), "external copy")

    def test_external_file_appearing_after_prepare_is_preserved(self):
        self._entry("2026-07-01", "database copy")
        operation_id = self._prepare()
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        target.write_text("new external copy", "utf-8")

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(target.read_text("utf-8"), "new external copy")

    def test_database_edit_after_prepare_stops_apply(self):
        self._entry("2026-07-01", "before")
        operation_id = self._prepare()
        self._entry("2026-07-01", "after")

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 409)
        self.assertFalse((vault_md.vault_dir() / "Journal" / "2026-07-01.md").exists())

    def test_preflight_checks_every_source_before_installing_any_file(self):
        self._entry("2026-07-01", "stable")
        self._entry("2026-07-02", "before")
        operation_id = self._prepare()
        self._entry("2026-07-02", "after")

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 409)
        self.assertFalse((vault_md.vault_dir() / "Journal" / "2026-07-01.md").exists())
        self.assertFalse((vault_md.vault_dir() / "Journal" / "2026-07-02.md").exists())

    def test_invalid_legacy_date_and_symlinked_target_fail_closed(self):
        db = self.db()
        try:
            db.add(JournalEntry(date="../../escape", content="never copy"))
            db.commit()
        finally:
            db.close()
        plan = self.client.get("/api/journal-migration/plan").json()
        self.assertEqual(plan["invalid_dates"], ["../../escape"])
        refused = self.client.post(
            "/api/journal-migration/prepare",
            json={"confirmation": plan["confirmation"]},
        )
        self.assertEqual(refused.status_code, 400)

        db = self.db()
        try:
            db.query(JournalEntry).delete()
            db.commit()
        finally:
            db.close()
        self._entry("2026-07-01", "do not follow")
        redirected = vault_md.vault_dir() / "redirected"
        redirected.mkdir()
        (vault_md.vault_dir() / "Journal").symlink_to(redirected, target_is_directory=True)
        plan = self.client.get("/api/journal-migration/plan").json()
        self.assertEqual(plan["conflicts"], ["Journal/2026-07-01.md"])
        self.assertFalse((redirected / "2026-07-01.md").exists())

    def test_apply_rejects_a_parent_swapped_to_a_symlink_after_prepare(self):
        self._entry("2026-07-01", "do not redirect")
        operation_id = self._prepare()
        journal = vault_md.vault_dir() / "Journal"
        journal.mkdir()
        journal.rename(vault_md.vault_dir() / "detached-journal")
        redirected = Path(self.operations_tmp.name) / "redirected-journal"
        redirected.mkdir()
        journal.symlink_to(redirected, target_is_directory=True)

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse((redirected / "2026-07-01.md").exists())

    def test_apply_resumes_when_exact_file_was_installed_before_manifest_update(self):
        self._entry("2026-07-01", "resume me")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        staged = operation / "stage" / "Journal" / "2026-07-01.md"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        target.write_bytes(staged.read_bytes())
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        identity = target.stat()
        manifest["rows"][0]["owned_device"] = identity.st_dev
        manifest["rows"][0]["owned_inode"] = identity.st_ino
        journal_migration._atomic_json(manifest_path, manifest)

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "applied")
        self.assertEqual(response.json()["installed"], 1)

    def test_apply_resumes_when_interrupted_after_install_ownership_is_persisted(self):
        self._entry("2026-07-01", "resume pending link")
        operation_id = self._prepare()
        original_link = journal_migration.os.link
        interrupted = False

        def interrupt(source, destination, **kwargs):
            nonlocal interrupted
            if str(source).endswith(".installing") and not interrupted:
                interrupted = True
                raise SystemExit("simulated install interruption")
            return original_link(source, destination, **kwargs)

        with mock.patch.object(journal_migration.os, "link", side_effect=interrupt):
            with self.assertRaisesRegex(SystemExit, "install interruption"):
                self.client.post(f"/api/journal-migration/{operation_id}/apply")

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "applied")
        self.assertTrue(target.is_file())
        self.assertEqual(list(target.parent.glob(".*.installing")), [])

    def test_apply_keeps_every_publication_link_on_the_vault_filesystem(self):
        self._entry("2026-07-01", "cross-volume safe")
        operation_id = self._prepare()
        original_link = journal_migration.os.link
        links = []

        def same_filesystem_link(source, destination, **kwargs):
            source = Path(source)
            destination = Path(destination)
            links.append((source, destination))
            self.assertEqual(source.parent, destination.parent)
            return original_link(source, destination, **kwargs)

        with mock.patch.object(
            journal_migration.os,
            "link",
            side_effect=same_filesystem_link,
        ):
            response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreaterEqual(len(links), 2)

    def test_apply_syncs_the_published_note_before_marking_the_operation_applied(self):
        self._entry("2026-07-01", "durable publish")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        manifest_path = operation / "manifest.json"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        events = []
        original_link = journal_migration._link_at
        original_sync = journal_migration._fsync_parent
        original_atomic = journal_migration._atomic_json

        def record_link(parent_fd, source, destination):
            if destination == target.name:
                events.append(("link", target))
            return original_link(parent_fd, source, destination)

        def record_sync(parent_fd, path):
            events.append(("sync", Path(path)))
            return original_sync(parent_fd, path)

        def record_manifest(path, value):
            if path == manifest_path:
                events.append(("manifest", value["state"]))
            return original_atomic(path, value)

        with (
            mock.patch.object(journal_migration, "_link_at", side_effect=record_link),
            mock.patch.object(
                journal_migration,
                "_fsync_parent",
                side_effect=record_sync,
            ),
            mock.patch.object(journal_migration, "_atomic_json", side_effect=record_manifest),
        ):
            response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        link_index = events.index(("link", target))
        applied_index = events.index(("manifest", "applied"))
        self.assertTrue(
            any(
                link_index < index < applied_index and event == ("sync", target.parent)
                for index, event in enumerate(events)
            )
        )

    def test_atomic_manifest_replacement_syncs_its_parent_directory(self):
        target = Path(self.operations_tmp.name) / "manifest-sync" / "manifest.json"

        with mock.patch.object(journal_migration, "_fsync_directory") as sync:
            journal_migration._atomic_json(target, {"state": "prepared"})

        sync.assert_called_once_with(target.parent)

    def test_install_sidecar_is_not_published_until_its_identity_is_durable(self):
        self._entry("2026-07-01", "private journal content")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        manifest_path = operation / "manifest.json"
        original_atomic = journal_migration._atomic_json
        writes = 0

        def interrupt_identity_write(path, value):
            nonlocal writes
            if path == manifest_path:
                writes += 1
                if writes == 1:
                    row = value["rows"][0]
                    sidecar = vault_md.vault_dir() / "Journal" / row["installing"]
                    seed = sidecar.parent / row["install_seed"]
                    self.assertIsNotNone(row["owned_device"])
                    self.assertIsNotNone(row["owned_inode"])
                    self.assertFalse(sidecar.exists())
                    self.assertEqual(seed.read_bytes(), b"")
                    raise SystemExit("simulated crash before plaintext write")
            return original_atomic(path, value)

        with mock.patch.object(
            journal_migration,
            "_atomic_json",
            side_effect=interrupt_identity_write,
        ):
            with self.assertRaisesRegex(SystemExit, "before plaintext write"):
                self.client.post(f"/api/journal-migration/{operation_id}/apply")

        persisted = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        row = persisted["rows"][0]
        self.assertIsNone(row["owned_device"])
        self.assertIsNone(row["owned_inode"])
        self.assertIsNone(row["installing"])
        self.assertEqual(list((vault_md.vault_dir() / "Journal").glob(".*.installing")), [])

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse((operation / "installing").exists())

    def test_apply_recovers_when_a_recorded_install_sidecar_was_never_created(self):
        self._entry("2026-07-01", "resume before sidecar creation")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        row = manifest["rows"][0]
        row["installing"] = ".2026-07-01.md.interrupted.installing"
        journal_migration._atomic_json(manifest_path, manifest)

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "applied")
        self.assertTrue((vault_md.vault_dir() / "Journal" / "2026-07-01.md").is_file())
        self.assertEqual(list((vault_md.vault_dir() / "Journal").glob(".*.installing")), [])

    def test_apply_resumes_after_link_publication_and_removes_the_install_sidecar(self):
        self._entry("2026-07-01", "resume published link")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        staged = operation / "stage" / "Journal" / "2026-07-01.md"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        installing = target.with_name(f".{target.name}.interrupted.installing")
        installing.write_bytes(staged.read_bytes())
        identity = installing.stat()
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        row = manifest["rows"][0]
        row["owned_device"] = identity.st_dev
        row["owned_inode"] = identity.st_ino
        row["installing"] = installing.name
        journal_migration.os.link(installing, target)
        journal_migration._atomic_json(manifest_path, manifest)

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "applied")
        self.assertTrue(target.is_file())
        self.assertFalse(installing.exists())

    def test_apply_resume_preserves_an_edit_to_the_published_install_inode(self):
        self._entry("2026-07-01", "resume published owner edit")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        staged = operation / "stage" / "Journal" / "2026-07-01.md"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        installing = target.with_name(f".{target.name}.interrupted.installing")
        installing.write_bytes(staged.read_bytes())
        identity = installing.stat()
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        row = manifest["rows"][0]
        row["owned_device"] = identity.st_dev
        row["owned_inode"] = identity.st_ino
        row["installing"] = installing.name
        journal_migration.os.link(installing, target)
        journal_migration._atomic_json(manifest_path, manifest)
        target.write_bytes(b"owner edit after publication")

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.read_bytes(), b"owner edit after publication")
        self.assertEqual(installing.read_bytes(), b"owner edit after publication")

    def test_apply_rewrites_an_owned_partial_install_after_interruption(self):
        self._entry("2026-07-01", "resume partial install")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        staged = operation / "stage" / "Journal" / "2026-07-01.md"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        installing = target.with_name(f".{target.name}.interrupted.installing")
        installing.write_bytes(b"partial")
        identity = installing.stat()
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        row = manifest["rows"][0]
        row["owned_device"] = identity.st_dev
        row["owned_inode"] = identity.st_ino
        row["installing"] = installing.name
        journal_migration._atomic_json(manifest_path, manifest)
        desired = staged.read_bytes()

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(target.read_bytes(), desired)
        self.assertFalse(installing.exists())

    def test_applied_retry_finishes_plaintext_stage_cleanup(self):
        self._entry("2026-07-01", "cleanup retry")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        manifest["state"] = "applied"
        journal_migration._atomic_json(manifest_path, manifest)
        self.assertTrue((operation / "stage").is_dir())

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse((operation / "stage").exists())

    def test_rollback_removes_an_owned_file_published_before_installed_flag(self):
        self._entry("2026-07-01", "rollback interrupted install")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        staged = operation / "stage" / "Journal" / "2026-07-01.md"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        target.write_bytes(staged.read_bytes())
        identity = target.stat()
        manifest["rows"][0]["owned_device"] = identity.st_dev
        manifest["rows"][0]["owned_inode"] = identity.st_ino
        journal_migration._atomic_json(manifest_path, manifest)

        response = self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "rolled_back")
        self.assertFalse(target.exists())

    def test_rollback_removes_target_and_install_sidecar_after_publish_interruption(self):
        self._entry("2026-07-01", "rollback published link and sidecar")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        staged = operation / "stage" / "Journal" / "2026-07-01.md"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        installing = target.with_name(f".{target.name}.interrupted.installing")
        installing.write_bytes(staged.read_bytes())
        identity = installing.stat()
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        row = manifest["rows"][0]
        row["owned_device"] = identity.st_dev
        row["owned_inode"] = identity.st_ino
        row["installing"] = installing.name
        journal_migration.os.link(installing, target)
        journal_migration._atomic_json(manifest_path, manifest)

        response = self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "rolled_back")
        self.assertFalse(target.exists())
        self.assertFalse(installing.exists())

    def test_rollback_preserves_an_edit_to_the_published_install_inode(self):
        self._entry("2026-07-01", "rollback published owner edit")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        staged = operation / "stage" / "Journal" / "2026-07-01.md"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        installing = target.with_name(f".{target.name}.interrupted.installing")
        installing.write_bytes(staged.read_bytes())
        identity = installing.stat()
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        row = manifest["rows"][0]
        row["owned_device"] = identity.st_dev
        row["owned_inode"] = identity.st_ino
        row["installing"] = installing.name
        journal_migration.os.link(installing, target)
        journal_migration._atomic_json(manifest_path, manifest)
        target.write_bytes(b"owner edit before rollback")

        response = self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "rolled_back_with_conflicts")
        self.assertEqual(target.read_bytes(), b"owner edit before rollback")
        self.assertEqual(installing.read_bytes(), b"owner edit before rollback")

    def test_rollback_removes_an_owned_partial_install(self):
        self._entry("2026-07-01", "rollback partial install")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        installing = target.with_name(f".{target.name}.interrupted.installing")
        installing.write_bytes(b"partial")
        identity = installing.stat()
        manifest_path = operation / "manifest.json"
        manifest = journal_migration.json.loads(manifest_path.read_text("utf-8"))
        row = manifest["rows"][0]
        row["owned_device"] = identity.st_dev
        row["owned_inode"] = identity.st_ino
        row["installing"] = installing.name
        journal_migration._atomic_json(manifest_path, manifest)

        response = self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "rolled_back")
        self.assertFalse(target.exists())
        self.assertFalse(installing.exists())

    def test_apply_never_claims_an_independently_created_identical_note(self):
        self._entry("2026-07-01", "independent")
        operation_id = self._prepare()
        operation = Path(self.operations_tmp.name) / "journal-migrations" / operation_id
        staged = operation / "stage" / "Journal" / "2026-07-01.md"
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.parent.mkdir(parents=True)
        independent_bytes = staged.read_bytes()
        target.write_bytes(independent_bytes)

        response = self.client.post(f"/api/journal-migration/{operation_id}/apply")
        rolled_back = self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(rolled_back.status_code, 200, rolled_back.text)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), independent_bytes)

    def test_rollback_never_deletes_a_new_external_edit(self):
        self._entry("2026-07-01", "installed")
        operation_id = self._prepare()
        self.client.post(f"/api/journal-migration/{operation_id}/apply")
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        target.write_text("edited after migration", "utf-8")

        response = self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "rolled_back_with_conflicts")
        self.assertEqual(response.json()["rollback_conflicts"], ["Journal/2026-07-01.md"])
        self.assertEqual(target.read_text("utf-8"), "edited after migration")

    def test_rollback_rechecks_identity_at_the_delete_boundary(self):
        self._entry("2026-07-01", "installed")
        operation_id = self._prepare()
        self.client.post(f"/api/journal-migration/{operation_id}/apply")
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        original_rename = journal_migration._rename_at_no_replace
        raced = False

        def race(parent_fd, source, destination):
            nonlocal raced
            if source == target.name and not raced:
                raced = True
                target.write_text("edited at rollback boundary", "utf-8")
            return original_rename(parent_fd, source, destination)

        with mock.patch.object(journal_migration, "_rename_at_no_replace", side_effect=race):
            response = self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "rolled_back_with_conflicts")
        self.assertEqual(target.read_text("utf-8"), "edited at rollback boundary")

    def test_rollback_resumes_a_persisted_quarantine_after_interruption(self):
        self._entry("2026-07-01", "installed")
        operation_id = self._prepare()
        self.client.post(f"/api/journal-migration/{operation_id}/apply")
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        original_rename = journal_migration._rename_at_no_replace

        def interrupt(parent_fd, source, destination):
            original_rename(parent_fd, source, destination)
            raise SystemExit("simulated rollback interruption")

        with mock.patch.object(journal_migration, "_rename_at_no_replace", side_effect=interrupt):
            with self.assertRaisesRegex(SystemExit, "rollback interruption"):
                self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertFalse(target.exists())
        response = self.client.post(f"/api/journal-migration/{operation_id}/rollback")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "rolled_back")
        self.assertEqual(response.json()["installed"], 0)
        self.assertEqual(len(list(target.parent.glob(".*.rollback"))), 1)

    def test_rollback_retains_writes_through_an_open_file_descriptor(self):
        self._entry("2026-07-01", "installed")
        operation_id = self._prepare()
        self.client.post(f"/api/journal-migration/{operation_id}/apply")
        target = vault_md.vault_dir() / "Journal" / "2026-07-01.md"
        original_hash = journal_migration._hash_bytes
        raced = False

        with target.open("r+b", buffering=0) as handle:

            def write_after_hash(value):
                nonlocal raced
                result = original_hash(value)
                if not raced and not target.exists():
                    raced = True
                    handle.seek(0)
                    handle.write(b"late editor write")
                    handle.truncate()
                    os.fsync(handle.fileno())
                return result

            with mock.patch.object(journal_migration, "_hash_bytes", side_effect=write_after_hash):
                response = self.client.post(f"/api/journal-migration/{operation_id}/rollback")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "rolled_back")
        self.assertTrue(raced)
        self.assertFalse(target.exists())
        [recovery] = list(target.parent.glob(".*.rollback"))
        self.assertEqual(recovery.read_bytes(), b"late editor write")

    def test_locked_journal_requires_unlock_and_exact_confirmation(self):
        self._entry("2026-07-01", "private")
        locked = self.client.post(
            "/api/journal/lock/set", json={"passcode": "journal-passcode-one"}
        )
        self.assertEqual(locked.status_code, 200)
        self.assertEqual(self.client.get("/api/journal-migration/plan").status_code, 403)

        unlocked = self.client.post(
            "/api/journal/unlock", json={"passcode": "journal-passcode-one"}
        )
        token = unlocked.json()["token"]
        headers = {"x-journal-token": token}
        plan = self.client.get("/api/journal-migration/plan", headers=headers)
        self.assertTrue(plan.json()["locked"])
        wrong = self.client.post(
            "/api/journal-migration/prepare",
            headers=headers,
            json={"confirmation": "yes"},
        )
        self.assertEqual(wrong.status_code, 400)
        prepared = self.client.post(
            "/api/journal-migration/prepare",
            headers=headers,
            json={"confirmation": plan.json()["confirmation"]},
        )
        self.assertEqual(prepared.status_code, 200, prepared.text)
