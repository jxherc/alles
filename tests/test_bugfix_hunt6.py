"""regression tests for the 7th bug-hunt iteration:
- a corrupt/fake/bomb image upload must raise a clean ValueError (-> 400), not 500, and leave no orphan
- user-uploaded svg/html must be served non-renderable (attachment + nosniff) to kill stored XSS
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["AUTH_ENABLED"] = "false"


class ImportImageTests(unittest.TestCase):
    def setUp(self):
        from services import photos_store as ps

        self.ps = ps
        self.pdir = Path(tempfile.mkdtemp())
        self.tdir = Path(tempfile.mkdtemp())
        self._p1 = mock.patch.object(ps, "photos_dir", lambda: self.pdir)
        self._p2 = mock.patch.object(ps, "thumbs_dir", lambda: self.tdir)
        self._p1.start()
        self._p2.start()

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()

    def test_junk_image_raises_valueerror_no_orphan(self):
        with self.assertRaises(ValueError):
            self.ps.import_image(b"this is not an image at all", "evil.jpg")
        # nothing should have been written to disk (decode fails before the write)
        self.assertEqual(list(self.pdir.iterdir()), [])

    def test_truncated_image_raises(self):
        # first bytes of a PNG signature then garbage -> not decodable
        with self.assertRaises(ValueError):
            self.ps.import_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "trunc.png")

    def test_valid_image_still_imports(self):
        from PIL import Image
        import io

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (255, 0, 0)).save(buf, "PNG")
        out = self.ps.import_image(buf.getvalue(), "ok.png")
        self.assertEqual(out["width"], 8)
        self.assertTrue((self.pdir / out["filename"]).exists())


class SvgServeTests(unittest.TestCase):
    def test_gallery_svg_forced_attachment_nosniff(self):
        from routes import gallery

        d = Path(tempfile.mkdtemp())
        svg = d / "x.svg"
        svg.write_text("<svg><script>alert(1)</script></svg>", "utf-8")
        resp = gallery._serve_safely(svg)
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("attachment", resp.headers.get("content-disposition", ""))

    def test_gallery_png_stays_inline(self):
        from routes import gallery

        d = Path(tempfile.mkdtemp())
        png = d / "x.png"
        png.write_bytes(b"\x89PNG\r\n")
        resp = gallery._serve_safely(png)
        self.assertIn("inline", resp.headers.get("content-disposition", ""))


if __name__ == "__main__":
    unittest.main()
