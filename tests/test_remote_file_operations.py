import json
import shutil
import tempfile
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
from services import file_operations, storage_backends
from tests._client import ApiTest


class RemoteFileOperationTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.local = self.base / "local"
        self.remote = self.base / "remote"
        self.local.mkdir()
        self.remote.mkdir()
        db = self.db()
        db.add_all(
            [
                StorageLocation(
                    id="local-op",
                    name="local",
                    kind="local",
                    access="managed",
                    root_path=str(self.local),
                    enabled=True,
                ),
                StorageLocation(
                    id="remote-op",
                    name="remote",
                    kind="webdav",
                    access="managed",
                    endpoint="https://dav.example.test/files",
                    enabled=True,
                ),
                StorageLocation(
                    id="s3-op",
                    name="s3",
                    kind="s3",
                    access="managed",
                    endpoint="https://s3.example.test",
                    bucket="files",
                    enabled=True,
                ),
            ]
        )
        db.commit()
        db.close()
        self.original_materialize = storage_backends.materialize
        self.original_upload_tree = storage_backends.upload_tree
        self.original_delete_tree = storage_backends.delete_tree
        self.original_item = storage_backends.item
        self.original_receipt_matches = storage_backends.operation_receipt_matches
        self.original_release_receipt = storage_backends.release_operation_receipt
        self.original_seal_receipt = storage_backends.seal_operation_receipt
        self.original_upload_releasable = storage_backends.incomplete_operation_upload_is_releasable
        self.receipts = set()
        self.unreleasable_receipts = set()
        self.delete_calls = []
        self.remote_identities = {}
        self.materialize_patch = mock.patch(
            "services.file_operations.storage_backends.materialize",
            side_effect=self._materialize,
        )
        self.upload_patch = mock.patch(
            "services.file_operations.storage_backends.upload_tree",
            side_effect=self._upload_tree,
        )
        self.delete_patch = mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=self._delete_tree,
        )
        self.receipt_match_patch = mock.patch(
            "services.file_operations.storage_backends.operation_receipt_matches",
            side_effect=self._receipt_matches,
        )
        self.receipt_release_patch = mock.patch(
            "services.file_operations.storage_backends.release_operation_receipt",
            side_effect=self._release_receipt,
        )
        self.receipt_seal_patch = mock.patch(
            "services.file_operations.storage_backends.seal_operation_receipt",
            side_effect=self._seal_receipt,
        )
        self.upload_releasable_patch = mock.patch(
            "services.file_operations.storage_backends.incomplete_operation_upload_is_releasable",
            side_effect=self._upload_releasable,
        )
        self.item_patch = mock.patch(
            "services.storage_backends.item",
            side_effect=self._item,
        )
        self.item_patch.start()
        self.materialize_patch.start()
        self.upload_patch.start()
        self.delete_patch.start()
        self.receipt_match_patch.start()
        self.receipt_release_patch.start()
        self.receipt_seal_patch.start()
        self.upload_releasable_patch.start()

    def tearDown(self):
        self.upload_releasable_patch.stop()
        self.receipt_seal_patch.stop()
        self.receipt_release_patch.stop()
        self.receipt_match_patch.stop()
        self.delete_patch.stop()
        self.upload_patch.stop()
        self.materialize_patch.stop()
        self.item_patch.stop()
        self.temp.cleanup()
        super().tearDown()

    def _path(self, location, path):
        root = self.local if location.id == "local-op" else self.remote
        return root / path

    def _item(self, location, path):
        if location.id == "local-op":
            return self.original_item(location, path)
        target = self._path(location, path)
        if not target.exists():
            raise storage_backends.StorageNotFoundError("source not found")
        identity = self.remote_identities.get((location.id, path), {})
        return {
            "name": target.name,
            "path": path,
            "type": "dir" if target.is_dir() else "file",
            "size": target.stat().st_size if target.is_file() else 0,
            "etag": identity.get("etag", '"remote"'),
            "version_id": identity.get(
                "version_id",
                "version-1" if location.kind == "s3" else "",
            ),
        }

    def _copy(self, source: Path, destination: Path):
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def _materialize(self, location, path, destination, **kwargs):
        if location.id == "local-op":
            return self.original_materialize(location, path, destination, **kwargs)
        source = self._path(location, path)
        if not source.exists():
            raise storage_backends.StorageNotFoundError("source not found")
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink(missing_ok=True)
        self._copy(source, destination)
        result = file_operations.fingerprint(destination)
        identity = self.remote_identities.get((location.id, path), {})
        return {
            **result,
            "etag": identity.get("etag", '"remote"'),
            "version_id": identity.get(
                "version_id",
                "version-1" if location.kind == "s3" else "",
            ),
            **({"manifest": identity["manifest"]} if "manifest" in identity else {}),
            **(
                {"directory_markers": identity["directory_markers"]}
                if "directory_markers" in identity
                else {}
            ),
        }

    def _receipt_matches(self, location, path, operation_id, expected):
        if location.id == "local-op":
            return self.original_receipt_matches(location, path, operation_id, expected)
        return (
            location.id,
            path,
            operation_id,
            json.dumps(expected, sort_keys=True),
        ) in self.receipts

    def _release_receipt(self, location, path, operation_id, expected):
        if location.id == "local-op":
            return self.original_release_receipt(location, path, operation_id, expected)
        key = (location.id, path, operation_id, json.dumps(expected, sort_keys=True))
        if key in self.unreleasable_receipts:
            raise storage_backends.StorageBackendError(
                "null-version ownership intent cannot be released safely"
            )
        self.receipts.discard(key)

    def _upload_releasable(self, location, path, operation_id, expected):
        key = (location.id, path, operation_id, json.dumps(expected, sort_keys=True))
        if key in self.unreleasable_receipts:
            return False
        return self.original_upload_releasable(
            location,
            path,
            operation_id,
            expected,
        )

    def _seal_receipt(self, location, path, operation_id, expected, destination_identity):
        if location.id == "local-op":
            return self.original_seal_receipt(
                location,
                path,
                operation_id,
                expected,
                destination_identity,
            )
        self.receipts.add((location.id, path, operation_id, json.dumps(expected, sort_keys=True)))
        return {"type": "file", "etag": '"sealed"', "version_id": ""}

    def _upload_tree(self, location, path, source, *, operation_id=""):
        if location.id == "local-op":
            return self.original_upload_tree(
                location,
                path,
                source,
                operation_id=operation_id,
            )
        if Path(source).is_dir():
            raise storage_backends.StorageBackendError(
                "remote folder transfers are unavailable because this backend cannot publish "
                "a complete tree atomically"
            )
        expected = file_operations.fingerprint(Path(source))
        identity = self.remote_identities.get((location.id, path), {})
        if (
            location.kind == "s3"
            and str(identity.get("version_id") or "").strip().lower() == "null"
        ):
            if operation_id:
                key = (location.id, path, operation_id, json.dumps(expected, sort_keys=True))
                self.receipts.add(key)
                self.unreleasable_receipts.add(key)
            raise storage_backends.StorageBackendError(
                "s3 null-version transfers are unavailable; private receipt was preserved"
            )
        destination = self._path(location, path)
        if destination.exists():
            if not self._receipt_matches(location, path, operation_id, expected):
                raise storage_backends.StorageBackendError("destination already exists")
        else:
            self._copy(Path(source), destination)
            expected = file_operations.fingerprint(destination)
        if Path(source).is_file():
            return {
                **expected,
                "etag": identity.get("etag", '"remote"'),
                "version_id": identity.get(
                    "version_id",
                    "version-1" if location.kind == "s3" else "",
                ),
            }
        return expected

    def _delete_tree(
        self,
        location,
        path,
        *,
        expected=None,
        expected_etag="",
        version_id="",
        verified_meta=None,
        operation_id="",
        owned_version=False,
        missing_ok=True,
    ):
        if location.id == "local-op":
            kwargs = {
                "expected": expected,
                "expected_etag": expected_etag,
                "version_id": version_id,
                "verified_meta": verified_meta,
                "operation_id": operation_id,
                "missing_ok": missing_ok,
            }
            if owned_version:
                kwargs["owned_version"] = True
            return self.original_delete_tree(location, path, **kwargs)
        self.delete_calls.append(
            {
                "location_id": location.id,
                "path": path,
                "version_id": version_id,
                "owned_version": owned_version,
            }
        )
        if location.kind == "s3" and version_id and not owned_version:
            identity = self.remote_identities.get((location.id, path), {})
            raise storage_backends.StorageVersionedDeleteRefused(
                "versioned s3 objects cannot be deleted atomically; source was preserved",
                before_mutation=True,
                source_identity={
                    "etag": identity.get("etag", '"remote"'),
                    "version_id": identity.get("version_id", version_id),
                    "manifest": identity.get("manifest"),
                    "directory_markers": identity.get("directory_markers"),
                },
            )
        target = self._path(location, path)
        if not target.exists():
            if missing_ok:
                return
            raise storage_backends.StorageNotFoundError("source not found")
        if location.kind == "s3" and owned_version:
            identity = self.remote_identities.get((location.id, path), {})
            current_version = identity.get("version_id", "version-1")
            if current_version != version_id:
                return
        if expected and file_operations.fingerprint(target) != expected:
            raise storage_backends.StorageBackendError("source changed; delete stopped")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def _delete_tree_after_versioning_appears(
        self,
        location,
        path,
        *,
        expected=None,
        expected_etag="",
        version_id="",
        verified_meta=None,
        operation_id="",
        owned_version=False,
        missing_ok=True,
    ):
        if location.kind == "s3" and not owned_version and not version_id:
            identity = self.remote_identities.setdefault((location.id, path), {})
            identity.setdefault("etag", '"remote"')
            identity["version_id"] = "null"
            self.delete_calls.append(
                {
                    "location_id": location.id,
                    "path": path,
                    "version_id": version_id,
                    "owned_version": owned_version,
                }
            )
            raise storage_backends.StorageVersionedDeleteRefused(
                "versioned s3 objects cannot be deleted atomically; source was preserved",
                before_mutation=True,
                source_identity={
                    "etag": identity["etag"],
                    "version_id": identity["version_id"],
                    "manifest": identity.get("manifest"),
                    "directory_markers": identity.get("directory_markers"),
                },
            )
        return self._delete_tree(
            location,
            path,
            expected=expected,
            expected_etag=expected_etag,
            version_id=version_id,
            verified_meta=verified_meta,
            operation_id=operation_id,
            owned_version=owned_version,
            missing_ok=missing_ok,
        )

    def _operation(self, **changes):
        payload = {
            "action": "copy",
            "source_location_id": "local-op",
            "source_path": "note.txt",
            "destination_location_id": "remote-op",
            "destination_path": "note.txt",
        }
        payload.update(changes)
        return self.client.post("/api/files/operations", json=payload)

    def _seed_remote_metadata(
        self,
        path: str,
        token: str,
        *,
        location_id: str = "remote-op",
    ) -> None:
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
                    token=f"remote-undo-{token}",
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

    def _assert_remote_metadata_absent(
        self,
        path: str,
        *,
        location_id: str = "remote-op",
    ) -> None:
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

    def _assert_remote_metadata_present(
        self,
        path: str,
        *,
        location_id: str = "remote-op",
    ) -> None:
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

    def test_cross_location_move_verifies_then_deletes_and_can_undo(self):
        (self.local / "note.txt").write_text("safe move", "utf-8")
        moved = self._operation(action="move")
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertTrue(moved.json()["non_atomic"])
        self.assertFalse((self.local / "note.txt").exists())
        self.assertEqual((self.remote / "note.txt").read_text("utf-8"), "safe move")
        undone = self.client.post(f"/api/files/operations/{moved.json()['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual((self.local / "note.txt").read_text("utf-8"), "safe move")
        self.assertFalse((self.remote / "note.txt").exists())

    def test_remote_copy_undo_purges_destination_scoped_live_metadata(self):
        (self.local / "metadata.txt").write_text("remote copy", "utf-8")
        copied = self._operation(
            source_path="metadata.txt",
            destination_path="metadata.txt",
        )
        self.assertEqual(copied.status_code, 200, copied.text)
        self._seed_remote_metadata("metadata.txt", "copy")

        undone = self.client.post(f"/api/files/operations/{copied.json()['id']}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self._assert_remote_metadata_absent("metadata.txt")

    def test_remote_copy_rejects_stale_destination_metadata_before_upload(self):
        (self.local / "metadata.txt").write_text("remote copy", "utf-8")
        self._seed_remote_metadata("stale.txt", "before-copy")

        response = self._operation(
            source_path="metadata.txt",
            destination_path="stale.txt",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse((self.remote / "stale.txt").exists())
        db = self.db()
        self.assertEqual(
            db.query(FileTag)
            .filter(FileTag.location_id == "remote-op", FileTag.normalized_path == "stale.txt")
            .count(),
            1,
        )
        db.close()

    def test_webdav_directory_move_fails_before_creating_a_destination(self):
        source = self.remote / "folder"
        source.mkdir()
        (source / "nested.txt").write_text("remote", "utf-8")

        response = self._operation(
            action="move",
            source_location_id="remote-op",
            source_path="folder",
            destination_location_id="local-op",
            destination_path="moved",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue(source.exists())
        self.assertFalse((self.local / "moved").exists())

    def test_s3_folder_move_fails_before_upload_and_leaves_source_discardable(self):
        source = self.remote / "s3-move-folder"
        source.mkdir()
        (source / "nested.txt").write_text("keep complete", encoding="utf-8")
        self.remote_identities[("s3-op", "s3-move-folder")] = {
            "etag": '"folder-etag"',
            "version_id": "",
        }

        response = self._operation(
            action="move",
            source_location_id="s3-op",
            source_path="s3-move-folder",
            destination_location_id="local-op",
            destination_path="moved-s3-folder",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((source / "nested.txt").read_text(encoding="utf-8"), "keep complete")
        self.assertFalse((self.local / "moved-s3-folder").exists())
        self.assertEqual(self.delete_calls, [])
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        self.assertTrue(file_operations.public_dict(operation)["can_discard"])
        db.close()

    def test_s3_folder_copy_remains_supported(self):
        source = self.remote / "s3-copy-folder"
        source.mkdir()
        (source / "nested.txt").write_text("copy folder", encoding="utf-8")
        self.remote_identities[("s3-op", "s3-copy-folder")] = {
            "etag": '"folder-etag"',
            "version_id": "",
        }

        response = self._operation(
            action="copy",
            source_location_id="s3-op",
            source_path="s3-copy-folder",
            destination_location_id="local-op",
            destination_path="copied-s3-folder",
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            (self.local / "copied-s3-folder" / "nested.txt").read_text(encoding="utf-8"),
            "copy folder",
        )
        self.assertEqual((source / "nested.txt").read_text(encoding="utf-8"), "copy folder")

    def test_webdav_directory_delete_fails_before_creating_trash(self):
        source = self.remote / "folder"
        source.mkdir()
        (source / "nested.txt").write_text("remote", "utf-8")

        response = self._operation(
            action="delete",
            source_location_id="remote-op",
            source_path="folder",
            destination_location_id=None,
            destination_path="",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue(source.exists())
        db = self.db()
        self.assertEqual(db.query(TrashItem).count(), 0)
        db.close()

    def test_versioned_s3_delete_fails_before_creating_trash_and_can_be_discarded(self):
        source = self.remote / "versioned-delete.txt"
        source.write_text("preserve this version", encoding="utf-8")

        response = self._operation(
            action="delete",
            source_location_id="s3-op",
            source_path="versioned-delete.txt",
            destination_location_id=None,
            destination_path="",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue(source.exists())
        self.assertEqual(self.delete_calls, [])
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        self.assertEqual(db.query(TrashItem).count(), 0)
        db.close()
        public = self.client.get(f"/api/files/operations/{operation.id}")
        self.assertTrue(public.json()["can_discard"])
        discarded = self.client.delete(f"/api/files/operations/{operation.id}")
        self.assertEqual(discarded.status_code, 200, discarded.text)

    def test_versioned_s3_move_fails_before_destination_upload_and_can_be_discarded(self):
        source = self.remote / "versioned-move.txt"
        source.write_text("preserve move source", encoding="utf-8")

        response = self._operation(
            action="move",
            source_location_id="s3-op",
            source_path="versioned-move.txt",
            destination_location_id="local-op",
            destination_path="moved-from-s3.txt",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue(source.exists())
        self.assertFalse((self.local / "moved-from-s3.txt").exists())
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        db.close()
        public = self.client.get(f"/api/files/operations/{operation.id}")
        self.assertTrue(public.json()["can_discard"])

    def test_versioned_s3_copy_undo_exact_deletes_only_the_owned_version(self):
        source = self.local / "versioned-copy.txt"
        source.write_text("owned destination version", encoding="utf-8")

        copied = self._operation(
            source_path="versioned-copy.txt",
            destination_location_id="s3-op",
            destination_path="versioned-copy.txt",
        )
        self.assertEqual(copied.status_code, 200, copied.text)

        undone = self.client.post(f"/api/files/operations/{copied.json()['id']}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertFalse((self.remote / "versioned-copy.txt").exists())
        self.assertEqual(len(self.delete_calls), 1)
        self.assertEqual(self.delete_calls[0]["version_id"], "version-1")
        self.assertTrue(self.delete_calls[0]["owned_version"])

    def test_versioned_s3_copy_undo_preserves_a_newer_version_and_live_metadata(self):
        source = self.local / "versioned-copy-newer.txt"
        source.write_text("owned destination version", encoding="utf-8")
        copied = self._operation(
            source_path="versioned-copy-newer.txt",
            destination_location_id="s3-op",
            destination_path="versioned-copy-newer.txt",
        )
        self.assertEqual(copied.status_code, 200, copied.text)
        destination = self.remote / "versioned-copy-newer.txt"
        destination.write_text("newer external version", encoding="utf-8")
        self.remote_identities[("s3-op", "versioned-copy-newer.txt")] = {
            "etag": '"newer"',
            "version_id": "version-2",
        }
        self._seed_remote_metadata(
            "versioned-copy-newer.txt",
            "newer-copy",
            location_id="s3-op",
        )

        undone = self.client.post(f"/api/files/operations/{copied.json()['id']}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(destination.read_text(encoding="utf-8"), "newer external version")
        self.assertEqual(source.read_text(encoding="utf-8"), "owned destination version")
        self._assert_remote_metadata_present(
            "versioned-copy-newer.txt",
            location_id="s3-op",
        )
        self.assertEqual(self.delete_calls[-1]["version_id"], "version-1")
        self.assertTrue(self.delete_calls[-1]["owned_version"])

    def test_versioned_s3_restore_undo_rejects_a_newer_version_without_side_effects(self):
        trash_name = "versioned-restore-stash"
        stash = file_operations.trash.stash_path(trash_name)
        stash.write_text("restored owned version", encoding="utf-8")
        db = self.db()
        item = file_operations.trash.record(
            db,
            "file",
            "versioned-restore.txt",
            "versioned-restore.txt",
            {"trash_name": trash_name, "is_dir": False, "remote": True},
            location_id="s3-op",
        )
        item_id = item.id
        db.close()

        restored = self._operation(
            action="restore",
            source_location_id="s3-op",
            source_path=item_id,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        destination = self.remote / "versioned-restore.txt"
        destination.write_text("newer external restore version", encoding="utf-8")
        self.remote_identities[("s3-op", "versioned-restore.txt")] = {
            "etag": '"newer-restore"',
            "version_id": "version-2",
        }
        self._seed_remote_metadata(
            "versioned-restore.txt",
            "newer-restore",
            location_id="s3-op",
        )
        db = self.db()
        trash_count = db.query(TrashItem).count()
        db.close()

        undone = self.client.post(f"/api/files/operations/{restored.json()['id']}/undo")

        self.assertEqual(undone.status_code, 409, undone.text)
        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            "newer external restore version",
        )
        self._assert_remote_metadata_present(
            "versioned-restore.txt",
            location_id="s3-op",
        )
        db = self.db()
        self.assertEqual(db.query(TrashItem).count(), trash_count)
        restored_row = db.get(FileOperation, restored.json()["id"])
        self.assertEqual(restored_row.state, "completed")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == restored_row.id)
            .count(),
            0,
        )
        db.close()

    def test_versioned_s3_restore_undo_detaches_metadata_from_revealed_older_version(self):
        trash_name = "versioned-restore-with-older-stash"
        stash = file_operations.trash.stash_path(trash_name)
        stash.write_text("restored owned version", encoding="utf-8")
        db = self.db()
        item = file_operations.trash.record(
            db,
            "file",
            "versioned-restore-with-older.txt",
            "versioned-restore-with-older.txt",
            {"trash_name": trash_name, "is_dir": False, "remote": True},
            location_id="s3-op",
        )
        item_id = item.id
        db.close()
        restored = self._operation(
            action="restore",
            source_location_id="s3-op",
            source_path=item_id,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        path = "versioned-restore-with-older.txt"
        self._seed_remote_metadata(path, "owned-restore", location_id="s3-op")
        original_delete = self._delete_tree

        def reveal_older(location, deleted_path, **kwargs):
            original_delete(location, deleted_path, **kwargs)
            if location.id == "s3-op" and deleted_path == path and kwargs.get("owned_version"):
                self._path(location, deleted_path).write_text("older version", encoding="utf-8")
                self.remote_identities[(location.id, deleted_path)] = {
                    "etag": '"older"',
                    "version_id": "version-0",
                }

        with mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=reveal_older,
        ):
            undone = self.client.post(f"/api/files/operations/{restored.json()['id']}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual((self.remote / path).read_text("utf-8"), "older version")
        self._assert_remote_metadata_absent(path, location_id="s3-op")
        db = self.db()
        details = json.loads(db.get(FileOperation, restored.json()["id"]).undo_json)
        undo_trash = db.get(TrashItem, details["undo_trash_id"])
        self.assertEqual(len(json.loads(undo_trash.payload)["metadata_snapshot"]), 6)
        db.close()

    def test_completed_s3_move_undo_preserves_newer_destination_and_metadata(self):
        source = self.local / "versioned-move-newer.txt"
        source.write_text("moved version", encoding="utf-8")
        moved = self._operation(
            action="move",
            source_path="versioned-move-newer.txt",
            destination_location_id="s3-op",
            destination_path="versioned-move-newer.txt",
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertFalse(source.exists())
        destination = self.remote / "versioned-move-newer.txt"
        self.remote_identities[("s3-op", "versioned-move-newer.txt")] = {
            "etag": '"newer-move"',
            "version_id": "version-2",
        }
        self._seed_remote_metadata(
            "versioned-move-newer.txt",
            "newer-move",
            location_id="s3-op",
        )

        undone = self.client.post(f"/api/files/operations/{moved.json()['id']}/undo")

        self.assertEqual(undone.status_code, 409, undone.text)
        self.assertFalse(source.exists())
        self.assertEqual(destination.read_text(encoding="utf-8"), "moved version")
        self._assert_remote_metadata_present(
            "versioned-move-newer.txt",
            location_id="s3-op",
        )
        self._assert_remote_metadata_absent(
            "versioned-move-newer.txt",
            location_id="local-op",
        )

    def test_s3_null_version_upload_is_never_promoted_to_owned(self):
        source = self.local / "null-version.txt"
        source.write_text("same null-version bytes", encoding="utf-8")
        self.remote_identities[("s3-op", "null-version.txt")] = {
            "etag": '"remote"',
            "version_id": "null",
        }

        copied = self._operation(
            source_path="null-version.txt",
            destination_location_id="s3-op",
            destination_path="null-version.txt",
        )

        self.assertEqual(copied.status_code, 409, copied.text)
        destination = self.remote / "null-version.txt"
        self.assertFalse(destination.exists())
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        details = json.loads(operation.undo_json)
        self.assertTrue(details["upload_started"])
        self.assertFalse(details.get("destination_owned"))
        operation_id = operation.id
        db.close()
        public = self.client.get(f"/api/files/operations/{operation_id}").json()
        self.assertFalse(public["can_undo"])
        self.assertFalse(public["can_discard"])
        self.assertEqual(
            self.client.post(f"/api/files/operations/{operation_id}/undo").status_code,
            409,
        )
        discarded = self.client.delete(f"/api/files/operations/{operation_id}")
        self.assertEqual(discarded.status_code, 409, discarded.text)
        self.assertFalse(destination.exists())
        self.assertTrue(any(receipt[2] == operation_id for receipt in self.receipts))
        db = self.db()
        self.assertIsNotNone(db.get(FileOperation, operation_id))
        db.close()
        self.assertEqual(self.delete_calls, [])

    def test_versioned_s3_folder_copy_and_restore_fail_without_destination(self):
        source = self.local / "versioned-folder"
        source.mkdir()
        (source / "note.txt").write_text("folder bytes", encoding="utf-8")
        artifact_calls = []

        def versioned_folder_upload(location, path, snapshot, *, operation_id=""):
            if location.kind != "s3" or not Path(snapshot).is_dir():
                return self._upload_tree(
                    location,
                    path,
                    snapshot,
                    operation_id=operation_id,
                )
            with (
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="enabled",
                ),
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=storage_backends.StorageNotFoundError("source not found"),
                ),
                mock.patch(
                    "services.storage_backends._write_operation_claim",
                    side_effect=lambda *_args: artifact_calls.append("claim") or {},
                ),
                mock.patch(
                    "services.storage_backends._write_operation_receipt",
                    side_effect=lambda *_args: artifact_calls.append("receipt") or {},
                ),
                mock.patch(
                    "services.storage_backends.release_operation_receipt",
                    side_effect=lambda *_args: artifact_calls.append("release"),
                ),
            ):
                return self.original_upload_tree(
                    location,
                    path,
                    snapshot,
                    operation_id=operation_id,
                )

        with mock.patch(
            "services.file_operations.storage_backends.upload_tree",
            side_effect=versioned_folder_upload,
        ):
            copied = self._operation(
                source_path="versioned-folder",
                destination_location_id="s3-op",
                destination_path="versioned-folder-copy",
            )

        self.assertEqual(copied.status_code, 409, copied.text)
        self.assertFalse((self.remote / "versioned-folder-copy").exists())
        db = self.db()
        copied_row = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        copied_id = copied_row.id
        db.close()
        self.assertTrue(self.client.get(f"/api/files/operations/{copied_id}").json()["can_discard"])

        trash_name = "versioned-folder-restore-stash"
        stash = file_operations.trash.stash_path(trash_name)
        shutil.copytree(source, stash)
        db = self.db()
        item = file_operations.trash.record(
            db,
            "file",
            "versioned-folder-restore",
            "versioned-folder-restore",
            {"trash_name": trash_name, "is_dir": True, "remote": True},
            location_id="s3-op",
        )
        item_id = item.id
        db.close()

        with mock.patch(
            "services.file_operations.storage_backends.upload_tree",
            side_effect=versioned_folder_upload,
        ):
            restored = self._operation(
                action="restore",
                source_location_id="s3-op",
                source_path=item_id,
                destination_location_id=None,
                destination_path="",
            )

        self.assertEqual(restored.status_code, 409, restored.text)
        self.assertFalse((self.remote / "versioned-folder-restore").exists())
        self.assertTrue(stash.exists())
        db = self.db()
        restored_row = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        restored_id = restored_row.id
        db.close()
        self.assertTrue(
            self.client.get(f"/api/files/operations/{restored_id}").json()["can_discard"]
        )
        self.assertEqual(artifact_calls, [])

    def test_late_versioned_s3_delete_refusal_undo_cancels_redundant_trash(self):
        source = self.remote / "late-delete.txt"
        source.write_text("original version remains", encoding="utf-8")
        self._seed_remote_metadata(
            "late-delete.txt",
            "late-delete",
            location_id="s3-op",
        )
        self.remote_identities[("s3-op", "late-delete.txt")] = {
            "etag": '"remote"',
            "version_id": "",
        }

        with mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=self._delete_tree_after_versioning_appears,
        ):
            failed = self._operation(
                action="delete",
                source_location_id="s3-op",
                source_path="late-delete.txt",
                destination_location_id=None,
                destination_path="",
            )

        self.assertEqual(failed.status_code, 409, failed.text)
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        details = json.loads(operation.undo_json)
        self.assertEqual(details["source_meta"]["version_id"], "")
        self.assertEqual(
            details["source_delete_refusal_identity"]["version_id"],
            "null",
        )
        self.assertTrue(details["source_delete_refused_before_mutation"])
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertTrue(stash.exists())
        operation_id = operation.id
        db.close()

        undone = self.client.post(f"/api/files/operations/{operation_id}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["state"], "undone")
        self.assertEqual(source.read_text(encoding="utf-8"), "original version remains")
        self.assertFalse(stash.exists())
        self._assert_remote_metadata_present("late-delete.txt", location_id="s3-op")
        db = self.db()
        self.assertIsNone(db.get(TrashItem, details["trash_id"]))
        db.close()

    def test_late_versioned_s3_move_refusal_undo_removes_only_owned_destination(self):
        source = self.remote / "late-move-source.txt"
        destination = self.remote / "late-move-destination.txt"
        source.write_text("original move source remains", encoding="utf-8")
        self._seed_remote_metadata(
            "late-move-source.txt",
            "late-move",
            location_id="s3-op",
        )
        self.remote_identities[("s3-op", "late-move-source.txt")] = {
            "etag": '"remote"',
            "version_id": "",
        }

        with mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=self._delete_tree_after_versioning_appears,
        ):
            failed = self._operation(
                action="move",
                source_location_id="s3-op",
                source_path="late-move-source.txt",
                destination_location_id="s3-op",
                destination_path="late-move-destination.txt",
            )

        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertTrue(source.exists())
        self.assertTrue(destination.exists())
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        operation_id = operation.id
        details = json.loads(operation.undo_json)
        self.assertEqual(details["source_meta"]["version_id"], "")
        self.assertEqual(
            details["source_delete_refusal_identity"]["version_id"],
            "null",
        )
        db.close()

        undone = self.client.post(f"/api/files/operations/{operation_id}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["state"], "undone")
        self.assertEqual(source.read_text(encoding="utf-8"), "original move source remains")
        self.assertFalse(destination.exists())
        self._assert_remote_metadata_present("late-move-source.txt", location_id="s3-op")
        self.assertEqual(self.delete_calls[-1]["path"], "late-move-destination.txt")
        self.assertEqual(self.delete_calls[-1]["version_id"], "version-1")
        self.assertTrue(self.delete_calls[-1]["owned_version"])

    def test_late_versioned_s3_move_refusal_undo_removes_owned_local_destination(self):
        source = self.remote / "late-local-move-source.txt"
        destination = self.local / "late-local-move-destination.txt"
        source.write_text("s3 source remains after local copy", encoding="utf-8")
        self._seed_remote_metadata(
            "late-local-move-source.txt",
            "late-local-move",
            location_id="s3-op",
        )

        def local_upload_with_receipt(location, path, snapshot, *, operation_id=""):
            result = self._upload_tree(
                location,
                path,
                snapshot,
                operation_id=operation_id,
            )
            expected = file_operations.fingerprint(Path(snapshot))
            self.receipts.add(
                (location.id, path, operation_id, json.dumps(expected, sort_keys=True))
            )
            return result

        with (
            mock.patch(
                "services.file_operations._has_versioned_s3_source",
                return_value=False,
            ),
            mock.patch(
                "services.file_operations.storage_backends.upload_tree",
                side_effect=local_upload_with_receipt,
            ),
        ):
            failed = self._operation(
                action="move",
                source_location_id="s3-op",
                source_path="late-local-move-source.txt",
                destination_location_id="local-op",
                destination_path="late-local-move-destination.txt",
            )
        self.assertEqual(failed.status_code, 409, failed.text)
        self.assertTrue(source.exists())
        self.assertTrue(destination.exists())
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        operation_id = operation.id
        db.close()

        undone = self.client.post(f"/api/files/operations/{operation_id}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["state"], "undone")
        self.assertEqual(
            source.read_text(encoding="utf-8"),
            "s3 source remains after local copy",
        )
        self.assertFalse(destination.exists())
        self._assert_remote_metadata_present(
            "late-local-move-source.txt",
            location_id="s3-op",
        )

    def test_late_s3_delete_undo_rejects_same_bytes_with_changed_remote_identity(self):
        source = self.remote / "changed-delete.txt"
        source.write_text("same bytes, different version", encoding="utf-8")
        self.remote_identities[("s3-op", "changed-delete.txt")] = {
            "etag": '"remote"',
            "version_id": "",
        }

        with mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=self._delete_tree_after_versioning_appears,
        ):
            failed = self._operation(
                action="delete",
                source_location_id="s3-op",
                source_path="changed-delete.txt",
                destination_location_id=None,
                destination_path="",
            )
        self.assertEqual(failed.status_code, 409, failed.text)
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        operation_id = operation.id
        details = json.loads(operation.undo_json)
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        db.close()
        self.remote_identities[("s3-op", "changed-delete.txt")] = {
            "etag": '"changed"',
            "version_id": "version-2",
        }

        undone = self.client.post(f"/api/files/operations/{operation_id}/undo")

        self.assertEqual(undone.status_code, 409, undone.text)
        self.assertTrue(source.exists())
        self.assertTrue(stash.exists())
        db = self.db()
        self.assertEqual(db.get(FileOperation, operation_id).state, "failed")
        self.assertEqual(
            db.query(FileOperationPathClaim)
            .filter(FileOperationPathClaim.operation_id == operation_id)
            .count(),
            0,
        )
        self.assertIsNotNone(db.get(TrashItem, details["trash_id"]))
        db.close()

    def test_remote_identity_comparison_includes_manifests_and_directory_markers(self):
        stored = {
            "etag": "",
            "version_id": "",
            "manifest": [
                {
                    "type": "file",
                    "path": "folder/note.txt",
                    "etag": '"note"',
                    "version_id": "note-v1",
                }
            ],
            "directory_markers": [
                {
                    "path": "folder",
                    "etag": '"folder"',
                    "version_id": "folder-v1",
                }
            ],
        }
        self.assertTrue(file_operations._same_remote_identity(dict(stored), stored))
        changed_manifest = json.loads(json.dumps(stored))
        changed_manifest["manifest"][0]["version_id"] = "note-v2"
        self.assertFalse(file_operations._same_remote_identity(changed_manifest, stored))
        changed_marker = json.loads(json.dumps(stored))
        changed_marker["directory_markers"][0]["etag"] = '"changed-folder"'
        self.assertFalse(file_operations._same_remote_identity(changed_marker, stored))
        self.assertTrue(
            file_operations._has_versioned_s3_source(
                mock.Mock(kind="s3"),
                {"directory_markers": stored["directory_markers"]},
            )
        )

    def test_failed_destination_verification_never_deletes_source(self):
        (self.local / "note.txt").write_text("only copy", "utf-8")

        def corrupt_upload(location, path, source, *, operation_id=""):
            destination = self._path(location, path)
            destination.write_text("corrupt", "utf-8")
            return file_operations.fingerprint(destination)

        with mock.patch(
            "services.file_operations.storage_backends.upload_tree",
            side_effect=corrupt_upload,
        ):
            response = self._operation(action="move")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual((self.local / "note.txt").read_text("utf-8"), "only copy")
        self.assertEqual((self.remote / "note.txt").read_text("utf-8"), "corrupt")

    def test_remote_move_failure_before_source_delete_undo_removes_only_destination(self):
        source = self.remote / "remote-before-delete.txt"
        destination = self.local / "remote-before-delete.txt"
        source.write_text("remote source remains intact", encoding="utf-8")

        def fail_before_source_delete(location, path, target, **kwargs):
            if Path(target).name == "source-before-delete":
                raise file_operations.FileOperationError("injected before remote source delete")
            return self._materialize(location, path, target, **kwargs)

        with mock.patch(
            "services.file_operations.storage_backends.materialize",
            side_effect=fail_before_source_delete,
        ):
            failed = self._operation(
                action="move",
                source_location_id="remote-op",
                source_path=source.name,
                destination_location_id="local-op",
                destination_path=destination.name,
            )

        self.assertEqual(failed.status_code, 409, failed.text)
        db = self.db()
        operation = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        operation_id = operation.id
        details = json.loads(operation.undo_json)
        self.assertTrue(details["destination_owned"])
        self.assertFalse(details.get("source_delete_started"))
        self.assertTrue(file_operations.public_dict(operation)["can_undo"])
        self.assertIsNotNone(db.get(FileOperationSourceClaim, operation_id))
        db.close()

        undone = self.client.post(f"/api/files/operations/{operation_id}/undo")

        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(source.read_text(encoding="utf-8"), "remote source remains intact")
        self.assertFalse(destination.exists())
        db = self.db()
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))
        db.close()

    def test_failed_owned_upload_discards_private_intent_but_preserves_visible_partial(self):
        source = self.local / "folder"
        source.mkdir()
        (source / "first.txt").write_text("first", "utf-8")
        (source / "second.txt").write_text("second", "utf-8")

        def fail_after_partial_upload(location, path, snapshot, *, operation_id=""):
            expected = file_operations.fingerprint(Path(snapshot))
            self.receipts.add(
                (location.id, path, operation_id, json.dumps(expected, sort_keys=True))
            )
            destination = self._path(location, path)
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(snapshot) / "first.txt", destination / "first.txt")
            raise storage_backends.StorageBackendError("interrupted remote upload")

        with mock.patch(
            "services.file_operations.storage_backends.upload_tree",
            side_effect=fail_after_partial_upload,
        ):
            response = self._operation(
                source_path="folder",
                destination_path="folder-copy",
            )

        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        row = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        operation_id = row.id
        details = json.loads(row.undo_json)
        self.assertTrue(details["upload_started"])
        db.close()

        public = self.client.get(f"/api/files/operations/{operation_id}").json()
        discarded = self.client.delete(f"/api/files/operations/{operation_id}")
        self.assertTrue(public["can_retry"])
        self.assertTrue(public["can_discard"])
        self.assertFalse(public["can_undo"])
        self.assertEqual(discarded.status_code, 200, discarded.text)
        self.assertTrue((self.remote / "folder-copy" / "first.txt").exists())
        db = self.db()
        self.assertIsNone(db.get(FileOperation, operation_id))
        db.close()

    def test_remote_directory_copy_fails_before_publication_and_is_discardable(self):
        source = self.local / "folder"
        source.mkdir()
        (source / "first.txt").write_text("first", "utf-8")
        (source / "second.txt").write_text("second", "utf-8")
        response = self._operation(
            source_path="folder",
            destination_path="folder-copy",
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("cannot publish a complete tree atomically", response.json()["detail"])
        self.assertTrue((source / "first.txt").exists())
        self.assertTrue((source / "second.txt").exists())
        self.assertFalse((self.remote / "folder-copy").exists())
        db = self.db()
        row = db.query(FileOperation).order_by(FileOperation.created_at.desc()).first()
        operation_id = row.id
        self.assertEqual(row.state, "failed")
        self.assertFalse(any(receipt[2] == operation_id for receipt in self.receipts))
        db.close()
        self.assertTrue(
            self.client.get(f"/api/files/operations/{operation_id}").json()["can_discard"]
        )
        discarded = self.client.delete(f"/api/files/operations/{operation_id}")
        self.assertEqual(discarded.status_code, 200, discarded.text)

    def test_remote_upload_crash_before_seal_never_adopts_the_destination(self):
        source = self.local / "intent.txt"
        source.write_text("restart safe", "utf-8")
        expected = file_operations.fingerprint(source)
        location = mock.Mock(id="remote-op", kind="webdav", access="managed")
        remote = {"exists": False}

        def remote_item(_location, _path):
            if not remote["exists"]:
                raise storage_backends.StorageNotFoundError("source not found")
            return {"type": "file", "etag": '"saved"', "version_id": ""}

        def crash_after_create(*_args, **_kwargs):
            remote["exists"] = True
            raise SystemExit("crash after remote create")

        def materialize_created(_location, _path, destination, **_kwargs):
            shutil.copy2(source, destination)
            return {
                **file_operations.fingerprint(destination),
                "etag": '"saved"',
                "version_id": "",
            }

        with (
            mock.patch("services.storage_backends.item", side_effect=remote_item),
            mock.patch(
                "services.storage_backends._write_operation_claim",
                return_value={"type": "file", "etag": '"claim"', "version_id": ""},
            ),
            mock.patch(
                "services.storage_backends._write_operation_receipt",
                return_value={"type": "file", "etag": '"receipt"', "version_id": ""},
            ),
            mock.patch(
                "services.storage_backends.operation_receipt_matches",
                return_value=False,
            ),
            mock.patch(
                "services.webdav_locations._mutation_capabilities",
                return_value={"move", "put"},
            ),
            mock.patch(
                "services.storage_backends.materialize",
                side_effect=materialize_created,
            ),
            mock.patch("services.storage_backends.upload", side_effect=crash_after_create),
        ):
            with self.assertRaises(SystemExit):
                self.original_upload_tree(
                    location,
                    "intent.txt",
                    source,
                    operation_id="restart-safe-operation",
                )
            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "destination already exists",
            ):
                self.original_upload_tree(
                    location,
                    "intent.txt",
                    source,
                    operation_id="restart-safe-operation",
                )

        self.assertTrue(remote["exists"])
        self.assertEqual(expected["checksum"], file_operations.fingerprint(source)["checksum"])

    def test_recovery_releases_a_sealed_claim_after_ownership_commit_crash(self):
        source = self.local / "release-after-restart.txt"
        source.write_text("durable ownership", encoding="utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="copy",
            source_location_id="local-op",
            source_path="release-after-restart.txt",
            destination_location_id="remote-op",
            destination_path="release-after-restart.txt",
        )
        operation_id = row.id
        release_calls = {"count": 0}

        def crash_before_release(location, path, receipt_operation_id, expected):
            release_calls["count"] += 1
            if release_calls["count"] == 1:
                raise SystemExit("crash before ownership artifact release")
            return self._release_receipt(location, path, receipt_operation_id, expected)

        with mock.patch(
            "services.file_operations.storage_backends.release_operation_receipt",
            side_effect=crash_before_release,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, row)

        crashed = db.get(FileOperation, operation_id)
        self.assertTrue(json.loads(crashed.undo_json)["destination_owned"])
        self.assertEqual(crashed.state, "running")
        self.assertTrue(any(receipt[2] == operation_id for receipt in self.receipts))
        db.close()

        db = self.db()
        file_operations.recover_interrupted(db)
        recovered = file_operations.run(db, db.get(FileOperation, operation_id))

        self.assertEqual(recovered.state, "completed")
        self.assertFalse(any(receipt[2] == operation_id for receipt in self.receipts))
        self.assertEqual(
            (self.remote / "release-after-restart.txt").read_text(encoding="utf-8"),
            "durable ownership",
        )
        db.close()

    def test_preupload_receipt_does_not_own_a_mismatched_destination(self):
        source = self.base / "complete-upload.txt"
        source.write_text("complete upload bytes", "utf-8")
        destination = self.local / "retry-upload.txt"
        destination.write_text("partial", "utf-8")
        expected = file_operations.fingerprint(source)
        operation_id = "repair-owned-partial"
        self.receipts.add(
            (
                "local-op",
                "retry-upload.txt",
                operation_id,
                json.dumps(expected, sort_keys=True),
            )
        )
        db = self.db()
        location = db.get(StorageLocation, "local-op")

        with (
            mock.patch(
                "services.storage_backends._operation_receipt_identity",
                return_value={"type": "file", "etag": "", "version_id": ""},
            ),
            self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "destination already exists",
            ),
        ):
            self.original_upload_tree(
                location,
                "retry-upload.txt",
                source,
                operation_id=operation_id,
            )

        self.assertEqual(destination.read_text("utf-8"), "partial")
        db.close()

    def test_preupload_receipt_never_adopts_a_matching_partial_directory(self):
        source = self.base / "complete-folder"
        source.mkdir()
        (source / "first.txt").write_text("first", "utf-8")
        (source / "second.txt").write_text("second", "utf-8")
        expected = file_operations.fingerprint(source)
        operation_id = "resume-owned-directory"
        db = self.db()
        location = db.get(StorageLocation, "local-op")
        self.receipts.add(
            (
                location.id,
                "folder-copy",
                operation_id,
                json.dumps(expected, sort_keys=True),
            )
        )
        destination = self.local / "folder-copy"
        destination.mkdir()
        shutil.copy2(source / "first.txt", destination / "first.txt")

        with (
            mock.patch(
                "services.storage_backends._operation_receipt_identity",
                return_value={"type": "file", "etag": "", "version_id": ""},
            ),
            self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "destination already exists",
            ),
        ):
            self.original_upload_tree(
                location,
                "folder-copy",
                source,
                operation_id=operation_id,
            )

        self.assertEqual((destination / "first.txt").read_text("utf-8"), "first")
        self.assertFalse((destination / "second.txt").exists())
        db.close()

    def test_remote_move_rejects_identical_destination_created_after_preflight_crash(self):
        (self.local / "note.txt").write_text("same bytes", "utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="local-op",
            source_path="note.txt",
            destination_location_id="remote-op",
            destination_path="note.txt",
        )
        operation_id = row.id
        with mock.patch(
            "services.file_operations.storage_backends.upload_tree",
            side_effect=SystemExit("crash before remote mutation"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, row)
        (self.remote / "note.txt").write_text("same bytes", "utf-8")
        db.close()

        db = self.db()
        file_operations.recover_interrupted(db)
        with self.assertRaisesRegex(
            file_operations.FileOperationError, "destination already exists"
        ):
            file_operations.run(db, db.get(FileOperation, operation_id))
        self.assertEqual((self.local / "note.txt").read_text("utf-8"), "same bytes")
        self.assertEqual((self.remote / "note.txt").read_text("utf-8"), "same bytes")
        db.close()

    def test_remote_restore_rejects_identical_destination_created_after_preflight_crash(self):
        (self.remote / "restore.txt").write_text("same restore", "utf-8")
        deleted = self._operation(
            action="delete",
            source_location_id="remote-op",
            source_path="restore.txt",
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        db = self.db()
        trash_id = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)["trash_id"]
        row = file_operations.enqueue(
            db,
            action="restore",
            source_location_id="remote-op",
            source_path=trash_id,
        )
        operation_id = row.id
        with mock.patch(
            "services.file_operations.storage_backends.upload_tree",
            side_effect=SystemExit("crash before remote restore"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, row)
        (self.remote / "restore.txt").write_text("same restore", "utf-8")
        db.close()

        db = self.db()
        file_operations.recover_interrupted(db)
        with self.assertRaisesRegex(
            file_operations.FileOperationError, "destination already exists"
        ):
            file_operations.run(db, db.get(FileOperation, operation_id))
        self.assertIsNotNone(db.get(FileOperation, operation_id))
        self.assertEqual((self.remote / "restore.txt").read_text("utf-8"), "same restore")
        db.close()

    def test_remote_move_recovers_after_durable_source_delete_intent(self):
        (self.local / "note.txt").write_text("recover move", "utf-8")
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id="local-op",
            source_path="note.txt",
            destination_location_id="remote-op",
            destination_path="note.txt",
        )
        operation_id = row.id

        def delete_then_crash(location, path, **kwargs):
            self._delete_tree(location, path, **kwargs)
            raise SystemExit("crash after source delete")

        with mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=delete_then_crash,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, row)
        self.assertFalse((self.local / "note.txt").exists())
        self.assertEqual((self.remote / "note.txt").read_text("utf-8"), "recover move")
        db.close()

        db = self.db()
        file_operations.recover_interrupted(db)
        recovered = file_operations.run(db, db.get(FileOperation, operation_id))
        self.assertEqual(recovered.state, "completed")
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))

        undone = file_operations.undo(db, recovered)
        self.assertEqual(undone.state, "undone")
        self.assertEqual((self.local / "note.txt").read_text("utf-8"), "recover move")
        self.assertFalse((self.remote / "note.txt").exists())
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))
        db.close()

    def _assert_remote_source_delete_crash_recovers(self, source_location_id: str):
        source = self.remote / "remote-delete-crash.txt"
        source.write_text("remote delete crash", encoding="utf-8")
        if source_location_id == "s3-op":
            self.remote_identities[(source_location_id, "remote-delete-crash.txt")] = {
                "etag": '"source-etag"',
                "version_id": "",
            }
        db = self.db()
        row = file_operations.enqueue(
            db,
            action="move",
            source_location_id=source_location_id,
            source_path="remote-delete-crash.txt",
            destination_location_id="local-op",
            destination_path="remote-delete-crash.txt",
        )
        operation_id = row.id

        def delete_then_crash(location, path, **kwargs):
            self._delete_tree(location, path, **kwargs)
            raise SystemExit("crash after remote source delete")

        with mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=delete_then_crash,
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, row)
        self.assertFalse(source.exists())
        self.assertEqual(
            (self.local / "remote-delete-crash.txt").read_text(encoding="utf-8"),
            "remote delete crash",
        )

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        recovered = file_operations.run(db, db.get(FileOperation, operation_id))
        self.assertEqual(recovered.state, "completed")
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))

        undone = file_operations.undo(db, recovered)
        self.assertEqual(undone.state, "undone")
        self.assertEqual(source.read_text(encoding="utf-8"), "remote delete crash")
        self.assertFalse((self.local / "remote-delete-crash.txt").exists())
        self.assertIsNone(db.get(FileOperationSourceClaim, operation_id))
        db.close()

    def test_webdav_move_delete_crash_recovers(self):
        self._assert_remote_source_delete_crash_recovers("remote-op")

    def test_s3_move_delete_crash_recovers(self):
        self._assert_remote_source_delete_crash_recovers("s3-op")

    def _assert_remote_source_claim_serializes_moves(self, source_location_id: str):
        source = self.remote / "claimed-source.txt"
        source.write_text("one remote source", encoding="utf-8")
        if source_location_id == "s3-op":
            self.remote_identities[(source_location_id, "claimed-source.txt")] = {
                "etag": '"source-etag"',
                "version_id": "",
            }
        db = self.db()
        first = file_operations.enqueue(
            db,
            action="move",
            source_location_id=source_location_id,
            source_path="claimed-source.txt",
            destination_location_id="remote-op",
            destination_path="claimed-first.txt",
        )
        second = file_operations.enqueue(
            db,
            action="move",
            source_location_id=source_location_id,
            source_path="claimed-source.txt",
            destination_location_id="remote-op",
            destination_path="claimed-second.txt",
        )
        first_id = first.id
        second_id = second.id

        with mock.patch(
            "services.file_operations.storage_backends.delete_tree",
            side_effect=SystemExit("crash before remote source delete"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, first)
        first_details = json.loads(first.undo_json)
        self.assertTrue(first_details["destination_owned"])
        self.assertTrue(first_details["source_delete_started"])

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, second)
        self.assertFalse((self.remote / "claimed-second.txt").exists())

        self.assertEqual(file_operations.recover_interrupted(db), 1)
        recovered = file_operations.run(db, db.get(FileOperation, first_id))
        self.assertEqual(recovered.state, "completed")
        self.assertFalse(source.exists())
        self.assertEqual(
            (self.remote / "claimed-first.txt").read_text(encoding="utf-8"),
            "one remote source",
        )

        with self.assertRaisesRegex(file_operations.FileOperationError, "source not found"):
            file_operations.retry(db, db.get(FileOperation, second_id))
        self.assertFalse((self.remote / "claimed-second.txt").exists())
        db.close()

    def test_webdav_moves_exclusively_claim_one_source_across_recovery(self):
        self._assert_remote_source_claim_serializes_moves("remote-op")

    def test_s3_moves_exclusively_claim_one_source_across_recovery(self):
        self._assert_remote_source_claim_serializes_moves("s3-op")

    def test_webdav_alias_roots_share_one_effective_source_claim(self):
        db = self.db()
        db.add(
            StorageLocation(
                id="remote-alias",
                name="remote alias",
                kind="webdav",
                access="managed",
                endpoint="https://DAV.EXAMPLE.TEST:443/files/nested",
                prefix="team",
                enabled=True,
            )
        )
        db.commit()
        first = file_operations.enqueue(
            db,
            action="move",
            source_location_id="remote-op",
            source_path="nested/team/alias-source.txt",
            destination_location_id="local-op",
            destination_path="webdav-alias-first.txt",
        )
        second = file_operations.enqueue(
            db,
            action="move",
            source_location_id="remote-alias",
            source_path="alias-source.txt",
            destination_location_id="local-op",
            destination_path="webdav-alias-second.txt",
        )

        with mock.patch(
            "services.file_operations._execute_transfer",
            side_effect=SystemExit("hold WebDAV effective source claim"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, first)

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, second)
        self.assertIsNotNone(db.get(FileOperationSourceClaim, first.id))
        self.assertIsNone(db.get(FileOperationSourceClaim, second.id))
        db.close()

    def test_webdav_claim_scope_canonicalizes_dns_root_dot_and_ipv6(self):
        endpoint_pairs = [
            ("https://dav.example.test/dav", "https://dav.example.test./dav"),
            ("https://dav.example.test/dav", "https://dav.example.test。/dav"),
            (
                "https://[2001:db8::1]/dav",
                "https://[2001:0db8:0:0:0:0:0:1]/dav",
            ),
        ]
        for first_endpoint, alias_endpoint in endpoint_pairs:
            with self.subTest(alias=alias_endpoint):
                first = mock.Mock(endpoint=first_endpoint, prefix="")
                alias = mock.Mock(endpoint=alias_endpoint, prefix="")
                self.assertEqual(
                    file_operations._webdav_source_claim_identity(first, "note.txt"),
                    file_operations._webdav_source_claim_identity(alias, "note.txt"),
                )

    def test_s3_prefix_aliases_share_one_effective_source_claim(self):
        db = self.db()
        db.add(
            StorageLocation(
                id="s3-alias",
                name="s3 alias",
                kind="s3",
                access="managed",
                endpoint="https://S3.EXAMPLE.TEST:443",
                bucket="files",
                prefix="team",
                enabled=True,
            )
        )
        db.commit()
        first = file_operations.enqueue(
            db,
            action="move",
            source_location_id="s3-op",
            source_path="team/alias-source.txt",
            destination_location_id="local-op",
            destination_path="s3-alias-first.txt",
        )
        second = file_operations.enqueue(
            db,
            action="move",
            source_location_id="s3-alias",
            source_path="alias-source.txt",
            destination_location_id="local-op",
            destination_path="s3-alias-second.txt",
        )

        with mock.patch(
            "services.file_operations._execute_transfer",
            side_effect=SystemExit("hold S3 effective source claim"),
        ):
            with self.assertRaises(SystemExit):
                file_operations.run(db, first)

        with self.assertRaisesRegex(file_operations.FileOperationError, "already in use"):
            file_operations.run(db, second)
        self.assertIsNotNone(db.get(FileOperationSourceClaim, first.id))
        self.assertIsNone(db.get(FileOperationSourceClaim, second.id))
        db.close()

    def test_remote_delete_trash_restore_and_undo_keep_a_verified_copy(self):
        (self.remote / "remove.txt").write_text("recover me", "utf-8")
        deleted = self._operation(
            action="delete",
            source_location_id="remote-op",
            source_path="remove.txt",
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse((self.remote / "remove.txt").exists())
        db = self.db()
        details = json.loads(db.get(FileOperation, deleted.json()["id"]).undo_json)
        trash_id = details["trash_id"]
        db.close()

        restored = self._operation(
            action="restore",
            source_location_id="remote-op",
            source_path=trash_id,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual((self.remote / "remove.txt").read_text("utf-8"), "recover me")
        self._seed_remote_metadata("remove.txt", "restore")
        undone = self.client.post(f"/api/files/operations/{restored.json()['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertFalse((self.remote / "remove.txt").exists())
        self._assert_remote_metadata_absent("remove.txt")

        db = self.db()
        undo_details = json.loads(db.get(FileOperation, restored.json()["id"]).undo_json)
        undo_trash_id = undo_details["undo_trash_id"]
        undo_trash = db.get(TrashItem, undo_trash_id)
        self.assertEqual(len(json.loads(undo_trash.payload)["metadata_snapshot"]), 6)
        db.close()

        restored_again = self._operation(
            action="restore",
            source_location_id="remote-op",
            source_path=undo_trash_id,
            destination_location_id=None,
            destination_path="",
        )
        self.assertEqual(restored_again.status_code, 200, restored_again.text)
        self._assert_remote_metadata_present("remove.txt")

    def test_remote_restore_race_rolls_verified_bytes_back_to_trash(self):
        source = self.remote / "restore-race.txt"
        source.write_text("verified original", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_location_id="remote-op",
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
            source_location_id="remote-op",
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

    def test_remote_delete_undo_race_rolls_verified_bytes_back_to_trash(self):
        source = self.remote / "delete-undo-race.txt"
        source.write_text("verified original", encoding="utf-8")
        deleted = self._operation(
            action="delete",
            source_location_id="remote-op",
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

    def test_remote_delete_reuses_its_trash_row_after_crash_before_stash(self):
        source = self.remote / "delete-retry.txt"
        source.write_text("keep one trash identity", encoding="utf-8")
        db = self.db()
        operation = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="remote-op",
            source_path="delete-retry.txt",
        )
        operation_id = operation.id
        original_rename = Path.rename

        def crash_before_stash(path, destination):
            if path.name == "delete-source":
                raise SystemExit("simulated crash before remote stash")
            return original_rename(path, destination)

        with mock.patch.object(Path, "rename", new=crash_before_stash):
            with self.assertRaises(SystemExit):
                file_operations.run(db, operation)
        details = json.loads(db.get(FileOperation, operation_id).undo_json)
        original_trash_id = details["trash_id"]
        self.assertEqual(db.query(TrashItem).count(), 1)
        db.close()

        db = self.db()
        self.assertEqual(file_operations.recover_interrupted(db), 1)
        recovered = file_operations.run(db, db.get(FileOperation, operation_id))

        self.assertEqual(recovered.state, "completed")
        self.assertFalse(source.exists())
        self.assertEqual(db.query(TrashItem).count(), 1)
        self.assertEqual(json.loads(recovered.undo_json)["trash_id"], original_trash_id)
        item = db.get(TrashItem, original_trash_id)
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertTrue(stash.exists())
        db.close()

    def test_remote_delete_retry_rejects_an_unverified_existing_stash(self):
        source = self.remote / "delete-corrupt-stash.txt"
        source.write_text("verified remote source", encoding="utf-8")
        db = self.db()
        operation = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="remote-op",
            source_path=source.name,
        )
        original_rename = Path.rename

        def corrupt_after_stash(path, destination):
            result = original_rename(path, destination)
            if path.name == "delete-source":
                Path(destination).write_text("corrupt stash", encoding="utf-8")
            return result

        with mock.patch.object(Path, "rename", new=corrupt_after_stash):
            with self.assertRaisesRegex(
                file_operations.FileOperationError,
                "remote trash verification failed",
            ):
                file_operations.run(db, operation)

        failed = db.get(FileOperation, operation.id)
        details = json.loads(failed.undo_json)
        self.assertTrue(details["source_meta"])
        item = db.get(TrashItem, details["trash_id"])
        stash = file_operations.trash.stash_path(json.loads(item.payload)["trash_name"])
        self.assertEqual(stash.read_text(encoding="utf-8"), "corrupt stash")
        self.assertEqual(source.read_text(encoding="utf-8"), "verified remote source")

        with mock.patch("services.file_operations.storage_backends.delete_tree") as delete_remote:
            with self.assertRaisesRegex(
                file_operations.FileOperationError,
                "remote trash verification failed",
            ):
                file_operations.retry(db, failed)

        delete_remote.assert_not_called()
        self.assertEqual(source.read_text(encoding="utf-8"), "verified remote source")
        db.close()

    def test_s3_directory_delete_retries_from_its_persisted_verified_manifest(self):
        source = self.remote / "folder"
        source.mkdir()
        (source / "first.txt").write_text("first", "utf-8")
        (source / "second.txt").write_text("second", "utf-8")
        db = self.db()
        location = db.get(StorageLocation, "remote-op")
        location.kind = "s3"
        location.endpoint = "https://s3.example.test"
        location.bucket = "files"
        db.commit()
        row = file_operations.enqueue(
            db,
            action="delete",
            source_location_id="remote-op",
            source_path="folder",
        )
        materialize_calls = 0
        delete_calls = 0

        def materialize_with_manifest(location, path, destination, **kwargs):
            nonlocal materialize_calls
            materialize_calls += 1
            result = self._materialize(location, path, destination, **kwargs)
            result["type"] = "dir"
            result["version_id"] = ""
            result["manifest"] = [
                {
                    "type": "file",
                    "path": "folder/first.txt",
                    "etag": "first",
                    "version_id": "",
                },
                {
                    "type": "file",
                    "path": "folder/second.txt",
                    "etag": "second",
                    "version_id": "",
                },
            ]
            return result

        def partial_then_resume(_location, _path, *, verified_meta=None, **_kwargs):
            nonlocal delete_calls
            delete_calls += 1
            self.assertIsInstance(verified_meta, dict)
            self.assertEqual(len(verified_meta.get("manifest", [])), 2)
            if delete_calls == 1:
                (source / "first.txt").unlink()
                raise storage_backends.StorageBackendError("temporary delete failure")
            shutil.rmtree(source)

        with (
            mock.patch(
                "services.file_operations.storage_backends.materialize",
                side_effect=materialize_with_manifest,
            ),
            mock.patch(
                "services.file_operations.storage_backends.delete_tree",
                side_effect=partial_then_resume,
            ),
        ):
            with self.assertRaises(file_operations.FileOperationError):
                file_operations.run(db, row)
            recovered = file_operations.run(db, db.get(FileOperation, row.id))

        self.assertEqual(recovered.state, "completed")
        self.assertFalse(source.exists())
        self.assertEqual(materialize_calls, 1)
        self.assertEqual(delete_calls, 2)
        db.close()

    def test_legacy_remote_rename_delete_and_restore_use_safe_operations(self):
        (self.remote / "direct.txt").write_text("direct route", "utf-8")
        renamed = self.client.post(
            "/api/files/rename",
            json={
                "location_id": "remote-op",
                "path": "direct.txt",
                "to": "renamed.txt",
            },
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertFalse((self.remote / "direct.txt").exists())
        self.assertEqual((self.remote / "renamed.txt").read_text("utf-8"), "direct route")

        deleted = self.client.delete(
            "/api/files/delete",
            params={"location_id": "remote-op", "path": "renamed.txt"},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse((self.remote / "renamed.txt").exists())
        trashed = self.client.get("/api/files/trash", params={"location_id": "remote-op"}).json()
        self.assertEqual(len(trashed), 1)

        restored = self.client.post(
            "/api/files/trash/restore",
            json={"location_id": "remote-op", "id": trashed[0]["id"]},
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual((self.remote / "renamed.txt").read_text("utf-8"), "direct route")


if __name__ == "__main__":
    import unittest

    unittest.main()
