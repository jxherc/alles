import tempfile
from pathlib import Path

import routes.uploads as up
from tests._client import ApiTest


class UploadsApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = up.UPLOAD_DIR
        up.UPLOAD_DIR = Path(self._tmp.name)

    def tearDown(self):
        up.UPLOAD_DIR = self._orig_dir
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

    def test_upload_returns_id_and_metadata(self):
        r = self.client.post("/api/uploads", files={"file": ("pic.png", b"\x89PNG", "image/png")})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn("id", j)
        self.assertEqual(j["type"], "image/png")
        self.assertEqual(j["size"], 4)

    def test_upload_multiple_independent_ids(self):
        a = self.client.post("/api/uploads", files={"file": ("a.txt", b"aaa", "text/plain")}).json()
        b = self.client.post("/api/uploads", files={"file": ("b.txt", b"bbb", "text/plain")}).json()
        self.assertNotEqual(a["id"], b["id"])

    def test_upload_exact_size_limit_ok(self):
        orig = up.MAX_SIZE
        up.MAX_SIZE = 5
        try:
            r = self.client.post(
                "/api/uploads", files={"file": ("ok.bin", b"12345", "application/octet-stream")}
            )
            self.assertEqual(r.status_code, 200)
        finally:
            up.MAX_SIZE = orig

    def test_delete_removes_file_from_disk(self):
        r = self.client.post(
            "/api/uploads", files={"file": ("tmp.txt", b"data", "text/plain")}
        ).json()
        uid = r["id"]
        files_before = list(Path(self._tmp.name).iterdir())
        self.assertEqual(len(files_before), 1)
        self.client.delete(f"/api/uploads/{uid}")
        files_after = list(Path(self._tmp.name).iterdir())
        self.assertEqual(len(files_after), 0)

    def test_delete_twice_second_is_404(self):
        r = self.client.post("/api/uploads", files={"file": ("x.txt", b"x", "text/plain")}).json()
        uid = r["id"]
        self.assertEqual(self.client.delete(f"/api/uploads/{uid}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/uploads/{uid}").status_code, 404)

    def test_upload_no_extension_stores_fine(self):
        r = self.client.post(
            "/api/uploads", files={"file": ("noext", b"raw", "application/octet-stream")}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "noext")
