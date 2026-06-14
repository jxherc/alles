import io
import tempfile
import zipfile
from pathlib import Path

import routes.backup as bk
from tests._client import ApiTest


class BackupApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        self.data.mkdir()
        (self.data / "aide.db").write_bytes(b"fake-sqlite")
        (self.data / "settings.json").write_text('{"x":1}')
        self._orig = bk.DATA_DIR
        bk.DATA_DIR = self.data   # never zip/overwrite the real data dir

    def tearDown(self):
        bk.DATA_DIR = self._orig
        self._tmp.cleanup()
        super().tearDown()

    def test_export_returns_zip_with_db(self):
        r = self.client.get("/api/backup")
        self.assertEqual(r.status_code, 200)
        self.assertIn("zip", r.headers["content-type"])
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertIn("aide.db", zf.namelist())
            self.assertIn("settings.json", zf.namelist())

    def _zip(self, members):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return buf.getvalue()

    def test_restore_roundtrip(self):
        z = self._zip({"aide.db": b"restored-db", "uploads/a.txt": b"hi"})
        r = self.client.post("/api/backup/restore", files={"file": ("b.zip", z, "application/zip")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.data / "aide.db").read_bytes(), b"restored-db")
        self.assertTrue((self.data / "uploads" / "a.txt").exists())

    def test_restore_rejects_non_zip(self):
        r = self.client.post("/api/backup/restore", files={"file": ("x.txt", b"not a zip", "text/plain")})
        self.assertEqual(r.status_code, 400)

    def test_restore_rejects_zip_without_db(self):
        z = self._zip({"random.txt": b"x"})
        self.assertEqual(self.client.post("/api/backup/restore", files={"file": ("b.zip", z, "application/zip")}).status_code, 400)

    def test_restore_rejects_empty(self):
        self.assertEqual(self.client.post("/api/backup/restore", files={"file": ("b.zip", b"", "application/zip")}).status_code, 400)

    def test_restore_blocks_zip_slip(self):
        z = self._zip({"aide.db": b"db", "../escape.txt": b"evil"})
        self.assertEqual(self.client.post("/api/backup/restore", files={"file": ("b.zip", z, "application/zip")}).status_code, 400)
