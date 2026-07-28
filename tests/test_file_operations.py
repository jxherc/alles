import json
import tempfile
import unicodedata
from pathlib import Path
from unittest import mock

from core.database import (
    FileComment,
    FileOperation,
    FileOperationPathClaim,
    FileOperationSourceClaim,
    FileTag,
    FileVersion,
    IndexChunk,
    OfflineFile,
    Share,
    StorageLocation,
    TrashItem,
)
from services import file_operations
from tests._client import ApiTest


class FileOperationApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.one = self.base / "one"
        self.two = self.base / "two"
        self.one.mkdir()
        self.two.mkdir()
        db = self.db()
        db.add_all(
            [
                StorageLocation(
                    id="one",
                    name="one",
                    kind="local",
                    access="managed",
                    root_path=str(self.one),
                    enabled=True,
                ),
                StorageLocation(
                    id="two",
                    name="two",
                    kind="local",
                    access="managed",
                    root_path=str(self.two),
                    enabled=True,
                ),
            ]
        )
        db.commit()
        db.close()

    def tearDown(self):
        self.temp.cleanup()
        super().tearDown()

    def _operation(self, **changes):
        body = {
            "action": "copy",
            "source_location_id": "one",
            "source_path": "note.txt",
            "destination_location_id": "two",
            "destination_path": "note.txt",
            "run_now": True,
        }
        body.update(changes)
        return self.client.post("/api/files/operations", json=body)

    def test_recovery_sibling_uses_the_destination_filesystem_name_limit(self):
        db = self.db()
        location = db.get(StorageLocation, "one")
        row = FileOperation(id="12345678-1234-1234-1234-123456789abc")

        with mock.patch(
            "services.internal_paths._component_limit",
            side_effect=lambda parent: (
                48
                if Path(parent).resolve(strict=False) == (self.one / "nested").resolve(strict=False)
                else 255
            ),
        ):
            recovered = file_operations._survivor_recovery_sibling(
                row,
                location,
                "nested/this-name-is-deliberately-much-too-long-for-the-mount.txt",
                2,
            )

        self.assertEqual(recovered.rpartition("/")[0], "nested")
        self.assertLessEqual(len(Path(recovered).name.encode("utf-8")), 48)
        db.close()

    def _seed_live_metadata(self, location_id: str, path: str, token: str) -> None:
        db = self.db()
        db.add_all(
            [
                FileTag(path=path, location_id=location_id, normalized_path=path, tags="undo"),
                FileComment(
                    path=path,
                    location_id=location_id,
                    normalized_path=path,
                    body="undo",
                ),
                FileVersion(path=path, location_id=location_id, normalized_path=path),
                OfflineFile(
                    location_id=location_id,
                    normalized_path=path,
                    state="ready",
                    cache_name=f"missing-{token}",
                ),
                Share(
                    token=f"undo-{token}",
                    kind="file",
                    ref=path,
                    location_id=location_id,
                    normalized_path=path,
                ),
                IndexChunk(
                    kind="file",
                    ref=path,
                    location_id=location_id,
                    normalized_path=path,
                    text="undo",
                ),
            ]
        )
        db.commit()
        db.close()

    def _assert_live_metadata_absent(self, location_id: str, path: str) -> None:
        db = self.db()
        for model in (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk):
            self.assertEqual(
                db.query(model)
                .filter(model.location_id == location_id, model.normalized_path == path)
                .count(),
                0,
                model.__name__,
            )
        db.close()

    def _assert_live_metadata_present(self, location_id: str, path: str) -> None:
        db = self.db()
        for model in (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk):
            self.assertEqual(
                db.query(model)
                .filter(model.location_id == location_id, model.normalized_path == path)
                .count(),
                1,
                model.__name__,
            )
        db.close()

    def test_directory_fingerprint_encodes_newline_names_without_collisions(self):
        if file_operations.os.name == "nt":
            self.skipTest("the collision fixture uses a colon, which Windows forbids")
        one_entry = self.one / "one-entry"
        two_entries = self.one / "two-entries"
        (one_entry / "x\nd:y").mkdir(parents=True)
        (two_entries / "x").mkdir(parents=True)
        (two_entries / "y").mkdir()

        first = file_operations.fingerprint(one_entry)
        second = file_operations.fingerprint(two_entries)

        self.assertNotEqual(first["checksum"], second["checksum"])

    def test_exact_copy_opens_root_and_nested_special_files_nonblocking(self):
        if file_operations.os.name == "nt":
            self.skipTest("FIFO files are unavailable on Windows")
        root_fifo = self.one / "root.pipe"
        nested_source = self.one / "nested-source"
        nested_source.mkdir()
        nested_fifo = nested_source / "nested.pipe"
        file_operations.os.mkfifo(root_fifo)
        file_operations.os.mkfifo(nested_fifo)
        original_open = file_operations.os.open
        observed = []

        def guarded_open(path, flags, *args, **kwargs):
            if Path(path).name in {root_fifo.name, nested_fifo.name}:
                self.assertTrue(flags & file_operations.os.O_NONBLOCK)
                observed.append(Path(path).name)
            return original_open(path, flags, *args, **kwargs)

        with mock.patch.object(file_operations.os, "open", side_effect=guarded_open):
            with self.assertRaisesRegex(
                file_operations.FileOperationError, "unsupported file type"
            ):
                file_operations._copy_exact(root_fifo, self.two / "root-copy")
            with self.assertRaisesRegex(
                file_operations.FileOperationError, "unsupported file type"
            ):
                file_operations._copy_exact(nested_source, self.two / "nested-copy")

        self.assertEqual(observed, [root_fifo.name, nested_fifo.name])

    def test_exact_s3_version_identity_rejects_whitespace(self):
        self.assertFalse(file_operations._is_exact_s3_version_id("   "))  # noqa: SLF001

    def test_copy_verifies_destination_and_undo_keeps_the_source(self):
        (self.one / "note.txt").write_text("hello", "utf-8")
        response = self._operation()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["state"], "completed")
        self.assertEqual(body["bytes_done"], 5)
        self.assertEqual((self.two / "note.txt").read_text("utf-8"), "hello")

        undone = self.client.post(f"/api/files/operations/{body['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["state"], "undone")
        self.assertTrue((self.one / "note.txt").exists())
        self.assertFalse((self.two / "note.txt").exists())

    def test_copy_accepts_a_max_length_destination_name(self):
        destination = f"{'c' * 251}.txt"
        (self.one / "note.txt").write_text("long destination", "utf-8")

        response = self._operation(destination_path=destination)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((self.two / destination).read_text("utf-8"), "long destination")

    def test_delete_accepts_a_max_length_source_name(self):
        source = f"{'d' * 251}.txt"
        (self.one / source).write_text("delete safely", "utf-8")

        response = self._operation(
            action="delete",
            source_path=source,
            destination_location_id="one",
            destination_path="",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse((self.one / source).exists())

    def test_copy_undo_purges_destination_scoped_live_metadata(self):
        (self.one / "undo-copy.txt").write_text("hello", "utf-8")
        copied = self._operation(
            source_path="undo-copy.txt",
            destination_path="undo-copy.txt",
        )
        self.assertEqual(copied.status_code, 200, copied.text)
        self._seed_live_metadata("two", "undo-copy.txt", "local-copy")

        undone = self.client.post(f"/api/files/operations/{copied.json()['id']}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self._assert_live_metadata_absent("two", "undo-copy.txt")

    def test_cancel_does_not_overwrite_an_operation_claimed_by_a_worker(self):
        (self.one / "cancel-race.txt").write_text("keep working", "utf-8")
        cancelling = self.db()
        row = file_operations.enqueue(
            cancelling,
            action="copy",
            source_location_id="one",
            source_path="cancel-race.txt",
            destination_location_id="two",
            destination_path="cancel-race.txt",
        )
        operation_id = row.id

        worker = self.db()
        claimed = worker.get(FileOperation, operation_id)
        claimed.state = "running"
        worker.commit()
        worker.close()

        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "only a queued operation can be cancelled",
        ):
            file_operations.cancel(cancelling, row)
        cancelling.close()

        checked = self.db()
        self.assertEqual(checked.get(FileOperation, operation_id).state, "running")
        checked.close()

    def test_copy_undo_stops_when_destination_changed(self):
        (self.one / "note.txt").write_text("hello", "utf-8")
        body = self._operation().json()
        (self.two / "note.txt").write_text("changed", "utf-8")
        response = self.client.post(f"/api/files/operations/{body['id']}/undo")
        self.assertEqual(response.status_code, 409)
        self.assertEqual((self.two / "note.txt").read_text("utf-8"), "changed")
        db = self.db()
        row = db.get(FileOperation, body["id"])
        self.assertEqual(row.state, "completed")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == body["id"])
            .count(),
            0,
        )
        db.close()

        replacement = self.client.post(
            "/api/files/upload",
            data={"path": "", "location_id": "two"},
            files={"file": ("note.txt", b"direct replacement", "text/plain")},
        )
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertEqual((self.two / "note.txt").read_text("utf-8"), "direct replacement")

    def test_undo_persists_intent_before_mutation_and_resumes_after_interruption(self):
        (self.one / "note.txt").write_text("hello", "utf-8")
        body = self._operation().json()
        original_remove = file_operations._remove

        def assert_undoing_before_remove(path):
            db = self.db()
            self.assertEqual(db.get(FileOperation, body["id"]).state, "undoing_claimed")
            db.close()
            original_remove(path)

        with mock.patch(
            "services.file_operations._remove",
            side_effect=assert_undoing_before_remove,
        ):
            undone = self.client.post(f"/api/files/operations/{body['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)

        (self.one / "again.txt").write_text("again", "utf-8")
        second = self._operation(
            source_path="again.txt",
            destination_path="again.txt",
        ).json()
        (self.two / "again.txt").unlink()
        db = self.db()
        row = db.get(FileOperation, second["id"])
        row.state = "undoing"
        db.commit()
        db.close()

        resumed = self.client.post(f"/api/files/operations/{second['id']}/undo")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["state"], "undone")

    def test_copy_rejects_a_preexisting_identical_destination(self):
        (self.one / "note.txt").write_text("same bytes", "utf-8")
        (self.two / "note.txt").write_text("same bytes", "utf-8")

        response = self._operation()

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((self.one / "note.txt").read_text("utf-8"), "same bytes")
        self.assertEqual((self.two / "note.txt").read_text("utf-8"), "same bytes")

    def test_trash_history_does_not_block_reusing_a_destination_path(self):
        (self.one / "new.txt").write_text("new bytes", "utf-8")
        db = self.db()
        db.add(
            TrashItem(
                kind="file",
                ref="available.txt",
                location_id="one",
                normalized_path="available.txt",
                name="old available.txt",
            )
        )
        db.commit()
        db.close()

        response = self._operation(
            action="rename",
            source_location_id="one",
            source_path="new.txt",
            destination_location_id="one",
            destination_path="available.txt",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((self.one / "available.txt").read_text("utf-8"), "new bytes")

    def test_copy_rejects_a_source_symlink_without_following_it(self):
        target = self.one / "target.txt"
        target.write_text("private target", "utf-8")
        (self.one / "link.txt").symlink_to(target)

        response = self._operation(source_path="link.txt", destination_path="copied.txt")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse((self.two / "copied.txt").exists())

    def test_local_access_rejects_a_parent_swapped_to_a_symlink_after_resolution(self):
        nested = self.one / "nested"
        nested.mkdir()
        (nested / "note.txt").write_text("owned bytes", "utf-8")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "note.txt").write_text("outside bytes", "utf-8")
        db = self.db()
        location = db.get(StorageLocation, "one")
        resolved = file_operations._absolute(location, "nested/note.txt")
        db.close()
        nested.rename(self.one / "detached-nested")
        nested.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(file_operations.FileOperationError, "symbolic links"):
            file_operations.fingerprint(resolved)

    def test_copy_does_not_overwrite_a_destination_created_during_publication(self):
        source = self.one / "note.txt"
        destination = self.two / "note.txt"
        source.write_text("source bytes", "utf-8")
        original_rename = file_operations._rename_no_replace
        raced = False

        def create_destination_while_publishing(path, published):
            nonlocal raced
            if not raced and Path(published).resolve(strict=False) == destination.resolve():
                destination.write_text("concurrent bytes", "utf-8")
                raced = True
            return original_rename(path, published)

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=create_destination_while_publishing,
        ):
            response = self._operation()

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(destination.read_text("utf-8"), "concurrent bytes")

    def test_copy_does_not_adopt_a_same_byte_replacement_after_publication(self):
        source = self.one / "note.txt"
        destination = self.one / "same-byte-copy.txt"
        source.write_text("same bytes, different owner", encoding="utf-8")
        original_publish = file_operations._publish_verified_copy
        raced = False

        def replace_after_publish(staged, published, expected):
            nonlocal raced
            result = original_publish(staged, published, expected)
            if not raced and Path(published).resolve(strict=False) == destination.resolve():
                replacement = self.one / "same-byte-replacement.tmp"
                replacement.write_text("same bytes, different owner", encoding="utf-8")
                replacement.replace(destination)
                raced = True
            return result

        with mock.patch(
            "services.file_operations._publish_verified_copy",
            side_effect=replace_after_publish,
        ):
            response = self._operation(
                destination_location_id="one",
                destination_path="same-byte-copy.txt",
            )

        self.assertTrue(raced)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            destination.read_text(encoding="utf-8"), source.read_text(encoding="utf-8")
        )
        db = self.db()
        row = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        details = json.loads(row.undo_json)
        self.assertEqual(row.state, "failed")
        self.assertFalse(details["destination_owned"])
        self.assertNotIn("destination_meta", details)
        db.close()

    def test_same_local_copy_records_identity_without_a_second_payload_copy(self):
        source = self.one / "note.txt"
        destination = self.one / "single-copy.txt"
        source.write_text("one payload copy is enough", encoding="utf-8")

        with mock.patch(
            "services.file_operations.storage_backends.materialize",
            side_effect=file_operations.FileOperationError("unexpected second payload copy"),
        ):
            response = self._operation(
                destination_location_id="one",
                destination_path=destination.name,
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            destination.read_text(encoding="utf-8"), source.read_text(encoding="utf-8")
        )

    def test_copy_undo_never_deletes_a_replacement_created_after_verification(self):
        source = self.one / "note.txt"
        destination = self.two / "note.txt"
        source.write_text("original bytes", "utf-8")
        body = self._operation().json()
        original_delete_tree = file_operations.storage_backends.delete_tree
        raced = False

        def replace_after_destination_check(location, path, **kwargs):
            nonlocal raced
            if location.id == "two" and path == "note.txt" and not raced:
                destination.write_text("replacement bytes", "utf-8")
                raced = True
            return original_delete_tree(location, path, **kwargs)

        with mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=replace_after_destination_check,
        ):
            response = self.client.post(f"/api/files/operations/{body['id']}/undo")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(destination.read_text("utf-8"), "replacement bytes")

    def test_copy_undo_never_deletes_a_same_byte_replacement(self):
        source = self.one / "same-byte-source.txt"
        destination = self.two / "same-byte-copy.txt"
        source.write_text("same bytes, different owner", encoding="utf-8")
        body = self._operation(
            source_path=source.name,
            destination_path=destination.name,
        ).json()
        published_inode = destination.stat().st_ino
        replacement = self.two / "same-byte-replacement.tmp"
        replacement.write_text("same bytes, different owner", encoding="utf-8")
        replacement.replace(destination)
        self.assertNotEqual(destination.stat().st_ino, published_inode)
        self._seed_live_metadata("two", destination.name, "replacement-owner")

        response = self.client.post(f"/api/files/operations/{body['id']}/undo")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            destination.read_text(encoding="utf-8"), source.read_text(encoding="utf-8")
        )
        self._assert_live_metadata_present("two", destination.name)
        db = self.db()
        row = db.get(FileOperation, body["id"])
        self.assertEqual(row.state, "completed")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == body["id"])
            .count(),
            0,
        )
        db.close()

    def test_copy_undo_restart_restores_a_quarantined_same_byte_replacement(self):
        source = self.one / "restart-source.txt"
        destination = self.one / "restart-copy.txt"
        source.write_text("same bytes, different owner", encoding="utf-8")
        body = self._operation(
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        ).json()
        replacement = self.one / "restart-replacement.tmp"
        replacement.write_text("same bytes, different owner", encoding="utf-8")
        replacement_inode = replacement.stat().st_ino
        replacement.replace(destination)
        self._seed_live_metadata("one", destination.name, "replacement-owner")

        db = self.db()
        with mock.patch(
            "services.file_operations._same_local_path_publication_identity",
            side_effect=SystemExit("simulated process exit after quarantine rename"),
        ):
            with self.assertRaisesRegex(SystemExit, "simulated process exit"):
                file_operations.undo(db, db.get(FileOperation, body["id"]))

        detached = file_operations._quarantine_path(destination, f"undo-{body['id']}")
        self.assertFalse(destination.exists())
        self.assertTrue(detached.exists())
        self.assertEqual(detached.stat().st_ino, replacement_inode)
        db.close()

        restarted = self.db()
        self.assertEqual(file_operations.recover_interrupted(restarted), 1)
        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "copy destination identity changed",
        ):
            file_operations.undo(restarted, restarted.get(FileOperation, body["id"]))
        restarted.close()

        self.assertTrue(destination.exists())
        self.assertEqual(destination.stat().st_ino, replacement_inode)
        self.assertFalse(detached.exists())
        self._assert_live_metadata_present("one", destination.name)

    def test_publication_quarantine_retry_restores_a_same_byte_replacement(self):
        destination = self.one / "helper-restart-copy.txt"
        destination.write_text("same bytes, different owner", encoding="utf-8")
        expected = file_operations.fingerprint(destination)
        stored = file_operations.storage_backends._local_path_receipt_identity(destination)
        replacement = self.one / "helper-restart-replacement.tmp"
        replacement.write_text("same bytes, different owner", encoding="utf-8")
        replacement_inode = replacement.stat().st_ino
        replacement.replace(destination)
        quarantine = file_operations._quarantine_path(destination, "helper-restart")
        file_operations._rename_no_replace(destination, quarantine)

        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "copy destination identity changed",
        ):
            file_operations._quarantine_verified_publication(
                destination,
                expected,
                stored,
                "helper-restart",
            )

        self.assertTrue(destination.exists())
        self.assertEqual(destination.stat().st_ino, replacement_inode)
        self.assertFalse(quarantine.exists())

    def test_copy_undo_restores_a_detached_copy_changed_before_deletion(self):
        source = self.one / "note.txt"
        destination = self.two / "note.txt"
        source.write_text("original bytes", "utf-8")
        body = self._operation().json()
        original_rename = file_operations._rename_no_replace
        raced = False

        def replace_detached_before_delete(path, detached):
            nonlocal raced
            result = original_rename(path, detached)
            if (
                not raced
                and Path(path).resolve(strict=False) == destination.resolve(strict=False)
                and ".alles-delete-undo-" in Path(detached).name
            ):
                Path(detached).write_text("replacement bytes", "utf-8")
                raced = True
            return result

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=replace_detached_before_delete,
        ):
            response = self.client.post(f"/api/files/operations/{body['id']}/undo")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(destination.read_text("utf-8"), "replacement bytes")

    def test_run_rechecks_managed_access_after_enqueue(self):
        (self.one / "note.txt").write_text("hello", "utf-8")
        queued = self._operation(run_now=False)
        self.assertEqual(queued.status_code, 200, queued.text)
        db = self.db()
        db.get(StorageLocation, "two").access = "read_only"
        db.commit()
        db.close()

        response = self.client.post(f"/api/files/operations/{queued.json()['id']}/run")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse((self.two / "note.txt").exists())

    def test_undo_rechecks_managed_access(self):
        (self.one / "note.txt").write_text("hello", "utf-8")
        completed = self._operation()
        self.assertEqual(completed.status_code, 200, completed.text)
        db = self.db()
        db.get(StorageLocation, "two").access = "read_only"
        db.commit()
        db.close()

        response = self.client.post(f"/api/files/operations/{completed.json()['id']}/undo")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue((self.two / "note.txt").exists())

    def test_cross_local_move_is_verified_and_undo_avoids_cross_root_rename(self):
        folder = self.one / "folder"
        folder.mkdir()
        (folder / "a.txt").write_text("a", "utf-8")
        (folder / "b.txt").write_text("bb", "utf-8")
        original_rename = file_operations._rename_no_replace
        cross_root_renames = []

        def reject_cross_root_rename(source, destination):
            source = Path(source).resolve(strict=False)
            destination = Path(destination).resolve(strict=False)
            source_root = next(
                (
                    root
                    for root in (self.one.resolve(), self.two.resolve())
                    if source.is_relative_to(root)
                ),
                None,
            )
            destination_root = next(
                (
                    root
                    for root in (self.one.resolve(), self.two.resolve())
                    if destination.is_relative_to(root)
                ),
                None,
            )
            if source_root is not None and destination_root is not None:
                if source_root != destination_root:
                    cross_root_renames.append((source, destination))
                    raise OSError(file_operations.errno.EXDEV, "cross-device link")
            return original_rename(source, destination)

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=reject_cross_root_rename,
        ):
            response = self._operation(
                action="move",
                source_path="folder",
                destination_path="moved",
            )
            body = response.json()
            source_removed = not folder.exists()
            destination_bytes = (self.two / "moved" / "b.txt").read_text("utf-8")
            undone = self.client.post(f"/api/files/operations/{body['id']}/undo")

        self.assertEqual(cross_root_renames, [])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(body["non_atomic"])
        self.assertTrue(source_removed)
        self.assertEqual(destination_bytes, "bb")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual((self.one / "folder" / "a.txt").read_text("utf-8"), "a")
        self.assertFalse((self.two / "moved").exists())

    def test_same_local_move_failure_before_source_quarantine_can_undo_published_copy(self):
        source = self.one / "undo-before-quarantine.txt"
        destination = self.one / "undo-before-quarantine-moved.txt"
        source.write_text("source remains intact", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )

        with mock.patch(
            "services.file_operations._quarantine_verified",
            side_effect=file_operations.FileOperationError("injected before source quarantine"),
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "injected"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, row.id)
        details = json.loads(failed.undo_json)
        self.assertTrue(details["destination_owned"])
        self.assertFalse(details.get("source_owned"))
        self.assertTrue(file_operations.public_dict(failed)["can_undo"])
        self.assertIsNotNone(db.get(FileOperationSourceClaim, row.id))

        undone = file_operations.undo(db, failed)

        self.assertEqual(undone.state, "undone")
        self.assertEqual(source.read_text(encoding="utf-8"), "source remains intact")
        self.assertFalse(destination.exists())
        self.assertIsNone(db.get(FileOperationSourceClaim, row.id))
        db.close()

    def test_same_local_move_retry_rejects_a_same_byte_destination_replacement(self):
        source = self.one / "move-retry-source.txt"
        destination = self.one / "move-retry-destination.txt"
        source.write_text("same bytes, different owner", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )

        with mock.patch(
            "services.file_operations._quarantine_verified",
            side_effect=file_operations.FileOperationError("stop after destination ownership"),
        ):
            with self.assertRaisesRegex(
                file_operations.FileOperationError, "destination ownership"
            ):
                file_operations.run(db, row)

        failed = db.get(FileOperation, row.id)
        self.assertTrue(json.loads(failed.undo_json)["destination_owned"])
        replacement = self.one / "move-retry-replacement.tmp"
        replacement.write_text("same bytes, different owner", encoding="utf-8")
        replacement_inode = replacement.stat().st_ino
        replacement.replace(destination)

        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "move destination changed",
        ):
            file_operations.retry(db, failed)

        self.assertTrue(source.exists())
        self.assertEqual(destination.stat().st_ino, replacement_inode)
        self.assertEqual(
            destination.read_text(encoding="utf-8"), source.read_text(encoding="utf-8")
        )
        db.close()

    def test_move_undo_recovers_a_source_detached_before_ownership_commit(self):
        source = self.one / "undo-after-quarantine.txt"
        destination = self.one / "undo-after-quarantine-moved.txt"
        source.write_text("detached source remains recoverable", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        quarantine = file_operations._quarantine_path(source, row.id)

        with mock.patch(
            "services.file_operations._record_local_source_ownership",
            side_effect=file_operations.FileOperationError("injected after source quarantine"),
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "injected"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, row.id)
        self.assertFalse(source.exists())
        self.assertTrue(quarantine.exists())
        self.assertTrue(destination.exists())
        self.assertTrue(file_operations.public_dict(failed)["can_undo"])

        undone = file_operations.undo(db, failed)

        self.assertEqual(undone.state, "undone")
        self.assertEqual(
            source.read_text(encoding="utf-8"),
            "detached source remains recoverable",
        )
        self.assertFalse(destination.exists())
        self.assertFalse(quarantine.exists())
        self.assertIsNone(db.get(FileOperationSourceClaim, row.id))
        db.close()

    def test_move_undo_recovers_a_source_detached_after_ownership_commit(self):
        source = self.one / "undo-after-owned-quarantine.txt"
        destination = self.one / "undo-after-owned-quarantine-moved.txt"
        source.write_text("owned detached source remains recoverable", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        quarantine = file_operations._quarantine_path(source, row.id)
        with mock.patch(
            "services.file_operations._remove",
            side_effect=file_operations.FileOperationError("injected after source ownership"),
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "injected"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, row.id)
        details = json.loads(failed.undo_json)
        self.assertTrue(details["source_owned"])
        self.assertFalse(source.exists())
        self.assertTrue(quarantine.exists())
        self.assertTrue(destination.exists())
        self.assertTrue(file_operations.public_dict(failed)["can_undo"])

        undone = file_operations.undo(db, failed)

        self.assertEqual(undone.state, "undone")
        self.assertEqual(
            source.read_text(encoding="utf-8"),
            "owned detached source remains recoverable",
        )
        self.assertFalse(destination.exists())
        self.assertFalse(quarantine.exists())
        self.assertIsNone(db.get(FileOperationSourceClaim, row.id))
        db.close()

    def test_undo_cleanup_keeps_an_exact_hold_when_the_source_path_is_recreated(self):
        source = self.one / "undo-cleanup-race.txt"
        source.write_text("verified source", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path="undo-cleanup-race-moved.txt",
        )
        quarantine = file_operations._quarantine_path(source, row.id)
        quarantine.write_text("verified source", encoding="utf-8")
        expected = file_operations.fingerprint(source)
        details = {}
        original_remove = file_operations._remove

        def recreate_source_after_duplicate_cleanup(path):
            original_remove(path)
            source.write_text("external replacement", encoding="utf-8")

        with (
            mock.patch.object(
                file_operations,
                "_remove",
                side_effect=recreate_source_after_duplicate_cleanup,
            ),
            self.assertRaisesRegex(
                file_operations.FileOperationError,
                "destination changed while restoring",
            ),
        ):
            file_operations._recover_local_operation_quarantine_for_undo(
                db,
                row,
                details,
                source,
                expected,
            )

        self.assertEqual(source.read_text(encoding="utf-8"), "external replacement")
        self.assertEqual(quarantine.read_text(encoding="utf-8"), "verified source")
        db.close()

    def test_move_undo_remembers_quarantine_recovery_across_a_restart(self):
        source = self.one / "undo-quarantine-restart.txt"
        destination = self.one / "undo-quarantine-restart-moved.txt"
        source.write_text("restart-safe detached source", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        operation_id = row.id
        quarantine = file_operations._quarantine_path(source, operation_id)

        with mock.patch(
            "services.file_operations._remove",
            side_effect=file_operations.FileOperationError("injected after source ownership"),
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "injected"):
                file_operations.run(db, row)

        original_recover = file_operations._recover_local_operation_quarantine_for_undo

        def crash_after_quarantine_recovery(*args, **kwargs):
            original_recover(*args, **kwargs)
            raise SystemExit("crash after quarantine recovery")

        with mock.patch(
            "services.file_operations._recover_local_operation_quarantine_for_undo",
            side_effect=crash_after_quarantine_recovery,
        ):
            with self.assertRaisesRegex(SystemExit, "crash after quarantine recovery"):
                file_operations.undo(db, db.get(FileOperation, operation_id))

        self.assertEqual(source.read_text(encoding="utf-8"), "restart-safe detached source")
        self.assertTrue(destination.exists())
        self.assertFalse(quarantine.exists())
        db.close()

        restarted = self.db()
        self.assertEqual(file_operations.recover_interrupted(restarted), 1)
        recovered = file_operations.undo(restarted, restarted.get(FileOperation, operation_id))

        self.assertEqual(recovered.state, "undone")
        self.assertEqual(source.read_text(encoding="utf-8"), "restart-safe detached source")
        self.assertFalse(destination.exists())
        self.assertFalse(quarantine.exists())
        self.assertIsNone(restarted.get(FileOperationSourceClaim, operation_id))
        restarted.close()

    def test_cross_location_move_failure_before_source_delete_can_undo_published_copy(self):
        source = self.one / "undo-before-delete.txt"
        destination = self.two / "undo-before-delete-moved.txt"
        source.write_text("cross source remains intact", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="two",
            destination_path=destination.name,
        )
        original_materialize = file_operations._materialize

        def fail_before_source_delete(location, path, target):
            if Path(target).name == "source-before-delete":
                raise file_operations.FileOperationError("injected before source delete")
            return original_materialize(location, path, target)

        with mock.patch(
            "services.file_operations._materialize",
            side_effect=fail_before_source_delete,
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "injected"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, row.id)
        details = json.loads(failed.undo_json)
        self.assertTrue(details["destination_owned"])
        self.assertFalse(details.get("source_delete_started"))
        self.assertTrue(file_operations.public_dict(failed)["can_undo"])
        self.assertIsNotNone(db.get(FileOperationSourceClaim, row.id))

        undone = file_operations.undo(db, failed)

        self.assertEqual(undone.state, "undone")
        self.assertEqual(source.read_text(encoding="utf-8"), "cross source remains intact")
        self.assertFalse(destination.exists())
        self.assertIsNone(db.get(FileOperationSourceClaim, row.id))
        db.close()

    def test_move_undo_checks_source_metadata_before_moving_bytes_back(self):
        (self.one / "note.txt").write_text("keep bytes", "utf-8")
        db = self.db()
        db.add(
            FileTag(
                path="note.txt",
                location_id="one",
                normalized_path="note.txt",
                tags="moved metadata",
            )
        )
        db.commit()
        db.close()
        moved = self._operation(
            action="move",
            source_path="note.txt",
            destination_path="moved.txt",
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        db = self.db()
        db.add(
            FileTag(
                path="note.txt",
                location_id="one",
                normalized_path="note.txt",
                tags="new source metadata",
            )
        )
        db.commit()
        db.close()

        undone = self.client.post(f"/api/files/operations/{moved.json()['id']}/undo")

        self.assertEqual(undone.status_code, 409, undone.text)
        self.assertFalse((self.one / "note.txt").exists())
        self.assertEqual((self.two / "moved.txt").read_text("utf-8"), "keep bytes")

    def test_move_preserves_a_replacement_created_after_source_quarantine(self):
        source = self.one / "note.txt"
        source.write_text("old bytes", "utf-8")
        original_rename = file_operations._rename_no_replace

        def replace_after_quarantine(path, quarantine):
            result = original_rename(path, quarantine)
            if (
                Path(path).resolve(strict=False) == source.resolve(strict=False)
                and ".alles-delete-" in Path(quarantine).name
            ):
                source.write_text("new bytes", "utf-8")
            return result

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=replace_after_quarantine,
        ):
            response = self._operation(action="move", destination_path="moved.txt")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(source.read_text("utf-8"), "new bytes")
        self.assertEqual((self.two / "moved.txt").read_text("utf-8"), "old bytes")

    def test_move_preserves_both_replacements_when_source_changes_across_detach(self):
        source = self.one / "compound-race.txt"
        destination = self.one / "compound-race-moved.txt"
        source.write_text("original source", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        operation_id = row.id
        quarantine = file_operations._quarantine_path(source, operation_id)
        original_rename = file_operations._rename_no_replace
        raced = False

        def replace_before_and_after_detach(path, target):
            nonlocal raced
            if (
                not raced
                and Path(path).resolve(strict=False) == source.resolve(strict=False)
                and Path(target).name.endswith(".quarantine")
            ):
                source.write_text("detached replacement", encoding="utf-8")
                result = original_rename(path, target)
                source.write_text("live replacement", encoding="utf-8")
                raced = True
                return result
            return original_rename(path, target)

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=replace_before_and_after_detach,
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "preserved"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, operation_id)
        details = json.loads(failed.undo_json)
        conflict = self.one / details["source_conflict_path"]
        self.assertTrue(details["source_conflict_published"])
        self.assertFalse(details.get("source_conflict_pending"))
        self.assertEqual(source.read_text(encoding="utf-8"), "live replacement")
        self.assertEqual(conflict.read_text(encoding="utf-8"), "detached replacement")
        self.assertEqual(destination.read_text(encoding="utf-8"), "original source")
        self.assertFalse(quarantine.exists())
        public = file_operations.public_dict(failed)
        self.assertFalse(public["can_retry"])
        self.assertFalse(public["can_undo"])
        self.assertTrue(public["can_discard"])
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))
        with self.assertRaisesRegex(file_operations.FileOperationError, "recovery was preserved"):
            file_operations.retry(db, failed)
        with self.assertRaisesRegex(file_operations.FileOperationError, "recovery was preserved"):
            file_operations.undo(db, failed)

        file_operations.discard(db, failed)

        self.assertIsNone(db.get(FileOperation, operation_id))
        self.assertEqual(source.read_text(encoding="utf-8"), "live replacement")
        self.assertEqual(conflict.read_text(encoding="utf-8"), "detached replacement")
        self.assertEqual(destination.read_text(encoding="utf-8"), "original source")
        db.close()

    def test_rename_publishes_a_compound_source_conflict_for_safe_discard(self):
        source = self.one / "rename-compound-race.txt"
        destination = self.one / "renamed-compound-race.txt"
        source.write_text("original rename source", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="rename",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        operation_id = row.id
        quarantine = file_operations._quarantine_path(source, operation_id)
        original_rename = file_operations._rename_no_replace
        raced = False

        def replace_before_and_after_detach(path, target):
            nonlocal raced
            if (
                not raced
                and Path(path).resolve(strict=False) == source.resolve(strict=False)
                and Path(target).name.endswith(".quarantine")
            ):
                source.write_text("detached rename replacement", encoding="utf-8")
                result = original_rename(path, target)
                source.write_text("live rename replacement", encoding="utf-8")
                raced = True
                return result
            return original_rename(path, target)

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=replace_before_and_after_detach,
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "preserved"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, operation_id)
        details = json.loads(failed.undo_json)
        conflict = self.one / details["source_conflict_path"]
        self.assertTrue(details["source_conflict_published"])
        self.assertEqual(source.read_text(encoding="utf-8"), "live rename replacement")
        self.assertEqual(
            conflict.read_text(encoding="utf-8"),
            "detached rename replacement",
        )
        self.assertFalse(destination.exists())
        self.assertFalse(quarantine.exists())
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))
        self.assertTrue(file_operations.public_dict(failed)["can_discard"])

        file_operations.discard(db, failed)

        self.assertEqual(source.read_text(encoding="utf-8"), "live rename replacement")
        self.assertEqual(
            conflict.read_text(encoding="utf-8"),
            "detached rename replacement",
        )
        db.close()

    def test_delete_uses_trash_and_undo_restores_verified_bytes(self):
        (self.one / "remove.txt").write_text("keep", "utf-8")
        response = self._operation(
            action="delete",
            source_path="remove.txt",
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse((self.one / "remove.txt").exists())
        undone = self.client.post(f"/api/files/operations/{body['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual((self.one / "remove.txt").read_text("utf-8"), "keep")

    def test_restore_preserves_an_explicit_alternate_destination(self):
        (self.one / "original.txt").write_text("recover elsewhere", "utf-8")
        deleted = self._operation(
            action="delete",
            source_path="original.txt",
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        try:
            trash_id = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)["trash_id"]
        finally:
            db.close()

        restored = self._operation(
            action="restore",
            source_path=trash_id,
            destination_location_id="one",
            destination_path="restored/alternate.txt",
        )

        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertFalse((self.one / "original.txt").exists())
        self.assertEqual(
            (self.one / "restored" / "alternate.txt").read_text("utf-8"),
            "recover elsewhere",
        )
        self.assertEqual(restored.json()["destination_path"], "restored/alternate.txt")

    def test_delete_undo_restores_every_location_scoped_metadata_record(self):
        (self.one / "metadata.txt").write_text("keep metadata", "utf-8")
        self._seed_live_metadata("one", "metadata.txt", "delete-undo")

        deleted = self._operation(
            action="delete",
            source_path="metadata.txt",
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self._assert_live_metadata_absent("one", "metadata.txt")

        undone = self.client.post(f"/api/files/operations/{deleted.json()['id']}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual((self.one / "metadata.txt").read_text("utf-8"), "keep metadata")
        db = self.db()
        for model in (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk):
            self.assertEqual(
                db.query(model)
                .filter(model.location_id == "one", model.normalized_path == "metadata.txt")
                .count(),
                1,
                model.__name__,
            )
        db.close()

    def test_local_restore_race_rolls_verified_bytes_back_to_trash(self):
        source = self.one / "restore-race.txt"
        source.write_text("verified original", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_path=source.name,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        deleted_details = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)
        item = db.get(TrashItem, deleted_details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        restored = file_operations.enqueue(
            db,
            action="restore",
            source_location_id="one",
            source_path=item.id,
        )
        original_remove = file_operations._remove

        def replace_after_stash_delete(path):
            original_remove(path)
            if Path(path) == stash:
                source.write_text("concurrent replacement", encoding="utf-8")

        with mock.patch(
            "services.file_operations._remove",
            side_effect=replace_after_stash_delete,
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "rolled back to Trash"):
                file_operations.run(db, restored)

        failed = db.get(FileOperation, restored.id)
        rollback_details = json.loads(failed.undo_json)
        item = db.get(TrashItem, deleted_details["trash_id"])
        rollback_stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertEqual(failed.state, "failed")
        self.assertTrue(rollback_details["restore_rolled_back"])
        self.assertEqual(source.read_text(encoding="utf-8"), "concurrent replacement")
        self.assertEqual(rollback_stash.read_text(encoding="utf-8"), "verified original")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == restored.id)
            .count(),
            0,
        )
        db.close()

    def test_local_restore_retry_removes_its_published_duplicate_after_stash_crash(self):
        source = self.one / "restore-crash.txt"
        source.write_text("verified original", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_path=source.name,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        deleted_details = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)
        item = db.get(TrashItem, deleted_details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        restored = file_operations.enqueue(
            db,
            action="restore",
            source_location_id="one",
            source_path=item.id,
        )
        original_remove = file_operations._remove

        def crash_after_stash_delete(path):
            original_remove(path)
            if Path(path) == stash:
                raise SystemExit("crash after trash removal")

        with mock.patch(
            "services.file_operations._remove",
            side_effect=crash_after_stash_delete,
        ):
            with self.assertRaisesRegex(SystemExit, "crash after trash removal"):
                file_operations.run(db, restored)

        self.assertTrue(source.exists())
        self.assertFalse(stash.exists())
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        with self.assertRaisesRegex(file_operations.FileOperationError, "rolled back to Trash"):
            file_operations.run(db, db.get(FileOperation, restored.id))

        failed = db.get(FileOperation, restored.id)
        restored_item = db.get(TrashItem, deleted_details["trash_id"])
        restored_stash = file_operations.trash.stash_path(
            json.loads(restored_item.payload)["trash_name"]
        )
        self.assertEqual(failed.state, "failed")
        self.assertFalse(source.exists())
        self.assertEqual(restored_stash.read_text("utf-8"), "verified original")
        db.close()

    def test_restore_retry_does_not_adopt_an_identical_unowned_destination(self):
        source = self.one / "restore-unowned.txt"
        source.write_text("identical bytes", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_path=source.name,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        deleted_details = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)
        item = db.get(TrashItem, deleted_details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        restored = file_operations.enqueue(
            db,
            action="restore",
            source_location_id="one",
            source_path=item.id,
        )

        with mock.patch(
            "services.file_operations._prepare_verified_copy",
            side_effect=SystemExit("restart after destination claim"),
        ):
            with self.assertRaises(SystemExit):
                file_operations._execute_restore(db, restored)  # noqa: SLF001

        source.write_text("identical bytes", encoding="utf-8")
        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "restore destination already exists",
        ):
            file_operations._execute_restore(db, restored)  # noqa: SLF001

        self.assertEqual(source.read_text("utf-8"), "identical bytes")
        self.assertEqual(stash.read_text("utf-8"), "identical bytes")
        self.assertIsNotNone(db.get(TrashItem, item.id))
        db.close()

    def test_legacy_restore_rollback_preserves_unrelated_live_metadata(self):
        source = self.one / "legacy-restore-race.txt"
        source.write_text("verified original", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_path=source.name,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        details = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)
        item = db.get(TrashItem, details["trash_id"])
        payload = json.loads(item.payload)
        payload.pop("metadata_snapshot", None)
        payload.pop("metadata_root", None)
        item.payload = json.dumps(payload, sort_keys=True)
        db.add(
            FileTag(
                path=source.name,
                location_id="one",
                normalized_path=source.name,
                tags="replacement",
            )
        )
        db.commit()
        stash = file_operations.trash.stash_path(payload["trash_name"])
        restored = file_operations.enqueue(
            db,
            action="restore",
            source_location_id="one",
            source_path=item.id,
        )
        original_remove = file_operations._remove

        def replace_after_stash_delete(path):
            original_remove(path)
            if Path(path) == stash:
                source.write_text("concurrent replacement", encoding="utf-8")

        with mock.patch(
            "services.file_operations._remove",
            side_effect=replace_after_stash_delete,
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "rolled back to Trash"):
                file_operations.run(db, restored)

        self.assertEqual(
            db.query(FileTag)
            .filter(FileTag.location_id == "one", FileTag.normalized_path == source.name)
            .one()
            .tags,
            "replacement",
        )
        item = db.get(TrashItem, details["trash_id"])
        self.assertNotIn("metadata_snapshot", json.loads(item.payload))
        db.close()

    def test_trash_purge_keeps_version_blob_referenced_by_another_snapshot(self):
        stored = "shared-version-blob"
        blob = file_operations.fileversions.versions_dir() / stored
        blob.write_bytes(b"shared historical bytes")
        version_snapshot = [
            {
                "model": "FileVersion",
                "values": {
                    "path": "history.txt",
                    "location_id": "one",
                    "normalized_path": "history.txt",
                    "stored": stored,
                },
            }
        ]
        db = self.db()
        first = TrashItem(
            kind="file",
            ref="first.txt",
            location_id="one",
            normalized_path="first.txt",
            payload=json.dumps({"metadata_snapshot": version_snapshot}),
        )
        second = TrashItem(
            kind="file",
            ref="second.txt",
            location_id="one",
            normalized_path="second.txt",
            payload=json.dumps({"metadata_snapshot": version_snapshot}),
        )
        db.add_all([first, second])
        db.commit()

        file_operations.discard_trash_metadata(db, first)
        self.assertTrue(blob.exists())
        db.delete(first)
        db.commit()
        file_operations.discard_trash_metadata(db, second)
        self.assertFalse(blob.exists())
        db.close()

    def test_local_delete_undo_race_rolls_verified_bytes_back_to_trash(self):
        source = self.one / "delete-undo-race.txt"
        source.write_text("verified original", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_path=source.name,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        row = db.get(FileOperation, deleted.json()["id"])
        details = json.loads(row.undo_json)
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        original_remove = file_operations._remove

        def replace_after_stash_delete(path):
            original_remove(path)
            if Path(path) == stash:
                source.write_text("concurrent replacement", encoding="utf-8")

        with mock.patch(
            "services.file_operations._remove",
            side_effect=replace_after_stash_delete,
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "rolled back to Trash"):
                file_operations.undo(db, row)

        refused = db.get(FileOperation, row.id)
        rollback_details = json.loads(refused.undo_json)
        item = db.get(TrashItem, details["trash_id"])
        rollback_stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertEqual(refused.state, "completed")
        self.assertTrue(rollback_details["restore_rolled_back"])
        self.assertEqual(source.read_text(encoding="utf-8"), "concurrent replacement")
        self.assertEqual(rollback_stash.read_text(encoding="utf-8"), "verified original")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == row.id)
            .count(),
            0,
        )
        db.close()

    def test_restart_rolls_an_interrupted_local_restore_back_to_trash(self):
        source = self.one / "restore-restart.txt"
        source.write_text("restart original", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_path=source.name,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        details = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        restored = file_operations.enqueue(
            db,
            action="restore",
            source_location_id="one",
            source_path=item.id,
        )
        original_remove = file_operations._remove

        def crash_after_stash_delete(path):
            original_remove(path)
            if Path(path) == stash:
                raise SystemExit("restart after restore stash delete")

        with mock.patch(
            "services.file_operations._remove",
            side_effect=crash_after_stash_delete,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, restored)

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        with self.assertRaisesRegex(file_operations.FileOperationError, "rolled back to Trash"):
            file_operations.run(db, db.get(FileOperation, restored.id))

        failed = db.get(FileOperation, restored.id)
        item = db.get(TrashItem, details["trash_id"])
        rollback_stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertEqual(failed.state, "failed")
        self.assertFalse(source.exists())
        self.assertEqual(rollback_stash.read_text(encoding="utf-8"), "restart original")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == restored.id)
            .count(),
            0,
        )
        db.close()

    def test_restart_rolls_an_interrupted_delete_undo_back_to_trash(self):
        source = self.one / "delete-undo-restart.txt"
        source.write_text("restart original", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_path=source.name,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        row = db.get(FileOperation, deleted.json()["id"])
        details = json.loads(row.undo_json)
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        original_remove = file_operations._remove

        def crash_after_stash_delete(path):
            original_remove(path)
            if Path(path) == stash:
                raise SystemExit("restart after delete undo stash delete")

        with mock.patch(
            "services.file_operations._remove",
            side_effect=crash_after_stash_delete,
        ):
            with self.assertRaises(SystemExit):
                file_operations.undo(db, row)

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        with self.assertRaisesRegex(file_operations.FileOperationError, "rolled back to Trash"):
            file_operations.undo(db, db.get(FileOperation, row.id))

        refused = db.get(FileOperation, row.id)
        item = db.get(TrashItem, details["trash_id"])
        rollback_stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertEqual(refused.state, "completed")
        self.assertEqual(source.read_text(encoding="utf-8"), "restart original")
        self.assertEqual(rollback_stash.read_text(encoding="utf-8"), "restart original")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == row.id)
            .count(),
            0,
        )
        db.close()

    def test_delete_does_not_commit_an_unassociated_trash_record(self):
        (self.one / "remove.txt").write_text("keep", "utf-8")
        original_record = file_operations.trash.record

        def crash_after_record(*args, **kwargs):
            original_record(*args, **kwargs)
            raise RuntimeError("simulated interruption")

        with mock.patch(
            "services.file_operations.trash.record",
            side_effect=crash_after_record,
        ):
            response = self._operation(
                action="delete",
                source_path="remove.txt",
                destination_location_id=None,
                destination_path="",
            )

        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertEqual(db.query(TrashItem).count(), 0)
        failed = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        self.assertEqual(json.loads(failed.undo_json or "{}"), {})
        db.close()

    def test_delete_preserves_a_replacement_created_after_source_quarantine(self):
        source = self.one / "remove.txt"
        source.write_text("old bytes", "utf-8")
        original_remove = file_operations._remove

        def replace_while_removing(path):
            source.write_text("new bytes", "utf-8")
            original_remove(path)

        with mock.patch(
            "services.file_operations._remove",
            side_effect=replace_while_removing,
        ):
            response = self._operation(
                action="delete",
                source_path="remove.txt",
                destination_location_id=None,
                destination_path="",
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(source.read_text("utf-8"), "new bytes")

    def test_delete_undo_recovers_a_source_detached_before_ownership_commit(self):
        source = self.one / "delete-after-quarantine.txt"
        source.write_text("detached delete remains recoverable", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="one",
            source_path=source.name,
        )
        quarantine = file_operations._quarantine_path(source, row.id)

        with mock.patch(
            "services.file_operations._record_local_source_ownership",
            side_effect=file_operations.FileOperationError("injected after delete quarantine"),
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "injected"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, row.id)
        details = json.loads(failed.undo_json)
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertFalse(source.exists())
        self.assertTrue(quarantine.exists())
        self.assertTrue(stash.exists())
        self.assertTrue(file_operations.public_dict(failed)["can_undo"])

        undone = file_operations.undo(db, failed)

        self.assertEqual(undone.state, "undone")
        self.assertEqual(
            source.read_text(encoding="utf-8"),
            "detached delete remains recoverable",
        )
        self.assertFalse(quarantine.exists())
        self.assertFalse(stash.exists())
        self.assertIsNone(db.get(TrashItem, details["trash_id"]))
        self.assertIsNone(db.get(FileOperationSourceClaim, row.id))
        db.close()

    def test_delete_undo_recovers_a_source_detached_after_ownership_commit(self):
        source = self.one / "delete-after-owned-quarantine.txt"
        source.write_text("owned delete remains recoverable", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="one",
            source_path=source.name,
        )
        quarantine = file_operations._quarantine_path(source, row.id)
        with mock.patch(
            "services.file_operations._remove",
            side_effect=file_operations.FileOperationError("injected after delete ownership"),
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "injected"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, row.id)
        details = json.loads(failed.undo_json)
        self.assertTrue(details["source_owned"])
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertFalse(source.exists())
        self.assertTrue(quarantine.exists())
        self.assertTrue(stash.exists())

        undone = file_operations.undo(db, failed)

        self.assertEqual(undone.state, "undone")
        self.assertEqual(source.read_text(encoding="utf-8"), "owned delete remains recoverable")
        self.assertFalse(quarantine.exists())
        self.assertFalse(stash.exists())
        self.assertIsNone(db.get(TrashItem, details["trash_id"]))
        self.assertIsNone(db.get(FileOperationSourceClaim, row.id))
        db.close()

    def test_delete_publishes_a_compound_source_conflict_and_keeps_trash(self):
        source = self.one / "delete-compound-race.txt"
        source.write_text("original delete source", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="one",
            source_path=source.name,
            destination_location_id=None,
            destination_path="",
        )
        operation_id = row.id
        quarantine = file_operations._quarantine_path(source, operation_id)
        original_rename = file_operations._rename_no_replace
        raced = False

        def replace_before_and_after_detach(path, target):
            nonlocal raced
            if (
                not raced
                and Path(path).resolve(strict=False) == source.resolve(strict=False)
                and Path(target).name.endswith(".quarantine")
            ):
                source.write_text("detached delete replacement", encoding="utf-8")
                result = original_rename(path, target)
                source.write_text("live delete replacement", encoding="utf-8")
                raced = True
                return result
            return original_rename(path, target)

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=replace_before_and_after_detach,
        ):
            with self.assertRaisesRegex(file_operations.FileOperationError, "preserved"):
                file_operations.run(db, row)

        failed = db.get(FileOperation, operation_id)
        details = json.loads(failed.undo_json)
        conflict = self.one / details["source_conflict_path"]
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertTrue(details["source_conflict_published"])
        self.assertEqual(source.read_text(encoding="utf-8"), "live delete replacement")
        self.assertEqual(
            conflict.read_text(encoding="utf-8"),
            "detached delete replacement",
        )
        self.assertEqual(stash.read_text(encoding="utf-8"), "original delete source")
        self.assertFalse(quarantine.exists())
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))
        self.assertTrue(file_operations.public_dict(failed)["can_discard"])

        file_operations.discard(db, failed)

        self.assertIsNotNone(db.get(TrashItem, details["trash_id"]))
        self.assertEqual(stash.read_text(encoding="utf-8"), "original delete source")
        self.assertEqual(source.read_text(encoding="utf-8"), "live delete replacement")
        self.assertEqual(
            conflict.read_text(encoding="utf-8"),
            "detached delete replacement",
        )
        db.close()

    def test_undo_restore_uses_the_restored_path_not_the_trash_id(self):
        (self.one / "restore-me.txt").write_text("recoverable", "utf-8")
        deleted = self._operation(
            action="delete",
            source_path="restore-me.txt",
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        deleted_row = db.get(FileOperation, deleted.json()["id"])
        import json

        trash_id = json.loads(deleted_row.undo_json)["trash_id"]
        db.close()
        restored = self._operation(
            action="restore",
            source_path=trash_id,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self._seed_live_metadata("one", "restore-me.txt", "local-restore")
        undone = self.client.post(f"/api/files/operations/{restored.json()['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertFalse((self.one / "restore-me.txt").exists())
        self._assert_live_metadata_absent("one", "restore-me.txt")

        db = self.db()
        undo_details = json.loads(db.get(FileOperation, restored.json()["id"]).undo_json)
        undo_trash_id = undo_details["undo_trash_id"]
        undo_trash = db.get(TrashItem, undo_trash_id)
        self.assertEqual(len(json.loads(undo_trash.payload)["metadata_snapshot"]), 6)
        db.close()

        restored_again = self._operation(
            action="restore",
            source_path=undo_trash_id,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(restored_again.status_code, 200, restored_again.text)
        self._assert_live_metadata_present("one", "restore-me.txt")

    def test_queued_cancel_and_interrupted_recovery_are_durable(self):
        (self.one / "note.txt").write_text("hello", "utf-8")
        queued = self._operation(run_now=False).json()
        self.assertTrue(queued["can_run"])
        cancelled = self.client.post(f"/api/files/operations/{queued['id']}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["state"], "cancelled")

        db = self.db()
        row = FileOperation(
            action="copy",
            source_location_id="one",
            source_path="note.txt",
            destination_location_id="two",
            destination_path="recovered.txt",
            state="running",
        )
        db.add(row)
        db.commit()
        recovered_id = row.id
        db.close()
        listing = self.client.get("/api/files/operations").json()["operations"]
        still_running = next(item for item in listing if item["id"] == recovered_id)
        self.assertEqual(still_running["state"], "running")
        self.assertEqual(still_running["error_code"], "")

        db = self.db()
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        db.close()
        recovered = self.client.get(f"/api/files/operations/{recovered_id}").json()
        self.assertEqual(recovered["state"], "queued")
        self.assertEqual(recovered["error_code"], "recovered_after_restart")
        run = self.client.post(f"/api/files/operations/{recovered_id}/run")
        self.assertEqual(run.status_code, 200, run.text)
        self.assertEqual((self.two / "recovered.txt").read_text("utf-8"), "hello")

    def test_recovered_operation_with_owned_side_effects_cannot_be_cancelled(self):
        db = self.db()
        row = FileOperation(
            action="rename",
            source_location_id="one",
            source_path="before.txt",
            destination_location_id="one",
            destination_path="after.txt",
            state="running",
            undo_json=json.dumps({"undo": "rename_back", "destination_owned": True}),
        )
        db.add(row)
        db.commit()
        operation_id = row.id

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        db.refresh(row)
        self.assertEqual(row.state, "queued")
        self.assertFalse(file_operations.public_dict(row)["can_cancel"])
        with self.assertRaisesRegex(file_operations.FileOperationError, "finish recovery"):
            file_operations.cancel(db, row)
        db.refresh(row)
        self.assertEqual(row.state, "queued")
        self.assertTrue(file_operations.public_dict(row)["can_retry"] is False)
        self.assertEqual(db.get(FileOperation, operation_id).state, "queued")
        db.close()

    def test_cancelling_a_recovered_operation_releases_its_durable_claims(self):
        db = self.db()
        row = FileOperation(
            action="move",
            source_location_id="one",
            source_path="before.txt",
            destination_location_id="two",
            destination_path="after.txt",
            state="running",
        )
        db.add(row)
        db.commit()
        db.add_all(
            [
                FileOperationSourceClaim(
                    operation_id=row.id,
                    location_id="one",
                    claim_scope="local-physical",
                    normalized_path="before.txt",
                ),
                FileOperationPathClaim(
                    operation_id=row.id,
                    location_id="one",
                    normalized_path="before.txt",
                    claim_scope="local-physical",
                ),
                FileOperationPathClaim(
                    operation_id=row.id,
                    location_id="two",
                    normalized_path="after.txt",
                    claim_scope="local-physical",
                ),
            ]
        )
        db.commit()

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        file_operations.cancel(db, row)

        self.assertEqual(row.state, "cancelled")
        self.assertEqual(
            db.query(FileOperationSourceClaim).filter_by(operation_id=row.id).count(), 0
        )
        self.assertEqual(db.query(FileOperationPathClaim).filter_by(operation_id=row.id).count(), 0)
        db.close()

    def test_local_claim_keys_fold_unicode_case_and_normalization(self):
        composed = file_operations.canonical_local_physical_claim_path("/data/Café/STRASSE")
        decomposed = file_operations.canonical_local_physical_claim_path("/data/CAFE\u0301/straße")

        self.assertEqual(composed, decomposed)

    def test_case_sensitive_local_claim_identity_preserves_distinct_paths(self):
        db = self.db()
        location = db.get(StorageLocation, "one")
        with mock.patch.object(
            file_operations, "_local_claim_case_insensitive", return_value=False
        ):
            upper_scope, upper = file_operations._path_claim_identity(location, "Folder/Note.md")
            lower_scope, lower = file_operations._path_claim_identity(location, "folder/note.md")
        self.assertEqual(upper_scope, "local-physical-cs")
        self.assertEqual(lower_scope, "local-physical-cs")
        self.assertNotEqual(upper, lower)
        db.close()

    def test_failed_operation_with_claimed_side_effects_cannot_be_discarded(self):
        (self.one / "after.txt").write_text("owned", encoding="utf-8")
        destination_meta = file_operations.storage_backends._local_path_receipt_identity(
            self.one / "after.txt"
        )
        db = self.db()
        row = FileOperation(
            action="rename",
            source_location_id="one",
            source_path="before.txt",
            destination_location_id="one",
            destination_path="after.txt",
            state="failed",
            undo_json=json.dumps(
                {
                    "undo": "rename_back",
                    "destination_owned": True,
                    "fingerprint": file_operations.fingerprint(self.one / "after.txt"),
                    "destination_meta": destination_meta,
                }
            ),
        )
        db.add(row)
        db.commit()
        operation_id = row.id
        workspace = file_operations._workspace(row)
        db.close()

        public = self.client.get(f"/api/files/operations/{operation_id}")
        discarded = self.client.delete(f"/api/files/operations/{operation_id}")

        self.assertFalse(public.json()["can_discard"])
        self.assertTrue(public.json()["can_undo"])
        self.assertEqual(discarded.status_code, 409, discarded.text)
        db = self.db()
        self.assertIsNotNone(db.get(FileOperation, operation_id))
        self.assertTrue(workspace.exists())
        db.close()

        undone = self.client.post(f"/api/files/operations/{operation_id}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual((self.one / "before.txt").read_text("utf-8"), "owned")
        self.assertFalse((self.one / "after.txt").exists())

    def test_failed_operation_without_owned_side_effects_can_be_discarded(self):
        (self.one / "note.txt").write_text("source", encoding="utf-8")
        db = self.db()
        row = FileOperation(
            action="copy",
            source_location_id="one",
            source_path="note.txt",
            destination_location_id="two",
            destination_path="occupied.txt",
            state="failed",
            undo_json=json.dumps(
                {
                    "undo": "remove_copy",
                    "destination_claimed": True,
                    "destination_owned": False,
                    "fingerprint": file_operations.fingerprint(self.one / "note.txt"),
                }
            ),
        )
        db.add(row)
        db.commit()
        operation_id = row.id
        workspace = file_operations._workspace(row)
        db.close()

        public = self.client.get(f"/api/files/operations/{operation_id}")
        discarded = self.client.delete(f"/api/files/operations/{operation_id}")

        self.assertTrue(public.json()["can_discard"])
        self.assertFalse(public.json()["can_undo"])
        self.assertEqual(discarded.status_code, 200, discarded.text)
        self.assertFalse(workspace.exists())

    def test_windows_directory_publication_uses_non_replacing_rename(self):
        source = self.one / "folder-partial"
        destination = self.two / "folder"
        source.mkdir()
        with (
            mock.patch.object(file_operations.os, "name", "nt"),
            mock.patch.object(file_operations.sys, "platform", "win32"),
            mock.patch("services.file_operations.os.rename") as rename,
        ):
            file_operations._rename_no_replace(source, destination)

        rename.assert_called_once_with(source, destination)

    def test_restart_releases_an_interrupted_undo_claim_for_safe_resume(self):
        db = self.db()
        row = FileOperation(
            action="copy",
            source_location_id="one",
            source_path="note.txt",
            destination_location_id="two",
            destination_path="note.txt",
            state="undoing_claimed",
            undo_json=json.dumps({"undo": "remove_destination"}),
        )
        db.add(row)
        db.commit()
        operation_id = row.id

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        db.close()

        recovered = self.client.get(f"/api/files/operations/{operation_id}").json()
        self.assertEqual(recovered["state"], "undoing")
        self.assertTrue(recovered["can_undo"])
        self.assertEqual(recovered["error_code"], "recovered_after_restart")

    def test_only_one_runner_can_claim_a_queued_operation(self):
        db_one = self.db()
        row_one = file_operations.enqueue(
            db_one,
            action="copy",
            source_location_id="one",
            source_path="note.txt",
            destination_location_id="two",
            destination_path="note.txt",
        )
        db_two = self.db()
        row_two = db_two.get(FileOperation, row_one.id)

        def execute_once(*_args, **_kwargs):
            with self.assertRaisesRegex(
                file_operations.FileOperationError,
                "already running",
            ):
                file_operations.run(db_two, row_two)
            return {}

        with mock.patch(
            "services.file_operations._execute_copy_or_move",
            side_effect=execute_once,
        ) as execute:
            completed = file_operations.run(db_one, row_one)

        self.assertEqual(completed.state, "completed")
        self.assertEqual(execute.call_count, 1)
        db_two.close()
        db_one.close()

    def test_only_one_stale_retry_caller_can_requeue_an_operation(self):
        (self.one / "note.txt").write_text("hello", encoding="utf-8")
        queued = self._operation(run_now=False).json()
        seeded = self.db()
        seeded.get(FileOperation, queued["id"]).state = "failed"
        seeded.commit()
        seeded.close()

        db_one = self.db()
        db_two = self.db()
        row_one = db_one.get(FileOperation, queued["id"])
        row_two = db_two.get(FileOperation, queued["id"])

        completed = file_operations.retry(db_one, row_one)
        self.assertEqual(completed.state, "completed")
        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "cannot be retried",
        ):
            file_operations.retry(db_two, row_two)

        checked = self.db()
        self.assertEqual(checked.get(FileOperation, queued["id"]).state, "completed")
        checked.close()
        db_two.close()
        db_one.close()

    def test_only_one_concurrent_caller_can_claim_an_undo(self):
        (self.one / "note.txt").write_text("hello", encoding="utf-8")
        completed = self._operation().json()
        db_one = self.db()
        db_two = self.db()
        row_one = db_one.get(FileOperation, completed["id"])
        row_two = db_two.get(FileOperation, completed["id"])
        original_undo = file_operations._undo_local
        entered = False

        def interleave(*args, **kwargs):
            nonlocal entered
            if not entered:
                entered = True
                with self.assertRaisesRegex(
                    file_operations.FileOperationError,
                    "already running",
                ):
                    file_operations.undo(db_two, row_two)
            return original_undo(*args, **kwargs)

        with mock.patch(
            "services.file_operations._undo_local",
            side_effect=interleave,
        ):
            undone = file_operations.undo(db_one, row_one)

        self.assertEqual(undone.state, "undone")
        self.assertFalse((self.two / "note.txt").exists())
        db_two.close()
        db_one.close()

    def test_trashed_files_disappear_from_starred_and_tag_views(self):
        (self.one / "remove.txt").write_text("delete me", "utf-8")
        db = self.db()
        db.add(
            FileTag(
                path="remove.txt",
                location_id="one",
                normalized_path="remove.txt",
                tags="work",
                starred=True,
            )
        )
        db.commit()
        db.close()

        deleted = self._operation(
            action="delete",
            source_path="remove.txt",
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)

        starred = self.client.get("/api/files/starred", params={"location_id": "one"})
        tagged = self.client.get(
            "/api/files/by-tag",
            params={"location_id": "one", "tag": "work"},
        )
        self.assertEqual(starred.status_code, 200, starred.text)
        self.assertEqual(tagged.status_code, 200, tagged.text)
        self.assertEqual(starred.json()["items"], [])
        self.assertEqual(tagged.json()["items"], [])

    def test_starred_folder_keeps_its_directory_type(self):
        (self.one / "folder").mkdir()
        starred = self.client.put(
            "/api/files/star",
            params={"location_id": "one", "path": "folder"},
            json={"starred": True},
        )
        self.assertEqual(starred.status_code, 200, starred.text)

        listed = self.client.get("/api/files/starred", params={"location_id": "one"})

        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["type"], "dir")

    def test_read_only_destination_is_rejected_before_queueing(self):
        db = self.db()
        db.get(StorageLocation, "two").access = "read_only"
        db.commit()
        db.close()
        (self.one / "note.txt").write_text("hello", "utf-8")
        response = self._operation()
        self.assertEqual(response.status_code, 409)
        self.assertIn("read-only", response.json()["detail"])
        self.assertFalse((self.two / "note.txt").exists())

    def test_same_path_and_destination_inside_source_are_rejected_without_data_loss(self):
        folder = self.one / "folder"
        folder.mkdir()
        (folder / "note.txt").write_text("keep me", "utf-8")
        for action, destination in (
            ("move", "folder"),
            ("rename", "folder"),
            ("copy", "folder/inside"),
            ("move", "folder/inside"),
        ):
            with self.subTest(action=action, destination=destination):
                response = self._operation(
                    action=action,
                    source_location_id="one",
                    source_path="folder",
                    destination_location_id="one",
                    destination_path=destination,
                )
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual((folder / "note.txt").read_text("utf-8"), "keep me")

    def test_local_alias_locations_reject_the_same_physical_destination(self):
        source = self.one / "physical.txt"
        source.write_text("keep physical source", encoding="utf-8")
        db = self.db()
        db.add(
            StorageLocation(
                id="one-alias",
                name="one alias",
                kind="local",
                access="managed",
                root_path=str(self.one),
                enabled=True,
            )
        )
        db.commit()
        db.close()

        response = self._operation(
            action="copy",
            source_path="physical.txt",
            destination_location_id="one-alias",
            destination_path="physical.txt",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(source.read_text(encoding="utf-8"), "keep physical source")

    def test_nested_local_root_rejects_a_destination_inside_the_source(self):
        source = self.one / "folder"
        source.mkdir()
        (source / "note.txt").write_text("keep nested source", encoding="utf-8")
        db = self.db()
        db.add(
            StorageLocation(
                id="nested-root",
                name="nested root",
                kind="local",
                access="managed",
                root_path=str(source),
                enabled=True,
            )
        )
        db.commit()
        db.close()

        response = self._operation(
            action="move",
            source_path="folder",
            destination_location_id="nested-root",
            destination_path="inside",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((source / "note.txt").read_text(encoding="utf-8"), "keep nested source")
        self.assertFalse((source / "inside").exists())

    def test_execution_rechecks_local_physical_roots_after_enqueue(self):
        source = self.one / "late-root.txt"
        source.write_text("keep after root change", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="late-root.txt",
            destination_location_id="two",
            destination_path="late-root.txt",
        )
        destination = db.get(StorageLocation, "two")
        destination.root_path = str(self.one)
        db.commit()

        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "destination must be outside the source",
        ):
            file_operations.run(db, row)

        self.assertEqual(source.read_text(encoding="utf-8"), "keep after root change")
        db.close()

    def test_rename_moves_every_location_scoped_metadata_record(self):
        source = self.one / "folder"
        source.mkdir()
        (source / "note.txt").write_text("indexed words", "utf-8")
        db = self.db()
        db.add_all(
            [
                FileTag(
                    path="folder/note.txt",
                    location_id="one",
                    normalized_path="",
                    tags="work",
                ),
                FileComment(
                    path="folder/note.txt",
                    location_id="one",
                    normalized_path="",
                    body="keep",
                ),
                FileVersion(
                    path="folder/note.txt",
                    location_id="one",
                    normalized_path="",
                ),
                OfflineFile(
                    location_id="one",
                    normalized_path="folder/note.txt",
                    state="ready",
                    cache_name="cached-note",
                ),
                Share(
                    token="phase7-metadata-share",
                    kind="file",
                    ref="folder/note.txt",
                    location_id="one",
                    normalized_path="",
                ),
                IndexChunk(
                    kind="file",
                    ref="folder/note.txt",
                    location_id="one",
                    normalized_path="",
                    text="indexed words",
                ),
                TrashItem(
                    kind="file",
                    ref="folder/old.txt",
                    location_id="one",
                    normalized_path="folder/old.txt",
                    name="old.txt",
                ),
            ]
        )
        db.commit()
        db.close()

        response = self._operation(
            action="rename",
            source_location_id="one",
            source_path="folder",
            destination_location_id="one",
            destination_path="renamed",
        )
        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        for model in (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk):
            row = db.query(model).first()
            self.assertEqual(row.location_id, "one", model.__name__)
            self.assertEqual(row.normalized_path, "renamed/note.txt", model.__name__)
        trashed = db.query(TrashItem).filter_by(name="old.txt").one()
        self.assertEqual(trashed.normalized_path, "folder/old.txt")
        self.assertEqual(trashed.ref, "folder/old.txt")
        db.close()

    def test_queued_delete_removes_all_location_scoped_live_metadata(self):
        folder = self.one / "delete-folder"
        folder.mkdir()
        (folder / "note.txt").write_text("delete metadata", "utf-8")
        db = self.db()
        db.add_all(
            [
                FileTag(
                    path="delete-folder/note.txt",
                    location_id="one",
                    normalized_path="delete-folder/note.txt",
                    tags="temporary",
                ),
                FileComment(
                    path="delete-folder/note.txt",
                    location_id="one",
                    normalized_path="delete-folder/note.txt",
                    body="remove",
                ),
                FileVersion(
                    path="delete-folder/note.txt",
                    location_id="one",
                    normalized_path="delete-folder/note.txt",
                ),
                OfflineFile(
                    location_id="one",
                    normalized_path="delete-folder/note.txt",
                    state="ready",
                    cache_name="missing-cache-entry",
                ),
                Share(
                    token="delete-folder-share",
                    kind="folder",
                    ref="delete-folder",
                    location_id="one",
                    normalized_path="delete-folder",
                ),
                IndexChunk(
                    kind="file",
                    ref="delete-folder/note.txt",
                    location_id="one",
                    normalized_path="delete-folder/note.txt",
                    text="delete metadata",
                ),
            ]
        )
        db.commit()
        db.close()

        response = self._operation(
            action="delete",
            source_location_id="one",
            source_path="delete-folder",
            destination_location_id="one",
            destination_path="",
        )
        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        for model in (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk):
            self.assertEqual(
                db.query(model).filter(model.location_id == "one").count(),
                0,
                model.__name__,
            )
        db.close()

    def test_move_rejects_stale_destination_metadata_before_touching_bytes(self):
        (self.one / "note.txt").write_text("source", "utf-8")
        db = self.db()
        db.add(
            FileTag(
                path="moved.txt",
                location_id="two",
                normalized_path="moved.txt",
                tags="stale",
            )
        )
        db.commit()
        db.close()

        response = self._operation(action="move", destination_path="moved.txt")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((self.one / "note.txt").read_text("utf-8"), "source")
        self.assertFalse((self.two / "moved.txt").exists())

    def test_copy_rejects_stale_destination_metadata_before_touching_bytes(self):
        (self.one / "note.txt").write_text("source", "utf-8")
        self._seed_live_metadata("two", "copied.txt", "stale-copy")

        response = self._operation(destination_path="copied.txt")

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((self.one / "note.txt").read_text("utf-8"), "source")
        self.assertFalse((self.two / "copied.txt").exists())
        db = self.db()
        self.assertEqual(
            db.query(FileTag)
            .filter(FileTag.location_id == "two", FileTag.normalized_path == "copied.txt")
            .count(),
            1,
        )
        db.close()

    def test_rename_and_delete_recover_after_a_crash_between_bytes_and_completion(self):
        (self.one / "rename.txt").write_text("rename safely", "utf-8")
        db = self.db()
        renamed = file_operations.enqueue(
            db,
            action="rename",
            source_location_id="one",
            source_path="rename.txt",
            destination_location_id="one",
            destination_path="renamed.txt",
        )
        renamed_id = renamed.id
        original_rename = file_operations._rename_no_replace

        def crash_after_rename(path, destination):
            original_rename(path, destination)
            raise SystemExit("simulated crash")

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=crash_after_rename,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, renamed)
        db.close()

        db = self.db()
        file_operations.recover_interrupted(db)
        file_operations.run(db, db.get(FileOperation, renamed_id))
        self.assertEqual((self.one / "renamed.txt").read_text("utf-8"), "rename safely")

        (self.one / "delete.txt").write_text("delete safely", "utf-8")
        deleted = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="one",
            source_path="delete.txt",
        )
        deleted_id = deleted.id
        original_remove = file_operations._remove

        def crash_after_remove(path):
            original_remove(path)
            raise SystemExit("simulated crash")

        with mock.patch("services.file_operations._remove", crash_after_remove):
            with self.assertRaises(SystemExit):
                file_operations.run(db, deleted)
        db.close()

        db = self.db()
        file_operations.recover_interrupted(db)
        file_operations.run(db, db.get(FileOperation, deleted_id))
        details = json.loads(db.get(FileOperation, deleted_id).undo_json)
        self.assertTrue(db.get(TrashItem, details["trash_id"]))
        db.close()

    def test_copy_crash_before_seal_preserves_destination_without_adopting_it(self):
        source = self.one / "copy-crash.txt"
        source.write_text("copy safely", "utf-8")
        db = self.db()
        copied = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="one",
            source_path="copy-crash.txt",
            destination_location_id="two",
            destination_path="copy-crash.txt",
        )
        copied_id = copied.id
        original_rename = file_operations._rename_no_replace

        def crash_after_publish(path, destination):
            original_rename(path, destination)
            raise SystemExit("simulated crash after copy publication")

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=crash_after_publish,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, copied)
        db.close()

        db = self.db()
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "destination already exists",
        ):
            file_operations.run(db, db.get(FileOperation, copied_id))
        self.assertEqual((self.two / "copy-crash.txt").read_text("utf-8"), "copy safely")
        failed = db.get(FileOperation, copied_id)
        details = json.loads(failed.undo_json)
        self.assertEqual(failed.state, "failed")
        self.assertFalse(details["destination_owned"])
        self.assertTrue(file_operations.public_dict(failed)["can_discard"])
        file_operations.discard(db, failed)
        self.assertIsNone(db.get(FileOperation, copied_id))
        self.assertEqual((self.one / "copy-crash.txt").read_text("utf-8"), "copy safely")
        self.assertEqual((self.two / "copy-crash.txt").read_text("utf-8"), "copy safely")
        db.close()

    def test_same_local_copy_recovers_its_exact_publication_after_a_crash(self):
        source = self.one / "same-local-crash.txt"
        destination = self.one / "same-local-copy.txt"
        source.write_text("recover exact publication", encoding="utf-8")
        db = self.db()
        copied = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        copied_id = copied.id
        original_rename = file_operations._rename_no_replace

        def crash_after_publish(path, published):
            original_rename(path, published)
            if Path(published).resolve(strict=False) == destination.resolve():
                raise SystemExit("simulated crash after same-local publication")

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=crash_after_publish,
        ):
            with self.assertRaisesRegex(SystemExit, "same-local publication"):
                file_operations.run(db, copied)
        db.close()

        db = self.db()
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        recovered = file_operations.run(db, db.get(FileOperation, copied_id))

        self.assertEqual(recovered.state, "completed")
        self.assertEqual(
            destination.read_text(encoding="utf-8"), source.read_text(encoding="utf-8")
        )
        details = json.loads(recovered.undo_json)
        self.assertTrue(details["destination_owned"])
        self.assertNotIn("destination_staged_publication_identity", details)
        db.close()

    def test_same_local_copy_crash_does_not_adopt_a_same_byte_replacement(self):
        source = self.one / "same-local-replaced-source.txt"
        destination = self.one / "same-local-replaced-copy.txt"
        source.write_text("same bytes, different owner", encoding="utf-8")
        db = self.db()
        copied = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        copied_id = copied.id
        original_rename = file_operations._rename_no_replace

        def crash_after_publish(path, published):
            original_rename(path, published)
            if Path(published).resolve(strict=False) == destination.resolve():
                raise SystemExit("simulated crash before ownership commit")

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=crash_after_publish,
        ):
            with self.assertRaisesRegex(SystemExit, "ownership commit"):
                file_operations.run(db, copied)
        db.close()

        replacement = self.one / "same-local-replacement.tmp"
        replacement.write_text("same bytes, different owner", encoding="utf-8")
        replacement_inode = replacement.stat().st_ino
        replacement.replace(destination)

        db = self.db()
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "destination already exists",
        ):
            file_operations.run(db, db.get(FileOperation, copied_id))

        failed = db.get(FileOperation, copied_id)
        self.assertEqual(failed.state, "failed")
        self.assertFalse(json.loads(failed.undo_json)["destination_owned"])
        self.assertEqual(destination.stat().st_ino, replacement_inode)
        db.close()

    def test_rename_crash_does_not_adopt_a_same_byte_replacement(self):
        source = self.one / "rename-replaced-source.txt"
        destination = self.one / "rename-replaced-destination.txt"
        source.write_text("same bytes, different owner", encoding="utf-8")
        db = self.db()
        renamed = file_operations.enqueue(
            db,
            action="rename",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        operation_id = renamed.id
        original_rename = file_operations._rename_no_replace

        def crash_after_publish(path, published):
            original_rename(path, published)
            if Path(published).resolve(strict=False) == destination.resolve(strict=False):
                raise SystemExit("simulated crash before rename ownership commit")

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=crash_after_publish,
        ):
            with self.assertRaisesRegex(SystemExit, "rename ownership commit"):
                file_operations.run(db, renamed)
        db.close()

        replacement = self.one / "rename-replacement.tmp"
        replacement.write_text("same bytes, different owner", encoding="utf-8")
        replacement_inode = replacement.stat().st_ino
        replacement.replace(destination)

        db = self.db()
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "verified bytes recovered",
        ):
            file_operations.run(db, db.get(FileOperation, operation_id))

        self.assertTrue(source.exists())
        self.assertEqual(source.read_text(encoding="utf-8"), "same bytes, different owner")
        self.assertEqual(destination.stat().st_ino, replacement_inode)
        db.close()

    def test_same_local_moves_exclusively_claim_one_source_across_recovery(self):
        source = self.one / "claimed.txt"
        source.write_text("one source", encoding="utf-8")
        db = self.db()
        first = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="claimed.txt",
            destination_location_id="one",
            destination_path="first.txt",
        )
        second = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="claimed.txt",
            destination_location_id="one",
            destination_path="second.txt",
        )
        first_id = first.id
        second_id = second.id

        with mock.patch(
            "services.file_operations._quarantine_verified",
            side_effect=SystemExit("crash before source quarantine"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, first)
        self.assertTrue(json.loads(first.undo_json)["destination_owned"])

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, second)
        self.assertFalse((self.one / "second.txt").exists())

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        recovered = file_operations.run(db, db.get(FileOperation, first_id))
        self.assertEqual(recovered.state, "completed")
        self.assertTrue(json.loads(recovered.undo_json)["source_owned"])
        self.assertFalse(source.exists())
        self.assertEqual((self.one / "first.txt").read_text(encoding="utf-8"), "one source")

        with self.assertRaisesRegex(file_operations.FileOperationError, "source not found"):
            file_operations.retry(db, db.get(FileOperation, second_id))
        self.assertFalse((self.one / "second.txt").exists())
        db.close()

    def test_local_alias_location_ids_share_one_physical_source_claim(self):
        source = self.one / "alias-claimed.txt"
        source.write_text("one physical source", encoding="utf-8")
        db = self.db()
        db.add(
            StorageLocation(
                id="one-source-alias",
                name="nested source alias",
                kind="local",
                access="managed",
                root_path=str(self.base),
                enabled=True,
            )
        )
        db.commit()
        first = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="alias-claimed.txt",
            destination_location_id="one",
            destination_path="alias-first.txt",
        )
        second = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one-source-alias",
            source_path="one/alias-claimed.txt",
            destination_location_id="one-source-alias",
            destination_path="one/alias-second.txt",
        )

        with mock.patch(
            "services.file_operations._quarantine_verified",
            side_effect=SystemExit("hold physical source claim"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, first)

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, second)
        self.assertEqual(source.read_text(encoding="utf-8"), "one physical source")
        self.assertFalse((self.one / "alias-second.txt").exists())
        db.close()

    def test_case_aliases_share_one_local_source_claim_on_case_insensitive_hosts(self):
        source = self.one / "Case-Claimed.txt"
        source.write_text("one case-folded source", encoding="utf-8")
        db = self.db()
        first = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="Case-Claimed.txt",
            destination_location_id="one",
            destination_path="case-first.txt",
        )
        second = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="case-claimed.txt",
            destination_location_id="one",
            destination_path="case-second.txt",
        )

        with (
            mock.patch.object(file_operations, "_local_claim_case_insensitive", return_value=True),
            mock.patch(
                "services.file_operations._quarantine_verified",
                side_effect=SystemExit("hold case-folded source claim"),
            ),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, first)

        with mock.patch.object(file_operations, "_local_claim_case_insensitive", return_value=True):
            with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
                file_operations.run(db, second)
        self.assertEqual(source.read_text(encoding="utf-8"), "one case-folded source")
        self.assertFalse((self.one / "case-second.txt").exists())
        db.close()

    def test_unicode_aliases_share_one_local_source_claim(self):
        composed_name = "Caf\u00e9-Claimed.txt"
        decomposed_name = unicodedata.normalize("NFD", composed_name)
        source = self.one / composed_name
        source.write_text("one unicode-normalized source", encoding="utf-8")
        db = self.db()
        first = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=composed_name,
            destination_location_id="one",
            destination_path="unicode-first.txt",
        )
        second = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=decomposed_name,
            destination_location_id="one",
            destination_path="unicode-second.txt",
        )

        with mock.patch(
            "services.file_operations._quarantine_verified",
            side_effect=SystemExit("hold unicode-normalized source claim"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, first)

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, second)
        self.assertEqual(source.read_text(encoding="utf-8"), "one unicode-normalized source")
        self.assertFalse((self.one / "unicode-second.txt").exists())
        db.close()

    def test_rename_commit_failure_after_quarantine_keeps_source_attributable(self):
        source = self.one / "rename-commit.txt"
        destination = self.one / "renamed-after-retry.txt"
        source.write_text("recover quarantined rename", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="rename",
            source_location_id="one",
            source_path="rename-commit.txt",
            destination_location_id="one",
            destination_path="renamed-after-retry.txt",
        )
        operation_id = row.id
        quarantine = file_operations._quarantine_path(source, operation_id)
        original_commit = db.commit
        failed = False

        def fail_source_ownership_commit():
            nonlocal failed
            details = json.loads(row.undo_json or "{}")
            if not failed and details.get("source_owned") and quarantine.exists():
                failed = True
                raise RuntimeError("source ownership commit failed")
            return original_commit()

        with mock.patch.object(db, "commit", side_effect=fail_source_ownership_commit):
            with self.assertRaisesRegex(
                file_operations.FileOperationError, "Files operation failed"
            ):
                file_operations.run(db, row)

        failed_row = db.get(FileOperation, operation_id)
        failed_details = json.loads(failed_row.undo_json)
        self.assertEqual(failed_row.state, "failed")
        self.assertTrue(failed_details["source_quarantine_started"])
        self.assertFalse(failed_details.get("source_owned"))
        self.assertFalse(source.exists())
        self.assertEqual(quarantine.read_text(encoding="utf-8"), "recover quarantined rename")
        self.assertIsNotNone(db.get(FileOperationSourceClaim, operation_id))
        self.assertFalse(file_operations.public_dict(failed_row)["can_discard"])
        with self.assertRaisesRegex(file_operations.FileOperationError, "recoverable side effects"):
            file_operations.discard(db, failed_row)

        recovered = file_operations.retry(db, failed_row)
        self.assertEqual(recovered.state, "completed")
        self.assertFalse(source.exists())
        self.assertFalse(quarantine.exists())
        self.assertEqual(destination.read_text(encoding="utf-8"), "recover quarantined rename")
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))
        db.close()

    def test_move_source_claim_blocks_delete_and_rename_before_mutation(self):
        source = self.one / "mutation-claimed.txt"
        source.write_text("one mutable source", encoding="utf-8")
        db = self.db()
        move = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="mutation-claimed.txt",
            destination_location_id="one",
            destination_path="moved.txt",
        )
        delete = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="one",
            source_path="mutation-claimed.txt",
        )
        rename = file_operations.enqueue(
            db,
            action="rename",
            source_location_id="one",
            source_path="mutation-claimed.txt",
            destination_location_id="one",
            destination_path="renamed.txt",
        )

        with mock.patch(
            "services.file_operations._quarantine_verified",
            side_effect=SystemExit("hold move source mutation claim"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, move)

        for loser in (delete, rename):
            with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
                file_operations.run(db, loser)
        self.assertEqual(source.read_text(encoding="utf-8"), "one mutable source")
        self.assertFalse((self.one / "renamed.txt").exists())
        self.assertEqual(db.query(TrashItem).count(), 0)

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        recovered = file_operations.run(db, db.get(FileOperation, move.id))
        self.assertEqual(recovered.state, "completed")
        self.assertFalse(source.exists())
        self.assertEqual((self.one / "moved.txt").read_text(encoding="utf-8"), "one mutable source")
        db.close()

    def test_cross_local_moves_exclusively_claim_one_source_across_recovery(self):
        source = self.one / "cross-claimed.txt"
        source.write_text("one cross source", encoding="utf-8")
        db = self.db()
        first = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="cross-claimed.txt",
            destination_location_id="two",
            destination_path="first.txt",
        )
        second = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="cross-claimed.txt",
            destination_location_id="two",
            destination_path="second.txt",
        )
        first_id = first.id
        second_id = second.id
        original_materialize = file_operations._materialize

        def crash_before_delete(location, path, target):
            if Path(target).name == "source-before-delete":
                raise SystemExit("crash before source delete")
            return original_materialize(location, path, target)

        with mock.patch(
            "services.file_operations._materialize",
            side_effect=crash_before_delete,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, first)
        first_details = json.loads(first.undo_json)
        self.assertTrue(first_details["destination_owned"])
        self.assertFalse(first_details.get("source_delete_started"))

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, second)
        self.assertFalse((self.two / "second.txt").exists())

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        recovered = file_operations.run(db, db.get(FileOperation, first_id))
        self.assertEqual(recovered.state, "completed")
        self.assertFalse(source.exists())
        self.assertEqual((self.two / "first.txt").read_text(encoding="utf-8"), "one cross source")

        with self.assertRaisesRegex(file_operations.FileOperationError, "source not found"):
            file_operations.retry(db, db.get(FileOperation, second_id))
        self.assertFalse((self.two / "second.txt").exists())
        db.close()

    def test_cross_local_move_does_not_credit_a_source_lost_before_delete(self):
        source = self.one / "lost-before-delete.txt"
        source.write_text("restore from destination", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="lost-before-delete.txt",
            destination_location_id="two",
            destination_path="lost-before-delete.txt",
        )
        operation_id = row.id
        original_materialize = file_operations._materialize

        def crash_before_delete(location, path, target):
            if Path(target).name == "source-before-delete":
                raise SystemExit("crash before source delete")
            return original_materialize(location, path, target)

        with mock.patch(
            "services.file_operations._materialize",
            side_effect=crash_before_delete,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, row)
        self.assertTrue((self.two / "lost-before-delete.txt").exists())
        self.assertFalse(json.loads(row.undo_json).get("source_delete_started"))

        source.unlink()
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        with self.assertRaisesRegex(file_operations.FileOperationError, "verified bytes recovered"):
            file_operations.run(db, db.get(FileOperation, operation_id))
        failed = db.get(FileOperation, operation_id)
        self.assertEqual(failed.state, "failed")
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))
        self.assertEqual(source.read_text(encoding="utf-8"), "restore from destination")
        self.assertTrue((self.two / "lost-before-delete.txt").exists())
        public = file_operations.public_dict(failed)
        self.assertFalse(public["can_retry"])
        self.assertFalse(public["can_undo"])
        self.assertTrue(public["can_discard"])
        db.close()

    def test_folder_source_claim_blocks_a_descendant_move(self):
        source = self.one / "claimed-folder"
        source.mkdir()
        child = source / "note.txt"
        child.write_text("keep child", encoding="utf-8")
        db = self.db()
        folder_move = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="claimed-folder",
            destination_location_id="one",
            destination_path="moved-folder",
        )
        child_move = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="claimed-folder/note.txt",
            destination_location_id="one",
            destination_path="moved-note.txt",
        )

        with mock.patch(
            "services.file_operations._quarantine_verified",
            side_effect=SystemExit("hold folder source claim"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, folder_move)

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, child_move)
        self.assertEqual(child.read_text(encoding="utf-8"), "keep child")
        self.assertFalse((self.one / "moved-note.txt").exists())
        db.close()

    def test_destination_path_claim_blocks_a_concurrent_descendant_copy(self):
        source_folder = self.one / "source-folder"
        source_folder.mkdir()
        (source_folder / "note.txt").write_text("folder bytes", encoding="utf-8")
        child_source = self.one / "child.txt"
        child_source.write_text("child bytes", encoding="utf-8")
        db = self.db()
        folder_copy = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="one",
            source_path="source-folder",
            destination_location_id="two",
            destination_path="reserved-folder",
        )
        child_copy = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="one",
            source_path="child.txt",
            destination_location_id="two",
            destination_path="reserved-folder/note.txt",
        )

        with mock.patch(
            "services.file_operations._execute_copy_or_move",
            side_effect=SystemExit("hold ancestor destination claim"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, folder_copy)

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, child_copy)
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == folder_copy.id)
            .count(),
            2,
        )
        self.assertFalse((self.two / "reserved-folder").exists())

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        self.assertEqual(file_operations.run(db, folder_copy).state, "completed")
        self.assertEqual(
            (self.two / "reserved-folder" / "note.txt").read_text(encoding="utf-8"),
            "folder bytes",
        )
        db.close()

    def test_move_keeps_destination_claim_through_source_delete_and_final_verification(self):
        source = self.one / "move-claim.txt"
        source.write_text("survivor bytes", encoding="utf-8")
        db = self.db()
        moved = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="move-claim.txt",
            destination_location_id="two",
            destination_path="move-claim.txt",
        )
        original_materialize = file_operations._materialize

        def stop_before_final_verification(location, path, target):
            if Path(target).name == "destination-after-delete":
                raise SystemExit("hold claims after source delete")
            return original_materialize(location, path, target)

        with mock.patch(
            "services.file_operations._materialize",
            side_effect=stop_before_final_verification,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, moved)

        self.assertFalse(source.exists())
        destination = self.two / "move-claim.txt"
        self.assertEqual(destination.read_text(encoding="utf-8"), "survivor bytes")
        concurrent_delete = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="two",
            source_path="move-claim.txt",
        )
        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, concurrent_delete)
        self.assertEqual(destination.read_text(encoding="utf-8"), "survivor bytes")

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        self.assertEqual(file_operations.run(db, moved).state, "completed")
        self.assertEqual(destination.read_text(encoding="utf-8"), "survivor bytes")
        db.close()

    def test_direct_upload_cannot_overwrite_an_operation_claimed_path(self):
        source = self.one / "direct-upload-claim.txt"
        source.write_text("operation owns this source", encoding="utf-8")
        db = self.db()
        moved = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="direct-upload-claim.txt",
            destination_location_id="two",
            destination_path="direct-upload-claim.txt",
        )

        with mock.patch(
            "services.file_operations._execute_copy_or_move",
            side_effect=SystemExit("hold operation path claims"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, moved)

        response = self.client.post(
            "/api/files/upload",
            data={"path": "", "location_id": "one"},
            files={
                "file": (
                    "direct-upload-claim.txt",
                    b"concurrent replacement",
                    "text/plain",
                )
            },
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("already in use", response.json()["detail"])
        tag_response = self.client.put(
            "/api/files/tags",
            params={"path": "direct-upload-claim.txt", "location_id": "one"},
            json={"tags": ["racing"]},
        )
        self.assertEqual(tag_response.status_code, 409, tag_response.text)
        self.assertIn("already in use", tag_response.json()["detail"])
        share_response = self.client.post(
            "/api/share",
            json={
                "kind": "file",
                "ref": "direct-upload-claim.txt",
                "location_id": "one",
            },
        )
        self.assertEqual(share_response.status_code, 409, share_response.text)
        self.assertIn("already in use", share_response.json()["detail"])
        offline_response = self.client.post(
            "/api/files/offline",
            json={
                "path": "direct-upload-claim.txt",
                "location_id": "one",
            },
        )
        self.assertEqual(offline_response.status_code, 409, offline_response.text)
        self.assertIn("already in use", offline_response.json()["detail"])
        self.assertEqual(source.read_text(encoding="utf-8"), "operation owns this source")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == moved.id)
            .count(),
            2,
        )
        self.assertEqual(
            db.query(FileOperation)
            .filter(FileOperation.action == file_operations.DIRECT_MUTATION_ACTION)
            .count(),
            0,
        )

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        self.assertEqual(file_operations.run(db, moved).state, "completed")
        db.close()

    def test_restart_removes_an_abandoned_direct_mutation_lease(self):
        db = self.db()
        location = db.get(StorageLocation, "one")
        row = FileOperation(
            action=file_operations.DIRECT_MUTATION_ACTION,
            source_location_id=location.id,
            source_path="abandoned.txt",
            destination_location_id=None,
            destination_path="",
            state="running",
            undo_json=json.dumps({"internal_direct_mutation": True}, sort_keys=True),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        operation_id = row.id
        file_operations._acquire_operation_path_claims(db, row)  # noqa: SLF001
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == operation_id)
            .count(),
            1,
        )
        db.close()

        restarted = self.db()
        self.assertEqual(file_operations.recover_interrupted(restarted), 1)
        self.assertIsNone(restarted.get(FileOperation, operation_id))
        self.assertEqual(
            restarted.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == operation_id)
            .count(),
            0,
        )
        restarted.close()

    def test_copy_undo_claims_source_before_destination_delete(self):
        source = self.one / "copy-undo-claim.txt"
        source.write_text("two verified copies", encoding="utf-8")
        db = self.db()
        copied = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="one",
            source_path="copy-undo-claim.txt",
            destination_location_id="two",
            destination_path="copy-undo-claim.txt",
        )
        self.assertEqual(file_operations.run(db, copied).state, "completed")
        original_snapshot = file_operations._destination_snapshot

        def stop_after_source_verification(location, path, target):
            result = original_snapshot(location, path, target)
            if Path(target).name == "undo-destination":
                raise SystemExit("hold copy undo claims")
            return result

        with mock.patch(
            "services.file_operations._destination_snapshot",
            side_effect=stop_after_source_verification,
        ):
            with self.assertRaises(SystemExit):
                file_operations.undo(db, copied)

        concurrent_delete = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="one",
            source_path="copy-undo-claim.txt",
        )
        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, concurrent_delete)
        self.assertTrue(source.exists())
        self.assertTrue((self.two / "copy-undo-claim.txt").exists())

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        self.assertEqual(file_operations.undo(db, copied).state, "undone")
        self.assertTrue(source.exists())
        self.assertFalse((self.two / "copy-undo-claim.txt").exists())
        db.close()

    def test_move_undo_claims_restored_source_until_destination_is_deleted(self):
        source = self.one / "move-undo-claim.txt"
        source.write_text("move undo survivor", encoding="utf-8")
        db = self.db()
        moved = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="move-undo-claim.txt",
            destination_location_id="two",
            destination_path="move-undo-claim.txt",
        )
        self.assertEqual(file_operations.run(db, moved).state, "completed")
        original_snapshot = file_operations._destination_snapshot

        def stop_before_destination_delete(location, path, target):
            if Path(target).name == "undo-destination-check":
                raise SystemExit("hold move undo claims")
            return original_snapshot(location, path, target)

        with mock.patch(
            "services.file_operations._destination_snapshot",
            side_effect=stop_before_destination_delete,
        ):
            with self.assertRaises(SystemExit):
                file_operations.undo(db, moved)

        self.assertEqual(source.read_text(encoding="utf-8"), "move undo survivor")
        self.assertTrue((self.two / "move-undo-claim.txt").exists())
        for location_id in ("one", "two"):
            concurrent_delete = file_operations.enqueue(
                db,
                action="delete",
                source_location_id=location_id,
                source_path="move-undo-claim.txt",
            )
            with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
                file_operations.run(db, concurrent_delete)

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        self.assertEqual(file_operations.undo(db, moved).state, "undone")
        self.assertEqual(source.read_text(encoding="utf-8"), "move undo survivor")
        self.assertFalse((self.two / "move-undo-claim.txt").exists())
        db.close()

    def test_receipt_release_error_stays_retryable_and_keeps_path_claims(self):
        source = self.one / "release-retry.txt"
        source.write_text("retry cleanup", encoding="utf-8")
        db = self.db()
        copied = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="one",
            source_path="release-retry.txt",
            destination_location_id="two",
            destination_path="release-retry.txt",
        )
        with mock.patch(
            "services.file_operations.storage_backends.release_operation_receipt",
            side_effect=file_operations.storage_backends.StorageBackendError(
                "temporary receipt cleanup failure"
            ),
        ):
            with self.assertRaisesRegex(
                file_operations.FileOperationError,
                "temporary receipt cleanup failure",
            ):
                file_operations.run(db, copied)

        failed = db.get(FileOperation, copied.id)
        self.assertEqual(failed.state, "failed")
        self.assertTrue(json.loads(failed.undo_json)["destination_owned"])
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == copied.id)
            .count(),
            2,
        )

        completed = file_operations.retry(db, failed)
        self.assertEqual(completed.state, "completed")
        self.assertEqual(
            (self.two / "release-retry.txt").read_text(encoding="utf-8"),
            "retry cleanup",
        )
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == copied.id)
            .count(),
            0,
        )
        db.close()

    def test_receipt_release_retry_rejects_same_byte_destination_replacement(self):
        source = self.one / "release-replaced.txt"
        destination = self.two / "release-replaced.txt"
        source.write_text("same bytes, different owner", encoding="utf-8")
        db = self.db()
        copied = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="one",
            source_path="release-replaced.txt",
            destination_location_id="two",
            destination_path="release-replaced.txt",
        )
        with mock.patch(
            "services.file_operations.storage_backends.release_operation_receipt",
            side_effect=file_operations.storage_backends.StorageBackendError(
                "temporary receipt cleanup failure"
            ),
        ):
            with self.assertRaisesRegex(
                file_operations.FileOperationError,
                "temporary receipt cleanup failure",
            ):
                file_operations.run(db, copied)

        failed = db.get(FileOperation, copied.id)
        details = json.loads(failed.undo_json)
        self.assertTrue(details["destination_receipt_release_started"])
        published_inode = destination.stat().st_ino
        replacement = self.two / "replacement.tmp"
        replacement.write_text("same bytes, different owner", encoding="utf-8")
        replacement.replace(destination)
        self.assertNotEqual(destination.stat().st_ino, published_inode)

        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "destination changed during transfer",
        ):
            file_operations.retry(db, failed)

        self.assertTrue(source.exists())
        self.assertEqual(
            destination.read_text(encoding="utf-8"), source.read_text(encoding="utf-8")
        )
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == copied.id)
            .count(),
            2,
        )
        db.close()

    def test_two_copies_of_one_source_do_not_take_mutation_claims(self):
        source = self.one / "copy-shared.txt"
        source.write_text("copy twice", encoding="utf-8")
        db = self.db()
        rows = [
            file_operations.enqueue(
                db,
                action="copy",
                source_location_id="one",
                source_path="copy-shared.txt",
                destination_location_id="one",
                destination_path=destination,
            )
            for destination in ("copy-one.txt", "copy-two.txt")
        ]

        for row in rows:
            self.assertEqual(file_operations.run(db, row).state, "completed")

        self.assertEqual(source.read_text(encoding="utf-8"), "copy twice")
        self.assertEqual((self.one / "copy-one.txt").read_text(encoding="utf-8"), "copy twice")
        self.assertEqual((self.one / "copy-two.txt").read_text(encoding="utf-8"), "copy twice")
        db.close()

    def test_same_local_move_recovers_after_owned_quarantine_was_deleted(self):
        source = self.one / "owned-delete.txt"
        destination = self.one / "owned-moved.txt"
        source.write_text("owned delete retry", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path="owned-delete.txt",
            destination_location_id="one",
            destination_path="owned-moved.txt",
        )
        operation_id = row.id
        original_remove = file_operations._remove

        def remove_then_crash(path):
            original_remove(path)
            raise SystemExit("crash after owned quarantine delete")

        with mock.patch("services.file_operations._remove", side_effect=remove_then_crash):
            with self.assertRaises(SystemExit):
                file_operations.run(db, row)
        details = json.loads(db.get(FileOperation, operation_id).undo_json)
        self.assertTrue(details["source_owned"])
        self.assertFalse(source.exists())
        self.assertTrue(destination.exists())

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        recovered = file_operations.run(db, db.get(FileOperation, operation_id))
        self.assertEqual(recovered.state, "completed")
        self.assertEqual(destination.read_text(encoding="utf-8"), "owned delete retry")
        db.close()

    def test_same_local_move_restart_restores_source_after_destination_replacement(self):
        source = self.one / "owned-replaced-source.txt"
        destination = self.one / "owned-replaced-destination.txt"
        source.write_text("same bytes, different owner", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        operation_id = row.id
        original_remove = file_operations._remove

        def remove_then_crash(path):
            original_remove(path)
            raise SystemExit("crash after source deletion")

        with mock.patch("services.file_operations._remove", side_effect=remove_then_crash):
            with self.assertRaisesRegex(SystemExit, "source deletion"):
                file_operations.run(db, row)
        self.assertFalse(source.exists())

        replacement = self.one / "owned-replacement.tmp"
        replacement.write_text("same bytes, different owner", encoding="utf-8")
        replacement_inode = replacement.stat().st_ino
        replacement.replace(destination)

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "verified bytes recovered",
        ):
            file_operations.run(db, db.get(FileOperation, operation_id))

        self.assertTrue(source.exists())
        self.assertEqual(source.read_text(encoding="utf-8"), "same bytes, different owner")
        self.assertEqual(destination.stat().st_ino, replacement_inode)
        db.close()

    def test_same_local_move_restart_restores_source_after_identity_read_failure(self):
        source = self.one / "owned-unreadable-source.txt"
        destination = self.one / "owned-unreadable-destination.txt"
        source.write_text("restore after identity read failure", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="one",
            source_path=source.name,
            destination_location_id="one",
            destination_path=destination.name,
        )
        operation_id = row.id
        original_remove = file_operations._remove

        def remove_then_crash(path):
            original_remove(path)
            raise SystemExit("crash after source deletion")

        with mock.patch("services.file_operations._remove", side_effect=remove_then_crash):
            with self.assertRaisesRegex(SystemExit, "source deletion"):
                file_operations.run(db, row)
        self.assertFalse(source.exists())
        self.assertTrue(destination.exists())
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        original_identity = file_operations._local_publication_identity

        def fail_destination_identity(path):
            if Path(path).resolve(strict=False) == destination.resolve(strict=False):
                raise file_operations.FileOperationError("identity read failed")
            return original_identity(path)

        with mock.patch(
            "services.file_operations._local_publication_identity",
            side_effect=fail_destination_identity,
        ):
            with self.assertRaisesRegex(
                file_operations.FileOperationError,
                "verified bytes recovered",
            ):
                file_operations.run(db, db.get(FileOperation, operation_id))

        self.assertTrue(source.exists())
        self.assertEqual(
            source.read_text(encoding="utf-8"),
            "restore after identity read failure",
        )
        self.assertTrue(destination.exists())
        db.close()

    def test_rename_restores_source_when_post_rename_verification_fails(self):
        source = self.one / "rename-race.txt"
        source.write_text("before", "utf-8")
        original_rename = file_operations._rename_no_replace

        def change_before_rename(path, destination):
            path.write_text("changed concurrently", "utf-8")
            original_rename(path, destination)

        with mock.patch(
            "services.file_operations._rename_no_replace",
            side_effect=change_before_rename,
        ):
            response = self._operation(
                action="rename",
                source_location_id="one",
                source_path="rename-race.txt",
                destination_location_id="one",
                destination_path="renamed-race.txt",
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(source.read_text("utf-8"), "before")
        self.assertFalse((self.one / "renamed-race.txt").exists())

    def test_delete_retry_accepts_its_existing_verified_trash_copy(self):
        source = self.one / "delete-after-copy.txt"
        source.write_text("delete safely", "utf-8")
        db = self.db()
        deleted = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="one",
            source_path="delete-after-copy.txt",
        )
        deleted_id = deleted.id

        with mock.patch(
            "services.file_operations._quarantine_verified",
            side_effect=SystemExit("simulated crash after verified trash copy"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, deleted)
        details = json.loads(db.get(FileOperation, deleted_id).undo_json)
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertTrue(source.exists())
        self.assertTrue(stash.exists())
        db.close()

        db = self.db()
        file_operations.recover_interrupted(db)
        recovered = file_operations.run(db, db.get(FileOperation, deleted_id))
        self.assertEqual(recovered.state, "completed")
        self.assertFalse(source.exists())
        self.assertTrue(stash.exists())
        db.close()

    def test_restore_recovers_after_crash_between_unstash_and_completion(self):
        (self.one / "restore.txt").write_text("restore safely", "utf-8")
        deleted = self._operation(
            action="delete",
            source_path="restore.txt",
            destination_location_id=None,
            destination_path="",
        )
        db = self.db()
        trash_id = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)["trash_id"]
        restored = file_operations.enqueue(
            db,
            action="restore",
            source_location_id="one",
            source_path=trash_id,
        )
        restored_id = restored.id
        original_unstash = file_operations._copy_verified

        def crash_after_unstash(stash, destination, operation_id):
            original_unstash(stash, destination, operation_id)
            raise SystemExit("simulated crash")

        with mock.patch(
            "services.file_operations._copy_verified",
            side_effect=crash_after_unstash,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, restored)
        db.close()

        db = self.db()
        file_operations.recover_interrupted(db)
        recovered = file_operations.run(db, db.get(FileOperation, restored_id))
        self.assertEqual(recovered.state, "completed")
        self.assertEqual((self.one / "restore.txt").read_text("utf-8"), "restore safely")
        db.close()

    def test_restore_rejects_an_identical_destination_it_did_not_create(self):
        (self.one / "restore-conflict.txt").write_text("same bytes", "utf-8")
        deleted = self._operation(
            action="delete",
            source_path="restore-conflict.txt",
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        trash_id = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)["trash_id"]
        db.close()
        (self.one / "restore-conflict.txt").write_text("same bytes", "utf-8")

        restored = self._operation(
            action="restore",
            source_path=trash_id,
            destination_location_id=None,
            destination_path="",
        )

        self.assertEqual(restored.status_code, 409, restored.text)
        self.assertEqual((self.one / "restore-conflict.txt").read_text("utf-8"), "same bytes")
        db = self.db()
        self.assertIsNotNone(db.get(TrashItem, trash_id))
        db.close()

    def test_legacy_local_rename_preflights_metadata_before_moving_bytes(self):
        (self.one / "legacy.txt").write_text("keep source", "utf-8")
        db = self.db()
        db.add_all(
            [
                FileTag(
                    path="legacy.txt",
                    location_id="one",
                    normalized_path="legacy.txt",
                    tags="source",
                ),
                FileTag(
                    path="occupied.txt",
                    location_id="one",
                    normalized_path="occupied.txt",
                    tags="destination",
                ),
            ]
        )
        db.commit()
        db.close()

        response = self.client.post(
            "/api/files/rename",
            json={"location_id": "one", "path": "legacy.txt", "to": "occupied.txt"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((self.one / "legacy.txt").read_text("utf-8"), "keep source")
        self.assertFalse((self.one / "occupied.txt").exists())

    def test_legacy_local_restore_uses_the_durable_operation_path(self):
        (self.one / "legacy-restore.txt").write_text("recover", "utf-8")
        self._seed_live_metadata("one", "legacy-restore.txt", "legacy-restore")
        deleted = self._operation(
            action="delete",
            source_path="legacy-restore.txt",
            destination_location_id=None,
            destination_path="",
        )
        self._assert_live_metadata_absent("one", "legacy-restore.txt")
        db = self.db()
        trash_id = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)["trash_id"]
        db.close()

        with mock.patch(
            "routes.files.trash.restore_file",
            side_effect=AssertionError("legacy restore path used"),
        ):
            restored = self.client.post(
                "/api/files/trash/restore",
                json={"location_id": "one", "id": trash_id},
            )

        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual((self.one / "legacy-restore.txt").read_text("utf-8"), "recover")
        db = self.db()
        for model in (FileTag, FileComment, FileVersion, OfflineFile, Share, IndexChunk):
            self.assertEqual(
                db.query(model)
                .filter(
                    model.location_id == "one",
                    model.normalized_path == "legacy-restore.txt",
                )
                .count(),
                1,
                model.__name__,
            )
        db.close()

    def test_remote_directory_ownership_requires_the_exact_uploaded_manifest(self):
        snapshot = self.base / "remote-directory-snapshot"
        snapshot.mkdir()
        uploaded = {
            "type": "dir",
            "etag": "",
            "version_id": "",
            "manifest": [
                {
                    "type": "file",
                    "path": "folder/note.txt",
                    "etag": '"uploaded"',
                    "version_id": "uploaded-version",
                }
            ],
            "directory_markers": [],
        }
        replaced = {
            **uploaded,
            "manifest": [
                {
                    "type": "file",
                    "path": "folder/note.txt",
                    "etag": '"replacement"',
                    "version_id": "replacement-version",
                }
            ],
        }
        location = type("RemoteLocation", (), {"kind": "s3"})()

        with self.assertRaisesRegex(
            file_operations.FileOperationError,
            "remote directory changed",
        ):
            file_operations._require_uploaded_identity(  # noqa: SLF001
                location,
                snapshot,
                uploaded,
                replaced,
            )

        file_operations._require_uploaded_identity(  # noqa: SLF001
            location,
            snapshot,
            uploaded,
            dict(uploaded),
        )
