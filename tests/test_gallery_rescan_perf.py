import io
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import routes.gallery as gallery
from core.database import GalleryImage, Photo
from services import photos_store
from tests._client import ApiTest


def _png(path: Path, color=(120, 40, 200)):
    from PIL import Image

    im = Image.new("RGB", (64, 48), color)
    b = io.BytesIO()
    im.save(b, "PNG")
    path.write_bytes(b.getvalue())


class GalleryRescanPerfTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_gallery = gallery.GALLERY_DIR
        gallery.GALLERY_DIR = self.root

    def tearDown(self):
        gallery.GALLERY_DIR = self.old_gallery
        self.tmp.cleanup()
        super().tearDown()

    def test_rescan_registers_loose_files_and_makes_thumb(self):
        _png(self.root / "loose.png")

        r = self.client.post("/api/gallery/rescan")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["added"], 1)

        d = self.client.get("/api/gallery?limit=10").json()
        self.assertEqual(len(d["items"]), 1)
        self.assertIn("/api/gallery/thumb/", d["items"][0]["thumb"])
        self.assertTrue((self.root / ".thumbs" / "loose.jpg").exists())

        tr = self.client.get(d["items"][0]["thumb"])
        self.assertEqual(tr.status_code, 200)
        self.assertIn("image/jpeg", tr.headers.get("content-type", ""))

    def test_gallery_list_is_paged(self):
        db = self.db()
        try:
            for i in range(55):
                db.add(GalleryImage(filename=f"{i}.png"))
            db.commit()
        finally:
            db.close()

        d = self.client.get("/api/gallery?offset=0&limit=20").json()
        self.assertEqual(len(d["items"]), 20)
        self.assertEqual(d["next"], 20)

    def test_mixed_gallery_deep_page_and_large_offset(self):
        start = datetime(2026, 9, 27, 12)
        db = self.db()
        try:
            for i in range(60):
                db.add(
                    GalleryImage(
                        id=f"g{i:03}",
                        filename=f"g{i:03}.png",
                        created_at=start + timedelta(minutes=2 * i),
                    )
                )
                db.add(
                    Photo(
                        id=f"p{i:03}",
                        filename=f"p{i:03}.png",
                        source="generated",
                        created_at=start + timedelta(minutes=2 * i + 1),
                    )
                )
            db.commit()
        finally:
            db.close()

        page = self.client.get("/api/gallery?offset=100&limit=20").json()
        expected = [id for i in range(9, -1, -1) for id in (f"p{i:03}", f"g{i:03}")]
        self.assertEqual([item["id"] for item in page["items"]], expected)
        self.assertEqual(page["next"], 120)
        self.assertEqual(
            self.client.get("/api/gallery?offset=1000000000&limit=20").json(),
            {"items": [], "next": None},
        )


class PhotosRescanTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.pdir = tempfile.TemporaryDirectory()
        self.tdir = tempfile.TemporaryDirectory()
        self._patches = [
            mock.patch.object(photos_store, "photos_dir", lambda: Path(self.pdir.name)),
            mock.patch.object(photos_store, "thumbs_dir", lambda: Path(self.tdir.name)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.pdir.cleanup()
        self.tdir.cleanup()
        super().tearDown()

    def test_rescan_registers_existing_photo_file(self):
        _png(Path(self.pdir.name) / "already-here.png")

        r = self.client.post("/api/photos/rescan")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["added"], 1)

        d = self.client.get("/api/photos/list?limit=10").json()
        self.assertEqual(d["count"], 1)
        item = d["moments"][0]["items"][0]
        self.assertEqual(item["original_name"], "already-here.png")
        self.assertEqual(self.client.get(item["thumb"]).status_code, 200)


if __name__ == "__main__":
    unittest.main()
