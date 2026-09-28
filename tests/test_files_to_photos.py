import base64
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.database import Base, FileOperation, FileOperationPathClaim, Photo, StorageLocation
from services import file_operations, files_to_photos
from tests._client import ApiTest

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FilesToPhotosTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.files = self.base / "files"
        self.photos = self.base / "photos"
        self.files.mkdir()
        self.photos.mkdir()
        (self.photos / ".thumbs").mkdir()
        db = self.db()
        db.add_all(
            [
                StorageLocation(
                    id="local-media",
                    name="local media",
                    kind="local",
                    access="managed",
                    root_path=str(self.files),
                    enabled=True,
                ),
                StorageLocation(
                    id="remote-media",
                    name="remote media",
                    kind="webdav",
                    access="managed",
                    endpoint="https://dav.example.test/media",
                    enabled=True,
                ),
            ]
        )
        db.commit()
        db.close()
        self.photos_patch = mock.patch("services.photos_store.photos_dir", return_value=self.photos)
        self.photos_patch.start()

    def tearDown(self):
        self.photos_patch.stop()
        self.temp.cleanup()
        super().tearDown()

    def test_local_file_import_keeps_source_identity_and_skips_repeat(self):
        (self.files / "image.png").write_bytes(PNG)
        first = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "image.png"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["imported"], 1)
        self.assertEqual(first.json()["skipped"], 0)

        second = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "image.png"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["imported"], 0)
        self.assertEqual(second.json()["skipped"], 1)
        db = self.db()
        rows = db.query(Photo).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "files")
        self.assertEqual(rows[0].source_id, "local-media:image.png")
        db.close()

    def test_files_rename_keeps_the_same_photo_source_and_local_choices(self):
        (self.files / "image.png").write_bytes(PNG)
        first = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "image.png"},
        )
        self.assertEqual(first.json()["imported"], 1)
        photo_id = first.json()["items"][0]["photo_id"]
        db = self.db()
        photo = db.get(Photo, photo_id)
        photo.favorite = True
        photo.hidden = True
        db.commit()
        db.close()

        renamed = self.client.post(
            "/api/files/rename",
            json={"location_id": "local-media", "path": "image.png", "to": "renamed.png"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        second = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "renamed.png"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["imported"], 0)
        self.assertEqual(second.json()["skipped"], 1)
        self.assertEqual(second.json()["items"][0]["photo_id"], photo_id)
        db = self.db()
        rows = db.query(Photo).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_id, "local-media:renamed.png")
        self.assertTrue(rows[0].favorite)
        self.assertTrue(rows[0].hidden)
        db.close()

    def test_folder_move_and_undo_keep_child_photo_identity(self):
        folder = self.files / "album"
        folder.mkdir()
        (folder / "image.png").write_bytes(PNG)
        other = self.base / "other"
        other.mkdir()
        db = self.db()
        db.add(
            StorageLocation(
                id="other-media",
                name="other media",
                kind="local",
                access="managed",
                root_path=str(other),
                enabled=True,
            )
        )
        db.commit()
        db.close()
        first = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "album"},
        )
        self.assertEqual(first.json()["imported"], 1)
        photo_id = first.json()["items"][0]["photo_id"]

        moved = self.client.post(
            "/api/files/operations",
            json={
                "action": "move",
                "source_location_id": "local-media",
                "source_path": "album",
                "destination_location_id": "other-media",
                "destination_path": "moved",
            },
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["state"], "completed")
        second = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "other-media", "path": "moved"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["imported"], 0)
        self.assertEqual(second.json()["items"][0]["photo_id"], photo_id)
        db = self.db()
        self.assertEqual(db.get(Photo, photo_id).source_id, "other-media:moved/image.png")
        db.close()

        undone = self.client.post(f"/api/files/operations/{moved.json()['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        third = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "album"},
        )
        self.assertEqual(third.status_code, 200, third.text)
        self.assertEqual(third.json()["imported"], 0)
        self.assertEqual(third.json()["items"][0]["photo_id"], photo_id)
        db = self.db()
        self.assertEqual(db.query(Photo).count(), 1)
        self.assertEqual(db.get(Photo, photo_id).source_id, "local-media:album/image.png")
        db.close()

    def test_rename_keeps_both_photos_when_destination_source_key_exists(self):
        (self.files / "one.png").write_bytes(PNG)
        Image.new("RGB", (2, 2), "red").save(self.files / "two.png")
        for path in ("one.png", "two.png"):
            response = self.client.post(
                "/api/files/to-photos",
                json={"location_id": "local-media", "path": path},
            )
            self.assertEqual(response.json()["imported"], 1)
        (self.files / "two.png").unlink()
        db = self.db()
        original = {row.source_id: (row.id, row.filename) for row in db.query(Photo).all()}
        db.close()

        renamed = self.client.post(
            "/api/files/rename",
            json={"location_id": "local-media", "path": "one.png", "to": "two.png"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        second = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "two.png"},
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertFalse(second.json()["ok"])
        self.assertIn("file changed", second.json()["failed"][0]["error"])
        db = self.db()
        self.assertEqual(
            {row.source_id: (row.id, row.filename) for row in db.query(Photo).all()},
            original,
        )
        db.close()

    def test_rename_does_not_rekey_similar_names_or_sql_wildcards(self):
        for folder_name in ("a%_", "aXY"):
            folder = self.files / folder_name
            folder.mkdir()
            (folder / "one.png").write_bytes(PNG)
            response = self.client.post(
                "/api/files/to-photos",
                json={"location_id": "local-media", "path": folder_name},
            )
            self.assertEqual(response.json()["imported"], 1)
        renamed = self.client.post(
            "/api/files/rename",
            json={"location_id": "local-media", "path": "a%_", "to": "new"},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        db = self.db()
        self.assertEqual(
            {row.source_id for row in db.query(Photo).all()},
            {"local-media:new/one.png", "local-media:aXY/one.png"},
        )
        db.close()

    def test_files_copy_does_not_take_the_original_photo_source_key(self):
        (self.files / "image.png").write_bytes(PNG)
        first = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "image.png"},
        )
        self.assertEqual(first.json()["imported"], 1)
        copied = self.client.post(
            "/api/files/operations",
            json={
                "action": "copy",
                "source_location_id": "local-media",
                "source_path": "image.png",
                "destination_location_id": "local-media",
                "destination_path": "copy.png",
            },
        )
        self.assertEqual(copied.status_code, 200, copied.text)
        second = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "copy.png"},
        )
        self.assertEqual(second.json()["imported"], 1)
        db = self.db()
        self.assertEqual(
            {row.source_id for row in db.query(Photo).all()},
            {"local-media:image.png", "local-media:copy.png"},
        )
        db.close()

    def test_changed_source_keeps_original_photo_and_reports_conflict(self):
        source = self.files / "image.png"
        source.write_bytes(PNG)
        first = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "image.png"},
        )
        self.assertEqual(first.json()["imported"], 1)

        db = self.db()
        photo = db.query(Photo).one()
        photo.favorite = True
        photo.hidden = True
        db.commit()
        original_id = photo.id
        original_name = photo.filename
        original_thumb = photo.thumb
        original_checksum = photo.checksum
        db.close()
        original_media = {
            path.relative_to(self.photos): path.read_bytes()
            for path in self.photos.rglob("*")
            if path.is_file()
        }

        Image.new("RGB", (2, 2), "red").save(source)
        response = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "image.png"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertFalse(result["ok"])
        self.assertFalse(result["partial"])
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["path"], "image.png")
        self.assertIn("file changed since it was sent to Photos", result["failed"][0]["error"])
        self.assertNotIn("UNIQUE constraint", result["failed"][0]["error"])
        db = self.db()
        rows = db.query(Photo).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, original_id)
        self.assertEqual(rows[0].filename, original_name)
        self.assertEqual(rows[0].thumb, original_thumb)
        self.assertEqual(rows[0].checksum, original_checksum)
        self.assertTrue(rows[0].favorite)
        self.assertTrue(rows[0].hidden)
        db.close()
        self.assertEqual(
            {
                path.relative_to(self.photos): path.read_bytes()
                for path in self.photos.rglob("*")
                if path.is_file()
            },
            original_media,
        )

    def test_changed_folder_item_does_not_stop_new_items(self):
        folder = self.files / "album"
        folder.mkdir()
        source = folder / "one.png"
        source.write_bytes(PNG)
        first = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "album"},
        )
        self.assertEqual(first.json()["imported"], 1)

        Image.new("RGB", (2, 2), "red").save(source)
        (folder / "two.png").write_bytes(PNG)
        response = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "album"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertFalse(result["ok"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual([item["path"] for item in result["failed"]], ["album/one.png"])
        self.assertIn("file changed since it was sent to Photos", result["failed"][0]["error"])
        db = self.db()
        rows = db.query(Photo).order_by(Photo.source_id).all()
        self.assertEqual(
            [row.source_id for row in rows],
            ["local-media:album/one.png", "local-media:album/two.png"],
        )
        db.close()

    def test_source_modification_time_is_converted_from_unix_time_in_utc(self):
        (self.files / "utc.png").write_bytes(PNG)
        with mock.patch("services.files_to_photos.datetime", wraps=datetime) as clock:
            response = self.client.post(
                "/api/files/to-photos",
                json={"location_id": "local-media", "path": "utc.png"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIs(clock.fromtimestamp.call_args.args[1], UTC)

    def test_remote_import_uses_verified_snapshot_and_cleans_it(self):
        staged = []

        def materialize(_location, path, destination, **_kwargs):
            self.assertEqual(path, "remote.png")
            staged.append(destination)
            destination.write_bytes(PNG)
            return file_operations.fingerprint(destination)

        with (
            mock.patch(
                "services.storage_backends.data_dir",
                return_value=self.base,
            ),
            mock.patch(
                "services.files_to_photos.storage_backends.materialize",
                side_effect=materialize,
            ),
        ):
            response = self.client.post(
                "/api/files/to-photos",
                json={"location_id": "remote-media", "path": "remote.png"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["imported"], 1)
        self.assertEqual(len(staged), 1)
        self.assertFalse(staged[0].exists())

    def test_folder_import_is_bounded_and_ignores_non_media(self):
        folder = self.files / "album"
        folder.mkdir()
        (folder / "one.png").write_bytes(PNG)
        (folder / "readme.txt").write_text("not media", "utf-8")
        response = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "album"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["imported"], 1)
        self.assertEqual(response.json()["ignored"], 1)

    def test_folder_bound_counts_directories_before_skipping_them(self):
        folder = self.files / "directory-heavy"
        folder.mkdir()
        for index in range(3):
            (folder / f"dir-{index}").mkdir()

        with mock.patch.object(files_to_photos, "MAX_IMPORT_ITEMS", 2):
            response = self.client.post(
                "/api/files/to-photos",
                json={"location_id": "local-media", "path": "directory-heavy"},
            )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("too many items", response.json()["detail"])

    def test_failed_item_removes_its_new_media_files(self):
        (self.files / "image.png").write_bytes(PNG)

        with mock.patch(
            "services.files_to_photos._photo",
            side_effect=RuntimeError("photo row failed"),
        ):
            response = self.client.post(
                "/api/files/to-photos",
                json={"location_id": "local-media", "path": "image.png"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(response.json()["imported"], 0)
        self.assertEqual(
            [path for path in self.photos.rglob("*") if path.is_file()],
            [],
        )
        db = self.db()
        self.assertEqual(db.query(Photo).count(), 0)
        self.assertEqual(db.query(FileOperationPathClaim).count(), 0)
        db.close()

    def test_send_rejects_an_owned_path_then_succeeds_after_release(self):
        (self.files / "image.png").write_bytes(PNG)
        db = self.db()
        location = db.get(StorageLocation, "local-media")
        location.access = "read_only"
        db.commit()
        with file_operations.direct_mutation_claim(db, location, "image.png"):
            blocked = self.client.post(
                "/api/files/to-photos",
                json={"location_id": "local-media", "path": "image.png"},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertIn("already in use", blocked.json()["detail"])
        db.close()

        retry = self.client.post(
            "/api/files/to-photos",
            json={"location_id": "local-media", "path": "image.png"},
        )
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["imported"], 1)


class FilesToPhotosConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.files = self.base / "files"
        self.photos = self.base / "photos"
        self.files.mkdir()
        self.photos.mkdir()
        (self.photos / ".thumbs").mkdir()
        self.engine = create_engine(
            f"sqlite:///{self.base / 'race.db'}",
            connect_args={"check_same_thread": False, "timeout": 2},
        )

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(connection, _record):
            connection.execute("pragma journal_mode=wal")
            connection.execute("pragma busy_timeout=2000")

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        with self.Session() as db:
            db.add(
                StorageLocation(
                    id="local-media",
                    name="local media",
                    kind="local",
                    access="managed",
                    root_path=str(self.files),
                    enabled=True,
                )
            )
            db.commit()
        self.photos_patch = mock.patch("services.photos_store.photos_dir", return_value=self.photos)
        self.files_data_patch = mock.patch(
            "services.file_operations.data_dir", return_value=self.base
        )
        self.photos_patch.start()
        self.files_data_patch.start()

    def tearDown(self):
        self.files_data_patch.stop()
        self.photos_patch.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def test_send_claim_prevents_rename_between_media_copy_and_photo_row(self):
        (self.files / "image.png").write_bytes(PNG)
        reached_row = threading.Event()
        finish_import = threading.Event()
        send_result = {}
        original_photo = files_to_photos._photo

        def pause_before_row(*args, **kwargs):
            reached_row.set()
            if not finish_import.wait(10):
                raise TimeoutError("send did not resume")
            return original_photo(*args, **kwargs)

        def send():
            with self.Session() as db:
                try:
                    send_result["value"] = files_to_photos.import_from_files(
                        db, location_id="local-media", path="image.png"
                    )
                except Exception as exc:
                    send_result["error"] = exc

        with mock.patch.object(files_to_photos, "_photo", side_effect=pause_before_row):
            worker = threading.Thread(target=send)
            worker.start()
            try:
                self.assertTrue(reached_row.wait(5), "send did not reach Photo row creation")
                with self.Session() as db:
                    rename = file_operations.enqueue(
                        db,
                        action="rename",
                        source_location_id="local-media",
                        source_path="image.png",
                        destination_location_id="local-media",
                        destination_path="renamed.png",
                    )
                    rename_id = rename.id
                    with self.assertRaisesRegex(
                        file_operations.FileOperationError, "already in use"
                    ):
                        file_operations.run(db, rename)
                    self.assertTrue((self.files / "image.png").exists())
                    self.assertFalse((self.files / "renamed.png").exists())
            finally:
                finish_import.set()
                worker.join(timeout=10)

        self.assertFalse(worker.is_alive())
        self.assertNotIn("error", send_result)
        self.assertEqual(send_result["value"]["imported"], 1)
        with self.Session() as db:
            self.assertEqual(
                file_operations.retry(db, db.get(FileOperation, rename_id)).state, "completed"
            )
            resent = files_to_photos.import_from_files(
                db, location_id="local-media", path="renamed.png"
            )
            self.assertEqual(resent["imported"], 0)
            self.assertEqual(resent["skipped"], 1)
            self.assertEqual(db.query(Photo).count(), 1)
            self.assertEqual(db.query(Photo).one().source_id, "local-media:renamed.png")


if __name__ == "__main__":
    unittest.main()
