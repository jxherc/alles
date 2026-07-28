import asyncio
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from core.database import (
    FileComment,
    FileOperation,
    FileTag,
    FileVersion,
    IndexChunk,
    OfflineFile,
    Share,
    StorageLocation,
    TrashItem,
)
from routes import files as files_route
from services import files_store, share, storage_backends, textindex, trash
from tests._client import ApiTest


class FilesLocationIdentityTests(ApiTest):
    def test_upload_reader_stops_one_byte_past_the_limit(self):
        class OversizedUpload:
            def __init__(self):
                self.remaining = 1000
                self.requested = []

            async def read(self, size):
                self.requested.append(size)
                count = min(size, self.remaining)
                self.remaining -= count
                return b"x" * count

        upload = OversizedUpload()
        with self.assertRaisesRegex(files_route.HTTPException, "100MB max"):
            asyncio.run(files_route._read_upload_limited(upload, limit=5))

        self.assertEqual(upload.requested, [6])
        self.assertEqual(upload.remaining, 994)

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "note.md").write_text("hello", "utf-8")
        self.root_patch = mock.patch.object(files_store, "files_dir", lambda: self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_legacy_list_url_defaults_to_default_local_identity(self):
        response = self.client.get("/api/files/list", params={"path": "docs"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["location_id"], "default-local")
        self.assertEqual(body["path"], "docs")
        self.assertEqual(body["items"][0]["normalized_path"], "docs/note.md")
        self.assertEqual(body["items"][0]["location_id"], "default-local")

    def test_legacy_local_delete_uses_the_verified_operation_path(self):
        target = self.root / "docs" / "legacy-delete.md"
        target.write_text("keep one verified copy", "utf-8")

        with mock.patch(
            "routes.files.trash.soft_delete_file",
            side_effect=AssertionError("legacy cross-filesystem move must not run"),
        ):
            response = self.client.delete(
                "/api/files/delete",
                params={"path": "docs/legacy-delete.md"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(target.exists())
        db = self.db()
        operation = db.query(FileOperation).filter_by(action="delete").one()
        self.assertEqual(operation.state, "completed")
        self.assertEqual(db.query(TrashItem).filter_by(kind="file").count(), 1)
        db.close()

    def test_default_location_learns_runtime_files_root_once(self):
        response = self.client.get("/api/storage-locations")
        self.assertEqual(response.status_code, 200)
        default = response.json()["locations"][0]
        self.assertEqual(Path(default["root_path"]), self.root)

    def test_unknown_or_unavailable_remote_location_fails_cleanly(self):
        missing = self.client.get("/api/files/list", params={"path": "", "location_id": "missing"})
        self.assertEqual(missing.status_code, 404)

        db = self.db()
        db.add(
            StorageLocation(
                id="remote",
                name="remote",
                kind="webdav",
                access="read_only",
                endpoint="https://dav.example.test",
            )
        )
        db.commit()
        db.close()
        with mock.patch(
            "services.webdav_locations.listdir",
            side_effect=RuntimeError("remote is unavailable"),
        ):
            pending = self.client.get(
                "/api/files/list", params={"path": "", "location_id": "remote"}
            )
        self.assertEqual(pending.status_code, 409)
        self.assertIn("unavailable", pending.json()["detail"])

    def test_trash_purge_is_scoped_to_the_selected_location(self):
        other_root = self.root / "other"
        other_root.mkdir()
        db = self.db()
        db.add(
            StorageLocation(
                id="other-local",
                name="other",
                kind="local",
                access="managed",
                root_path=str(other_root),
                enabled=True,
            )
        )
        db.commit()
        default_item = trash.record(
            db,
            "file",
            "default.txt",
            "default.txt",
            {"trash_name": "default-stash", "is_dir": False},
            location_id="default-local",
        )
        other_item = trash.record(
            db,
            "file",
            "other.txt",
            "other.txt",
            {"trash_name": "other-stash", "is_dir": False},
            location_id="other-local",
        )
        default_item.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        other_item.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        db.commit()
        default_id = default_item.id
        other_id = other_item.id
        trash.stash_path("default-stash").write_text("default", encoding="utf-8")
        trash.stash_path("other-stash").write_text("other", encoding="utf-8")
        db.close()

        response = self.client.post(
            "/api/files/trash/purge",
            params={"location_id": "default-local"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["purged"], 1)
        db = self.db()
        self.assertIsNone(db.get(TrashItem, default_id))
        self.assertIsNotNone(db.get(TrashItem, other_id))
        self.assertFalse(trash.stash_path("default-stash").exists())
        self.assertTrue(trash.stash_path("other-stash").exists())
        db.close()

    def test_trash_purge_refuses_a_read_only_location(self):
        db = self.db()
        db.add(
            StorageLocation(
                id="read-only-trash",
                name="read only",
                kind="local",
                access="read_only",
                root_path=str(self.root),
                enabled=True,
            )
        )
        db.commit()
        item = trash.record(
            db,
            "file",
            "kept.txt",
            "kept.txt",
            {"trash_name": "read-only-stash", "is_dir": False},
            location_id="read-only-trash",
        )
        item.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        db.commit()
        item_id = item.id
        trash.stash_path("read-only-stash").write_text("keep", encoding="utf-8")
        db.close()

        response = self.client.post(
            "/api/files/trash/purge",
            params={"location_id": "read-only-trash"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        db = self.db()
        self.assertIsNotNone(db.get(TrashItem, item_id))
        self.assertTrue(trash.stash_path("read-only-stash").exists())
        db.close()

    def test_metadata_writes_store_location_and_normalized_path(self):
        response = self.client.put(
            "/api/files/tags",
            params={"path": "docs\\note.md", "location_id": "default-local"},
            json={"tags": ["work"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        expected_path = "docs/note.md" if os.name == "nt" else "docs\\note.md"
        self.assertEqual(response.json()["path"], expected_path)
        db = self.db()
        row = db.query(FileTag).one()
        self.assertEqual(row.location_id, "default-local")
        self.assertEqual(row.normalized_path, expected_path)
        db.close()

    def test_legacy_metadata_row_is_read_through_path_fallback(self):
        db = self.db()
        db.add(
            FileTag(
                id="legacy",
                path="docs/note.md",
                location_id="default-local",
                normalized_path="",
                tags="legacy",
            )
        )
        db.commit()
        db.close()
        body = self.client.get("/api/files/tags", params={"path": "docs/note.md"}).json()
        self.assertEqual(body["tags"], ["legacy"])

    def test_same_normalized_path_can_exist_in_two_locations(self):
        db = self.db()
        db.add(
            StorageLocation(
                id="other-local",
                name="other",
                kind="local",
                access="read_only",
                root_path=str(self.root),
            )
        )
        db.add_all(
            [
                FileTag(
                    id="one",
                    path="same.txt",
                    location_id="default-local",
                    normalized_path="same.txt",
                ),
                FileTag(
                    id="two",
                    path="same.txt",
                    location_id="other-local",
                    normalized_path="same.txt",
                ),
            ]
        )
        db.commit()
        self.assertEqual(db.query(FileTag).filter_by(normalized_path="same.txt").count(), 2)
        db.close()

    def test_recreated_live_path_is_not_hidden_by_older_trash_history(self):
        recreated = self.root / "docs" / "recreated.md"
        recreated.write_text("recreated searchable words", "utf-8")
        db = self.db()
        db.add_all(
            [
                TrashItem(
                    kind="file",
                    ref="docs/recreated.md",
                    location_id="default-local",
                    normalized_path="docs/recreated.md",
                    name="older recreated.md",
                ),
                FileTag(
                    path="docs/recreated.md",
                    location_id="default-local",
                    normalized_path="docs/recreated.md",
                    tags="current",
                    starred=True,
                ),
            ]
        )
        db.commit()
        db.close()

        starred = self.client.get("/api/files/starred").json()["items"]
        tagged = self.client.get("/api/files/by-tag", params={"tag": "current"}).json()["items"]
        searched = self.client.get("/api/files/search", params={"q": "recreated"}).json()["results"]

        self.assertEqual([item["path"] for item in starred], ["docs/recreated.md"])
        self.assertEqual([item["path"] for item in tagged], ["docs/recreated.md"])
        self.assertIn("docs/recreated.md", [item["path"] for item in searched])

    def test_local_delete_removes_every_live_location_scoped_identity(self):
        target = self.root / "docs" / "delete-me.md"
        target.write_text("remove indexed words", "utf-8")
        db = self.db()
        db.add_all(
            [
                OfflineFile(
                    location_id="default-local",
                    normalized_path="docs/delete-me.md",
                    state="ready",
                    cache_name="missing-delete-cache",
                ),
                Share(
                    token="delete-local-share",
                    kind="file",
                    ref="docs/delete-me.md",
                    location_id="default-local",
                    normalized_path="docs/delete-me.md",
                ),
                IndexChunk(
                    kind="file",
                    ref="docs/delete-me.md",
                    location_id="default-local",
                    normalized_path="docs/delete-me.md",
                    text="remove indexed words",
                ),
            ]
        )
        db.commit()
        db.close()

        response = self.client.delete("/api/files/delete", params={"path": "docs/delete-me.md"})
        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        for model in (OfflineFile, Share, IndexChunk):
            self.assertEqual(db.query(model).count(), 0, model.__name__)
        self.assertEqual(db.query(TrashItem).filter_by(kind="file").count(), 1)
        db.close()

    def test_second_local_location_lists_and_reads_its_own_root(self):
        other_root = self.root / "other-root"
        other_root.mkdir()
        (other_root / "second.txt").write_text("second root", "utf-8")
        db = self.db()
        db.add(
            StorageLocation(
                id="second-local",
                name="second",
                kind="local",
                access="read_only",
                root_path=str(other_root),
            )
        )
        db.commit()
        db.close()
        listing = self.client.get(
            "/api/files/list", params={"path": "", "location_id": "second-local"}
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json()["items"][0]["name"], "second.txt")
        self.assertEqual(listing.json()["location_id"], "second-local")
        read = self.client.get(
            "/api/files/read",
            params={"path": "second.txt", "location_id": "second-local"},
        )
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["content"], "second root")

    def test_read_only_local_location_rejects_writes(self):
        other_root = self.root / "read-only-root"
        other_root.mkdir()
        db = self.db()
        db.add(
            StorageLocation(
                id="read-only-local",
                name="read only",
                kind="local",
                access="read_only",
                root_path=str(other_root),
            )
        )
        db.commit()
        db.close()
        response = self.client.post(
            "/api/files/mkdir",
            json={"path": "blocked", "location_id": "read-only-local"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse((other_root / "blocked").exists())

    def test_missing_local_root_is_not_recreated_by_mkdir(self):
        missing_root = self.root / "disconnected-drive"
        db = self.db()
        db.add(
            StorageLocation(
                id="missing-local",
                name="missing local",
                kind="local",
                access="managed",
                root_path=str(missing_root),
            )
        )
        db.commit()
        db.close()

        response = self.client.post(
            "/api/files/mkdir",
            json={"path": "must-not-exist", "location_id": "missing-local"},
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(missing_root.exists())

    def test_new_share_trash_and_index_rows_carry_default_location_identity(self):
        db = self.db()
        shared = share.mint(db, "file", "docs/note.md")
        trashed = trash.record(db, "file", "docs/note.md", "note.md")
        textindex.index(db, "file", "docs/note.md", "hello world")
        db.refresh(shared)
        db.refresh(trashed)
        indexed = db.query(IndexChunk).filter_by(kind="file").one()
        for row in (shared, trashed, indexed):
            self.assertEqual(row.location_id, "default-local")
            self.assertEqual(row.normalized_path, "docs/note.md")
        self.assertEqual(db.query(Share).count(), 1)
        self.assertEqual(db.query(TrashItem).count(), 1)
        db.close()

    def test_same_file_path_can_be_shared_independently_from_two_locations(self):
        other_root = self.root / "shared-other-root"
        (other_root / "docs").mkdir(parents=True)
        (other_root / "docs" / "note.md").write_text("other location", "utf-8")
        db = self.db()
        db.add(
            StorageLocation(
                id="shared-other",
                name="shared other",
                kind="local",
                access="read_only",
                root_path=str(other_root),
                enabled=True,
            )
        )
        db.commit()
        db.close()

        first = self.client.post(
            "/api/share",
            json={
                "kind": "file",
                "ref": "docs/note.md",
                "location_id": "default-local",
            },
        )
        second = self.client.post(
            "/api/share",
            json={
                "kind": "file",
                "ref": "docs/note.md",
                "location_id": "shared-other",
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(first.json()["token"], second.json()["token"])
        self.assertEqual(first.json()["location_id"], "default-local")
        self.assertEqual(second.json()["location_id"], "shared-other")

        first_public = self.client.get(first.json()["url"])
        second_public = self.client.get(second.json()["url"])
        self.assertEqual(first_public.content, b"hello")
        self.assertEqual(second_public.content, b"other location")

        first_lookup = self.client.get(
            "/api/share",
            params={
                "kind": "file",
                "ref": "docs/note.md",
                "location_id": "default-local",
            },
        )
        second_lookup = self.client.get(
            "/api/share",
            params={
                "kind": "file",
                "ref": "docs/note.md",
                "location_id": "shared-other",
            },
        )
        self.assertEqual(first_lookup.json()["token"], first.json()["token"])
        self.assertEqual(second_lookup.json()["token"], second.json()["token"])

    def test_old_metadata_and_version_urls_write_default_identity(self):
        self.assertEqual(
            self.client.put(
                "/api/files/star",
                params={"path": "docs/note.md"},
                json={"starred": True},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/files/comments",
                json={"path": "docs/note.md", "body": "keep this"},
            ).status_code,
            200,
        )
        response = self.client.post(
            "/api/files/upload",
            data={"path": "docs"},
            files={"file": ("note.md", b"updated", "text/markdown")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        versions = self.client.get("/api/files/versions", params={"path": "docs/note.md"}).json()
        self.assertEqual(versions[0]["location_id"], "default-local")
        self.assertEqual(versions[0]["normalized_path"], "docs/note.md")

        db = self.db()
        for row in (
            db.query(FileTag).one(),
            db.query(FileComment).one(),
            db.query(FileVersion).one(),
        ):
            self.assertEqual(row.location_id, "default-local")
            self.assertEqual(row.normalized_path, "docs/note.md")
        db.close()

    def test_reply_without_location_inherits_its_non_default_parent_location(self):
        other_root = self.root / "other-comments"
        other_root.mkdir()
        db = self.db()
        db.add(
            StorageLocation(
                id="comment-location",
                name="comment location",
                kind="local",
                access="managed",
                root_path=str(other_root),
                enabled=True,
            )
        )
        db.commit()
        db.close()
        root = self.client.post(
            "/api/files/comments",
            json={
                "path": "notes/thread.md",
                "location_id": "comment-location",
                "body": "root",
            },
        )
        self.assertEqual(root.status_code, 200, root.text)

        reply = self.client.post(
            "/api/files/comments",
            json={"parent_id": root.json()["id"], "body": "reply"},
        )

        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json()["location_id"], "comment-location")
        self.assertEqual(reply.json()["path"], "notes/thread.md")

    def test_large_upload_failure_keeps_the_existing_file(self):
        target = self.root / "docs" / "large.bin"
        old_size = 25 * 1024 * 1024 + 1
        with target.open("wb") as handle:
            handle.truncate(old_size)

        with mock.patch.object(os, "replace", side_effect=OSError("disk full")):
            response = self.client.post(
                "/api/files/upload",
                data={"path": "docs"},
                files={"file": ("large.bin", b"new bytes", "application/octet-stream")},
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(target.stat().st_size, old_size)
        self.assertEqual(list(target.parent.glob(".large.bin.alles-upload-*")), [])

    def test_local_download_publish_failure_keeps_the_existing_target(self):
        location = StorageLocation(
            id="download-local",
            name="download local",
            kind="local",
            access="managed",
            root_path=str(self.root),
            enabled=True,
        )
        target = self.root / "existing-download.txt"
        target.write_bytes(b"verified old copy")

        with mock.patch.object(
            storage_backends.os,
            "replace",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(storage_backends.StorageBackendError, "disk full"):
                storage_backends.download(location, "docs/note.md", target)

        self.assertEqual(target.read_bytes(), b"verified old copy")

    def test_upload_accepts_a_max_length_filename(self):
        filename = f"{'u' * 251}.txt"

        response = self.client.post(
            "/api/files/upload",
            data={"path": "docs"},
            files={"file": (filename, b"long name", "text/plain")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((self.root / "docs" / filename).read_bytes(), b"long name")
        self.assertEqual(list((self.root / "docs").glob(".alles-upload-*")), [])

    def test_rename_does_not_touch_same_path_in_another_location(self):
        db = self.db()
        db.add(
            StorageLocation(
                id="other-local",
                name="other",
                kind="local",
                access="read_only",
                root_path=str(self.root),
            )
        )
        db.add_all(
            [
                FileTag(
                    id="default-tag",
                    path="docs/note.md",
                    location_id="default-local",
                    normalized_path="docs/note.md",
                ),
                FileTag(
                    id="other-tag",
                    path="docs/note.md",
                    location_id="other-local",
                    normalized_path="docs/note.md",
                ),
            ]
        )
        db.commit()
        db.close()

        response = self.client.post(
            "/api/files/rename",
            json={"path": "docs/note.md", "to": "docs/renamed.md"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        db = self.db()
        self.assertEqual(db.get(FileTag, "default-tag").normalized_path, "docs/renamed.md")
        self.assertEqual(db.get(FileTag, "other-tag").normalized_path, "docs/note.md")
        db.close()

    def test_remote_metadata_is_available_while_local_only_tools_fail_cleanly(self):
        db = self.db()
        db.add(
            StorageLocation(
                id="remote",
                name="remote",
                kind="webdav",
                access="read_only",
                endpoint="https://dav.example.test",
            )
        )
        db.commit()
        db.close()
        local_only = (("/api/files/read", {"path": "docs/note.md"}),)
        with mock.patch(
            "services.webdav_locations.download",
            side_effect=RuntimeError("remote is unavailable"),
        ):
            for url, params in local_only:
                with self.subTest(url=url):
                    response = self.client.get(url, params={**params, "location_id": "remote"})
                    self.assertEqual(response.status_code, 409, response.text)
        metadata = (
            ("/api/files/starred", {}),
            ("/api/files/comments", {"path": "docs/note.md"}),
        )
        for url, params in metadata:
            with self.subTest(url=url):
                response = self.client.get(url, params={**params, "location_id": "remote"})
                self.assertEqual(response.status_code, 200, response.text)
