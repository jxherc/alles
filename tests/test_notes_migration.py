import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import core.database as db
from core.migrations import m0009_notes_to_vault as m0009
from core.migrations import m0010_drop_note_table as m0010
from core.migrations.runner import MigrationBlockedError, run_migrations
from services import notes_vault, vault_md
from services.recovery_crypto import decrypt_recovery_container, load_recovery_key
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
                {
                    "id": nid,
                    "t": title,
                    "c": content,
                    "p": pinned,
                    "a": archived,
                    "tg": tags,
                    "it": items,
                    "d": due,
                    "ca": "2026-06-01 10:00:00",
                    "ua": "2026-06-01 10:00:00",
                },
            )

    def _has_notes_table(self):
        with self.eng.begin() as c:
            return bool(
                c.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='notes'")
                ).first()
            )

    def test_migration_creates_a_file_per_row(self):
        self._seed("a", "alpha", "first")
        self._seed("b", "beta", "second")
        run_migrations(self.eng, modules=[m0009])
        self.assertEqual(len(notes_vault.all_notes()), 2)
        self.assertTrue(self._has_notes_table())  # m0009 is additive — table stays

    def test_migration_preserves_fields(self):
        self._seed(
            "g",
            "groceries",
            "body here",
            pinned=1,
            tags="home,urgent",
            items='[{"text": "milk", "done": true}]',
            due="2026-07-01",
        )
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

    def test_beta_note_shape_gets_missing_optional_fields_before_copy(self):
        with self.eng.begin() as c:
            c.execute(text("DROP TABLE notes"))
            c.execute(
                text(
                    "CREATE TABLE notes (id TEXT PRIMARY KEY, title TEXT, content TEXT, "
                    "pinned BOOLEAN DEFAULT 0, archived BOOLEAN DEFAULT 0, created_at DATETIME)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO notes(id,title,content,pinned,archived,created_at) "
                    "VALUES ('beta-note','beta','kept',1,0,'2025-01-01')"
                )
            )

        run_migrations(self.eng, modules=[m0009])

        with self.eng.connect() as c:
            columns = {row[1] for row in c.execute(text("PRAGMA table_info(notes)"))}
        self.assertTrue({"tags", "items", "due"}.issubset(columns))
        migrated = notes_vault.get("beta")
        self.assertEqual(migrated["content"], "kept")
        self.assertEqual(migrated["items"], [])

    def test_drop_after_migrate_removes_table(self):
        self._seed("a", "alpha", "x")
        run_migrations(self.eng, modules=[m0009, m0010])
        self.assertFalse(self._has_notes_table())  # dropped once safely in the vault
        self.assertEqual(len(notes_vault.all_notes()), 1)

    def test_drop_skips_when_not_migrated(self):
        self._seed("a", "alpha", "x")
        # run ONLY the drop (no m0009 copy) → migration remains pending instead of recording
        # a false success that future boots would skip.
        with self.assertRaises(MigrationBlockedError):
            run_migrations(self.eng, modules=[m0010])
        self.assertTrue(self._has_notes_table())
        with self.eng.connect() as c:
            recorded = c.execute(text("SELECT 1 FROM schema_migrations WHERE version = 10")).first()
        self.assertIsNone(recorded)


class BackupVaultTest(ApiTest):
    def test_backup_includes_vault(self):
        import routes.backup as bk

        tmp = Path(tempfile.mkdtemp())
        (tmp / "vault" / "Notes").mkdir(parents=True)
        (tmp / "vault" / "Notes" / "hi.md").write_text("hello", "utf-8")
        with closing(sqlite3.connect(tmp / "aide.db")) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', '')")
            conn.commit()
        orig = bk.DATA_DIR
        bk.DATA_DIR = tmp
        try:
            r = self.client.get("/api/backup")
            self.assertEqual(r.status_code, 200)
            encrypted = tmp / "download.alles-backup"
            plaintext = tmp / "download.zip"
            encrypted.write_bytes(r.content)
            decrypt_recovery_container(
                encrypted, plaintext, load_recovery_key(tmp / "recovery.key")
            )
            with zipfile.ZipFile(plaintext) as archive:
                names = archive.namelist()
            self.assertIn("payload/data/vault/Notes/hi.md", names)
        finally:
            bk.DATA_DIR = orig
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
