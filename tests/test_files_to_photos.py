import base64
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from core.database import Photo, StorageLocation
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
        db.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
