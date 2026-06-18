import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from PIL import Image

from core.database import Photo
from services import photo_sync, photos_store
from tests._client import ApiTest


class SidecarParseTests(unittest.TestCase):
    def test_photo_taken_time(self):
        m = photo_sync.parse_takeout_sidecar({"photoTakenTime": {"timestamp": "1718700000"}})
        self.assertEqual(m["taken_at"], datetime.utcfromtimestamp(1718700000))

    def test_geo_data(self):
        m = photo_sync.parse_takeout_sidecar({"geoData": {"latitude": 37.8083, "longitude": -122.4192}})
        self.assertEqual(m["lat"], 37.8083)
        self.assertEqual(m["lon"], -122.4192)

    def test_zero_geo_ignored(self):
        m = photo_sync.parse_takeout_sidecar({"geoData": {"latitude": 0.0, "longitude": 0.0}})
        self.assertNotIn("lat", m)

    def test_prefers_photo_taken_over_creation(self):
        m = photo_sync.parse_takeout_sidecar({
            "photoTakenTime": {"timestamp": "1718700000"},
            "creationTime": {"timestamp": "1000000000"},
        })
        self.assertEqual(m["taken_at"], datetime.utcfromtimestamp(1718700000))

    def test_empty(self):
        self.assertEqual(photo_sync.parse_takeout_sidecar({}), {})

    def test_bad_timestamp(self):
        m = photo_sync.parse_takeout_sidecar({"photoTakenTime": {"timestamp": "nope"}})
        self.assertNotIn("taken_at", m)


class TakeoutSyncTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.src = tempfile.TemporaryDirectory()
        self.lib = tempfile.TemporaryDirectory()
        lib = Path(self.lib.name)
        (lib / ".thumbs").mkdir()
        self._mp = [
            mock.patch.object(photos_store, "photos_dir", lambda: lib),
            mock.patch.object(photos_store, "thumbs_dir", lambda: lib / ".thumbs"),
            mock.patch.object(photo_sync, "_STATE", Path(self.src.name) / "state.json"),
        ]
        for p in self._mp:
            p.start()

    def tearDown(self):
        for p in self._mp:
            p.stop()
        self.src.cleanup()
        self.lib.cleanup()
        super().tearDown()

    def _img(self, name):
        p = Path(self.src.name) / name
        Image.new("RGB", (32, 24), "green").save(p, "JPEG")
        return p

    def test_sidecar_sets_taken_and_gps(self):
        self._img("IMG_1.jpg")
        (Path(self.src.name) / "IMG_1.jpg.json").write_text(json.dumps({
            "photoTakenTime": {"timestamp": "1718700000"},
            "geoData": {"latitude": 37.8083, "longitude": -122.4192},
        }))
        photo_sync.sync_folder(self.src.name, self.db())
        p = self.db().query(Photo).first()
        self.assertEqual(p.taken_at, datetime.utcfromtimestamp(1718700000))
        self.assertEqual(json.loads(p.exif)["lat"], 37.8083)

    def test_supplemental_metadata_variant(self):
        self._img("IMG_2.jpg")
        (Path(self.src.name) / "IMG_2.jpg.supplemental-metadata.json").write_text(json.dumps({
            "photoTakenTime": {"timestamp": "1700000000"},
        }))
        photo_sync.sync_folder(self.src.name, self.db())
        p = self.db().query(Photo).first()
        self.assertEqual(p.taken_at, datetime.utcfromtimestamp(1700000000))

    def test_no_sidecar_still_imports(self):
        self._img("plain.jpg")
        res = photo_sync.sync_folder(self.src.name, self.db())
        self.assertEqual(res["imported"], 1)
        self.assertEqual(self.db().query(Photo).count(), 1)


if __name__ == "__main__":
    unittest.main()
