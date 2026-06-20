import tempfile
from pathlib import Path

import routes.gallery as gal
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
        self.assertEqual(self.client.get("/api/gallery").json(), [])

    def test_upload_list_serve_delete(self):
        r = self._upload(tags="animals")
        self.assertEqual(r.status_code, 200)
        img = r.json()
        self.assertEqual(img["source"], "upload")
        self.assertEqual(img["prompt"], "a cat")
        self.assertTrue(img["url"].startswith("/api/gallery/file/"))

        self.assertEqual(len(self.client.get("/api/gallery").json()), 1)
        # serve the actual file
        self.assertEqual(self.client.get(img["url"]).status_code, 200)
        # delete
        self.assertEqual(self.client.delete(f"/api/gallery/{img['id']}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/gallery").json(), [])

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
        self.assertEqual(
            self.client.get("/api/gallery/file/%2F..%2Fetc%2Fpasswd").status_code, 404
        )

    def test_multiple_uploads_list_order(self):
        self._upload("a.png")
        self._upload("b.png")
        lst = self.client.get("/api/gallery").json()
        self.assertEqual(len(lst), 2)
        # newest first
        self.assertIsNotNone(lst[0]["created_at"])
