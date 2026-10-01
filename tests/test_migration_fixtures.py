import hashlib
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from sqlalchemy import create_engine

import cli
from core.database import Base
from core.migrations.runner import (
    PHOTO_FORK_COLUMNS,
    discover,
    migration_catalog,
    run_migrations,
)
from services import notes_vault, vault_md
from services.backup_recovery import (
    current_schema_version,
    refresh_prepared_recovery,
    stage_recovery_archive,
    verify_staged_recovery,
)

FIXTURES = Path(__file__).parent / "fixtures" / "migrations"


def _quoted(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class MigrationFixtureRecoveryTest(unittest.TestCase):
    maxDiff = None

    def _load_fixture(self, root: Path, name: str) -> None:
        root.mkdir(parents=True)
        with closing(sqlite3.connect(root / "aide.db")) as conn:
            conn.executescript((FIXTURES / name).read_text("utf-8"))
        self._add_managed_files(root)

    @staticmethod
    def _add_managed_files(root: Path) -> None:
        (root / "vault" / "Notes").mkdir(parents=True, exist_ok=True)
        (root / "vault" / "Existing.md").write_text(
            "# existing\n\nSynthetic vault sentinel.\n", "utf-8"
        )
        (root / "files").mkdir(exist_ok=True)
        (root / "files" / "sentinel.bin").write_bytes(b"alles-migration-file-sentinel\x00")
        (root / "photos" / ".thumbs").mkdir(parents=True, exist_ok=True)
        (root / "photos" / "fixture-photo.jpg").write_bytes(b"synthetic-photo-original")
        (root / "photos" / ".thumbs" / "fixture-photo-thumb.jpg").write_bytes(
            b"synthetic-photo-thumbnail"
        )
        (root / "settings.json").write_text('{"theme":"dark"}', "utf-8")

    @staticmethod
    def _snapshot_database(path: Path) -> dict:
        snapshot = {}
        with closing(sqlite3.connect(path)) as conn:
            tables = sorted(
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            )
            for table in tables:
                columns = [row[1] for row in conn.execute(f"PRAGMA table_info({_quoted(table)})")]
                select = ",".join(_quoted(column) for column in columns)
                rows = conn.execute(
                    f"SELECT {select} FROM {_quoted(table)} ORDER BY rowid"
                ).fetchall()
                snapshot[table] = {"columns": columns, "rows": rows}
        return snapshot

    @staticmethod
    def _hash_managed_files(root: Path) -> dict[str, str]:
        hashes = {}
        excluded = {"aide.db", "aide.db-wal", "aide.db-shm", "aide.db-journal"}
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name not in excluded:
                hashes[path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        return hashes

    @staticmethod
    def _legacy_archive(source: Path, archive: Path) -> None:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            for path in sorted(source.rglob("*")):
                if path.is_file() and path.name not in {
                    "aide.db-wal",
                    "aide.db-shm",
                    "aide.db-journal",
                }:
                    output.write(path, path.relative_to(source).as_posix())

    @staticmethod
    def _rows_using_old_columns(path: Path, before: dict) -> dict:
        rows = {}
        with closing(sqlite3.connect(path)) as conn:
            actual_tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table, item in before.items():
                if table in {"notes", "schema_migrations"}:
                    continue
                if table not in actual_tables:
                    raise AssertionError(f"migration removed table {table}")
                select = ",".join(_quoted(column) for column in item["columns"])
                rows[table] = conn.execute(
                    f"SELECT {select} FROM {_quoted(table)} ORDER BY rowid"
                ).fetchall()
        return rows

    def _assert_current_schema_and_history(self, data_root: Path) -> None:
        expected_columns = {
            name: {column.name for column in table.columns}
            for name, table in Base.metadata.tables.items()
        }
        with closing(sqlite3.connect(data_root / "aide.db")) as conn:
            actual_tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertNotIn("notes", actual_tables)
            for table, expected in expected_columns.items():
                self.assertIn(table, actual_tables)
                actual = {row[1] for row in conn.execute(f"PRAGMA table_info({_quoted(table)})")}
                self.assertFalse(expected - actual, f"{table} missing {sorted(expected - actual)}")

            history = conn.execute(
                "SELECT version,name FROM schema_migrations ORDER BY version"
            ).fetchall()
            catalog = migration_catalog()
            expected_history = [(version, catalog[version]) for version in sorted(catalog)]
            self.assertEqual(history, expected_history)
            self.assertEqual(history[-1][0], current_schema_version())
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertIsNone(conn.execute("PRAGMA foreign_key_check").fetchone())

            photo_columns = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
            self.assertTrue(
                {"source", "source_id", "source_asset_id", "source_modified_at"}.issubset(
                    photo_columns
                )
            )
            mail_columns = {row[1] for row in conn.execute("PRAGMA table_info(cached_messages)")}
            self.assertTrue({"recipients", "has_attachment"}.issubset(mail_columns))

    def _recover_and_check(self, source: Path, base: Path) -> None:
        before_db = self._snapshot_database(source / "aide.db")
        preserved_db = {
            table: item
            for table, item in before_db.items()
            if table not in {"notes", "schema_migrations"} and item["rows"]
        }
        before_rows = {table: item["rows"] for table, item in preserved_db.items()}
        note_ids = {
            row[0]
            for row in before_db.get("notes", {}).get("rows", [])
            if row and isinstance(row[0], str)
        }
        before_files = self._hash_managed_files(source)

        live = base / "live"
        live.mkdir()
        archive = base / "legacy.zip"
        self._legacy_archive(source, archive)
        staged = stage_recovery_archive(archive, live)

        cli._prepare_staged_candidate(staged, live)
        prepared = refresh_prepared_recovery(live, staged.restore_id)
        verify_staged_recovery(live, staged.restore_id)
        self.assertTrue(cli._run_recovery_probe(prepared.data_dir, passes=1))

        self._assert_current_schema_and_history(prepared.data_dir)
        self.assertEqual(
            self._rows_using_old_columns(prepared.data_dir / "aide.db", preserved_db),
            before_rows,
        )
        after_files = self._hash_managed_files(prepared.data_dir)
        for path, digest in before_files.items():
            self.assertEqual(after_files.get(path), digest, path)

        original_vault_dir = vault_md.vault_dir
        vault_md.vault_dir = lambda: (prepared.data_dir / "vault").resolve()
        try:
            self.assertTrue(note_ids.issubset(notes_vault.existing_legacy_ids()))
        finally:
            vault_md.vault_dir = original_vault_dir

        stable_rows = self._snapshot_database(prepared.data_dir / "aide.db")
        stable_files = self._hash_managed_files(prepared.data_dir)
        self.assertTrue(cli._run_recovery_probe(prepared.data_dir, passes=1))
        self.assertEqual(self._snapshot_database(prepared.data_dir / "aide.db"), stable_rows)
        self.assertEqual(self._hash_managed_files(prepared.data_dir), stable_files)

    def _materialize_canonical_prefix(self, root: Path, version: int) -> None:
        engine = create_engine(f"sqlite:///{root / 'aide.db'}")
        Base.metadata.create_all(engine)
        original_vault_dir = vault_md.vault_dir
        vault_md.vault_dir = lambda: (root / "vault").resolve()
        try:
            modules = [module for module in discover() if module.VERSION <= version]
            run_migrations(engine, modules=modules)
        finally:
            vault_md.vault_dir = original_vault_dir
            engine.dispose()

    @staticmethod
    def _trim_photo_fork(root: Path, version: int) -> None:
        with closing(sqlite3.connect(root / "aide.db")) as conn:
            for later in range(13, version, -1):
                for column in PHOTO_FORK_COLUMNS[later]:
                    conn.execute(f"ALTER TABLE photos DROP COLUMN {_quoted(column)}")
            conn.execute("DELETE FROM schema_migrations WHERE version > ?", (version,))
            conn.commit()

    def test_released_no_history_schemas_restore_migrate_twice_and_boot(self):
        for fixture in ("beta-0.1.0.sql", "late-legacy-v0.sql"):
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                source = base / "source"
                self._load_fixture(source, fixture)
                self._recover_and_check(source, base)

    def test_every_canonical_prefix_restores_migrates_twice_and_boots(self):
        for version in range(1, current_schema_version() + 1):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                source = base / "source"
                self._load_fixture(source, "late-legacy-v0.sql")
                self._materialize_canonical_prefix(source, version)
                self._recover_and_check(source, base)

    def test_every_photo_fork_prefix_restores_migrates_twice_and_boots(self):
        for version in range(9, 14):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                source = base / "source"
                self._load_fixture(source, "photo-fork-v13.sql")
                self._trim_photo_fork(source, version)
                self._recover_and_check(source, base)


if __name__ == "__main__":
    unittest.main()
