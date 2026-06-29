import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import core.database as db
from core.migrations import m0009_notes_to_vault as m0009
from core.migrations import m0010_drop_note_table as m0010
from core.migrations.runner import run_migrations
from services import notes_vault, vault_md
from tests._client import ApiTest

_DDL = (
    "CREATE TABLE notes (id TEXT PRIMARY KEY, title TEXT DEFAULT '', content TEXT DEFAULT '', "
    "pinned BOOLEAN DEFAULT 0, archived BOOLEAN DEFAULT 0, tags TEXT DEFAULT '', "
    "items TEXT DEFAULT '[]', due TEXT DEFAULT '', created_at DATETIME, updated_at DATETIME)"
)


class NotesMigrationTest(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        with self.eng.begin() as c:  # the legacy notes table (model is gone now)
            c.execute(text(_DDL))
        self._orig_engine = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_vault = vault_md.vault_dir
        vault_md.vault_dir = lambda: self.tmp.resolve()

    def tearDown(self):
        vault_md.vault_dir = self._orig_vault
        shutil.rmtree(self.tmp, ignore_errors=True)
        db.SessionLocal.configure(bind=self._orig_engine)
        db.engine = self._orig_engine
        self.eng.dispose()

    def _seed(self, nid, title, content="", pinned=0, archived=0, tags="", items="[]", due=""):
        with self.eng.begin() as c:
            c.execute(
                text(
                    "INSERT INTO notes (id,title,content,pinned,archived,tags,items,due,created_at,updated_at)"
                    " VALUES (:id,:t,:c,:p,:a,:tg,:it,:d,:ca,:ua)"
                ),
                {"id": nid, "t": title, "c": content, "p": pinned, "a": archived, "tg": tags,
                 "it": items, "d": due, "ca": "2026-06-01 10:00:00", "ua": "2026-06-01 10:00:00"},
            )

    def _has_notes_table(self):
        with self.eng.begin() as c:
            return bool(
                c.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='notes'")).first()
            )

    def test_migration_creates_a_file_per_row(self):
        self._seed("a", "alpha", "first")
        self._seed("b", "beta", "second")
        run_migrations(self.eng, modules=[m0009])
        self.assertEqual(len(notes_vault.all_notes()), 2)
        self.assertTrue(self._has_notes_table())  # m0009 is additive — table stays

    def test_migration_preserves_fields(self):
        self._seed("g", "groceries", "body here", pinned=1, tags="home,urgent",
                   items='[{"text": "milk", "done": true}]', due="2026-07-01")
        run_migrations(self.eng, modules=[m0009])
        got = notes_vault.get("groceries")
        self.assertEqual(got["content"], "body here")
        self.assertTrue(got["pinned"])
        self.assertEqual(got["tags"], ["home", "urgent"])
        self.assertEqual(got["items"], [{"text": "milk", "done": True}])
        self.assertEqual(got["due"], "2026-07-01")

    def test_migration_preserves_archived(self):
        self._seed("o", "old thing", "x", archived=1)
        run_migrations(self.eng, modules=[m0009])
        self.assertTrue(notes_vault.get("old thing")["archived"])

    def test_drop_after_migrate_removes_table(self):
        self._seed("a", "alpha", "x")
        run_migrations(self.eng, modules=[m0009, m0010])
        self.assertFalse(self._has_notes_table())  # dropped once safely in the vault
        self.assertEqual(len(notes_vault.all_notes()), 1)

    def test_drop_skips_when_not_migrated(self):
        self._seed("a", "alpha", "x")
        # run ONLY the drop (no m0009 copy) → guard keeps the table as a safety net
        run_migrations(self.eng, modules=[m0010])
        self.assertTrue(self._has_notes_table())


class BackupVaultTest(ApiTest):
    def test_backup_includes_vault(self):
        import routes.backup as bk

        tmp = Path(tempfile.mkdtemp())
        (tmp / "vault" / "Notes").mkdir(parents=True)
        (tmp / "vault" / "Notes" / "hi.md").write_text("hello", "utf-8")
        orig = bk.DATA_DIR
        bk.DATA_DIR = tmp
        try:
            r = self.client.get("/api/backup")
            self.assertEqual(r.status_code, 200)
            names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
            self.assertIn("vault/Notes/hi.md", names)
        finally:
            bk.DATA_DIR = orig
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
