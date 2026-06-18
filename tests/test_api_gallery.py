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

    def _upload(self, name="pic.png", data=b"\x89PNG\r\n\x1a\n"):
        return self.client.post(
            "/api/gallery/upload",
            files={"file": (name, data, "image/png")},
            data={"prompt": "a cat", "tags": "animals"},
        )

    def test_list_empty(self):
        self.assertEqual(self.client.get("/api/gallery").json(), [])

    def test_upload_list_serve_delete(self):
        r = self._upload()
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
