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

    def test_jpeg_ext_normalized_to_jpg(self):
        info = ps.import_image(_png(), "photo.jpeg")
        self.assertTrue(info["filename"].endswith(".jpg"))

    def test_import_gif(self):
        buf = io.BytesIO()
        from PIL import Image

        Image.new("P", (10, 10), 0).save(buf, "GIF")
        info = ps.import_image(buf.getvalue(), "anim.gif")
        self.assertTrue(info["filename"].endswith(".gif"))
        self.assertTrue(ps.original_path(info["filename"]).is_file())

    def test_delete_missing_files_is_silent(self):
        # should not raise even if files don't exist
        ps.delete_files("nonexistent_" + "x" * 32 + ".jpg", "nonexistent_thumb.jpg")

    def test_original_path_resolves_inside_dir(self):
        info = ps.import_image(_png(), "test.png")
        p = ps.original_path(info["filename"])
        base = ps.photos_dir()
        self.assertTrue(p.is_relative_to(base))

    def test_collage_single_image(self):
        info = ps.import_image(_png(size=(100, 100)), "col.png")
        orig = ps.original_path(info["filename"])
        result = ps.make_collage([orig], cols=1, cell=100)
        self.assertIsInstance(result, bytes)
        self.assertTrue(len(result) > 0)

    def test_import_video_stored_as_is(self):
        data = b"\x00\x00\x00\x20ftyp"  # fake mp4 header
        info = ps.import_video(data, "clip.mp4")
        self.assertTrue(info["filename"].endswith(".mp4"))
        self.assertEqual(info["thumb"], "")
        self.assertTrue(info["is_video"])
        p = ps.original_path(info["filename"])
        self.assertTrue(p.is_file())


if __name__ == "__main__":
    unittest.main()
