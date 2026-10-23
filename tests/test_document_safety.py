import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from services import document_safety, vault_md


class DocumentSafetyTests(unittest.TestCase):
    """Every safety artifact and document lives in a throwaway directory."""

    def setUp(self):
        self.vault_tmp = tempfile.TemporaryDirectory(prefix="alles-safe-doc-vault-")
        self.state_tmp = tempfile.TemporaryDirectory(prefix="alles-safe-doc-state-")
        self.vault = Path(self.vault_tmp.name)
        self.state = Path(self.state_tmp.name)
        self.vault_patch = mock.patch.object(vault_md, "vault_dir", lambda: self.vault)
        self.state_patch = mock.patch.object(document_safety, "_state_root", lambda: self.state)
        self.vault_patch.start()
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.vault_patch.stop()
        self.state_tmp.cleanup()
        self.vault_tmp.cleanup()

    def test_draft_is_private_hashed_and_does_not_touch_the_vault(self):
        before = list(self.vault.rglob("*"))
        saved = document_safety.save_draft("plans/private.md", "local work", "base")

        self.assertEqual(saved["path"], "plans/private.md")
        self.assertNotIn("private", str(next((self.state / "drafts").iterdir())))
        self.assertEqual(document_safety.load_draft("plans/private.md")["content"], "local work")
        self.assertEqual(len(document_safety.list_drafts()), 1)
        self.assertEqual(list(self.vault.rglob("*")), before)
        self.assertTrue(document_safety.delete_draft("plans/private.md"))
        self.assertIsNone(document_safety.load_draft("plans/private.md"))

    def test_draft_content_and_metadata_publish_as_one_atomic_bundle(self):
        document_safety.save_draft("atomic.md", "first", "base-one")
        original_replace = os.replace

        def interrupt(source, destination):
            if Path(destination).name == "draft.json":
                raise SystemExit("simulated draft interruption")
            return original_replace(source, destination)

        with mock.patch.object(document_safety.os, "replace", side_effect=interrupt):
            with self.assertRaisesRegex(SystemExit, "draft interruption"):
                document_safety.save_draft("atomic.md", "second", "base-two")

        draft = document_safety.load_draft("atomic.md")
        self.assertEqual(draft["content"], "first")
        self.assertEqual(draft["base_hash"], "base-one")

    def test_unconditional_draft_delete_waits_for_draft_mutations(self):
        document_safety.save_draft("plans/private.md", "local work", "base")
        started = threading.Event()
        result = []

        def remove():
            started.set()
            result.append(document_safety.delete_draft("plans/private.md"))

        with document_safety._DRAFT_LOCK:
            worker = threading.Thread(target=remove)
            worker.start()
            self.assertTrue(started.wait(1))
            worker.join(0.05)
            self.assertTrue(worker.is_alive())
        worker.join(1)

        self.assertEqual(result, [True])
        self.assertIsNone(document_safety.load_draft("plans/private.md"))

    def test_older_draft_write_from_the_same_session_cannot_replace_newer_content(self):
        document_safety.save_draft("ordered.md", "latest", "base", "browser-session", 12)

        stale = document_safety.save_draft("ordered.md", "stale", "base", "browser-session", 11)

        self.assertEqual(stale["write_revision"], 12)
        draft = document_safety.load_draft("ordered.md")
        self.assertEqual(draft["content"], "latest")
        self.assertEqual(draft["write_revision"], 12)

    def test_older_browser_generation_cannot_replace_a_newer_session_draft(self):
        document_safety.save_draft("ordered.md", "new tab", "base", "new-session", 1, 200)

        stale = document_safety.save_draft(
            "ordered.md", "old delayed tab", "base", "old-session", 99, 100
        )

        self.assertEqual(stale["write_session"], "new-session")
        self.assertEqual(stale["write_generation"], 200)
        draft = document_safety.load_draft("ordered.md")
        self.assertEqual(draft["content"], "new tab")

        document_safety.save_draft("ordered.md", "newest tab", "base", "newest-session", 1, 300)
        self.assertEqual(document_safety.load_draft("ordered.md")["content"], "newest tab")

    def test_stale_save_keeps_external_file_local_draft_and_conflict_copies(self):
        opened = vault_md.write("note.md", "base")
        document_safety.save_draft("note.md", "my local edit", opened["hash"])
        external = vault_md.write("note.md", "external edit")

        with self.assertRaises(document_safety.DocumentSaveConflict) as caught:
            document_safety.save_document("note.md", "my local edit", opened["hash"])

        self.assertEqual(vault_md.read("note.md")["content"], "external edit")
        conflict = document_safety.load_conflict(caught.exception.conflict["id"])
        self.assertEqual(conflict["local"], "my local edit")
        self.assertEqual(conflict["external"], "external edit")
        self.assertEqual(conflict["external_hash"], external["hash"])
        self.assertEqual(document_safety.load_draft("note.md")["content"], "my local edit")

        comparison = document_safety.compare_document("note.md", "my local edit", opened["hash"])
        self.assertFalse(comparison["base_matches"])
        self.assertIn("-external edit", comparison["diff"])
        self.assertIn("+my local edit", comparison["diff"])

    def test_conflict_for_an_externally_deleted_document_remains_loadable(self):
        opened = vault_md.write("deleted.md", "base")
        document_safety.save_draft("deleted.md", "local edit", opened["hash"])
        (self.vault / "deleted.md").unlink()

        with self.assertRaises(document_safety.DocumentSaveConflict) as caught:
            document_safety.save_document("deleted.md", "local edit", opened["hash"])

        conflict = document_safety.load_conflict(caught.exception.conflict["id"])
        self.assertEqual(conflict["local"], "local edit")
        self.assertEqual(conflict["external"], "")
        self.assertFalse(conflict["external_exists"])

    def test_interrupted_conditional_save_restores_the_visible_document_on_startup(self):
        opened = vault_md.write("restart-save.md", "original")
        destination = self.vault / "restart-save.md"
        original_publish = document_safety._publish_exclusive

        def crash_after_quarantine(source, target):
            if Path(target).resolve() == destination.resolve():
                raise SystemExit("simulated power loss")
            return original_publish(source, target)

        with mock.patch.object(
            document_safety, "_publish_exclusive", side_effect=crash_after_quarantine
        ):
            with self.assertRaises(SystemExit):
                document_safety._conditional_replace(destination, b"replacement", opened["hash"])

        self.assertFalse(destination.exists())
        self.assertEqual(document_safety.recover_interrupted_writes(), 1)
        self.assertEqual(destination.read_text("utf-8"), "original")
        self.assertEqual(document_safety.recover_interrupted_writes(), 0)

    def test_incomplete_write_journal_is_never_exposed_as_a_recoverable_transaction(self):
        opened = vault_md.write("private-journal.md", "original")
        destination = self.vault / "private-journal.md"
        original_write_json = document_safety._write_json

        def interrupt_manifest(path, value):
            if Path(path).name == "manifest.json":
                raise SystemExit("simulated crash while building the private journal")
            return original_write_json(path, value)

        with mock.patch.object(document_safety, "_write_json", side_effect=interrupt_manifest):
            with self.assertRaisesRegex(SystemExit, "private journal"):
                document_safety._conditional_replace(
                    destination,
                    b"replacement",
                    opened["hash"],
                )

        self.assertEqual(destination.read_text("utf-8"), "original")
        self.assertEqual(document_safety.recover_interrupted_writes(), 0)
        self.assertEqual(list((self.state / "write-transactions").iterdir()), [])

    def test_recovery_removes_a_journaled_vault_staging_file(self):
        opened = vault_md.write("staged-recovery.md", "original")
        destination = self.vault / "staged-recovery.md"
        transaction_id = "a" * 32
        backup = self.vault / f".{destination.name}.alles-{transaction_id}.backup"
        staging = self.vault / f".{destination.name}.alles-{transaction_id}.conditional"
        document_safety._publish_write_transaction(  # noqa: SLF001
            transaction_id,
            b"private replacement",
            {
                "id": transaction_id,
                "path": destination.name,
                "backup_path": backup.name,
                "staging_path": staging.name,
                "expected_hash": opened["hash"],
                "replacement_hash": document_safety._hash(b"private replacement"),  # noqa: SLF001
                "created_at": document_safety._now(),  # noqa: SLF001
            },
        )
        staging.write_bytes(b"private replacement")

        self.assertEqual(document_safety.recover_interrupted_writes(), 1)
        self.assertFalse(staging.exists())
        self.assertEqual(destination.read_text("utf-8"), "original")
        self.assertEqual(document_safety.recover_interrupted_writes(), 0)

    def test_recovery_accepts_an_unapplied_interrupted_document_create(self):
        transaction_id = "b" * 32
        destination = self.vault / "new-document.md"
        replacement = b"new document"
        document_safety._publish_write_transaction(  # noqa: SLF001
            transaction_id,
            replacement,
            {
                "id": transaction_id,
                "path": destination.name,
                "backup_path": f".{destination.name}.alles-{transaction_id}.backup",
                "staging_path": f".{destination.name}.alles-{transaction_id}.conditional",
                "expected_hash": "",
                "replacement_hash": document_safety._hash(replacement),  # noqa: SLF001
                "created_at": document_safety._now(),  # noqa: SLF001
            },
        )

        self.assertEqual(document_safety.recover_interrupted_writes(), 1)
        self.assertFalse(destination.exists())

    def test_recovery_accepts_a_completed_interrupted_document_create(self):
        transaction_id = "c" * 32
        destination = self.vault / "completed-create.md"
        replacement = b"new document"
        destination.write_bytes(replacement)
        document_safety._publish_write_transaction(  # noqa: SLF001
            transaction_id,
            replacement,
            {
                "id": transaction_id,
                "path": destination.name,
                "backup_path": f".{destination.name}.alles-{transaction_id}.backup",
                "staging_path": f".{destination.name}.alles-{transaction_id}.conditional",
                "expected_hash": "",
                "replacement_hash": document_safety._hash(replacement),  # noqa: SLF001
                "created_at": document_safety._now(),  # noqa: SLF001
            },
        )

        self.assertEqual(document_safety.recover_interrupted_writes(), 1)
        self.assertEqual(destination.read_bytes(), replacement)

    def test_unsupported_exclusive_publication_keeps_the_live_document_visible(self):
        opened = vault_md.write("unsupported.md", "original")
        destination = self.vault / "unsupported.md"

        with mock.patch.object(
            document_safety,
            "_publish_exclusive",
            side_effect=OSError("exclusive publication unsupported"),
        ):
            with self.assertRaisesRegex(OSError, "unsupported"):
                document_safety._conditional_replace(destination, b"replacement", opened["hash"])

        self.assertEqual(destination.read_text("utf-8"), "original")

    def test_conditional_replace_syncs_each_directory_mutation_before_backup_cleanup(self):
        opened = vault_md.write("durable.md", "original")
        destination = self.vault / "durable.md"
        syncs = []

        with (
            mock.patch.object(document_safety, "_require_exclusive_publication"),
            mock.patch.object(
                document_safety,
                "_fsync_directory",
                side_effect=lambda path: syncs.append(Path(path)),
            ),
        ):
            document_safety._conditional_replace(destination, b"replacement", opened["hash"])

        self.assertEqual(destination.read_bytes(), b"replacement")
        self.assertGreaterEqual(syncs.count(destination.parent), 3)

    def test_save_preserves_an_edit_that_arrives_at_the_publish_boundary(self):
        opened = vault_md.write("save-race.md", "original")
        path = self.vault / "save-race.md"
        original_rename = os.rename
        raced = False

        def race(source, destination):
            nonlocal raced
            if Path(source).resolve() == path.resolve() and not raced:
                raced = True
                path.write_bytes(b"owner edit during save")
            return original_rename(source, destination)

        with mock.patch.object(document_safety.os, "rename", side_effect=race):
            with self.assertRaises(document_safety.DocumentSaveConflict):
                document_safety.save_document("save-race.md", "alles edit", opened["hash"])
        self.assertEqual(path.read_bytes(), b"owner edit during save")

    def test_successful_save_revisions_and_restore_preserve_exact_bytes(self):
        original = b"\xef\xbb\xbf---\r\ntitle: exact\r\n---\r\nbody without newline"
        (self.vault / "exact.md").write_bytes(original)
        opened = vault_md.read("exact.md")
        candidate = opened["content"].replace("exact", "changed", 1)
        document_safety.save_draft("exact.md", candidate, opened["hash"])

        saved = document_safety.save_document("exact.md", candidate, opened["hash"])
        self.assertIsNotNone(saved["revision"])
        self.assertIsNone(document_safety.load_draft("exact.md"))
        revisions = document_safety.list_revisions("exact.md")
        self.assertEqual(revisions[0]["hash"], vault_md._hash_bytes(original))

        restored = document_safety.restore_revision("exact.md", revisions[0]["id"], saved["hash"])
        self.assertEqual((self.vault / "exact.md").read_bytes(), original)
        self.assertEqual(restored["hash"], vault_md._hash_bytes(original))

    def test_successful_save_does_not_clear_a_newer_concurrent_draft(self):
        opened = vault_md.write("newer-draft.md", "original")
        document_safety.save_draft(
            "newer-draft.md", "save candidate", opened["hash"], "browser-session", 1
        )
        original_replace = document_safety._conditional_replace

        def publish_then_autosave(path, content, expected_hash):
            original_replace(path, content, expected_hash)
            document_safety.save_draft(
                "newer-draft.md", "newer concurrent edit", opened["hash"], "browser-session", 2
            )

        with mock.patch.object(
            document_safety,
            "_conditional_replace",
            side_effect=publish_then_autosave,
        ):
            saved = document_safety.save_document(
                "newer-draft.md", "save candidate", opened["hash"]
            )

        self.assertTrue(saved["ok"])
        self.assertEqual(
            document_safety.load_draft("newer-draft.md")["content"],
            "newer concurrent edit",
        )

    def test_revision_restore_does_not_clear_a_newer_concurrent_draft(self):
        opened = vault_md.write("restore-draft.md", "original")
        saved = document_safety.save_document("restore-draft.md", "changed", opened["hash"])
        revision = document_safety.list_revisions("restore-draft.md")[0]
        original_replace = document_safety._conditional_replace

        def restore_then_autosave(path, content, expected_hash):
            original_replace(path, content, expected_hash)
            document_safety.save_draft(
                "restore-draft.md", "newer concurrent edit", saved["hash"], "browser-session", 4
            )

        with mock.patch.object(
            document_safety,
            "_conditional_replace",
            side_effect=restore_then_autosave,
        ):
            document_safety.restore_revision("restore-draft.md", revision["id"], saved["hash"])

        self.assertEqual(
            document_safety.load_draft("restore-draft.md")["content"],
            "newer concurrent edit",
        )

    def test_revision_restore_rechecks_after_snapshot_and_preserves_racing_edit(self):
        opened = vault_md.write("race.md", "original")
        saved = document_safety.save_document("race.md", "changed", opened["hash"])
        revision = document_safety.list_revisions("race.md")[0]
        path = self.vault / "race.md"
        original_rename = os.rename
        raced = False

        def race(source, destination):
            nonlocal raced
            if Path(source).resolve() == path.resolve() and not raced:
                raced = True
                path.write_bytes(b"owner edit during restore")
            return original_rename(source, destination)

        with mock.patch.object(document_safety.os, "rename", side_effect=race):
            with self.assertRaises(document_safety.RecoveryConflict):
                document_safety.restore_revision("race.md", revision["id"], saved["hash"])
        self.assertEqual(path.read_bytes(), b"owner edit during restore")

    def test_watcher_origin_distinguishes_local_external_and_draft_conflict(self):
        opened = vault_md.write("observe.md", "base")
        document_safety.save_draft("observe.md", "unfinished local", opened["hash"])
        external = vault_md.write("observe.md", "external")
        self.assertEqual(
            document_safety.classify_observed_change("observe.md", external["hash"]),
            "conflict",
        )

        document_safety.delete_draft("observe.md")
        document_safety.record_local_write("observe.md", external["hash"])
        self.assertEqual(
            document_safety.classify_observed_change("observe.md", external["hash"]),
            "local",
        )
        self.assertEqual(
            document_safety.classify_observed_change("observe.md", external["hash"]),
            "external",
        )

    def test_local_write_marker_survives_a_fresh_process(self):
        with tempfile.TemporaryDirectory(prefix="alles-safe-doc-restart-") as tmp:
            data = Path(tmp)
            (data / "settings.json").write_text(
                json.dumps({"vault_dir": str(self.vault)}),
                "utf-8",
            )
            written = vault_md.write("restart.md", "saved locally")
            with mock.patch.object(
                document_safety, "_state_root", lambda: data / ".document-safety"
            ):
                document_safety.record_local_write("restart.md", written["hash"])

            script = (
                "from services.document_safety import classify_observed_change; "
                f"print(classify_observed_change('restart.md', '{written['hash']}'))"
            )
            env = os.environ.copy()
            env["ALLES_DATA"] = str(data)
            process = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout.strip(), "local")

    def _rename_fixture(self):
        vault_md.write("topic.md", "# topic\n\nself [[topic#part]]\n")
        vault_md.write("ref.md", "alias [[topic|shown]] and [[Topic]]")
        vault_md.write("other.md", "unrelated [[elsewhere]]\r\n")
        return {path.name: path.read_bytes() for path in self.vault.glob("*.md")}

    def test_transactional_rename_updates_links_and_preserves_unrelated_bytes(self):
        before = self._rename_fixture()
        result = document_safety.rename_document("topic.md", "renamed.md")

        self.assertEqual(result["state"], "complete")
        self.assertFalse((self.vault / "topic.md").exists())
        self.assertIn("[[renamed#part]]", vault_md.read("renamed.md")["content"])
        self.assertEqual(
            vault_md.read("ref.md")["content"],
            "alias [[renamed|shown]] and [[renamed]]",
        )
        self.assertEqual((self.vault / "other.md").read_bytes(), before["other.md"])
        self.assertEqual(document_safety.pending_renames(), [])

    def test_case_only_rename_uses_the_transaction_move_when_paths_alias(self):
        vault_md.write("Foo.md", "self [[Foo]]")
        original_normalise = document_safety._normalise_rel
        _, source = original_normalise("Foo.md")

        def case_insensitive_normalise(value, *, add_markdown_suffix=True):
            rel, path = original_normalise(value, add_markdown_suffix=add_markdown_suffix)
            if rel.casefold() == "foo.md":
                return rel, source
            return rel, path

        with mock.patch.object(
            document_safety,
            "_normalise_rel",
            side_effect=case_insensitive_normalise,
        ):
            renamed = document_safety.rename_document("Foo.md", "foo.md")
            rolled_back = document_safety.rollback_rename(renamed["id"])

        self.assertEqual(renamed["state"], "complete")
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertEqual(source.read_text("utf-8"), "self [[Foo]]")

    def test_nested_rename_rewrites_qualified_links_without_ambiguous_bare_links(self):
        vault_md.write("one/topic.md", "one")
        vault_md.write("two/topic.md", "two")
        vault_md.write("ref.md", "[[one/topic]] [[topic]] [[two/topic]]")

        document_safety.rename_document("one/topic.md", "one/renamed.md")

        self.assertEqual(
            vault_md.read("ref.md")["content"],
            "[[one/renamed]] [[topic]] [[two/topic]]",
        )

    def test_crash_after_move_and_partial_link_write_can_resume(self):
        self._rename_fixture()
        manifest = document_safety.prepare_rename("topic.md", "renamed.md")
        transaction_dir = self.state / "rename-transactions" / manifest["id"]

        (self.vault / "topic.md").rename(self.vault / "renamed.md")
        first = manifest["changes"][0]
        first_path = self.vault / first["path_after"]
        first_target = (transaction_dir / "changes" / first["target_blob"]).read_bytes()
        vault_md._atomic_write(first_path, first_target)

        recovered = document_safety.resume_rename(manifest["id"])
        self.assertEqual(recovered["state"], "complete")
        self.assertIn("[[renamed|shown]]", vault_md.read("ref.md")["content"])
        self.assertIn("[[renamed#part]]", vault_md.read("renamed.md")["content"])

    def test_crash_in_the_rename_move_is_recoverable_from_its_manifest(self):
        self._rename_fixture()
        manifest = document_safety.prepare_rename("topic.md", "renamed.md")
        destination = self.vault / "renamed.md"
        original_publish = document_safety._publish_exclusive

        def crash_after_quarantine(source, target):
            if Path(target).resolve() == destination.resolve() and ".moving" in Path(source).name:
                raise SystemExit("simulated power loss")
            return original_publish(source, target)

        with mock.patch.object(
            document_safety,
            "_publish_exclusive",
            side_effect=crash_after_quarantine,
        ):
            with self.assertRaises(SystemExit):
                document_safety.resume_rename(manifest["id"])

        self.assertFalse((self.vault / "topic.md").exists())
        self.assertFalse(destination.exists())
        recovered = document_safety.resume_rename(manifest["id"])
        self.assertEqual(recovered["state"], "complete")
        self.assertTrue(destination.is_file())

    def test_partial_rename_can_roll_back_to_every_original_byte(self):
        before = self._rename_fixture()
        manifest = document_safety.prepare_rename("topic.md", "renamed.md")
        transaction_dir = self.state / "rename-transactions" / manifest["id"]

        (self.vault / "topic.md").rename(self.vault / "renamed.md")
        first = manifest["changes"][0]
        first_path = self.vault / first["path_after"]
        vault_md._atomic_write(
            first_path,
            (transaction_dir / "changes" / first["target_blob"]).read_bytes(),
        )

        rolled_back = document_safety.rollback_rename(manifest["id"])
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertFalse((self.vault / "renamed.md").exists())
        after = {path.name: path.read_bytes() for path in self.vault.glob("*.md")}
        self.assertEqual(after, before)

    def test_rename_rollback_recovers_after_restore_crashes_before_destination_cleanup(self):
        before = self._rename_fixture()
        manifest = document_safety.prepare_rename("topic.md", "renamed.md")
        source = self.vault / "topic.md"
        destination = self.vault / "renamed.md"
        quarantine = self.vault / Path(manifest["quarantine_path"]).name
        source.rename(quarantine)
        os.link(quarantine, destination)
        original_restore = document_safety._restore_exclusive

        def crash_after_restore(backup, path):
            original_restore(backup, path)
            raise SystemExit("simulated crash after rename restore")

        with mock.patch.object(
            document_safety, "_restore_exclusive", side_effect=crash_after_restore
        ):
            with self.assertRaisesRegex(SystemExit, "crash after rename restore"):
                document_safety.rollback_rename(manifest["id"])

        self.assertTrue(source.is_file())
        self.assertTrue(destination.is_file())
        self.assertTrue(os.path.samefile(source, destination))
        rolled_back = document_safety.rollback_rename(manifest["id"])
        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertFalse(destination.exists())
        after = {path.name: path.read_bytes() for path in self.vault.glob("*.md")}
        self.assertEqual(after, before)

    def test_recovery_refuses_to_overwrite_a_new_external_edit(self):
        self._rename_fixture()
        manifest = document_safety.prepare_rename("topic.md", "renamed.md")
        (self.vault / "topic.md").rename(self.vault / "renamed.md")
        owner_edit = b"owner changed this after the rename started\n"
        (self.vault / "ref.md").write_bytes(owner_edit)

        with self.assertRaises(document_safety.RecoveryConflict):
            document_safety.resume_rename(manifest["id"])
        self.assertEqual((self.vault / "ref.md").read_bytes(), owner_edit)
        with self.assertRaises(document_safety.RecoveryConflict):
            document_safety.rollback_rename(manifest["id"])
        self.assertEqual((self.vault / "ref.md").read_bytes(), owner_edit)

    def test_rename_does_not_replace_destination_created_during_publish(self):
        self._rename_fixture()
        manifest = document_safety.prepare_rename("topic.md", "renamed.md")
        destination = self.vault / "renamed.md"
        original_publish = document_safety._publish_exclusive
        raced = False

        def race(source, target):
            nonlocal raced
            if Path(target).resolve() == destination.resolve() and not raced:
                raced = True
                destination.write_bytes(b"owner created destination")
            return original_publish(source, target)

        with mock.patch.object(document_safety, "_publish_exclusive", side_effect=race):
            with self.assertRaises(document_safety.RecoveryConflict):
                document_safety.resume_rename(manifest["id"])
        self.assertEqual(destination.read_bytes(), b"owner created destination")
        self.assertTrue((self.vault / "topic.md").is_file())


if __name__ == "__main__":
    unittest.main()
