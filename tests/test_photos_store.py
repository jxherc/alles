import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from services import photos_store as ps


def _png(color=(40, 120, 90), size=(60, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class PhotosStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(ps, "photos_dir", lambda: Path(self.tmp.name))
        self._p.start()
        (Path(self.tmp.name) / ".thumbs").mkdir(exist_ok=True)

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def test_import_makes_thumb_and_meta(self):
        info = ps.import_image(_png(size=(80, 50)), "shot.png")
        self.assertEqual(info["width"], 80)
        self.assertEqual(info["height"], 50)
        self.assertTrue(info["thumb"])
        self.assertTrue(ps.original_path(info["filename"]).is_file())
        self.assertTrue(ps.thumb_path(info["thumb"]).is_file())
        self.assertIsNotNone(info["taken_at"])  # EXIF or now() fallback

    def test_thumb_is_bounded(self):
        info = ps.import_image(_png(size=(2000, 1500)), "big.png")
        with Image.open(ps.thumb_path(info["thumb"])) as t:
            self.assertLessEqual(max(t.size), 512)

    def test_unsupported_ext_rejected(self):
        with self.assertRaises(ValueError):
            ps.import_image(b"xx", "evil.exe")

    def test_delete_removes_files(self):
        info = ps.import_image(_png(), "a.png")
        ps.delete_files(info["filename"], info["thumb"])
        self.assertFalse(ps.original_path(info["filename"]).is_file())
        self.assertFalse(ps.thumb_path(info["thumb"]).is_file())

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            ps._safe("../../secret")


if __name__ == "__main__":
    unittest.main()
