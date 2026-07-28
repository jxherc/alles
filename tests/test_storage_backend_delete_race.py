import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import file_operations, storage_backends


class StorageBackendDeleteRaceTests(unittest.TestCase):
    def test_local_folder_materialize_rejects_descendant_symlinks(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            storage_root = root / "storage"
            source = storage_root / "folder"
            source.mkdir(parents=True)
            outside = root / "outside.txt"
            outside.write_text("private bytes", encoding="utf-8")
            try:
                (source / "outside-link").symlink_to(outside)
            except OSError:
                self.skipTest("symlinks are unavailable")
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            destination = root / "snapshot"

            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "symbolic links",
            ):
                storage_backends.materialize(row, "folder", destination)

            self.assertFalse(destination.exists())

    def test_local_publication_identity_is_a_fixed_sha256_digest(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            folder = root / "folder"
            folder.mkdir()
            (folder / "child.txt").write_text("identity bytes", encoding="utf-8")

            publication_identity = file_operations._local_publication_identity(  # noqa: SLF001
                folder
            )
            receipt = storage_backends._local_path_receipt_identity(folder)  # noqa: SLF001

            self.assertEqual(len(publication_identity), 64)
            self.assertEqual(receipt["local_publication_identity"], publication_identity)

    def test_temporary_path_bounds_long_remote_names_and_keeps_the_extension(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            row = SimpleNamespace(id="remote")
            remote_name = f"{'x' * 251}.jpg"
            with mock.patch("services.storage_backends.data_dir", return_value=root):
                target = storage_backends.temporary_path(row, remote_name)
                target.write_bytes(b"preview")

            self.assertEqual(target.suffix, ".jpg")
            self.assertLessEqual(len(target.name.encode("utf-8")), 255)

    def test_listing_hides_only_owned_internal_transfer_names(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            source = root / "source.txt"
            source.write_text("source", encoding="utf-8")
            (root / "report.alles-receipt").write_text("user receipt", encoding="utf-8")
            (root / "report.alles-partial").write_text("user partial", encoding="utf-8")
            fake_operation_id = str(uuid.uuid4())
            fake_receipt = (
                root
                / Path(storage_backends._operation_receipt_path("report", fake_operation_id)).name
            )
            fake_receipt.write_text("not an Alles receipt", encoding="utf-8")
            unowned_partial = (
                root
                / Path(storage_backends._operation_partial_path("report", fake_operation_id)).name
            )
            unowned_partial.write_text("user file", encoding="utf-8")
            internal_partial = (
                root
                / Path(storage_backends._operation_partial_path("published.txt", operation_id)).name
            )
            internal_partial.write_text("published bytes", encoding="utf-8")
            expected = file_operations.fingerprint(internal_partial)
            storage_backends._write_operation_receipt(  # noqa: SLF001 - service ownership proof
                row,
                "published.txt",
                operation_id,
                expected,
            )

            listed_paths = [
                source,
                root / "report.alles-receipt",
                root / "report.alles-partial",
                fake_receipt,
                unowned_partial,
                internal_partial,
                storage_backends.local_path(
                    row,
                    storage_backends._operation_receipt_path("published.txt", operation_id),
                ),
            ]
            raw_items = [
                {
                    "name": path.name,
                    "path": path.name,
                    "normalized_path": path.name,
                    "type": "file",
                    "size": path.stat().st_size,
                    "etag": "",
                }
                for path in listed_paths
            ]
            with mock.patch(
                "services.storage_backends._raw_listdir",
                return_value={"path": "", "items": raw_items},
            ):
                names = {item["name"] for item in storage_backends.listdir(row)["items"]}

            self.assertIn("report.alles-receipt", names)
            self.assertIn("report.alles-partial", names)
            self.assertIn(fake_receipt.name, names)
            self.assertIn(unowned_partial.name, names)
            self.assertNotIn(internal_partial.name, names)
            self.assertNotIn(
                Path(storage_backends._operation_receipt_path("published.txt", operation_id)).name,
                names,
            )

    def test_listing_hides_owned_undo_transfer_names(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(root),
                id="local",
            )
            operation_id = f"undo-{uuid.uuid4()}"
            partial = (
                root
                / Path(storage_backends._operation_partial_path("restored.txt", operation_id)).name
            )
            partial.write_text("restored bytes", encoding="utf-8")
            expected = file_operations.fingerprint(partial)
            storage_backends._write_operation_receipt(  # noqa: SLF001 - service ownership proof
                row,
                "restored.txt",
                operation_id,
                expected,
            )
            receipt = storage_backends.local_path(
                row,
                storage_backends._operation_receipt_path("restored.txt", operation_id),
            )
            raw_items = [
                {
                    "name": path.name,
                    "path": path.name,
                    "normalized_path": path.name,
                    "type": "file",
                    "size": path.stat().st_size,
                    "etag": "",
                }
                for path in (partial, receipt)
            ]

            with mock.patch(
                "services.storage_backends._raw_listdir",
                return_value={"path": "", "items": raw_items},
            ):
                names = {item["name"] for item in storage_backends.listdir(row)["items"]}

            self.assertNotIn(partial.name, names)
            self.assertNotIn(receipt.name, names)

    def test_interrupted_local_upload_keeps_partial_bytes_out_of_the_files_view(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("complete transfer bytes", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            original_copy = storage_backends._copy_file

            def interrupt_copy(incoming, destination):
                if destination.name.endswith(
                    (
                        storage_backends.RECEIPT_SUFFIX,
                        storage_backends.CLAIM_SUFFIX,
                        storage_backends.SEAL_SUFFIX,
                    )
                ):
                    return original_copy(incoming, destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"partial")
                raise OSError("interrupted transfer")

            operation_id = str(uuid.uuid4())
            with mock.patch(
                "services.storage_backends._copy_file",
                side_effect=interrupt_copy,
            ):
                with self.assertRaises(storage_backends.StorageBackendError):
                    storage_backends.upload_tree(
                        row,
                        "published.txt",
                        source,
                        operation_id=operation_id,
                    )

            self.assertFalse((storage_root / "published.txt").exists())
            self.assertEqual(storage_backends.listdir(row)["items"], [])

            result = storage_backends.upload_tree(
                row,
                "published.txt",
                source,
                operation_id=operation_id,
            )

            self.assertEqual(
                (storage_root / "published.txt").read_text("utf-8"), source.read_text("utf-8")
            )
            self.assertEqual(result["checksum"], file_operations.fingerprint(source)["checksum"])

    def test_local_file_upload_receipt_does_not_adopt_a_post_publish_replacement(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("same bytes, different owner", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            destination = storage_root / "published.txt"
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            original_item = storage_backends.item
            raced = False
            replacement_inode = 0

            def replace_before_receipt(candidate, path):
                nonlocal raced, replacement_inode
                if not raced and path == "published.txt" and destination.exists():
                    replacement = storage_root / "same-byte-replacement.tmp"
                    shutil.copy2(source, replacement)
                    replacement_inode = replacement.stat().st_ino
                    replacement.replace(destination)
                    raced = True
                return original_item(candidate, path)

            with mock.patch(
                "services.storage_backends.item",
                side_effect=replace_before_receipt,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "upload verification failed",
                ):
                    storage_backends.upload_tree(
                        row,
                        "published.txt",
                        source,
                        operation_id=operation_id,
                    )

            self.assertTrue(raced)
            self.assertEqual(destination.stat().st_ino, replacement_inode)

    def test_local_directory_upload_receipt_does_not_adopt_a_changed_child(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source"
            source.mkdir()
            (source / "child.txt").write_text("same child bytes", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            destination = storage_root / "published"
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            original_item = storage_backends.item
            raced = False
            replacement_inode = 0

            def replace_child_before_receipt(candidate, path):
                nonlocal raced, replacement_inode
                if not raced and path == "published" and destination.exists():
                    replacement = storage_root / "same-child-replacement.tmp"
                    replacement.write_text("same child bytes", encoding="utf-8")
                    replacement_inode = replacement.stat().st_ino
                    replacement.replace(destination / "child.txt")
                    raced = True
                return original_item(candidate, path)

            with mock.patch(
                "services.storage_backends.item",
                side_effect=replace_child_before_receipt,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "upload verification failed",
                ):
                    storage_backends.upload_tree(
                        row,
                        "published",
                        source,
                        operation_id=operation_id,
                    )

            self.assertTrue(raced)
            self.assertEqual(
                (destination / "child.txt").stat().st_ino,
                replacement_inode,
            )

    def test_preupload_receipt_never_claims_a_concurrent_matching_destination(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("same bytes", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            storage_backends._write_operation_receipt(  # noqa: SLF001 - fail-first proof
                row,
                "published.txt",
                operation_id,
                expected,
            )
            destination = storage_root / "published.txt"
            shutil.copy2(source, destination)

            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "destination already exists",
            ):
                storage_backends.upload_tree(
                    row,
                    "published.txt",
                    source,
                    operation_id=operation_id,
                )

            self.assertEqual(destination.read_text(encoding="utf-8"), "same bytes")

    def test_destination_claim_is_exclusive_across_local_root_aliases(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            storage_root = root / "storage"
            nested_root = storage_root / "nested"
            nested_root.mkdir(parents=True)
            first = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="first",
            )
            alias = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(nested_root),
                id="alias",
            )
            expected = {"kind": "file", "size": 4, "count": 1, "checksum": "same"}
            first_operation = str(uuid.uuid4())
            second_operation = str(uuid.uuid4())

            storage_backends._write_operation_claim(  # noqa: SLF001 - ownership proof
                first,
                "nested/report.txt",
                first_operation,
                expected,
            )
            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "destination is in use",
            ):
                storage_backends._write_operation_claim(  # noqa: SLF001 - ownership proof
                    alias,
                    "report.txt",
                    second_operation,
                    expected,
                )

            self.assertIsNotNone(
                storage_backends._operation_claim_identity(  # noqa: SLF001
                    first,
                    "nested/report.txt",
                    first_operation,
                    expected,
                )
            )
            self.assertIsNone(
                storage_backends._operation_claim_identity(  # noqa: SLF001
                    alias,
                    "report.txt",
                    second_operation,
                    expected,
                )
            )

    def test_destination_ownership_requires_a_post_publication_seal(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("sealed bytes", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            published = storage_backends.upload_tree(
                row,
                "published.txt",
                source,
                operation_id=operation_id,
            )

            self.assertFalse(
                storage_backends.operation_receipt_matches(
                    row,
                    "published.txt",
                    operation_id,
                    expected,
                )
            )
            storage_backends.seal_operation_receipt(
                row,
                "published.txt",
                operation_id,
                expected,
                published,
            )
            self.assertTrue(
                storage_backends.operation_receipt_matches(
                    row,
                    "published.txt",
                    operation_id,
                    expected,
                )
            )
            self.assertEqual(
                [item["name"] for item in storage_backends.listdir(row)["items"]],
                ["published.txt"],
            )
            storage_backends.release_operation_receipt(
                row,
                "published.txt",
                operation_id,
                expected,
            )
            self.assertFalse(
                storage_backends.local_path(
                    row,
                    storage_backends._operation_claim_path("published.txt"),  # noqa: SLF001
                ).exists()
            )

    def test_local_seal_rejects_a_same_byte_replacement_after_publication(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("sealed bytes", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            published = storage_backends.upload_tree(
                row,
                "published.txt",
                source,
                operation_id=operation_id,
            )
            destination = storage_root / "published.txt"
            replacement = storage_root / "replacement.txt"
            shutil.copy2(source, replacement)
            replacement.replace(destination)
            current = storage_backends.item(row, "published.txt")
            self.assertNotEqual(published["local_inode"], current["local_inode"])

            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "changed before ownership was sealed",
            ):
                storage_backends.seal_operation_receipt(
                    row,
                    "published.txt",
                    operation_id,
                    expected,
                    published,
                )
            self.assertFalse(
                storage_backends.operation_receipt_matches(
                    row,
                    "published.txt",
                    operation_id,
                    expected,
                )
            )

    def test_local_directory_seal_rejects_a_changed_child(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source"
            source.mkdir()
            (source / "child.txt").write_text("original", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            published = storage_backends.upload_tree(
                row,
                "published",
                source,
                operation_id=operation_id,
            )
            (storage_root / "published" / "child.txt").write_text(
                "replacement",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "changed before ownership was sealed",
            ):
                storage_backends.seal_operation_receipt(
                    row,
                    "published",
                    operation_id,
                    expected,
                    published,
                )

    def test_local_directory_receipt_stops_matching_after_a_child_replacement(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source"
            source.mkdir()
            (source / "child.txt").write_text("original", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            published = storage_backends.upload_tree(
                row,
                "published",
                source,
                operation_id=operation_id,
            )
            storage_backends.seal_operation_receipt(
                row,
                "published",
                operation_id,
                expected,
                published,
            )
            self.assertTrue(
                storage_backends.operation_receipt_matches(
                    row,
                    "published",
                    operation_id,
                    expected,
                )
            )

            child = storage_root / "published" / "child.txt"
            replacement = storage_root / "replacement.txt"
            replacement.write_text("original", encoding="utf-8")
            replacement.replace(child)

            self.assertFalse(
                storage_backends.operation_receipt_matches(
                    row,
                    "published",
                    operation_id,
                    expected,
                )
            )

    def test_directory_receipt_never_accepts_a_file_destination(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            destination = storage_root / "published"
            destination.write_text("not a directory", encoding="utf-8")
            operation_id = str(uuid.uuid4())
            expected = {"kind": "dir", "size": 0, "count": 0, "checksum": "empty"}
            storage_backends._write_operation_claim(  # noqa: SLF001
                row,
                "published",
                operation_id,
                expected,
            )
            storage_backends._write_operation_receipt(  # noqa: SLF001
                row,
                "published",
                operation_id,
                expected,
            )

            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "destination type changed",
            ):
                storage_backends.seal_operation_receipt(
                    row,
                    "published",
                    operation_id,
                    expected,
                    storage_backends.item(row, "published"),
                )
            self.assertFalse(
                storage_backends.operation_receipt_matches(
                    row,
                    "published",
                    operation_id,
                    expected,
                )
            )

    def test_receipt_release_read_failure_preserves_every_ownership_artifact(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("sealed bytes", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            published = storage_backends.upload_tree(
                row,
                "published.txt",
                source,
                operation_id=operation_id,
            )
            storage_backends.seal_operation_receipt(
                row,
                "published.txt",
                operation_id,
                expected,
                published,
            )
            artifact_paths = (
                storage_backends._operation_claim_path("published.txt"),  # noqa: SLF001
                storage_backends._operation_receipt_path(  # noqa: SLF001
                    "published.txt", operation_id
                ),
                storage_backends._operation_seal_path(  # noqa: SLF001
                    "published.txt", operation_id
                ),
            )
            original_download = storage_backends.download

            def fail_claim_download(_row, path, target, **kwargs):
                if path == artifact_paths[0]:
                    raise storage_backends.StorageBackendError("temporary read failure")
                return original_download(_row, path, target, **kwargs)

            with mock.patch(
                "services.storage_backends.download",
                side_effect=fail_claim_download,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "temporary read failure",
                ):
                    storage_backends.release_operation_receipt(
                        row,
                        "published.txt",
                        operation_id,
                        expected,
                    )

            for artifact_path in artifact_paths:
                self.assertTrue(storage_backends.local_path(row, artifact_path).exists())

            storage_backends.release_operation_receipt(
                row,
                "published.txt",
                operation_id,
                expected,
            )
            for artifact_path in artifact_paths:
                self.assertFalse(storage_backends.local_path(row, artifact_path).exists())

    def test_direct_descendant_upload_respects_an_ancestor_operation_claim(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            storage_root = root / "storage"
            storage_root.mkdir()
            source = root / "source.txt"
            source.write_text("child bytes", encoding="utf-8")
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            storage_backends._write_operation_claim(  # noqa: SLF001 - race regression
                row,
                "folder",
                operation_id,
                {"kind": "dir", "size": 0, "count": 0, "checksum": "reserved"},
            )

            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "destination is in use",
            ):
                storage_backends.upload(row, "folder/note.txt", source)
            self.assertFalse((storage_root / "folder" / "note.txt").exists())

    def test_webdav_folder_upload_stops_before_any_publication_artifact(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "folder"
            source.mkdir()
            (source / "note.txt").write_text("same bytes", encoding="utf-8")
            row = SimpleNamespace(kind="webdav", access="managed", id="remote")

            def remote_item(_row, path):
                if path == "folder":
                    raise storage_backends.StorageNotFoundError("not found")
                raise storage_backends.StorageNotFoundError("not found")

            with (
                mock.patch("services.storage_backends.item", side_effect=remote_item),
                mock.patch("services.storage_backends._write_operation_claim") as claim,
                mock.patch("services.storage_backends._write_operation_receipt") as receipt,
                mock.patch("services.storage_backends.mkdir") as mkdir,
                mock.patch("services.storage_backends.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "cannot publish a complete tree atomically",
                ):
                    storage_backends.upload_tree(
                        row,
                        "folder",
                        source,
                        operation_id="ancestor-operation",
                    )

            claim.assert_not_called()
            receipt.assert_not_called()
            mkdir.assert_not_called()
            upload.assert_not_called()

    def test_webdav_file_upload_requires_stable_etags_before_ownership_artifacts(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "note.txt"
            source.write_text("owner bytes", encoding="utf-8")
            row = SimpleNamespace(kind="webdav", access="managed", id="remote")
            with (
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=storage_backends.StorageNotFoundError("not found"),
                ),
                mock.patch(
                    "services.storage_backends.webdav_locations._mutation_capabilities",
                    side_effect=storage_backends.webdav_locations.WebDAVLocationError(
                        "managed WebDAV writes require stable ETags"
                    ),
                ),
                mock.patch("services.storage_backends._write_operation_claim") as claim,
                mock.patch("services.storage_backends._write_operation_receipt") as receipt,
                mock.patch("services.storage_backends.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "stable ETags",
                ):
                    storage_backends.upload_tree(
                        row,
                        "published.txt",
                        source,
                        operation_id="webdav-etag-preflight",
                    )

            claim.assert_not_called()
            receipt.assert_not_called()
            upload.assert_not_called()

    def test_unversioned_s3_folder_upload_stops_before_any_publication_artifact(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "folder"
            source.mkdir()
            (source / "note.txt").write_text("same bytes", encoding="utf-8")
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            with (
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=storage_backends.StorageNotFoundError("not found"),
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="disabled",
                ),
                mock.patch("services.storage_backends._write_operation_claim") as claim,
                mock.patch("services.storage_backends._write_operation_receipt") as receipt,
                mock.patch("services.storage_backends.mkdir") as mkdir,
                mock.patch("services.storage_backends.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "cannot publish a complete tree atomically",
                ):
                    storage_backends.upload_tree(
                        row,
                        "folder",
                        source,
                        operation_id="ancestor-operation",
                    )

            claim.assert_not_called()
            receipt.assert_not_called()
            mkdir.assert_not_called()
            upload.assert_not_called()

    def test_unversioned_s3_file_operation_stops_before_any_publication_artifact(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "note.txt"
            source.write_text("owner bytes", encoding="utf-8")
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            with (
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=storage_backends.StorageNotFoundError("not found"),
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="disabled",
                ),
                mock.patch("services.storage_backends._write_operation_claim") as claim,
                mock.patch("services.storage_backends._write_operation_receipt") as receipt,
                mock.patch("services.storage_backends.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "requires enabled bucket versioning",
                ):
                    storage_backends.upload_tree(
                        row,
                        "note.txt",
                        source,
                        operation_id="unversioned-file-operation",
                    )

            claim.assert_not_called()
            receipt.assert_not_called()
            upload.assert_not_called()

    def test_operation_upload_requires_versioning_before_the_s3_put(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "note.txt"
            source.write_text("owner bytes", encoding="utf-8")
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            with (
                mock.patch("services.storage_backends._assert_no_foreign_destination_claim"),
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="disabled",
                ),
                mock.patch("services.storage_backends.s3_locations.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "requires enabled bucket versioning",
                ):
                    storage_backends.upload(
                        row,
                        "note.txt",
                        source,
                        operation_id="unversioned-direct-operation",
                    )

            upload.assert_not_called()

    def test_failed_direct_local_copy_removes_the_unpublished_destination(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            destination = root / "destination.txt"
            source.write_text("complete transfer bytes", encoding="utf-8")

            with mock.patch("services.storage_backends.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    storage_backends._copy_file(source, destination)  # noqa: SLF001

            self.assertFalse(destination.exists())
            storage_backends._copy_file(source, destination)  # noqa: SLF001
            self.assertEqual(destination.read_text("utf-8"), source.read_text("utf-8"))

    def test_interrupted_local_folder_upload_never_publishes_a_partial_child(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source"
            source.mkdir()
            (source / "child.txt").write_text("complete transfer bytes", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )

            def interrupt_copy(_incoming, destination, **_kwargs):
                destination.mkdir(parents=True)
                (destination / "child.txt").write_bytes(b"partial")
                raise OSError("interrupted transfer")

            operation_id = str(uuid.uuid4())
            with mock.patch(
                "services.storage_backends.shutil.copytree",
                side_effect=interrupt_copy,
            ):
                with self.assertRaises(storage_backends.StorageBackendError):
                    storage_backends.upload_tree(
                        row,
                        "published",
                        source,
                        operation_id=operation_id,
                    )

            self.assertFalse((storage_root / "published" / "child.txt").exists())
            self.assertNotIn(
                "published",
                {item["name"] for item in storage_backends.listdir(row)["items"]},
            )

            result = storage_backends.upload_tree(
                row,
                "published",
                source,
                operation_id=operation_id,
            )

            self.assertEqual(
                (storage_root / "published" / "child.txt").read_text(encoding="utf-8"),
                "complete transfer bytes",
            )
            expected = file_operations.fingerprint(source)
            self.assertEqual({key: result[key] for key in expected}, expected)

    def test_local_materialize_rejects_a_source_that_changes_during_the_copy(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            storage_root = root / "storage"
            storage_root.mkdir()
            source = storage_root / "source.txt"
            source.write_text("original bytes", encoding="utf-8")
            destination = root / "snapshot.txt"
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            original_copy = storage_backends._copy_file

            def change_source(incoming, target):
                result = original_copy(incoming, target)
                source.write_text("changed bytes", encoding="utf-8")
                return result

            with mock.patch(
                "services.storage_backends._copy_file",
                side_effect=change_source,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "source changed",
                ):
                    storage_backends.materialize(row, "source.txt", destination)

            self.assertFalse(destination.exists())

    def test_local_operation_receipt_is_removed_after_ownership_is_recorded(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("receipt cleanup", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = "release-local-receipt"
            expected = file_operations.fingerprint(source)

            storage_backends.upload_tree(
                row,
                "published.txt",
                source,
                operation_id=operation_id,
            )
            receipt = storage_backends.local_path(
                row,
                storage_backends._operation_receipt_path("published.txt", operation_id),
            )
            self.assertTrue(receipt.exists())

            storage_backends.release_operation_receipt(
                row,
                "published.txt",
                operation_id,
                expected,
            )

            self.assertFalse(receipt.exists())

    def test_versioned_s3_operation_receipt_uses_exact_owned_version_delete(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        metadata = {
            "type": "file",
            "etag": '"receipt"',
            "version_id": "receipt-version",
        }
        with (
            mock.patch(
                "services.storage_backends._operation_claim_identity",
                return_value=None,
            ),
            mock.patch(
                "services.storage_backends._operation_receipt_identity",
                return_value=metadata,
            ),
            mock.patch(
                "services.storage_backends._operation_seal_identity",
                return_value=None,
            ),
            mock.patch(
                "services.storage_backends.item",
                side_effect=storage_backends.StorageNotFoundError("not found"),
            ),
            mock.patch(
                "services.storage_backends.s3_locations.delete_owned_version",
            ) as exact_delete,
            mock.patch("services.storage_backends.s3_locations.delete") as generic_delete,
        ):
            storage_backends.release_operation_receipt(
                row,
                "published.txt",
                "release-versioned-receipt",
                {"kind": "file", "size": 7, "checksum": "abc"},
            )

        exact_delete.assert_called_once_with(
            row,
            storage_backends._operation_receipt_path("published.txt", "release-versioned-receipt"),
            expected_etag='"receipt"',
            version_id="receipt-version",
        )
        generic_delete.assert_not_called()

    def test_null_version_s3_receipt_cleanup_fails_closed(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        metadata = {"type": "file", "etag": '"receipt"', "version_id": "null"}
        with (
            mock.patch(
                "services.storage_backends._operation_claim_identity",
                return_value=None,
            ),
            mock.patch(
                "services.storage_backends._operation_receipt_identity",
                return_value=metadata,
            ),
            mock.patch(
                "services.storage_backends._operation_seal_identity",
                return_value=None,
            ),
            mock.patch(
                "services.storage_backends.item",
                side_effect=storage_backends.StorageNotFoundError("not found"),
            ),
            mock.patch(
                "services.storage_backends.s3_locations.delete_owned_version",
                side_effect=storage_backends.s3_locations.S3LocationError(
                    "an exact version ID is required before deleting an owned version"
                ),
            ) as exact_delete,
            mock.patch("services.storage_backends.s3_locations.delete") as generic_delete,
        ):
            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "exact version ID",
            ):
                storage_backends.release_operation_receipt(
                    row,
                    "published.txt",
                    "release-null-receipt",
                    {"kind": "file", "size": 7, "checksum": "abc"},
                )

        exact_delete.assert_called_once_with(
            row,
            storage_backends._operation_receipt_path("published.txt", "release-null-receipt"),
            expected_etag='"receipt"',
            version_id="null",
        )
        generic_delete.assert_not_called()

    def test_receipt_cleanup_uses_download_identity_when_s3_version_listing_falls_back(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        operation_id = "fallback-versioned-receipt"
        expected = {"kind": "file", "size": 7, "count": 1, "checksum": "abc"}

        def download_receipt(_row, _path, target, **_kwargs):
            target.write_text(
                __import__("json").dumps(
                    storage_backends._operation_receipt_payload(
                        row, "published.txt", operation_id, expected
                    )
                ),
                encoding="utf-8",
            )
            return {
                "size": target.stat().st_size,
                "checksum": "receipt",
                "etag": '"head-etag"',
                "version_id": "head-version",
            }

        with tempfile.TemporaryDirectory() as root_text:
            receipt_path = storage_backends._operation_receipt_path(  # noqa: SLF001
                "published.txt", operation_id
            )

            def artifact_item(_row, path):
                if path == receipt_path:
                    return {
                        "type": "file",
                        "size": 128,
                        "etag": '"listed-etag"',
                        "version_id": "",
                    }
                raise storage_backends.StorageNotFoundError("not found")

            with (
                mock.patch(
                    "services.storage_backends._operation_claim_identity",
                    return_value=None,
                ),
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=artifact_item,
                ),
                mock.patch(
                    "services.storage_backends.temporary_path",
                    return_value=Path(root_text) / "receipt.json",
                ),
                mock.patch(
                    "services.storage_backends.download",
                    side_effect=download_receipt,
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.delete_owned_version"
                ) as exact_delete,
                mock.patch("services.storage_backends.s3_locations.delete") as generic_delete,
            ):
                storage_backends.release_operation_receipt(
                    row,
                    "published.txt",
                    operation_id,
                    expected,
                )

        exact_delete.assert_called_once_with(
            row,
            storage_backends._operation_receipt_path("published.txt", operation_id),
            expected_etag='"head-etag"',
            version_id="head-version",
        )
        generic_delete.assert_not_called()

    def test_existing_s3_destination_receipt_never_promotes_an_unsealed_version(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "source.txt"
            source.write_text("same bytes", encoding="utf-8")
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            with (
                mock.patch(
                    "services.storage_backends.item",
                    return_value={
                        "type": "file",
                        "etag": '"same"',
                        "version_id": "concurrent-version",
                    },
                ),
                mock.patch(
                    "services.storage_backends._operation_receipt_identity",
                    return_value={"type": "file", "etag": '"receipt"'},
                ),
                mock.patch(
                    "services.storage_backends.operation_receipt_matches",
                    return_value=False,
                ),
                mock.patch("services.storage_backends.materialize") as materialize,
                mock.patch("services.storage_backends.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "destination already exists",
                ):
                    storage_backends.upload_tree(
                        row,
                        "published.txt",
                        source,
                        operation_id="crashed-versioned-upload",
                    )

        materialize.assert_not_called()
        upload.assert_not_called()

    def test_suspended_s3_versioning_stops_before_any_transfer_artifact(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "source.txt"
            source.write_text("do not upload", encoding="utf-8")
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            with (
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=storage_backends.StorageNotFoundError("not found"),
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="suspended",
                ),
                mock.patch("services.storage_backends._write_operation_claim") as write_claim,
                mock.patch("services.storage_backends._write_operation_receipt") as write_receipt,
                mock.patch("services.storage_backends.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "versioning is suspended",
                ):
                    storage_backends.upload_tree(
                        row,
                        "published.txt",
                        source,
                        operation_id="null-version-upload",
                    )

        write_claim.assert_not_called()
        write_receipt.assert_not_called()
        upload.assert_not_called()

    def test_suspended_s3_versioning_allows_exact_owned_upload_recovery(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("already published bytes", encoding="utf-8")
            check = root / "owned-check.txt"
            expected = file_operations.fingerprint(source)
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            current = {
                "type": "file",
                "size": expected["size"],
                "etag": '"owned-etag"',
                "version_id": "owned-version",
            }

            def materialize_owned(_row, _path, destination, **_kwargs):
                shutil.copy2(source, destination)
                return {**expected, **current}

            with (
                mock.patch("services.storage_backends.item", return_value=current),
                mock.patch(
                    "services.storage_backends.operation_receipt_matches",
                    return_value=True,
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="suspended",
                ),
                mock.patch(
                    "services.storage_backends.temporary_path",
                    return_value=check,
                ),
                mock.patch(
                    "services.storage_backends.materialize",
                    side_effect=materialize_owned,
                ) as materialize,
                mock.patch("services.storage_backends.upload") as upload,
            ):
                result = storage_backends.upload_tree(
                    row,
                    "published.txt",
                    source,
                    operation_id="resume-owned-version",
                )

        self.assertEqual(result["etag"], '"owned-etag"')
        self.assertEqual(result["version_id"], "owned-version")
        materialize.assert_called_once()
        upload.assert_not_called()

    def test_enabled_s3_versioning_requires_exact_artifact_versions(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "source.txt"
            source.write_text("keep the upload private", encoding="utf-8")
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            with (
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=storage_backends.StorageNotFoundError("not found"),
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="enabled",
                ),
                mock.patch(
                    "services.storage_backends._write_operation_claim",
                    return_value={"etag": '"claim"', "version_id": ""},
                ),
                mock.patch(
                    "services.storage_backends._write_operation_receipt",
                    return_value={"etag": '"receipt"', "version_id": "receipt-version"},
                ),
                mock.patch("services.storage_backends.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "artifact identity is incomplete",
                ):
                    storage_backends.upload_tree(
                        row,
                        "published.txt",
                        source,
                        operation_id="missing-artifact-version",
                    )

        upload.assert_not_called()

    def test_enabled_s3_versioning_requires_the_uploaded_version(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "source.txt"
            source.write_text("preserve the ownership receipt", encoding="utf-8")
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            with (
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=storage_backends.StorageNotFoundError("not found"),
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="enabled",
                ),
                mock.patch(
                    "services.storage_backends._write_operation_claim",
                    return_value={"etag": '"claim"', "version_id": "claim-version"},
                ),
                mock.patch(
                    "services.storage_backends._write_operation_receipt",
                    return_value={"etag": '"receipt"', "version_id": "receipt-version"},
                ),
                mock.patch(
                    "services.storage_backends.upload",
                    return_value={"etag": '"uploaded"', "version_id": "   "},
                ),
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "upload identity is incomplete",
                ):
                    storage_backends.upload_tree(
                        row,
                        "published.txt",
                        source,
                        operation_id="missing-upload-version",
                    )

    def test_versioned_s3_folder_upload_stops_before_any_transfer_artifact(self):
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "folder"
            source.mkdir()
            (source / "note.txt").write_text("folder upload", encoding="utf-8")
            row = SimpleNamespace(kind="s3", access="managed", id="remote")
            with (
                mock.patch(
                    "services.storage_backends.item",
                    side_effect=storage_backends.StorageNotFoundError("not found"),
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.versioning_state",
                    return_value="enabled",
                ),
                mock.patch("services.storage_backends._write_operation_claim") as write_claim,
                mock.patch("services.storage_backends._write_operation_receipt") as write_receipt,
                mock.patch("services.storage_backends.mkdir") as mkdir,
                mock.patch("services.storage_backends.upload") as upload,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "versioned s3 folder transfers",
                ):
                    storage_backends.upload_tree(
                        row,
                        "folder-copy",
                        source,
                        operation_id="folder-operation",
                    )

        write_claim.assert_not_called()
        write_receipt.assert_not_called()
        mkdir.assert_not_called()
        upload.assert_not_called()

    def test_s3_folder_materialize_keeps_head_verified_child_and_marker_versions(self):
        with tempfile.TemporaryDirectory() as root_text:
            target = Path(root_text) / "snapshot"
            row = SimpleNamespace(kind="s3", access="managed", id="remote")

            def download_child(_row, _path, destination, **_kwargs):
                destination.write_text("verified", encoding="utf-8")
                return {
                    "size": 8,
                    "checksum": file_operations.fingerprint(destination)["checksum"],
                    "etag": '"head-child"',
                    "version_id": "head-child-version",
                }

            def marker(_row, path):
                return {
                    "etag": f'"{path}-marker"',
                    "version_id": f"{path}-marker-version",
                }

            with (
                mock.patch(
                    "services.storage_backends.item",
                    return_value={"type": "dir", "etag": "", "version_id": ""},
                ),
                mock.patch(
                    "services.storage_backends.listdir",
                    side_effect=[
                        {
                            "items": [
                                {
                                    "type": "dir",
                                    "path": "folder/nested",
                                    "etag": "",
                                    "version_id": "",
                                },
                                {
                                    "type": "file",
                                    "path": "folder/note.txt",
                                    "size": 8,
                                    "etag": '"listed-child"',
                                    "version_id": "",
                                },
                            ]
                        },
                        {"items": []},
                    ],
                ),
                mock.patch(
                    "services.storage_backends.download",
                    side_effect=download_child,
                ),
                mock.patch(
                    "services.storage_backends.s3_locations.directory_marker_metadata",
                    side_effect=marker,
                    create=True,
                ),
            ):
                result = storage_backends.materialize(row, "folder", target)

        child = next(item for item in result["manifest"] if item["type"] == "file")
        self.assertEqual(child["etag"], '"head-child"')
        self.assertEqual(child["version_id"], "head-child-version")
        self.assertEqual(
            [entry["path"] for entry in result["directory_markers"]],
            ["folder", "folder/nested"],
        )
        self.assertTrue(
            all(
                entry["version_id"].endswith("-marker-version")
                for entry in result["directory_markers"]
            )
        )

    def test_delete_tree_exact_deletes_an_operation_owned_s3_file_version(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        expected = {"kind": "file", "size": 5, "count": 1, "checksum": "abc"}
        verified = {
            **expected,
            "type": "file",
            "etag": '"newer"',
            "version_id": "newer-version",
        }
        with (
            mock.patch(
                "services.storage_backends.s3_locations.delete_owned_version"
            ) as exact_delete,
            mock.patch("services.storage_backends.s3_locations.delete") as generic_delete,
        ):
            storage_backends.delete_tree(
                row,
                "published.txt",
                expected=expected,
                expected_etag='"owned"',
                version_id="owned-version",
                verified_meta=verified,
                operation_id="undo-owned",
                owned_version=True,
            )

        exact_delete.assert_called_once_with(
            row,
            "published.txt",
            expected_etag='"owned"',
            version_id="owned-version",
        )
        generic_delete.assert_not_called()

    def test_incomplete_local_upload_release_preserves_unattributed_partial(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "source.txt"
            source.write_text("keep source", encoding="utf-8")
            storage_root = root / "storage"
            storage_root.mkdir()
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(storage_root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            storage_backends._write_operation_receipt(  # noqa: SLF001 - ownership fixture
                row,
                "published.txt",
                operation_id,
                expected,
            )
            partial = storage_backends.local_path(
                row,
                storage_backends._operation_partial_path("published.txt", operation_id),
            )
            partial.write_text("private partial", encoding="utf-8")
            receipt = storage_backends.local_path(
                row,
                storage_backends._operation_receipt_path("published.txt", operation_id),
            )

            storage_backends.release_incomplete_operation_upload(
                row,
                "published.txt",
                operation_id,
                expected,
            )

            self.assertTrue(partial.exists())
            self.assertFalse(receipt.exists())
            self.assertEqual(source.read_text(encoding="utf-8"), "keep source")
            self.assertFalse((storage_root / "published.txt").exists())

    def test_local_delete_rechecks_the_atomically_quarantined_source(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "note.txt"
            source.write_text("original", encoding="utf-8")
            expected = file_operations.fingerprint(source)
            row = SimpleNamespace(kind="local", access="managed", root_path=str(root), id="local")

            def stale_snapshot(_row, _path, destination, **_kwargs):
                shutil.copy2(source, destination)
                source.write_text("newer bytes", encoding="utf-8")
                return {**expected, "etag": "", "version_id": ""}

            with mock.patch(
                "services.storage_backends.materialize",
                side_effect=stale_snapshot,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "source changed",
                ):
                    storage_backends.delete_tree(row, "note.txt", expected=expected)
            self.assertEqual(source.read_text(encoding="utf-8"), "newer bytes")

    def test_local_delete_does_not_adopt_a_same_byte_replacement_after_validation(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "note.txt"
            source.write_text("same bytes, different owner", encoding="utf-8")
            row = SimpleNamespace(kind="local", access="managed", root_path=str(root), id="local")
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            verified = storage_backends.materialize(
                row,
                "note.txt",
                root / "verified-note.txt",
            )
            original_same = storage_backends._same_local_path_receipt_identity
            replacement_inode = 0

            def replace_after_validation(path, metadata):
                nonlocal replacement_inode
                result = original_same(path, metadata)
                if result and not replacement_inode:
                    replacement = root / "same-byte-replacement.tmp"
                    replacement.write_text("same bytes, different owner", encoding="utf-8")
                    replacement_inode = replacement.stat().st_ino
                    replacement.replace(source)
                return result

            with mock.patch(
                "services.storage_backends._same_local_path_receipt_identity",
                side_effect=replace_after_validation,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "source identity changed",
                ):
                    storage_backends.delete_tree(
                        row,
                        "note.txt",
                        expected=expected,
                        verified_meta=verified,
                        operation_id=operation_id,
                    )

            self.assertTrue(source.exists())
            self.assertEqual(source.stat().st_ino, replacement_inode)
            self.assertEqual(source.read_text(encoding="utf-8"), "same bytes, different owner")

    def test_local_delete_restart_restores_a_quarantined_same_byte_replacement(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "note.txt"
            source.write_text("same bytes, different owner", encoding="utf-8")
            row = SimpleNamespace(kind="local", access="managed", root_path=str(root), id="local")
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            verified = storage_backends.materialize(
                row,
                "note.txt",
                root / "verified-note.txt",
            )
            original_same = storage_backends._same_local_path_receipt_identity
            original_identity = file_operations._local_publication_identity
            replacement_inode = 0

            def replace_after_validation(path, metadata):
                nonlocal replacement_inode
                result = original_same(path, metadata)
                if result and not replacement_inode:
                    replacement = root / "same-byte-replacement.tmp"
                    replacement.write_text("same bytes, different owner", encoding="utf-8")
                    replacement_inode = replacement.stat().st_ino
                    replacement.replace(source)
                return result

            def exit_after_quarantine_rename(path):
                if ".alles-delete-" in Path(path).name:
                    raise SystemExit("simulated process exit after quarantine rename")
                return original_identity(path)

            with (
                mock.patch(
                    "services.storage_backends._same_local_path_receipt_identity",
                    side_effect=replace_after_validation,
                ),
                mock.patch(
                    "services.file_operations._local_publication_identity",
                    side_effect=exit_after_quarantine_rename,
                ),
            ):
                with self.assertRaisesRegex(SystemExit, "simulated process exit"):
                    storage_backends.delete_tree(
                        row,
                        "note.txt",
                        expected=expected,
                        verified_meta=verified,
                        operation_id=operation_id,
                    )

            quarantines = list(root.glob(".alles-delete-*"))
            self.assertFalse(source.exists())
            self.assertEqual(len(quarantines), 1)
            self.assertEqual(quarantines[0].stat().st_ino, replacement_inode)

            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "source identity changed",
            ):
                storage_backends.delete_tree(
                    row,
                    "note.txt",
                    expected=expected,
                    verified_meta=verified,
                    operation_id=operation_id,
                )

            self.assertTrue(source.exists())
            self.assertEqual(source.stat().st_ino, replacement_inode)
            self.assertFalse(quarantines[0].exists())

    def test_local_delete_restores_quarantine_when_identity_read_raises(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "note.txt"
            source.write_text("restore after identity error", encoding="utf-8")
            row = SimpleNamespace(kind="local", access="managed", root_path=str(root), id="local")
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            verified = storage_backends.materialize(
                row,
                "note.txt",
                root / "verified-note.txt",
            )
            original_identity = file_operations._local_publication_identity

            def fail_for_quarantine(path):
                if ".alles-delete-" in Path(path).name:
                    raise file_operations.FileOperationError("identity read failed")
                return original_identity(path)

            with mock.patch(
                "services.file_operations._local_publication_identity",
                side_effect=fail_for_quarantine,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "source identity changed",
                ):
                    storage_backends.delete_tree(
                        row,
                        "note.txt",
                        expected=expected,
                        verified_meta=verified,
                        operation_id=operation_id,
                    )

            self.assertTrue(source.exists())
            self.assertEqual(source.read_text(encoding="utf-8"), "restore after identity error")

    def test_local_delete_recovers_an_interrupted_stable_quarantine(self):
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            source = root / "note.txt"
            source.write_text("private bytes", encoding="utf-8")
            row = SimpleNamespace(
                kind="local",
                access="managed",
                root_path=str(root),
                id="local",
            )
            operation_id = str(uuid.uuid4())
            expected = file_operations.fingerprint(source)
            verified = storage_backends.materialize(
                row,
                "note.txt",
                root / "verified-note.txt",
            )
            original_unlink = Path.unlink

            def interrupt_unlink(path, *args, **kwargs):
                if ".alles-delete-" in path.name:
                    raise OSError("interrupted delete")
                return original_unlink(path, *args, **kwargs)

            with mock.patch.object(Path, "unlink", autospec=True, side_effect=interrupt_unlink):
                with self.assertRaisesRegex(OSError, "interrupted delete"):
                    storage_backends.delete_tree(
                        row,
                        "note.txt",
                        expected=expected,
                        verified_meta=verified,
                        operation_id=operation_id,
                    )

            self.assertFalse(source.exists())
            quarantines = list(root.glob(".alles-delete-*"))
            self.assertEqual(len(quarantines), 1)

            storage_backends.delete_tree(
                row,
                "note.txt",
                expected=expected,
                verified_meta=verified,
                operation_id=operation_id,
            )

            self.assertFalse(source.exists())
            self.assertFalse(quarantines[0].exists())

    def test_s3_tree_delete_removes_the_directory_marker(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        with (
            mock.patch(
                "services.storage_backends.item",
                return_value={"type": "dir", "etag": "", "version_id": ""},
            ),
            mock.patch(
                "services.storage_backends.listdir",
                return_value={"items": []},
            ),
            mock.patch(
                "services.storage_backends.s3_locations.delete_directory_marker"
            ) as delete_marker,
        ):
            storage_backends.delete_tree(row, "folder")

        delete_marker.assert_called_once_with(row, "folder")

    def test_s3_tree_delete_refuses_a_versioned_marker_before_any_delete(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        expected = {"kind": "dir", "size": 0, "count": 0, "checksum": "empty"}
        marker = {
            "path": "folder",
            "etag": '"marker"',
            "version_id": "marker-version",
        }
        verified = {
            **expected,
            "type": "dir",
            "etag": "",
            "version_id": "",
            "manifest": [],
            "directory_markers": [marker],
        }
        with (
            mock.patch(
                "services.storage_backends.listdir",
                return_value={"items": []},
            ),
            mock.patch(
                "services.storage_backends.s3_locations.directory_marker_metadata",
                return_value=marker,
            ),
            mock.patch("services.storage_backends.s3_locations.delete") as delete,
            mock.patch(
                "services.storage_backends.s3_locations.delete_directory_marker"
            ) as delete_marker,
        ):
            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "versioned s3 objects",
            ):
                storage_backends.delete_tree(
                    row,
                    "folder",
                    expected=expected,
                    verified_meta=verified,
                )

        delete.assert_not_called()
        delete_marker.assert_not_called()

    def test_s3_tree_delete_leaves_a_marker_absent_from_the_verified_manifest(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        expected = {"kind": "dir", "size": 0, "count": 0, "checksum": "empty"}
        verified = {
            **expected,
            "type": "dir",
            "etag": "",
            "version_id": "",
            "manifest": [],
            "directory_markers": [],
        }
        with (
            mock.patch("services.storage_backends.listdir", return_value={"items": []}),
            mock.patch(
                "services.storage_backends.s3_locations.directory_marker_metadata",
                return_value=None,
            ),
            mock.patch("services.storage_backends.s3_locations.delete") as delete,
            mock.patch(
                "services.storage_backends.s3_locations.delete_directory_marker"
            ) as delete_marker,
        ):
            storage_backends.delete_tree(
                row,
                "folder",
                expected=expected,
                verified_meta=verified,
            )

        delete.assert_not_called()
        delete_marker.assert_not_called()

    def test_s3_tree_delete_conditionally_rechecks_a_verified_marker(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        expected = {"kind": "dir", "size": 0, "count": 0, "checksum": "empty"}
        marker = {"path": "folder", "etag": '"old-marker"', "version_id": ""}
        verified = {
            **expected,
            "type": "dir",
            "etag": "",
            "version_id": "",
            "manifest": [],
            "directory_markers": [marker],
        }
        with (
            mock.patch("services.storage_backends.listdir", return_value={"items": []}),
            mock.patch(
                "services.storage_backends.s3_locations.directory_marker_metadata",
                return_value=marker,
            ),
            mock.patch(
                "services.storage_backends.s3_locations.delete",
                side_effect=storage_backends.s3_locations.S3LocationError("remote file changed"),
            ) as delete,
            mock.patch(
                "services.storage_backends.s3_locations.delete_directory_marker"
            ) as delete_marker,
        ):
            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "remote file changed",
            ):
                storage_backends.delete_tree(
                    row,
                    "folder",
                    expected=expected,
                    verified_meta=verified,
                )

        delete.assert_called_once_with(
            row,
            "folder",
            expected_etag='"old-marker"',
            version_id="",
            directory=True,
        )
        delete_marker.assert_not_called()

    def test_s3_tree_delete_removes_nested_directory_markers_deepest_first(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")

        def children(_row, path):
            return {
                "folder": {
                    "items": [
                        {"type": "dir", "path": "folder/child"},
                        {"type": "file", "path": "folder/root.txt", "etag": "root"},
                    ]
                },
                "folder/child": {
                    "items": [
                        {"type": "dir", "path": "folder/child/deep"},
                        {"type": "file", "path": "folder/child/a.txt", "etag": "a"},
                    ]
                },
                "folder/child/deep": {"items": []},
            }[path]

        with (
            mock.patch(
                "services.storage_backends.item",
                return_value={"type": "dir", "etag": "", "version_id": ""},
            ),
            mock.patch("services.storage_backends.listdir", side_effect=children),
            mock.patch("services.storage_backends.s3_locations.delete"),
            mock.patch(
                "services.storage_backends.s3_locations.delete_directory_marker"
            ) as delete_marker,
        ):
            storage_backends.delete_tree(row, "folder")

        self.assertEqual(
            [call.args[1] for call in delete_marker.call_args_list],
            ["folder/child/deep", "folder/child", "folder"],
        )

    def test_s3_tree_delete_stops_when_an_unverified_object_appears(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "expected"
            source.mkdir()
            (source / "old.txt").write_text("old", encoding="utf-8")
            expected = file_operations.fingerprint(source)

            def verified_materialize(_row, _path, destination, **_kwargs):
                shutil.copytree(source, destination)
                return {
                    "type": "dir",
                    "manifest": [
                        {
                            "type": "file",
                            "path": "folder/old.txt",
                            "etag": "old-etag",
                            "version_id": "old-version",
                        }
                    ],
                }

            with (
                mock.patch(
                    "services.storage_backends.materialize",
                    side_effect=verified_materialize,
                ),
                mock.patch(
                    "services.storage_backends.listdir",
                    return_value={
                        "items": [
                            {
                                "type": "file",
                                "path": "folder/new.txt",
                                "etag": "new-etag",
                                "version_id": "new-version",
                            }
                        ]
                    },
                ),
                mock.patch("services.storage_backends.s3_locations.delete") as delete,
                mock.patch("services.storage_backends.s3_locations.delete_directory_marker"),
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "source changed",
                ):
                    storage_backends.delete_tree(row, "folder", expected=expected)

        delete.assert_not_called()

    def test_s3_tree_delete_retries_a_verified_manifest_after_partial_success(self):
        row = SimpleNamespace(kind="s3", access="managed", id="remote")
        expected = {"kind": "dir", "size": 6, "count": 2, "checksum": "verified"}
        verified = {
            **expected,
            "type": "dir",
            "etag": "folder-etag",
            "version_id": "folder-version",
            "manifest": [
                {"type": "file", "path": "folder/first.txt", "etag": "first"},
                {"type": "file", "path": "folder/second.txt", "etag": "second"},
            ],
        }
        deleted = []

        def delete(_row, path, **_kwargs):
            deleted.append(path)
            if path == "folder/first.txt":
                raise storage_backends.s3_locations.S3NotFoundError("already deleted")

        with (
            mock.patch(
                "services.storage_backends.materialize",
                side_effect=AssertionError("retry must use the persisted verified manifest"),
            ),
            mock.patch("services.storage_backends.s3_locations.delete", side_effect=delete),
            mock.patch("services.storage_backends.s3_locations.delete_directory_marker"),
            mock.patch(
                "services.storage_backends.listdir",
                side_effect=[
                    {
                        "items": [
                            {
                                "type": "file",
                                "path": "folder/second.txt",
                                "etag": "second",
                            }
                        ]
                    },
                    {"items": []},
                ],
            ),
        ):
            storage_backends.delete_tree(
                row,
                "folder",
                expected=expected,
                verified_meta=verified,
            )

        self.assertEqual(deleted, ["folder/second.txt", "folder/first.txt"])

    def test_webdav_tree_delete_refuses_an_unsafe_collection_delete(self):
        row = SimpleNamespace(kind="webdav", access="managed", id="remote")
        with tempfile.TemporaryDirectory() as root_text:
            source = Path(root_text) / "expected"
            source.mkdir()
            (source / "old.txt").write_text("old", encoding="utf-8")
            expected = file_operations.fingerprint(source)

            def verified_materialize(_row, _path, destination, **_kwargs):
                shutil.copytree(source, destination)
                return {
                    "type": "dir",
                    "etag": "folder-etag",
                    "manifest": [
                        {
                            "type": "file",
                            "path": "folder/old.txt",
                            "etag": "old-etag",
                        }
                    ],
                }

            with (
                mock.patch(
                    "services.storage_backends.materialize",
                    side_effect=verified_materialize,
                ),
                mock.patch(
                    "services.storage_backends._raw_listdir",
                    return_value={
                        "items": [
                            {
                                "type": "file",
                                "path": "folder/new.txt",
                                "etag": "new-etag",
                            }
                        ]
                    },
                ),
                mock.patch("services.storage_backends.webdav_locations.delete") as delete,
            ):
                with self.assertRaisesRegex(
                    storage_backends.StorageBackendError,
                    "folder deletion",
                ):
                    storage_backends.delete_tree(row, "folder", expected=expected)

        delete.assert_not_called()

    def test_verified_webdav_delete_recovery_accepts_an_already_missing_file(self):
        row = SimpleNamespace(kind="webdav", access="managed", id="remote")
        expected = {"kind": "file", "size": 4, "count": 1, "checksum": "safe"}
        verified = {
            **expected,
            "type": "file",
            "etag": '"verified"',
            "version_id": "",
        }
        with mock.patch(
            "services.storage_backends.webdav_locations.delete",
            side_effect=storage_backends.webdav_locations.WebDAVNotFoundError(
                "webdav delete failed with status 404"
            ),
        ):
            storage_backends.delete_tree(
                row,
                "gone.txt",
                expected=expected,
                verified_meta=verified,
            )

    def test_unverified_webdav_delete_does_not_swallow_a_missing_file(self):
        row = SimpleNamespace(kind="webdav", access="managed", id="remote")
        with (
            mock.patch(
                "services.storage_backends.item",
                return_value={"type": "file", "etag": '"verified"'},
            ),
            mock.patch(
                "services.storage_backends.webdav_locations.delete",
                side_effect=storage_backends.webdav_locations.WebDAVNotFoundError(
                    "webdav delete failed with status 404"
                ),
            ),
        ):
            with self.assertRaisesRegex(
                storage_backends.StorageBackendError,
                "status 404",
            ):
                storage_backends.delete_tree(row, "gone.txt")

    def test_unverified_missing_remote_source_honors_missing_ok(self):
        for kind in ("webdav", "s3"):
            with self.subTest(kind=kind):
                row = SimpleNamespace(kind=kind, access="managed", id="remote")
                with (
                    mock.patch(
                        "services.storage_backends.item",
                        side_effect=storage_backends.StorageNotFoundError("missing"),
                    ),
                    mock.patch(
                        "services.storage_backends.webdav_locations.delete"
                    ) as webdav_delete,
                    mock.patch("services.storage_backends.s3_locations.delete") as s3_delete,
                ):
                    storage_backends.delete_tree(row, "gone.txt", missing_ok=True)

                webdav_delete.assert_not_called()
                s3_delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
