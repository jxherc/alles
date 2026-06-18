import tempfile
from pathlib import Path

import routes.uploads as up
from tests._client import ApiTest


class UploadsApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = up.UPLOAD_DIR
        up.UPLOAD_DIR = Path(self._tmp.name)

    def tearDown(self):
        up.UPLOAD_DIR = self._orig
        self._tmp.cleanup()
        super().tearDown()

    def test_upload_serve_delete(self):
        r = self.client.post(
            "/api/uploads", files={"file": ("notes.txt", b"hello world", "text/plain")}
        )
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["name"], "notes.txt")
        self.assertEqual(j["size"], 11)
        self.assertEqual(j["type"], "text/plain")
        uid = j["id"]
        self.assertEqual(self.client.get(f"/api/uploads/{uid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/uploads/{uid}").json(), {"ok": True})
        self.assertEqual(self.client.get(f"/api/uploads/{uid}").status_code, 404)

    def test_too_large_rejected(self):
        orig = up.MAX_SIZE
        up.MAX_SIZE = 8
        try:
            r = self.client.post(
                "/api/uploads",
                files={"file": ("big.bin", b"123456789", "application/octet-stream")},
            )
            self.assertEqual(r.status_code, 400)
        finally:
            up.MAX_SIZE = orig

    def test_missing_404(self):
        self.assertEqual(self.client.get("/api/uploads/nope").status_code, 404)
        self.assertEqual(self.client.delete("/api/uploads/nope").status_code, 404)
