import io
import tempfile
import unittest
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
        bk.DATA_DIR = self.data  # never zip/overwrite the real data dir

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

    def test_restore_removes_stale_wal_shm(self):
        # a wal/shm left over from the pre-restore db must be cleared, else SQLite replays the
        # old wal onto the freshly restored aide.db on the next open
        (self.data / "aide.db-wal").write_bytes(b"stale-wal")
        (self.data / "aide.db-shm").write_bytes(b"stale-shm")
        z = self._zip({"aide.db": b"restored-db"})
        r = self.client.post("/api/backup/restore", files={"file": ("b.zip", z, "application/zip")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.data / "aide.db").read_bytes(), b"restored-db")
        self.assertFalse((self.data / "aide.db-wal").exists())
        self.assertFalse((self.data / "aide.db-shm").exists())

    def test_restore_rejects_non_zip(self):
        r = self.client.post(
            "/api/backup/restore", files={"file": ("x.txt", b"not a zip", "text/plain")}
        )
        self.assertEqual(r.status_code, 400)

    def test_restore_rejects_zip_without_db(self):
        z = self._zip({"random.txt": b"x"})
        self.assertEqual(
            self.client.post(
                "/api/backup/restore", files={"file": ("b.zip", z, "application/zip")}
            ).status_code,
            400,
        )

    def test_restore_rejects_empty(self):
        self.assertEqual(
            self.client.post(
                "/api/backup/restore", files={"file": ("b.zip", b"", "application/zip")}
            ).status_code,
            400,
        )

    def test_restore_blocks_zip_slip(self):
        z = self._zip({"aide.db": b"db", "../escape.txt": b"evil"})
        self.assertEqual(
            self.client.post(
                "/api/backup/restore", files={"file": ("b.zip", z, "application/zip")}
            ).status_code,
            400,
        )

    def test_export_includes_uploads(self):
        (self.data / "uploads").mkdir()
        (self.data / "uploads" / "photo.jpg").write_bytes(b"jpeg-data")
        r = self.client.get("/api/backup")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertIn("uploads/photo.jpg", zf.namelist())

    def test_export_checkpoints_wal_so_recent_writes_are_backed_up(self):
        # WAL mode keeps recent commits in aide.db-wal; the backup ships only aide.db, so without
        # a checkpoint the backed-up db is missing them. write data into the wal, export, then open
        # the backed-up aide.db ALONE (no -wal) and confirm the row made it in.
        import sqlalchemy as sa

        import core.database as db

        dbfile = self.data / "aide.db"
        dbfile.unlink()  # drop the fake one; make a real WAL db here
        eng = sa.create_engine(f"sqlite:///{dbfile.as_posix()}")
        with eng.connect() as c:
            c.exec_driver_sql("PRAGMA journal_mode=WAL")
            c.exec_driver_sql("CREATE TABLE t (x TEXT)")
            c.exec_driver_sql("INSERT INTO t VALUES ('hello-wal')")
            c.commit()  # committed to the -wal, NOT checkpointed into aide.db

        orig = db.engine
        db.engine = eng  # the backup checkpoints core.database.engine
        try:
            r = self.client.get("/api/backup")
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                backed = zf.read("aide.db")
        finally:
            db.engine = orig
            eng.dispose()

        out = Path(self._tmp.name) / "restored.db"  # open standalone, no wal beside it
        out.write_bytes(backed)
        chk = sa.create_engine(f"sqlite:///{out.as_posix()}")
        try:
            with chk.connect() as c:
                rows = c.exec_driver_sql("SELECT x FROM t").fetchall()
        finally:
            chk.dispose()
        self.assertEqual(rows, [("hello-wal",)])

    def test_export_content_disposition_header(self):
        r = self.client.get("/api/backup")
        cd = r.headers.get("content-disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn(".zip", cd)

    def test_restore_ok_response_shape(self):
        z = self._zip({"aide.db": b"db"})
        r = self.client.post("/api/backup/restore", files={"file": ("b.zip", z, "application/zip")})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("ok", body)
        self.assertTrue(body["ok"])


if __name__ == "__main__":
    unittest.main()
