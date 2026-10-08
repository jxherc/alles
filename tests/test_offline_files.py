import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from core.database import FileOperationPathClaim, OfflineFile, StorageLocation
from services import internal_paths, offline_files
from tests._client import ApiTest


class OfflineFilesTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.cache = Path(self.temp.name) / "cache"
        self.root.mkdir()
        self.cache.mkdir()
        db = self.db()
        db.add(
            StorageLocation(
                id="local",
                name="local",
                kind="local",
                access="managed",
                root_path=str(self.root),
                enabled=True,
            )
        )
        db.commit()
        db.close()
        self.cache_patch = mock.patch.object(offline_files, "cache_root", lambda: self.cache)
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.temp.cleanup()
        super().tearDown()

    def test_file_available_offline_is_verified_and_removable(self):
        (self.root / "note.txt").write_text("offline", "utf-8")
        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "note.txt"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["state"], "ready")
        self.assertEqual(body["size"], 7)
        self.assertTrue(body["cache_only"])
        self.assertFalse(body["is_backup"])
        raw = self.client.get(
            "/api/files/offline/raw", params={"location_id": "local", "path": "note.txt"}
        )
        self.assertEqual(raw.status_code, 200, raw.text)
        self.assertEqual(raw.content, b"offline")

        removed = self.client.request(
            "DELETE",
            "/api/files/offline",
            json={"location_id": "local", "path": "note.txt"},
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_windows_local_offline_copy_fails_before_creating_state(self):
        (self.root / "note.txt").write_text("offline", "utf-8")
        db = self.db()
        with (
            mock.patch.object(offline_files, "_safe_local_copy_supported", return_value=False),
            self.assertRaisesRegex(offline_files.OfflineFileError, "unavailable on Windows"),
        ):
            offline_files.enable(db, location_id="local", path="note.txt")

        self.assertEqual(db.query(OfflineFile).count(), 0)
        db.close()

    def test_local_offline_copy_rejects_every_symlink_component(self):
        private = Path(self.temp.name) / "private"
        private.mkdir()
        (private / "secret.txt").write_text("private", "utf-8")
        (self.root / "alias").symlink_to(private, target_is_directory=True)

        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "alias/secret.txt"}
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("symbolic links", response.json()["detail"])
        self.assertFalse(any(path.is_file() for path in self.cache.rglob("*")))

    def test_local_offline_copy_rejects_a_fifo_without_blocking(self):
        fifo = self.root / "stream.pipe"
        os.mkfifo(fifo)

        with self.assertRaisesRegex(offline_files.OfflineFileError, "regular file"):
            offline_files._open_local_source(self.root, fifo.resolve())

        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": fifo.name}
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn(
            response.json()["detail"], {"source not found", "offline source is not a regular file"}
        )
        self.assertFalse(any(path.is_file() for path in self.cache.rglob("*")))

    def test_local_directory_cannot_recursively_copy_its_offline_cache(self):
        container = self.root / "container"
        nested_cache = container / "offline-files"
        nested_cache.mkdir(parents=True)
        (container / "note.txt").write_text("owner data", "utf-8")

        with mock.patch.object(offline_files, "cache_root", lambda: nested_cache):
            response = self.client.post(
                "/api/files/offline",
                json={"location_id": "local", "path": "container"},
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("cannot contain the offline cache", response.json()["detail"])
        self.assertFalse(any(path.name.endswith(".partial") for path in nested_cache.iterdir()))

    def test_raw_offline_file_keeps_the_requested_media_type(self):
        (self.root / "photo.png").write_bytes(b"not-a-real-png")
        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "photo.png"}
        )
        self.assertEqual(response.status_code, 200, response.text)

        raw = self.client.get(
            "/api/files/offline/raw", params={"location_id": "local", "path": "photo.png"}
        )

        self.assertEqual(raw.status_code, 200, raw.text)
        self.assertEqual(raw.headers["content-type"], "image/png")

    def test_raw_offline_active_content_is_forced_to_download(self):
        for name, content in (
            ("page.html", b"<script>top.fetch('/api/settings')</script>"),
            ("image.svg", b"<svg onload=\"top.fetch('/api/settings')\"></svg>"),
            ("feed.atom", b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'),
        ):
            with self.subTest(name=name):
                (self.root / name).write_bytes(content)
                enabled = self.client.post(
                    "/api/files/offline", json={"location_id": "local", "path": name}
                )
                self.assertEqual(enabled.status_code, 200, enabled.text)

                raw = self.client.get(
                    "/api/files/offline/raw",
                    params={"location_id": "local", "path": name},
                )

                self.assertEqual(raw.status_code, 200, raw.text)
                self.assertEqual(raw.headers["content-type"], "application/octet-stream")
                self.assertTrue(raw.headers["content-disposition"].startswith("attachment;"))
                self.assertEqual(raw.headers["x-content-type-options"], "nosniff")

    def test_disable_keeps_recovery_row_when_cache_removal_fails(self):
        folder = self.root / "folder"
        folder.mkdir()
        (folder / "note.txt").write_text("offline", "utf-8")
        enabled = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "folder"}
        )
        self.assertEqual(enabled.status_code, 200, enabled.text)
        db = self.db()
        enabled_row = db.get(OfflineFile, enabled.json()["id"])
        target = self.cache / enabled_row.cache_name
        db.close()
        original_rmtree = shutil.rmtree

        def fail_target(path, *args, **kwargs):
            if Path(path).resolve() == target.resolve():
                raise OSError("disk refused removal")
            return original_rmtree(path, *args, **kwargs)

        with mock.patch("services.offline_files.shutil.rmtree", side_effect=fail_target):
            removed = self.client.request(
                "DELETE",
                "/api/files/offline",
                json={"location_id": "local", "path": "folder"},
            )

        self.assertEqual(removed.status_code, 409, removed.text)
        self.assertTrue(target.exists())
        db = self.db()
        row = db.get(OfflineFile, enabled.json()["id"])
        self.assertIsNotNone(row)
        self.assertEqual(row.state, "deleting")
        db.close()

    def test_disable_uses_the_same_canonical_path_as_enable(self):
        folder = self.root / "folder"
        folder.mkdir()
        (folder / "note.txt").write_text("offline", "utf-8")
        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "folder/note.txt"}
        )
        self.assertEqual(response.status_code, 200, response.text)

        removed = self.client.request(
            "DELETE",
            "/api/files/offline",
            json={"location_id": "local", "path": "folder/./note.txt"},
        )

        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_disable_survives_a_disabled_location_but_enable_does_not(self):
        (self.root / "note.txt").write_text("offline", "utf-8")
        db = self.db()
        enabled = offline_files.enable(db, location_id="local", path="note.txt")
        location = db.get(StorageLocation, "local")
        location.enabled = False
        db.commit()

        with self.assertRaisesRegex(RuntimeError, "disabled"):
            offline_files.enable(db, location_id="local", path="another.txt")

        original_disable = offline_files._disable_claimed

        def disable_with_claim(*args, **kwargs):
            self.assertEqual(db.query(FileOperationPathClaim).count(), 1)
            return original_disable(*args, **kwargs)

        with mock.patch.object(
            offline_files,
            "_disable_claimed",
            side_effect=disable_with_claim,
        ):
            offline_files.disable(db, db.get(OfflineFile, enabled.id))

        self.assertEqual(list(self.cache.iterdir()), [])
        self.assertIsNone(db.get(OfflineFile, enabled.id))
        self.assertEqual(db.query(FileOperationPathClaim).count(), 0)
        db.close()

    def test_disable_removes_retained_remote_resume_artifacts(self):
        db = self.db()
        row = OfflineFile(
            id="resume-offline",
            location_id="local",
            normalized_path="note.txt",
            state="failed",
            cache_name="resume-cache",
        )
        db.add(row)
        db.commit()
        target = self.cache / row.cache_name
        incoming = self.cache / f".{target.name}.{row.id}.incoming"
        partial = internal_paths.artifact_sibling(incoming, "download", suffix=".partial")
        identity = internal_paths.artifact_sibling(incoming, "download", suffix=".json")
        partial.write_bytes(b"retained download")
        identity.write_text('{"etag":"v1"}', encoding="utf-8")

        offline_files.disable(db, row)

        self.assertEqual(list(self.cache.iterdir()), [])
        db.close()

    def test_disable_rejects_a_refresh_in_progress_without_removing_cache(self):
        db = self.db()
        row = OfflineFile(
            id="refresh-owned",
            location_id="local",
            normalized_path="note.txt",
            state="syncing",
            cache_name="refresh-cache",
        )
        db.add(row)
        db.commit()
        target = self.cache / row.cache_name
        previous = self.cache / f".{target.name}.{row.id}.previous"
        target.write_bytes(b"refresh candidate")
        previous.write_bytes(b"last verified copy")

        with self.assertRaisesRegex(offline_files.OfflineFileError, "still syncing"):
            offline_files.disable(db, row)

        db.refresh(row)
        self.assertEqual(row.state, "syncing")
        self.assertEqual(target.read_bytes(), b"refresh candidate")
        self.assertEqual(previous.read_bytes(), b"last verified copy")
        db.close()

    def test_folder_offline_copy_serves_nested_file(self):
        folder = self.root / "folder"
        folder.mkdir()
        (folder / "nested.txt").write_text("nested", "utf-8")
        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "folder"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        raw = self.client.get(
            "/api/files/offline/raw",
            params={"location_id": "local", "path": "folder/nested.txt"},
        )
        self.assertEqual(raw.content, b"nested")
        listed = self.client.get("/api/files/offline", params={"location_id": "local"}).json()
        self.assertEqual(listed["items"][0]["type"], "dir")

    def test_folder_offline_copy_never_follows_an_external_symlink(self):
        folder = self.root / "folder"
        folder.mkdir()
        external = Path(self.temp.name) / "private.txt"
        external.write_text("must stay outside the cache", "utf-8")
        (folder / "escape.txt").symlink_to(external)

        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "folder"}
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertNotIn(
            "must stay outside",
            "".join(
                path.read_text("utf-8", errors="ignore")
                for path in self.cache.rglob("*")
                if path.is_file() and not path.is_symlink()
            ),
        )

    def test_folder_offline_copy_never_follows_a_nested_directory_symlink(self):
        folder = self.root / "folder-link"
        folder.mkdir()
        external = Path(self.temp.name) / "private-folder"
        external.mkdir()
        (external / "secret.txt").write_text("must stay outside the cache", "utf-8")
        (folder / "escape").symlink_to(external, target_is_directory=True)

        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "folder-link"}
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(any(path.name == "secret.txt" for path in self.cache.rglob("*")))

    def test_folder_copy_opens_each_file_nonblocking_before_type_verification(self):
        folder = self.root / "nonblocking"
        folder.mkdir()
        (folder / "note.txt").write_text("safe", "utf-8")
        target = self.cache / "copy"
        real_open = os.open
        observed_flags: list[int] = []

        def observe_open(path, flags, *args, **kwargs):
            if path == "note.txt":
                observed_flags.append(flags)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(offline_files.os, "open", side_effect=observe_open):
            offline_files._copy_local_tree(
                self.root.resolve(), folder.resolve(), target, lambda: None
            )

        self.assertEqual((target / "note.txt").read_text("utf-8"), "safe")
        self.assertTrue(observed_flags)
        self.assertTrue(all(flags & os.O_NONBLOCK for flags in observed_flags))

    def test_cached_folder_can_be_browsed_and_read_after_the_live_source_disappears(self):
        folder = self.root / "folder"
        nested = folder / "nested"
        nested.mkdir(parents=True)
        (nested / "note.txt").write_text("cached only", "utf-8")
        response = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "folder"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        shutil.rmtree(folder)

        root_listing = self.client.get(
            "/api/files/offline/list",
            params={"location_id": "local", "path": "folder"},
        )
        self.assertEqual(root_listing.status_code, 200, root_listing.text)
        self.assertEqual(root_listing.json()["items"][0]["path"], "folder/nested")
        self.assertTrue(root_listing.json()["items"][0]["cache_only"])

        nested_listing = self.client.get(
            "/api/files/offline/list",
            params={"location_id": "local", "path": "folder/nested"},
        )
        self.assertEqual(nested_listing.status_code, 200, nested_listing.text)
        self.assertEqual(nested_listing.json()["items"][0]["path"], "folder/nested/note.txt")

        read = self.client.get(
            "/api/files/offline/read",
            params={"location_id": "local", "path": "folder/nested/note.txt"},
        )
        self.assertEqual(read.status_code, 200, read.text)
        self.assertTrue(read.json()["is_text"])
        self.assertEqual(read.json()["content"], "cached only")

        raw = self.client.get(
            "/api/files/offline/raw",
            params={"location_id": "local", "path": "folder/nested/note.txt"},
        )
        self.assertEqual(raw.status_code, 200, raw.text)
        self.assertEqual(raw.content, b"cached only")

    def test_listing_does_not_recover_a_live_sync(self):
        db = self.db()
        row = OfflineFile(
            id="live-sync",
            location_id="local",
            normalized_path="note.txt",
            state="syncing",
            cache_name="live-cache",
        )
        db.add(row)
        db.commit()
        db.close()

        with mock.patch("routes.offline_files.offline_files.recover_interrupted") as recover:
            response = self.client.get("/api/files/offline", params={"location_id": "local"})

        self.assertEqual(response.status_code, 200, response.text)
        recover.assert_not_called()
        db = self.db()
        self.assertEqual(db.get(OfflineFile, "live-sync").state, "syncing")
        db.close()

    def test_enable_rejects_an_offline_copy_that_already_has_an_owner(self):
        (self.root / "note.txt").write_text("source", encoding="utf-8")
        db = self.db()
        row = OfflineFile(
            id="owned-sync",
            location_id="local",
            normalized_path="note.txt",
            state="syncing",
            cache_name="owned-cache",
        )
        db.add(row)
        db.commit()
        partial = self.cache / ".owned-cache.owned-sync.partial"
        partial.write_bytes(b"first owner")

        with mock.patch.object(offline_files, "_copy_to_cache") as copy:
            with self.assertRaisesRegex(offline_files.OfflineFileError, "already running"):
                offline_files.enable(db, location_id="local", path="note.txt")

        copy.assert_not_called()
        self.assertEqual(partial.read_bytes(), b"first owner")
        db.close()

    def test_no_space_failure_keeps_source_and_records_failure(self):
        (self.root / "large.bin").write_bytes(b"0123456789")
        usage = mock.Mock(total=10, used=9, free=1)
        with mock.patch("services.offline_files.shutil.disk_usage", return_value=usage):
            response = self.client.post(
                "/api/files/offline", json={"location_id": "local", "path": "large.bin"}
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual((self.root / "large.bin").read_bytes(), b"0123456789")
        db = self.db()
        row = db.query(OfflineFile).one()
        self.assertEqual(row.state, "failed")
        self.assertIn("not enough space", row.error_code)
        db.close()

    def test_refresh_checks_space_before_copying_the_ready_cache(self):
        source = self.root / "refresh.bin"
        source.write_bytes(b"first")
        first = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": source.name}
        )
        self.assertEqual(first.status_code, 200, first.text)
        source.write_bytes(b"replacement")
        usage = mock.Mock(total=10, used=6, free=4)

        with mock.patch("services.offline_files.shutil.disk_usage", return_value=usage):
            refresh = self.client.post(
                "/api/files/offline", json={"location_id": "local", "path": source.name}
            )

        self.assertEqual(refresh.status_code, 409, refresh.text)
        self.assertIn("recovery copy", refresh.json()["detail"])
        raw = self.client.get(
            "/api/files/offline/raw", params={"location_id": "local", "path": source.name}
        )
        self.assertEqual(raw.content, b"first")
        self.assertFalse(any(path.name.endswith(".previous") for path in self.cache.iterdir()))
        db = self.db()
        row = db.query(OfflineFile).one()
        self.assertEqual(row.state, "ready")
        self.assertIn("refresh_failed", row.error_code)
        db.close()

    def test_failed_refresh_keeps_last_verified_cache(self):
        source = self.root / "note.txt"
        source.write_text("first", "utf-8")
        first = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "note.txt"}
        )
        self.assertEqual(first.status_code, 200)
        source.unlink()
        refresh = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "note.txt"}
        )
        self.assertEqual(refresh.status_code, 409)
        raw = self.client.get(
            "/api/files/offline/raw", params={"location_id": "local", "path": "note.txt"}
        )
        self.assertEqual(raw.content, b"first")
        listed = self.client.get("/api/files/offline", params={"location_id": "local"}).json()
        self.assertEqual(listed["items"][0]["state"], "ready")
        self.assertIn("refresh_failed", listed["items"][0]["error_code"])

    def _remote(self):
        db = self.db()
        db.add(
            StorageLocation(
                id="remote",
                name="remote",
                kind="webdav",
                access="managed",
                endpoint="https://dav.example.test/files",
                enabled=True,
            )
        )
        db.commit()
        db.close()

    def test_remote_file_and_folder_can_be_made_available_offline(self):
        self._remote()
        listings = {
            "": {
                "items": [
                    {
                        "path": "remote.txt",
                        "normalized_path": "remote.txt",
                        "type": "file",
                        "size": 6,
                        "etag": '"r1"',
                    },
                    {
                        "path": "folder",
                        "normalized_path": "folder",
                        "type": "dir",
                        "size": 0,
                        "etag": "",
                    },
                ]
            },
            "folder": {
                "items": [
                    {
                        "path": "folder/nested.txt",
                        "normalized_path": "folder/nested.txt",
                        "type": "file",
                        "size": 6,
                        "etag": '"n1"',
                    }
                ]
            },
        }

        def download(_location, path, destination, **_kwargs):
            payload = b"remote" if path == "remote.txt" else b"nested"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            import hashlib

            return {
                "size": len(payload),
                "checksum": hashlib.sha256(payload).hexdigest(),
                "etag": '"saved"',
                "version_id": "version-1",
            }

        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                side_effect=lambda _location, path: listings[path],
            ),
            mock.patch(
                "services.offline_files.storage_backends.download",
                side_effect=download,
            ),
        ):
            file_response = self.client.post(
                "/api/files/offline", json={"location_id": "remote", "path": "remote.txt"}
            )
            folder_response = self.client.post(
                "/api/files/offline", json={"location_id": "remote", "path": "folder"}
            )
        self.assertEqual(file_response.status_code, 200, file_response.text)
        self.assertEqual(file_response.json()["version_id"], "version-1")
        self.assertEqual(folder_response.status_code, 200, folder_response.text)
        raw = self.client.get(
            "/api/files/offline/raw",
            params={"location_id": "remote", "path": "folder/nested.txt"},
        )
        self.assertEqual(raw.content, b"nested")

    def test_remote_file_checks_free_space_before_downloading(self):
        self._remote()
        listing = {
            "items": [
                {
                    "path": "large.bin",
                    "normalized_path": "large.bin",
                    "type": "file",
                    "size": 10,
                    "etag": '"large"',
                }
            ]
        }
        usage = mock.Mock(total=10, used=9, free=1)
        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                return_value=listing,
            ),
            mock.patch("services.offline_files.shutil.disk_usage", return_value=usage),
            mock.patch("services.offline_files.storage_backends.download") as download,
        ):
            response = self.client.post(
                "/api/files/offline",
                json={"location_id": "remote", "path": "large.bin"},
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("not enough space", response.json()["detail"])
        download.assert_not_called()

    def test_unknown_remote_file_size_uses_the_real_streaming_limit(self):
        self._remote()
        listing = {
            "items": [
                {
                    "path": "unknown.bin",
                    "normalized_path": "unknown.bin",
                    "type": "file",
                    "size": None,
                    "etag": '"unknown"',
                }
            ]
        }
        usage = mock.Mock(total=10, used=2, free=8)
        payload = b"abc"

        def download(_location, _path, destination, **kwargs):
            self.assertIsNone(kwargs["expected_size"])
            self.assertEqual(kwargs["max_bytes"], 8)
            destination.write_bytes(payload)
            import hashlib

            return {
                "size": len(payload),
                "checksum": hashlib.sha256(payload).hexdigest(),
                "etag": '"unknown"',
            }

        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                return_value=listing,
            ),
            mock.patch("services.offline_files.shutil.disk_usage", return_value=usage),
            mock.patch(
                "services.offline_files.storage_backends.download",
                side_effect=download,
            ),
        ):
            response = self.client.post(
                "/api/files/offline",
                json={"location_id": "remote", "path": "unknown.bin"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["size"], len(payload))

    def test_unknown_remote_folder_sizes_are_bounded_and_zero_stays_exact(self):
        self._remote()
        listings = {
            "": {
                "items": [
                    {
                        "path": "folder",
                        "normalized_path": "folder",
                        "type": "dir",
                        "size": 0,
                        "etag": "",
                    }
                ]
            },
            "folder": {
                "items": [
                    {
                        "path": "folder/unknown.bin",
                        "normalized_path": "folder/unknown.bin",
                        "type": "file",
                        "size": None,
                        "etag": '"unknown"',
                    },
                    {
                        "path": "folder/empty.bin",
                        "normalized_path": "folder/empty.bin",
                        "type": "file",
                        "size": 0,
                        "etag": '"empty"',
                    },
                ]
            },
        }
        usage = mock.Mock(total=10, used=0, free=10)
        calls = []

        def download(_location, path, destination, **kwargs):
            payload = b"abc" if path.endswith("unknown.bin") else b""
            if path.endswith("unknown.bin"):
                self.assertIsNone(kwargs["expected_size"])
                self.assertEqual(kwargs["max_bytes"], 10)
            else:
                self.assertEqual(kwargs["expected_size"], 0)
                self.assertEqual(kwargs["max_bytes"], 0)
            destination.write_bytes(payload)
            calls.append(path)
            return {"size": len(payload), "checksum": "", "etag": kwargs["expected_etag"]}

        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                side_effect=lambda _location, path: listings[path],
            ),
            mock.patch("services.offline_files.shutil.disk_usage", return_value=usage),
            mock.patch(
                "services.offline_files.storage_backends.download",
                side_effect=download,
            ),
        ):
            response = self.client.post(
                "/api/files/offline",
                json={"location_id": "remote", "path": "folder"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["size"], 3)
        self.assertEqual(calls, ["folder/unknown.bin", "folder/empty.bin"])
        db = self.db()
        empty = offline_files.resolve_cached(
            db,
            location_id="remote",
            path="folder/empty.bin",
        )
        db.close()
        self.assertIsNotNone(empty)
        self.assertEqual(empty.read_bytes(), b"")

    def test_remote_file_enforces_advertised_and_actual_download_size(self):
        self._remote()
        listing = {
            "items": [
                {
                    "path": "bounded.bin",
                    "normalized_path": "bounded.bin",
                    "type": "file",
                    "size": 4,
                    "etag": '"bounded"',
                }
            ]
        }

        def oversized_download(_location, _path, destination, **kwargs):
            self.assertEqual(kwargs["expected_size"], 4)
            self.assertEqual(kwargs["max_bytes"], 4)
            destination.write_bytes(b"12345")
            return {"size": 5, "checksum": "ignored", "etag": '"bounded"'}

        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                return_value=listing,
            ),
            mock.patch(
                "services.offline_files.storage_backends.download",
                side_effect=oversized_download,
            ),
        ):
            response = self.client.post(
                "/api/files/offline",
                json={"location_id": "remote", "path": "bounded.bin"},
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("download size", response.json()["detail"])
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_remote_folder_rejects_a_per_file_checksum_mismatch(self):
        self._remote()
        listings = {
            "": {
                "items": [
                    {
                        "path": "folder",
                        "normalized_path": "folder",
                        "type": "dir",
                        "size": 0,
                        "etag": "",
                    }
                ]
            },
            "folder": {
                "items": [
                    {
                        "path": "folder/note.txt",
                        "normalized_path": "folder/note.txt",
                        "type": "file",
                        "size": 4,
                        "etag": '"v1"',
                    }
                ]
            },
        }

        def download(_location, _path, destination, **_kwargs):
            destination.write_bytes(b"safe")
            return {"size": 4, "checksum": "0" * 64, "etag": '"v1"'}

        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                side_effect=lambda _location, path: listings[path],
            ),
            mock.patch("services.offline_files.storage_backends.download", side_effect=download),
        ):
            response = self.client.post(
                "/api/files/offline", json={"location_id": "remote", "path": "folder"}
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("verification", response.json()["detail"])
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_unsynced_offline_size_remains_unknown(self):
        db = self.db()
        row = OfflineFile(
            location_id="local",
            normalized_path="unknown.txt",
            state="queued",
            cache_name="unknown-cache",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        self.assertIsNone(offline_files.public_dict(row)["size"])
        db.close()

    def test_verified_empty_offline_file_keeps_its_real_zero_size(self):
        db = self.db()
        row = OfflineFile(
            location_id="local",
            normalized_path="empty.txt",
            state="ready",
            cache_name="empty-cache",
            size=0,
            checksum="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        self.assertEqual(offline_files.public_dict(row)["size"], 0)
        db.close()

    def test_remote_offline_copy_preserves_empty_folders(self):
        self._remote()
        listings = {
            "": {
                "items": [
                    {
                        "path": "folder",
                        "normalized_path": "folder",
                        "type": "dir",
                        "size": 0,
                        "etag": "",
                    },
                ]
            },
            "folder": {
                "items": [
                    {
                        "path": "folder/empty",
                        "normalized_path": "folder/empty",
                        "type": "dir",
                        "size": 0,
                        "etag": "",
                    },
                ]
            },
            "folder/empty": {"items": []},
        }
        with mock.patch(
            "services.offline_files.storage_backends.listdir",
            side_effect=lambda _location, path: listings[path],
        ):
            response = self.client.post(
                "/api/files/offline", json={"location_id": "remote", "path": "folder"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        cached = offline_files.resolve_cached(db, location_id="remote", path="folder/empty")
        db.close()
        self.assertIsNotNone(cached)
        self.assertTrue(cached.is_dir())

    def test_remote_offline_copy_rejects_case_collisions_before_downloading(self):
        self._remote()
        listings = {
            "": {
                "items": [
                    {
                        "path": "folder",
                        "normalized_path": "folder",
                        "type": "dir",
                        "size": 0,
                        "etag": "",
                    }
                ]
            },
            "folder": {
                "items": [
                    {
                        "path": "folder/A.txt",
                        "normalized_path": "folder/A.txt",
                        "type": "file",
                        "size": 1,
                        "etag": '"a"',
                    },
                    {
                        "path": "folder/a.txt",
                        "normalized_path": "folder/a.txt",
                        "type": "file",
                        "size": 1,
                        "etag": '"b"',
                    },
                ]
            },
        }
        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                side_effect=lambda _location, path: listings[path],
            ),
            mock.patch("services.offline_files.storage_backends.download") as download,
        ):
            response = self.client.post(
                "/api/files/offline", json={"location_id": "remote", "path": "folder"}
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("colliding", response.json()["detail"])
        download.assert_not_called()

    def test_windows_remote_offline_copy_rejects_colliding_and_reserved_names(self):
        self._remote()
        root_item = {
            "path": "folder",
            "normalized_path": "folder",
            "type": "dir",
            "size": 0,
            "etag": "",
        }
        for unsafe_items in (
            [
                {
                    "path": "folder/report",
                    "normalized_path": "folder/report",
                    "type": "file",
                    "size": 1,
                    "etag": '"a"',
                },
                {
                    "path": "folder/report.",
                    "normalized_path": "folder/report.",
                    "type": "file",
                    "size": 1,
                    "etag": '"b"',
                },
            ],
            [
                {
                    "path": "folder/CON.txt",
                    "normalized_path": "folder/CON.txt",
                    "type": "file",
                    "size": 1,
                    "etag": '"c"',
                }
            ],
        ):
            listings = {"": {"items": [root_item]}, "folder": {"items": unsafe_items}}
            with (
                mock.patch.object(offline_files, "_windows_namespace_rules", return_value=True),
                mock.patch(
                    "services.offline_files.storage_backends.listdir",
                    side_effect=lambda _location, path: listings[path],
                ),
                mock.patch("services.offline_files.storage_backends.download") as download,
            ):
                response = self.client.post(
                    "/api/files/offline", json={"location_id": "remote", "path": "folder"}
                )

            self.assertEqual(response.status_code, 409, response.text)
            self.assertRegex(response.json()["detail"], "colliding|Windows-incompatible")
            download.assert_not_called()

    def test_remote_refresh_failure_keeps_previous_verified_copy(self):
        self._remote()
        item = {
            "path": "note.txt",
            "normalized_path": "note.txt",
            "type": "file",
            "size": 5,
            "etag": '"v1"',
        }

        def first_download(_location, _path, destination, **_kwargs):
            destination.write_bytes(b"first")
            import hashlib

            return {
                "size": 5,
                "checksum": hashlib.sha256(b"first").hexdigest(),
                "etag": '"v1"',
                "version_id": "",
            }

        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                return_value={"items": [item]},
            ),
            mock.patch(
                "services.offline_files.storage_backends.download",
                side_effect=first_download,
            ),
        ):
            first = self.client.post(
                "/api/files/offline", json={"location_id": "remote", "path": "note.txt"}
            )
        self.assertEqual(first.status_code, 200, first.text)
        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                return_value={"items": [item]},
            ),
            mock.patch(
                "services.offline_files.storage_backends.download",
                side_effect=RuntimeError("network lost"),
            ),
        ):
            refresh = self.client.post(
                "/api/files/offline", json={"location_id": "remote", "path": "note.txt"}
            )
        self.assertEqual(refresh.status_code, 409)
        raw = self.client.get(
            "/api/files/offline/raw", params={"location_id": "remote", "path": "note.txt"}
        )
        self.assertEqual(raw.content, b"first")

    def test_restart_recovery_and_cancel_state_are_explicit(self):
        (self.root / "queued.txt").write_text("queued", "utf-8")
        db = self.db()
        row = OfflineFile(
            id="queued-offline",
            location_id="local",
            normalized_path="queued.txt",
            state="queued",
            cache_name="queued-cache",
        )
        db.add(row)
        db.commit()
        db.close()
        cancelled = self.client.post("/api/files/offline/queued-offline/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["state"], "cancelled")

        db = self.db()
        interrupted = OfflineFile(
            id="interrupted-offline",
            location_id="local",
            normalized_path="other.txt",
            state="syncing",
            cache_name="interrupted-cache",
        )
        db.add(interrupted)
        db.commit()
        self.assertEqual(offline_files.recover_interrupted(db), 1)
        db.close()
        listed = self.client.get("/api/files/offline").json()["items"]
        recovered = next(item for item in listed if item["id"] == "interrupted-offline")
        self.assertEqual(recovered["state"], "queued")
        self.assertEqual(recovered["error_code"], "recovered_after_restart")

    def test_restart_recovery_removes_every_attempt_staging_artifact(self):
        db = self.db()
        row = OfflineFile(
            id="staging-interrupted",
            location_id="local",
            normalized_path="note.txt",
            state="syncing",
            cache_name="staging-cache",
        )
        db.add(row)
        db.commit()
        target = self.cache / row.cache_name
        local_partial = self.cache / f".{target.name}.{row.id}.partial"
        incoming = self.cache / f".{target.name}.{row.id}.incoming"
        remote_partial = internal_paths.artifact_sibling(incoming, "download", suffix=".partial")
        remote_identity = internal_paths.artifact_sibling(incoming, "download", suffix=".json")
        old = self.cache / f".{target.name}.{row.id}.old"
        local_partial.write_bytes(b"local partial")
        incoming.mkdir()
        (incoming / "nested.txt").write_text("remote tree", encoding="utf-8")
        remote_partial.write_bytes(b"remote partial")
        remote_identity.write_text('{"etag":"v1"}', encoding="utf-8")
        old.write_bytes(b"unverified old copy")

        self.assertEqual(offline_files.recover_interrupted(db), 1)

        db.refresh(row)
        self.assertEqual(row.state, "queued")
        self.assertEqual(list(self.cache.iterdir()), [])
        db.close()

    def test_restart_recovery_removes_an_uncommitted_published_cache(self):
        db = self.db()
        row = OfflineFile(
            id="published-interrupted",
            location_id="local",
            normalized_path="note.txt",
            state="syncing",
            cache_name="published-cache",
            size=0,
            checksum="",
        )
        db.add(row)
        db.commit()
        target = self.cache / row.cache_name
        target.write_bytes(b"published before ready commit")

        self.assertEqual(offline_files.recover_interrupted(db), 1)

        db.refresh(row)
        self.assertEqual(row.state, "queued")
        self.assertEqual(row.error_code, "recovered_after_restart")
        self.assertFalse(target.exists())
        db.close()

    def test_restart_finishes_an_interrupted_offline_disable(self):
        db = self.db()
        row = OfflineFile(
            id="deleting-offline",
            location_id="local",
            normalized_path="note.txt",
            state="deleting",
            cache_name="deleting-cache",
        )
        db.add(row)
        db.commit()
        target = self.cache / row.cache_name
        previous = self.cache / f".{target.name}.{row.id}.previous"
        partial = self.cache / f".{target.name}.{row.id}.partial"
        target.write_bytes(b"published cache")
        previous.write_bytes(b"verified cache")
        partial.write_bytes(b"attempt bytes")

        self.assertEqual(offline_files.recover_interrupted(db), 1)

        self.assertIsNone(db.get(OfflineFile, row.id))
        self.assertEqual(list(self.cache.iterdir()), [])
        db.close()

    def test_restart_recovery_restores_previous_verified_refresh_snapshot(self):
        import hashlib

        original = b"verified before refresh"
        replacement = b"published but not committed"
        db = self.db()
        interrupted = OfflineFile(
            id="refresh-interrupted",
            location_id="local",
            normalized_path="note.txt",
            state="syncing",
            cache_name="refresh-cache",
            size=len(original),
            checksum=hashlib.sha256(original).hexdigest(),
        )
        db.add(interrupted)
        db.commit()
        target = self.cache / "refresh-cache"
        previous = self.cache / ".refresh-cache.refresh-interrupted.previous"
        target.write_bytes(replacement)
        previous.write_bytes(original)

        self.assertEqual(offline_files.recover_interrupted(db), 1)
        db.refresh(interrupted)

        self.assertEqual(interrupted.state, "ready")
        self.assertEqual(interrupted.error_code, "refresh_interrupted")
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(previous.exists())
        db.close()

    def test_restart_recovery_restores_a_cancelled_refresh_snapshot(self):
        import hashlib

        original = b"verified before cancelled refresh"
        replacement = b"published after cancellation"
        db = self.db()
        interrupted = OfflineFile(
            id="cancelled-refresh-restart",
            location_id="local",
            normalized_path="note.txt",
            state="cancelled",
            cache_name="cancelled-refresh-cache",
            size=len(original),
            checksum=hashlib.sha256(original).hexdigest(),
        )
        db.add(interrupted)
        db.commit()
        target = self.cache / interrupted.cache_name
        previous = self.cache / f".{target.name}.{interrupted.id}.previous"
        target.write_bytes(replacement)
        previous.write_bytes(original)

        self.assertEqual(offline_files.recover_interrupted(db), 1)
        db.refresh(interrupted)

        self.assertEqual(interrupted.state, "ready")
        self.assertEqual(interrupted.error_code, "refresh_cancelled")
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(previous.exists())
        db.close()

    def test_hard_crash_before_refresh_commit_restores_the_verified_remote_copy(self):
        import hashlib

        self._remote()
        payload = {"body": b"first"}

        def listing(_location, _path):
            body = payload["body"]
            return {
                "items": [
                    {
                        "path": "note.txt",
                        "normalized_path": "note.txt",
                        "type": "file",
                        "size": len(body),
                        "etag": f'"{body.decode()}"',
                    }
                ]
            }

        def download(_location, _path, destination, **_kwargs):
            body = payload["body"]
            destination.write_bytes(body)
            return {
                "size": len(body),
                "checksum": hashlib.sha256(body).hexdigest(),
                "etag": f'"{body.decode()}"',
                "version_id": "",
            }

        with (
            mock.patch(
                "services.offline_files.storage_backends.listdir",
                side_effect=listing,
            ),
            mock.patch(
                "services.offline_files.storage_backends.download",
                side_effect=download,
            ),
        ):
            db = self.db()
            ready = offline_files.enable(db, location_id="remote", path="note.txt")
            cache_name = ready.cache_name
            row_id = ready.id
            payload["body"] = b"second"
            original_commit = db.commit
            commits = 0

            def crash_on_ready_commit():
                nonlocal commits
                commits += 1
                # Two durable path-lease commits precede the syncing and ready commits.
                if commits == 4:
                    raise SystemExit("simulated hard crash before ready commit")
                return original_commit()

            with mock.patch.object(db, "commit", side_effect=crash_on_ready_commit):
                with self.assertRaisesRegex(SystemExit, "simulated hard crash"):
                    offline_files.enable(db, location_id="remote", path="note.txt")
            db.close()

        old = self.cache / f".{cache_name}.{row_id}.old"
        self.assertEqual(old.read_bytes(), b"first")

        recovered_db = self.db()
        self.assertEqual(offline_files.recover_interrupted(recovered_db), 1)
        recovered = recovered_db.get(OfflineFile, row_id)
        self.assertEqual(recovered.state, "ready")
        self.assertEqual(recovered.error_code, "refresh_interrupted")
        recovered_db.close()
        self.assertEqual((self.cache / cache_name).read_bytes(), b"first")
        self.assertFalse(old.exists())

    def test_restart_cleans_the_previous_snapshot_after_a_committed_refresh(self):
        source = self.root / "note.txt"
        source.write_bytes(b"first")
        db = self.db()
        ready = offline_files.enable(db, location_id="local", path="note.txt")
        target = self.cache / ready.cache_name
        previous = self.cache / f".{target.name}.{ready.id}.previous"
        self.assertEqual(ready.state, "ready")
        self.assertEqual(target.read_bytes(), b"first")
        source.write_bytes(b"second")
        original_remove = offline_files._remove_cache_entry
        previous_removals = 0

        def crash_before_snapshot_cleanup(path):
            nonlocal previous_removals
            if path.name == previous.name:
                previous_removals += 1
                if previous_removals == 2:
                    raise SystemExit("simulated hard crash after ready commit")
            return original_remove(path)

        with mock.patch.object(
            offline_files,
            "_remove_cache_entry",
            side_effect=crash_before_snapshot_cleanup,
        ):
            with self.assertRaisesRegex(SystemExit, "after ready commit"):
                offline_files.enable(db, location_id="local", path="note.txt")
        row_id = ready.id
        db.close()

        self.assertEqual(target.read_bytes(), b"second")
        self.assertEqual(previous.read_bytes(), b"first")
        committed_db = self.db()
        committed = committed_db.get(OfflineFile, row_id)
        self.assertEqual(committed.state, "ready")
        self.assertEqual(
            committed.checksum, offline_files.file_operations.fingerprint(target)["checksum"]
        )
        committed_db.close()
        recovered_db = self.db()
        self.assertEqual(offline_files.recover_interrupted(recovered_db), 1)
        recovered = recovered_db.get(OfflineFile, row_id)
        self.assertEqual(recovered.state, "ready")
        self.assertEqual(
            recovered.checksum, offline_files.file_operations.fingerprint(target)["checksum"]
        )
        recovered_db.close()
        self.assertEqual(target.read_bytes(), b"second")
        self.assertFalse(previous.exists())

    def test_post_commit_snapshot_cleanup_error_never_rolls_ready_bytes_backward(self):
        source = self.root / "note.txt"
        source.write_bytes(b"first")
        db = self.db()
        ready = offline_files.enable(db, location_id="local", path="note.txt")
        target = self.cache / ready.cache_name
        previous = self.cache / f".{target.name}.{ready.id}.previous"
        source.write_bytes(b"second")
        original_remove = offline_files._remove_cache_entry
        previous_removals = 0

        def fail_post_commit_cleanup(path):
            nonlocal previous_removals
            if path.name == previous.name:
                previous_removals += 1
                if previous_removals == 2:
                    raise OSError("simulated snapshot cleanup failure")
            return original_remove(path)

        with mock.patch.object(
            offline_files,
            "_remove_cache_entry",
            side_effect=fail_post_commit_cleanup,
        ):
            refreshed = offline_files.enable(db, location_id="local", path="note.txt")

        self.assertEqual(refreshed.state, "ready")
        self.assertEqual(target.read_bytes(), b"second")
        self.assertEqual(previous.read_bytes(), b"first")
        self.assertEqual(
            refreshed.checksum,
            offline_files.file_operations.fingerprint(target)["checksum"],
        )
        self.assertIsNotNone(offline_files.resolve_cached(db, location_id="local", path="note.txt"))
        self.assertEqual(offline_files.recover_interrupted(db), 1)
        self.assertEqual(target.read_bytes(), b"second")
        self.assertFalse(previous.exists())
        db.close()

    def test_post_commit_refresh_error_never_rolls_ready_bytes_backward(self):
        source = self.root / "note.txt"
        source.write_bytes(b"first")
        db = self.db()
        ready = offline_files.enable(db, location_id="local", path="note.txt")
        target = self.cache / ready.cache_name
        previous = self.cache / f".{target.name}.{ready.id}.previous"
        source.write_bytes(b"second")
        original_refresh = db.refresh

        def fail_post_commit_refresh(instance):
            observer = self.db()
            state = observer.get(OfflineFile, ready.id).state
            observer.close()
            if state == "ready":
                raise OSError("simulated post-commit refresh failure")
            return original_refresh(instance)

        with mock.patch.object(db, "refresh", side_effect=fail_post_commit_refresh):
            offline_files.enable(db, location_id="local", path="note.txt")

        committed = db.get(OfflineFile, ready.id)
        db.refresh(committed)
        self.assertEqual(committed.state, "ready")
        self.assertEqual(target.read_bytes(), b"second")
        self.assertEqual(
            committed.checksum,
            offline_files.file_operations.fingerprint(target)["checksum"],
        )
        self.assertFalse(previous.exists())
        db.close()

    def test_restart_preserves_unverified_bytes_for_a_ready_cache(self):
        import hashlib

        db = self.db()
        row = OfflineFile(
            id="ready-unverified",
            location_id="local",
            normalized_path="note.txt",
            state="ready",
            cache_name="ready-cache",
            size=5,
            checksum=hashlib.sha256(b"known").hexdigest(),
        )
        db.add(row)
        db.commit()
        target = self.cache / row.cache_name
        previous = self.cache / f".{target.name}.{row.id}.previous"
        target.write_bytes(b"unknown current bytes")
        previous.write_bytes(b"unknown previous bytes")

        self.assertEqual(offline_files.recover_interrupted(db), 1)

        self.assertEqual(target.read_bytes(), b"unknown current bytes")
        self.assertEqual(previous.read_bytes(), b"unknown previous bytes")
        db.refresh(row)
        self.assertEqual(row.state, "failed")
        self.assertEqual(row.error_code, "offline_cache_integrity_unverified")
        self.assertIsNone(offline_files.resolve_cached(db, location_id="local", path="note.txt"))
        db.close()

    def test_cancel_during_copy_cannot_publish_the_cache_as_ready(self):
        source = self.root / "large.bin"
        source.write_bytes(b"cancel me")
        original_copy = offline_files._copy_to_cache

        def copy_then_cancel(path, target, token, **kwargs):
            expected = original_copy(path, target, token, **kwargs)
            cancelling = self.db()
            row = cancelling.get(OfflineFile, token)
            offline_files.cancel(cancelling, row)
            cancelling.close()
            return expected

        db = self.db()
        with mock.patch(
            "services.offline_files._copy_to_cache",
            side_effect=copy_then_cancel,
        ):
            with self.assertRaisesRegex(offline_files.OfflineFileError, "cancelled"):
                offline_files.enable(db, location_id="local", path="large.bin")
        db.close()

        check = self.db()
        row = check.query(OfflineFile).one()
        self.assertEqual(row.state, "cancelled")
        self.assertFalse((self.cache / row.cache_name).exists())
        check.close()

    def test_cancelled_refresh_restores_the_previous_ready_copy(self):
        source = self.root / "note.txt"
        source.write_text("verified original", encoding="utf-8")
        first = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "note.txt"}
        )
        self.assertEqual(first.status_code, 200, first.text)
        source.write_text("replacement", encoding="utf-8")
        original_copy = offline_files._copy_to_cache

        def copy_then_cancel(path, target, token, **kwargs):
            expected = original_copy(path, target, token, **kwargs)
            cancelling = self.db()
            row = cancelling.get(OfflineFile, token)
            offline_files.cancel(cancelling, row)
            cancelling.close()
            return expected

        db = self.db()
        with mock.patch(
            "services.offline_files._copy_to_cache",
            side_effect=copy_then_cancel,
        ):
            with self.assertRaisesRegex(offline_files.OfflineFileError, "cancelled"):
                offline_files.enable(db, location_id="local", path="note.txt")
        db.close()

        check = self.db()
        row = check.query(OfflineFile).one()
        self.assertEqual(row.state, "ready")
        self.assertEqual(row.error_code, "refresh_cancelled")
        cached = offline_files.resolve_cached(
            check,
            location_id="local",
            path="note.txt",
        )
        self.assertIsNotNone(cached)
        self.assertEqual(cached.read_text("utf-8"), "verified original")
        check.close()

    def test_cancelled_refresh_keeps_the_ready_copy_before_previous_is_created(self):
        db = self.db()
        target = self.cache / "ready-cache"
        target.write_bytes(b"verified original")
        expected = offline_files.file_operations.fingerprint(target)
        row = OfflineFile(
            id="cancelled-refresh-window",
            location_id="local",
            normalized_path="note.txt",
            state="cancelled",
            cache_name=target.name,
            size=expected["size"],
            checksum=expected["checksum"],
        )
        db.add(row)
        db.commit()

        self.assertEqual(offline_files.recover_interrupted(db), 1)

        db.refresh(row)
        self.assertEqual(row.state, "ready")
        self.assertEqual(row.error_code, "refresh_cancelled")
        self.assertEqual(target.read_bytes(), b"verified original")
        db.close()

    def test_failed_refresh_does_not_restore_a_corrupted_ready_copy(self):
        source = self.root / "note.txt"
        source.write_text("verified original", encoding="utf-8")
        first = self.client.post(
            "/api/files/offline", json={"location_id": "local", "path": "note.txt"}
        )
        self.assertEqual(first.status_code, 200, first.text)

        db = self.db()
        row = db.query(OfflineFile).one()
        target = self.cache / row.cache_name
        target.write_text("corrupted cache", encoding="utf-8")
        db.close()

        refresh = self.db()
        with mock.patch(
            "services.offline_files._copy_to_cache",
            side_effect=offline_files.OfflineFileError("refresh unavailable"),
        ):
            with self.assertRaisesRegex(offline_files.OfflineFileError, "refresh unavailable"):
                offline_files.enable(refresh, location_id="local", path="note.txt")
        refresh.close()

        check = self.db()
        failed = check.query(OfflineFile).one()
        self.assertEqual(failed.state, "failed")
        self.assertFalse(target.exists())
        self.assertIsNone(offline_files.resolve_cached(check, location_id="local", path="note.txt"))
        check.close()
