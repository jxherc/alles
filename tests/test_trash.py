import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from core.database import TrashItem
from services import files_store as fs
from services import trash
from tests._client import ApiTest


class TrashTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "files").mkdir()
        (self.root / "data").mkdir()
        self._patches = [
            mock.patch.object(fs, "files_dir", lambda: self.root / "files"),
            mock.patch.object(trash, "data_dir", lambda: self.root / "data"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _mkfile(self, rel, content="hi"):
        p = fs.files_dir() / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, "utf-8")
        return p

    # ── service ──
    def test_stash_and_unstash_roundtrip(self):
        p = self._mkfile("a.txt", "body")
        name = trash.stash_file(p)
        self.assertFalse(p.exists())
        self.assertTrue(trash.stash_path(name).exists())
        trash.unstash_file(name, p)
        self.assertTrue(p.exists())
        self.assertEqual(p.read_text("utf-8"), "body")

    def test_record_creates_item_with_expiry(self):
        d = self.db()
        it = trash.record(d, "file", "a.txt", "a.txt")
        self.assertIsNotNone(it.expires_at)
        self.assertGreater(it.expires_at, datetime.utcnow())

    def test_list_items_kind_filter(self):
        d = self.db()
        trash.record(d, "file", "a.txt", "a")
        trash.record(d, "photo", "pid", "p")
        self.assertEqual(len(trash.list_items(d, kind="file")), 1)
        self.assertEqual(len(trash.list_items(d)), 2)

    def test_soft_delete_file_moves_and_records(self):
        d = self.db()
        p = self._mkfile("doc.txt")
        it = trash.soft_delete_file(d, "doc.txt", p)
        self.assertFalse(p.exists())
        self.assertEqual(it.kind, "file")
        self.assertEqual(d.query(TrashItem).count(), 1)

    def test_restore_file_brings_back(self):
        d = self.db()
        p = self._mkfile("doc.txt", "keep")
        it = trash.soft_delete_file(d, "doc.txt", p)
        trash.restore_file(d, it, fs.abspath("doc.txt"))
        self.assertTrue((fs.files_dir() / "doc.txt").exists())
        self.assertEqual((fs.files_dir() / "doc.txt").read_text("utf-8"), "keep")
        self.assertEqual(d.query(TrashItem).count(), 0)

    def test_purge_expired_removes_file_and_row(self):
        d = self.db()
        p = self._mkfile("old.txt")
        it = trash.soft_delete_file(d, "old.txt", p)
        it.expires_at = datetime.utcnow() - timedelta(days=1)
        d.commit()
        tn = __import__("json").loads(it.payload)["trash_name"]
        self.assertEqual(trash.purge_expired(d), 1)
        self.assertFalse(trash.stash_path(tn).exists())
        self.assertEqual(d.query(TrashItem).count(), 0)

    def test_purge_keeps_unexpired(self):
        d = self.db()
        p = self._mkfile("fresh.txt")
        trash.soft_delete_file(d, "fresh.txt", p)
        self.assertEqual(trash.purge_expired(d), 0)
        self.assertEqual(d.query(TrashItem).count(), 1)

    # ── files API ──
    def test_api_delete_moves_to_trash(self):
        self._mkfile("note.txt")
        r = self.client.request("DELETE", "/api/files/delete", params={"path": "note.txt"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("trashed"))
        self.assertFalse((fs.files_dir() / "note.txt").exists())
        tr = self.client.get("/api/files/trash").json()
        self.assertTrue(any(t["ref"] == "note.txt" for t in tr))

    def test_api_restore(self):
        self._mkfile("note.txt", "data")
        self.client.request("DELETE", "/api/files/delete", params={"path": "note.txt"})
        tid = self.client.get("/api/files/trash").json()[0]["id"]
        r = self.client.post("/api/files/trash/restore", json={"id": tid})
        self.assertEqual(r.status_code, 200)
        self.assertTrue((fs.files_dir() / "note.txt").exists())
        self.assertEqual(self.client.get("/api/files/trash").json(), [])

    def test_api_delete_dir_trashed(self):
        self._mkfile("proj/inner.txt")
        self.client.request("DELETE", "/api/files/delete", params={"path": "proj"})
        self.assertFalse((fs.files_dir() / "proj").exists())
        self.assertTrue(any(t["ref"] == "proj" for t in self.client.get("/api/files/trash").json()))

    def test_api_delete_root_400(self):
        r = self.client.request("DELETE", "/api/files/delete", params={"path": ""})
        self.assertEqual(r.status_code, 400)

    def test_api_restore_unknown_404(self):
        r = self.client.post("/api/files/trash/restore", json={"id": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_api_purge(self):
        self._mkfile("x.txt")
        self.client.request("DELETE", "/api/files/delete", params={"path": "x.txt"})
        # expire it
        d = self.db()
        it = d.query(TrashItem).first()
        it.expires_at = datetime.utcnow() - timedelta(days=1)
        d.commit()
        r = self.client.post("/api/files/trash/purge")
        self.assertEqual(r.json()["purged"], 1)
