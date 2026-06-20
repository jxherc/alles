import io
import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (24, 24), (90, 90, 90)).save(buf, "PNG")
    return buf.getvalue()


def _items(d):
    return [p for m in d.get("moments", []) for p in m["items"]]


class PhotosVideoTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles7c2-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    def _upload(self, name, data, ctype):
        return self.client.post("/api/photos/upload", files={"file": (name, data, ctype)})

    # ---- store layer ----
    def test_import_media_video_flag(self):
        from services import photos_store as ps

        info = ps.import_media(b"\x00\x00fakemp4", "clip.mp4")
        self.assertTrue(info["is_video"])
        self.assertEqual(info["thumb"], "")

    def test_import_media_image_still_works(self):
        from services import photos_store as ps

        info = ps.import_media(_png(), "pic.png")
        self.assertFalse(info["is_video"])
        self.assertGreater(info["width"], 0)

    def test_unsupported_ext_rejected(self):
        from services import photos_store as ps

        with self.assertRaises(ValueError):
            ps.import_media(b"hello", "notes.txt")

    def test_image_not_flagged_video(self):
        from services import photos_store as ps

        self.assertFalse(ps.import_media(_png(), "x.jpg")["is_video"])

    # ---- api ----
    def test_upload_video_sets_is_video(self):
        d = self._upload("movie.mp4", b"\x00\x00ftypmp42", "video/mp4").json()
        self.assertTrue(d["is_video"])

    def test_fmt_has_is_video(self):
        d = self._upload("pic.png", _png(), "image/png").json()
        self.assertIn("is_video", d)
        self.assertFalse(d["is_video"])

    def test_list_includes_video(self):
        vid = self._upload("clip.mp4", b"\x00\x00ftyp", "video/mp4").json()["id"]
        items = _items(self.client.get("/api/photos/list").json())
        self.assertTrue(any(i["id"] == vid and i["is_video"] for i in items))

    def test_search_matches_video_name(self):
        vid = self._upload("vacation.mp4", b"\x00\x00ftyp", "video/mp4").json()["id"]
        items = _items(self.client.get("/api/photos/search?q=vacation").json())
        self.assertTrue(any(i["id"] == vid for i in items))

    def test_video_original_served(self):
        vid = self._upload("clip.mp4", b"\x00\x00ftypmp42moov", "video/mp4").json()["id"]
        r = self.client.get(f"/api/photos/original/{vid}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("video/"))
