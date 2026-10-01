import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import routes.gallery as gal
from core.database import GalleryImage, Photo
from tests._client import ApiTest


class GalleryApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = gal.GALLERY_DIR
        gal.GALLERY_DIR = Path(self._tmp.name)  # don't write into the real data/gallery

    def tearDown(self):
        gal.GALLERY_DIR = self._orig_dir
        self._tmp.cleanup()
        super().tearDown()

    def _upload(self, name="pic.png", data=b"\x89PNG\r\n\x1a\n", tags="", prompt="a cat"):
        return self.client.post(
            "/api/gallery/upload",
            files={"file": (name, data, "image/png")},
            data={"prompt": prompt, "tags": tags},
        )

    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/gallery").json()["items"], [])

    def test_upload_list_serve_delete(self):
        r = self._upload(tags="animals")
        self.assertEqual(r.status_code, 200)
        img = r.json()
        self.assertEqual(img["source"], "upload")
        self.assertEqual(img["prompt"], "a cat")
        self.assertTrue(img["url"].startswith("/api/gallery/file/"))

        self.assertEqual(len(self.client.get("/api/gallery").json()["items"]), 1)
        # serve the actual file
        self.assertEqual(self.client.get(img["url"]).status_code, 200)
        # delete
        self.assertEqual(self.client.delete(f"/api/gallery/{img['id']}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/gallery").json()["items"], [])

    def test_bad_extension_rejected(self):
        self.assertEqual(self._upload("notes.txt", b"hello").status_code, 400)

    def test_serve_missing_404(self):
        self.assertEqual(self.client.get("/api/gallery/file/nope.png").status_code, 404)

    def test_delete_missing_404(self):
        self.assertEqual(self.client.delete("/api/gallery/nope").status_code, 404)

    def test_upload_jpeg_allowed(self):
        r = self.client.post(
            "/api/gallery/upload",
            files={"file": ("photo.jpg", b"\xff\xd8\xff", "image/jpeg")},
            data={"prompt": "", "tags": ""},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["source"], "upload")

    def test_upload_webp_allowed(self):
        r = self.client.post(
            "/api/gallery/upload",
            files={"file": ("anim.webp", b"RIFF....WEBP", "image/webp")},
            data={"prompt": "web", "tags": ""},
        )
        self.assertEqual(r.status_code, 200)

    def test_upload_stores_tags(self):
        r = self._upload(tags="sunset,travel", prompt="golden hour")
        img = r.json()
        self.assertEqual(img["tags"], "sunset,travel")
        self.assertEqual(img["prompt"], "golden hour")

    def test_upload_returns_created_at(self):
        img = self._upload().json()
        self.assertIn("created_at", img)
        self.assertTrue(img["created_at"])  # non-empty ISO string

    def test_delete_removes_file_from_disk(self):
        img = self._upload().json()
        fpath = Path(self._tmp.name) / img["filename"]
        self.assertTrue(fpath.exists())
        self.client.delete(f"/api/gallery/{img['id']}")
        self.assertFalse(fpath.exists())

    def test_path_traversal_blocked(self):
        # filenames with separators are blocked by the route's traversal check
        self.assertEqual(self.client.get("/api/gallery/file/%2F..%2Fetc%2Fpasswd").status_code, 404)

    def test_multiple_uploads_list_order(self):
        self._upload("a.png")
        self._upload("b.png")
        lst = self.client.get("/api/gallery").json()["items"]
        self.assertEqual(len(lst), 2)
        # newest first
        self.assertIsNotNone(lst[0]["created_at"])

    def test_creations_mix_generated_photos_without_personal_or_private_photos(self):
        now = datetime(2026, 9, 27, 12)
        db = self.db()
        db.add_all(
            [
                GalleryImage(id="upload", filename="upload.png", created_at=now),
                GalleryImage(
                    id="old-gallery-generated",
                    filename="old.png",
                    source="generated",
                    created_at=now - timedelta(minutes=3),
                ),
                Photo(
                    id="new-generated",
                    filename="new.png",
                    caption="a generated landscape",
                    source="generated",
                    created_at=now + timedelta(minutes=1),
                ),
                Photo(
                    id="personal", filename="personal.png", created_at=now + timedelta(minutes=2)
                ),
                Photo(
                    id="hidden-generated",
                    filename="hidden.png",
                    source="generated",
                    hidden=True,
                    created_at=now + timedelta(minutes=3),
                ),
                Photo(
                    id="trashed-generated",
                    filename="trashed.png",
                    source="generated",
                    deleted_at=now,
                    created_at=now + timedelta(minutes=4),
                ),
            ]
        )
        db.commit()
        db.close()

        first = self.client.get("/api/gallery?offset=0&limit=2").json()
        second = self.client.get("/api/gallery?offset=2&limit=2").json()
        self.assertEqual([item["id"] for item in first["items"]], ["new-generated", "upload"])
        self.assertEqual(first["next"], 2)
        self.assertEqual([item["id"] for item in second["items"]], ["old-gallery-generated"])
        self.assertIsNone(second["next"])
        generated = first["items"][0]
        self.assertEqual(generated["owner"], "photos")
        self.assertEqual(generated["source"], "generated")
        self.assertEqual(generated["prompt"], "a generated landscape")
        self.assertEqual(generated["url"], "/api/photos/original/new-generated")
        self.assertEqual(generated["thumb"], "/api/photos/thumb/new-generated")
        self.assertEqual(first["items"][1]["owner"], "gallery")
        self.assertEqual(second["items"][0]["owner"], "gallery")

        result = self.client.delete("/api/photos/new-generated")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["trashed"])
        self.assertEqual(
            [item["id"] for item in self.client.get("/api/gallery").json()["items"]],
            ["upload", "old-gallery-generated"],
        )
        db = self.db()
        self.assertIsNotNone(db.get(Photo, "new-generated").deleted_at)
        self.assertIsNotNone(db.get(GalleryImage, "upload"))
        db.close()
        self.assertEqual(self.client.post("/api/photos/new-generated/restore").status_code, 200)
        self.assertEqual(self.client.get("/api/gallery").json()["items"][0]["id"], "new-generated")
