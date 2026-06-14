import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import photos_store, photo_sync
from tests._client import ApiTest


def _png(path: Path, color=(200, 30, 30)):
    from PIL import Image
    img = Image.new("RGB", (24, 24), color)
    buf = io.BytesIO(); img.save(buf, "PNG")
    path.write_bytes(buf.getvalue())


class PhotoSyncStoreTest(unittest.TestCase):
    """service-level, with photo dirs + sync state redirected to temp."""
    def setUp(self):
        self.pdir = tempfile.TemporaryDirectory()
        self.tdir = tempfile.TemporaryDirectory()
        self.src = tempfile.TemporaryDirectory()
        self.state = tempfile.TemporaryDirectory()
        self._patches = [
            mock.patch.object(photos_store, "photos_dir", lambda: Path(self.pdir.name)),
            mock.patch.object(photos_store, "thumbs_dir", lambda: Path(self.tdir.name)),
            mock.patch.object(photo_sync, "_STATE", Path(self.state.name) / "state.json"),
        ]
        for p in self._patches:
            p.start()
        _png(Path(self.src.name) / "a.png")
        _png(Path(self.src.name) / "b.png", (30, 30, 200))

    def tearDown(self):
        for p in self._patches:
            p.stop()
        for d in (self.pdir, self.tdir, self.src, self.state):
            d.cleanup()

    def test_sync_imports_then_dedupes(self):
        # uses an in-memory db via a throwaway session
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        import core.database as db
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        db.Base.metadata.create_all(eng)
        Sess = sessionmaker(bind=eng)

        s1 = Sess()
        r1 = photo_sync.sync_folder(self.src.name, s1)
        s1.close()
        self.assertEqual(r1["imported"], 2)
        self.assertEqual(r1["failed"], 0)

        # second run: nothing new → all skipped
        s2 = Sess()
        r2 = photo_sync.sync_folder(self.src.name, s2)
        s2.close()
        self.assertEqual(r2["imported"], 0)
        self.assertEqual(r2["skipped"], 2)

        # a new file shows up → only that one imports
        _png(Path(self.src.name) / "c.png", (30, 200, 30))
        s3 = Sess()
        r3 = photo_sync.sync_folder(self.src.name, s3)
        s3.close()
        self.assertEqual(r3["imported"], 1)

    def test_bad_folder_raises(self):
        with self.assertRaises(ValueError):
            photo_sync.sync_folder(str(Path(self.src.name) / "nope"))

    def test_macos_bridge_guarded_off_mac(self):
        import sys
        if sys.platform != "darwin":
            with self.assertRaises(NotImplementedError):
                photo_sync.pull_from_macos_photos("/tmp/whatever")


class PhotoSyncApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.pdir = tempfile.TemporaryDirectory()
        self.tdir = tempfile.TemporaryDirectory()
        self.src = tempfile.TemporaryDirectory()
        self.state = tempfile.TemporaryDirectory()
        self._patches = [
            mock.patch.object(photos_store, "photos_dir", lambda: Path(self.pdir.name)),
            mock.patch.object(photos_store, "thumbs_dir", lambda: Path(self.tdir.name)),
            mock.patch.object(photo_sync, "_STATE", Path(self.state.name) / "state.json"),
        ]
        for p in self._patches:
            p.start()
        _png(Path(self.src.name) / "x.png")

    def tearDown(self):
        for p in self._patches:
            p.stop()
        for d in (self.pdir, self.tdir, self.src, self.state):
            d.cleanup()
        super().tearDown()

    def test_sync_route(self):
        r = self.client.post("/api/photos/sync", json={"source": self.src.name})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["imported"], 1)

    def test_sync_route_bad_folder_400(self):
        self.assertEqual(self.client.post("/api/photos/sync", json={"source": "/no/such/dir/xyz"}).status_code, 400)

    def test_macos_route_501_off_mac(self):
        import sys
        if sys.platform != "darwin":
            self.assertEqual(self.client.post("/api/photos/sync/macos").status_code, 501)


if __name__ == "__main__":
    unittest.main()
