import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from core.database import DEFAULT_LOCAL_STORAGE_LOCATION_ID, StorageLocation, TrashItem
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
        self.assertGreater(it.expires_at, datetime.now(UTC).replace(tzinfo=None))

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

    def test_soft_delete_record_failure_leaves_the_original_untouched(self):
        d = self.db()
        p = self._mkfile("record-failure.txt", "only copy")
        with mock.patch.object(trash, "record", side_effect=RuntimeError("database failed")):
            with self.assertRaisesRegex(RuntimeError, "database failed"):
                trash.soft_delete_file(d, "record-failure.txt", p)
        self.assertEqual(p.read_text("utf-8"), "only copy")
        self.assertEqual(list((self.root / "data" / ".trash").glob("*")), [])

    def test_soft_delete_move_failure_keeps_source_and_removes_registry_row(self):
        d = self.db()
        p = self._mkfile("move-failure.txt", "only copy")
        with mock.patch.object(trash, "_stash_file_as", side_effect=OSError("move failed")):
            with self.assertRaisesRegex(OSError, "move failed"):
                trash.soft_delete_file(d, "move-failure.txt", p)
        self.assertEqual(p.read_text("utf-8"), "only copy")
        self.assertEqual(d.query(TrashItem).count(), 0)

    def test_recovery_removes_a_pending_trash_row_when_source_was_never_moved(self):
        d = self.db()
        p = self._mkfile("pending-delete.txt", "still live")
        item = trash.record(
            d,
            "file",
            "pending-delete.txt",
            "pending-delete.txt",
            {"trash_name": "pending-delete-stash", "is_dir": False, "state": "pending"},
        )

        self.assertEqual(trash.recover_interrupted_files(d), 1)
        self.assertEqual(p.read_text("utf-8"), "still live")
        self.assertIsNone(d.get(TrashItem, item.id))

    def test_recovery_initializes_an_empty_default_root_before_inspecting_files(self):
        d = self.db()
        d.add(
            StorageLocation(
                id=DEFAULT_LOCAL_STORAGE_LOCATION_ID,
                name="on this server",
                kind="local",
                access="managed",
                root_path="",
                enabled=True,
                is_default=True,
            )
        )
        d.commit()
        stash = trash.stash_path("pending-empty-root-stash")
        stash.write_text("moved safely", "utf-8")
        item = trash.record(
            d,
            "file",
            "pending-empty-root.txt",
            "pending-empty-root.txt",
            {"trash_name": stash.name, "is_dir": False, "state": "pending"},
            location_id=DEFAULT_LOCAL_STORAGE_LOCATION_ID,
        )
        process_dir = self.root / "process"
        process_dir.mkdir()
        collision = process_dir / "pending-empty-root.txt"
        collision.write_text("unrelated process file", "utf-8")
        previous_cwd = Path.cwd()
        try:
            os.chdir(process_dir)
            with mock.patch.object(fs, "root_dir", return_value=(self.root / "files").resolve()):
                self.assertEqual(trash.recover_interrupted_files(d), 1)
        finally:
            os.chdir(previous_cwd)

        d.refresh(item)
        self.assertEqual(json.loads(item.payload)["state"], "ready")
        self.assertEqual(stash.read_text("utf-8"), "moved safely")
        self.assertEqual(collision.read_text("utf-8"), "unrelated process file")
        self.assertEqual(
            d.get(StorageLocation, DEFAULT_LOCAL_STORAGE_LOCATION_ID).root_path,
            str((self.root / "files").resolve()),
        )

    def test_recovery_removes_a_pending_vault_row_when_source_was_never_moved(self):
        d = self.db()
        vault = self.root / "vault"
        source = vault / "Notes" / "pending.md"
        source.parent.mkdir(parents=True)
        source.write_text("still live", "utf-8")
        item = trash.record(
            d,
            "vault",
            "Notes/pending.md",
            "pending.md",
            {"trash_name": "pending-vault-stash", "is_dir": False, "state": "pending"},
        )

        with mock.patch("services.vault_md.root_dir", return_value=vault.resolve()):
            self.assertEqual(trash.recover_interrupted_files(d), 1)

        self.assertEqual(source.read_text("utf-8"), "still live")
        self.assertIsNone(d.get(TrashItem, item.id))

    def test_recovery_finishes_a_pending_vault_row_after_the_move(self):
        d = self.db()
        vault = self.root / "vault"
        vault.mkdir()
        stash = trash.stash_path("pending-vault-stash")
        stash.write_text("moved safely", "utf-8")
        item = trash.record(
            d,
            "vault",
            "Notes/moved.md",
            "moved.md",
            {"trash_name": stash.name, "is_dir": False, "state": "pending"},
        )

        with mock.patch("services.vault_md.root_dir", return_value=vault.resolve()):
            self.assertEqual(trash.recover_interrupted_files(d), 1)

        d.refresh(item)
        self.assertEqual(item.kind, "vault")
        self.assertEqual(json.loads(item.payload)["state"], "ready")
        self.assertEqual(stash.read_text("utf-8"), "moved safely")

    def test_recovery_preserves_both_copies_when_source_reappears_after_stash(self):
        d = self.db()
        source = self._mkfile("recreated.txt", "new sync copy")
        stash = trash.stash_path("recreated-stash")
        stash.write_text("original trashed copy", "utf-8")
        item = trash.record(
            d,
            "file",
            "recreated.txt",
            "recreated.txt",
            {"trash_name": stash.name, "is_dir": False, "state": "pending"},
            location_id=DEFAULT_LOCAL_STORAGE_LOCATION_ID,
        )

        self.assertEqual(trash.recover_interrupted_files(d), 1)

        d.refresh(item)
        payload = json.loads(item.payload)
        self.assertEqual(payload["state"], "conflicted")
        self.assertEqual(source.read_text("utf-8"), "new sync copy")
        self.assertEqual(stash.read_text("utf-8"), "original trashed copy")

    def test_restore_file_brings_back(self):
        d = self.db()
        p = self._mkfile("doc.txt", "keep")
        it = trash.soft_delete_file(d, "doc.txt", p)
        trash.restore_file(d, it, fs.abspath("doc.txt"))
        self.assertTrue((fs.files_dir() / "doc.txt").exists())
        self.assertEqual((fs.files_dir() / "doc.txt").read_text("utf-8"), "keep")
        self.assertEqual(d.query(TrashItem).count(), 0)

    def test_missing_trashed_copy_never_discards_its_registry_row(self):
        d = self.db()
        item = trash.record(
            d,
            "file",
            "missing.txt",
            "missing.txt",
            {"trash_name": "missing.txt", "is_dir": False},
        )
        with self.assertRaises(FileNotFoundError):
            trash.restore_file(d, item, fs.abspath("missing.txt"))
        self.assertEqual(d.query(TrashItem).count(), 1)

    def test_purge_expired_removes_file_and_row(self):
        d = self.db()
        p = self._mkfile("old.txt")
        it = trash.soft_delete_file(d, "old.txt", p)
        it.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
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
        it.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        d.commit()
        r = self.client.post("/api/files/trash/purge")
        self.assertEqual(r.json()["purged"], 1)
