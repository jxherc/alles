import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import core.database as db
from core.database import Note
from core.migrations import m0009_notes_to_vault as m0009
from core.migrations.runner import run_migrations
from services import notes_vault, vault_md
from tests._client import ApiTest


class NotesMigrationTest(unittest.TestCase):
    def setUp(self):
        self.eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.Base.metadata.create_all(self.eng)
        self._orig_engine = db.engine
        db.engine = self.eng
        db.SessionLocal.configure(bind=self.eng)
        self.s = db.SessionLocal()
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_vault = vault_md.vault_dir
        vault_md.vault_dir = lambda: self.tmp.resolve()

    def tearDown(self):
        self.s.close()
        vault_md.vault_dir = self._orig_vault
        shutil.rmtree(self.tmp, ignore_errors=True)
        db.SessionLocal.configure(bind=self._orig_engine)
        db.engine = self._orig_engine
        self.eng.dispose()

    def _seed(self, **kw):
        n = Note(**kw)
        self.s.add(n)
        self.s.commit()
        return n

    def test_migration_creates_a_file_per_row(self):
        self._seed(title="alpha", content="first")
        self._seed(title="beta", content="second")
        run_migrations(self.eng, modules=[m0009])
        self.assertEqual(len(notes_vault.all_notes()), 2)
        # the notes table is untouched (DB stays a backup)
        self.assertEqual(self.s.query(Note).count(), 2)

    def test_migration_preserves_fields(self):
        self._seed(
            title="groceries", content="body here", pinned=True, archived=False,
            tags="home,urgent", items=json.dumps([{"text": "milk", "done": True}]), due="2026-07-01",
        )
        run_migrations(self.eng, modules=[m0009])
        got = notes_vault.get("groceries")
        self.assertEqual(got["content"], "body here")
        self.assertTrue(got["pinned"])
        self.assertEqual(got["tags"], ["home", "urgent"])
        self.assertEqual(got["items"], [{"text": "milk", "done": True}])
        self.assertEqual(got["due"], "2026-07-01")

    def test_migration_preserves_archived(self):
        self._seed(title="old thing", content="x", archived=True)
        run_migrations(self.eng, modules=[m0009])
        self.assertTrue(notes_vault.get("old thing")["archived"])

    def test_migration_idempotent(self):
        self._seed(title="once", content="x")
        run_migrations(self.eng, modules=[m0009])
        # second run must not create a duplicate (matched by legacy_id)
        m0009.up(self.eng.connect())  # call up() directly so it re-runs even though recorded
        self.assertEqual(len(notes_vault.all_notes()), 1)

    def test_migration_plan_dry_run(self):
        self._seed(title="planme", content="x")
        plan = notes_vault.migration_plan(self.s)
        self.assertEqual(plan, [{"id": plan[0]["id"], "target": "Notes/planme.md", "action": "create"}])
        # writing nothing yet
        self.assertEqual(len(notes_vault.all_notes()), 0)
        run_migrations(self.eng, modules=[m0009])
        self.assertEqual(notes_vault.migration_plan(self.s)[0]["action"], "skip")


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
