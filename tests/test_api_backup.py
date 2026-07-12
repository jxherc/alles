import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

import routes.backup as bk
from services.backup_recovery import (
    ArchiveLimits,
    create_recovery_archive,
    staging_root,
)
from services.recovery_crypto import (
    decrypt_recovery_container,
    encrypt_recovery_archive,
    load_or_create_recovery_key,
    load_recovery_key,
    parse_recovery_key,
    recovery_key_document,
    recovery_key_path,
)
from tests._client import ApiTest


class BackupApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.data = self.base / "data"
        self.data.mkdir()
        self._make_db(self.data / "aide.db")
        (self.data / "settings.json").write_text('{"x":1}', "utf-8")
        self._orig = bk.DATA_DIR
        self._orig_limits = bk.BACKUP_LIMITS
        self._export_index = 0
        bk.DATA_DIR = self.data

    def tearDown(self):
        bk.DATA_DIR = self._orig
        bk.BACKUP_LIMITS = self._orig_limits
        self._tmp.cleanup()
        super().tearDown()

    @staticmethod
    def _make_db(path: Path, *, value: str = "original"):
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute(
                "INSERT INTO schema_migrations VALUES (1, 'baseline', '2026-01-01T00:00:00')"
            )
            conn.execute("CREATE TABLE backup_fixture (value TEXT)")
            conn.execute("INSERT INTO backup_fixture VALUES (?)", (value,))
            conn.commit()

    def _legacy_zip(self, *, db_path: Path | None = None, members=None) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_path or (self.data / "aide.db"), "aide.db")
            for name, content in (members or {}).items():
                zf.writestr(name, content)
        return buf.getvalue()

    def _decrypt_export(self, response) -> bytes:
        self._export_index += 1
        container = self.base / f"export-{self._export_index}.alles-backup"
        plain = self.base / f"export-{self._export_index}.zip"
        container.write_bytes(response.content)
        decrypt_recovery_container(
            container, plain, load_recovery_key(recovery_key_path(self.data))
        )
        return plain.read_bytes()

    def test_export_returns_encrypted_v1_backup_with_manifest_and_db(self):
        response = self.client.get("/api/backup")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/vnd.alles.backup")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.content.startswith(b"ALLES-BACKUP-V1\0"))
        self.assertNotIn(recovery_key_path(self.data).read_bytes(), response.content)
        with zipfile.ZipFile(io.BytesIO(self._decrypt_export(response))) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            self.assertEqual(manifest["format"], "alles-recovery")
            self.assertEqual(manifest["format_version"], 1)
            self.assertIn("payload/data/aide.db", zf.namelist())
            self.assertIn("payload/data/settings.json", zf.namelist())
            self.assertIn("payload/data/recovery.key", zf.namelist())

    def test_restore_stages_valid_backup_without_touching_live_data_or_sidecars(self):
        restored_db = self.base / "restored.db"
        self._make_db(restored_db, value="restored")
        original_db = (self.data / "aide.db").read_bytes()
        (self.data / "aide.db-wal").write_bytes(b"live-wal")
        (self.data / "aide.db-shm").write_bytes(b"live-shm")
        archive = self._legacy_zip(db_path=restored_db, members={"uploads/a.txt": b"staged-only"})

        response = self.client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", archive, "application/zip")},
        )

        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["status"], "staged")
        self.assertTrue(body["requires_offline_apply"])
        self.assertNotIn("path", body)
        self.assertEqual((self.data / "aide.db").read_bytes(), original_db)
        self.assertFalse((self.data / "uploads" / "a.txt").exists())
        self.assertEqual((self.data / "aide.db-wal").read_bytes(), b"live-wal")
        self.assertEqual((self.data / "aide.db-shm").read_bytes(), b"live-shm")

        staged = staging_root(self.data) / "staged" / body["restore_id"] / "data"
        self.assertEqual((staged / "uploads" / "a.txt").read_bytes(), b"staged-only")
        with closing(sqlite3.connect(staged / "aide.db")) as conn:
            value = conn.execute("SELECT value FROM backup_fixture").fetchone()[0]
        self.assertEqual(value, "restored")

    def test_restore_status_and_cancel_only_manage_the_stage(self):
        archive = self._legacy_zip()
        staged = self.client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", archive, "application/zip")},
        ).json()
        restore_id = staged["restore_id"]

        status = self.client.get(f"/api/backup/restores/{restore_id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "staged")

        cancelled = self.client.delete(f"/api/backup/restores/{restore_id}")
        self.assertEqual(cancelled.status_code, 200)
        self.assertFalse((staging_root(self.data) / "staged" / restore_id).exists())
        self.assertTrue((self.data / "aide.db").is_file())

    def test_restore_rejects_non_zip_without_leaving_a_stage(self):
        response = self.client.post(
            "/api/backup/restore",
            files={"file": ("x.txt", b"not a zip", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list((staging_root(self.data) / "staged").glob("*")), [])

    def test_restore_rejects_zip_without_db(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("random.txt", b"x")
        response = self.client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", buf.getvalue(), "application/zip")},
        )
        self.assertEqual(response.status_code, 400)

    def test_restore_rejects_empty(self):
        response = self.client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", b"", "application/zip")},
        )
        self.assertEqual(response.status_code, 400)

    def test_restore_blocks_late_zip_slip_without_partial_or_live_writes(self):
        original_db = (self.data / "aide.db").read_bytes()
        archive = self._legacy_zip(
            members={"uploads/partial.txt": b"partial", "../escape.txt": b"evil"}
        )

        response = self.client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", archive, "application/zip")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual((self.data / "aide.db").read_bytes(), original_db)
        self.assertFalse((self.data / "uploads" / "partial.txt").exists())
        self.assertFalse((self.base / "escape.txt").exists())
        self.assertEqual(list((staging_root(self.data) / "staged").glob("*")), [])

    def test_restore_rejects_oversized_upload_while_streaming(self):
        bk.BACKUP_LIMITS = ArchiveLimits(max_archive_bytes=10)
        response = self.client.post(
            "/api/backup/restore",
            files={"file": ("backup.zip", b"x" * 11, "application/zip")},
        )
        self.assertEqual(response.status_code, 413)
        incoming = staging_root(self.data) / "incoming"
        self.assertEqual(list(incoming.glob("*")), [])

    def test_cross_site_backup_read_and_restore_are_rejected(self):
        headers = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        self.assertEqual(self.client.get("/api/backup", headers=headers).status_code, 403)
        self.assertEqual(
            self.client.get("/api/backup/recovery-key", headers=headers).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                "/api/backup/restore",
                headers=headers,
                files={"file": ("backup.zip", self._legacy_zip(), "application/zip")},
            ).status_code,
            403,
        )

    def test_export_includes_managed_data_root_files(self):
        (self.data / "uploads").mkdir()
        (self.data / "uploads" / "photo.jpg").write_bytes(b"jpeg-data")
        (self.data / "vault_attachments").mkdir()
        (self.data / "vault_attachments" / "abc.enc").write_bytes(b"ciphertext")
        response = self.client.get("/api/backup")
        with zipfile.ZipFile(io.BytesIO(self._decrypt_export(response))) as zf:
            self.assertIn("payload/data/uploads/photo.jpg", zf.namelist())
            self.assertIn("payload/data/vault_attachments/abc.enc", zf.namelist())

    def test_export_snapshot_includes_recent_committed_wal_rows(self):
        dbfile = self.data / "aide.db"
        dbfile.unlink()
        with closing(sqlite3.connect(dbfile)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', '')")
            conn.execute("CREATE TABLE t (x TEXT)")
            conn.execute("INSERT INTO t VALUES ('hello-wal')")
            conn.commit()
            response = self.client.get("/api/backup")

        with zipfile.ZipFile(io.BytesIO(self._decrypt_export(response))) as zf:
            backed = zf.read("payload/data/aide.db")
        out = self.base / "restored.db"
        out.write_bytes(backed)
        with closing(sqlite3.connect(out)) as conn:
            rows = conn.execute("SELECT x FROM t").fetchall()
        self.assertEqual(rows, [("hello-wal",)])

    def test_export_keeps_committed_wal_row_while_an_old_reader_is_active(self):
        dbfile = self.data / "aide.db"
        dbfile.unlink()
        with closing(sqlite3.connect(dbfile)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            writer.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            writer.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            writer.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', '')")
            writer.execute("CREATE TABLE t (x TEXT)")
            writer.execute("INSERT INTO t VALUES ('before-reader')")
            writer.commit()

            with closing(sqlite3.connect(dbfile)) as reader:
                reader.execute("BEGIN")
                reader.execute("SELECT x FROM t").fetchall()
                writer.execute("INSERT INTO t VALUES ('committed-during-reader')")
                writer.commit()
                response = self.client.get("/api/backup")

        with zipfile.ZipFile(io.BytesIO(self._decrypt_export(response))) as zf:
            backed = zf.read("payload/data/aide.db")
        out = self.base / "reader-safe.db"
        out.write_bytes(backed)
        with closing(sqlite3.connect(out)) as conn:
            rows = conn.execute("SELECT x FROM t ORDER BY rowid").fetchall()
        self.assertEqual(rows, [("before-reader",), ("committed-during-reader",)])

    def test_export_content_disposition_and_temp_cleanup(self):
        response = self.client.get("/api/backup")
        disposition = response.headers.get("content-disposition", "")
        self.assertIn("attachment", disposition)
        self.assertIn(".alles-backup", disposition)
        exports = staging_root(self.data) / "exports"
        self.assertEqual(list(exports.glob("*")), [])

    def test_recovery_key_can_be_exported_separately(self):
        response = self.client.get("/api/backup/recovery-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            parse_recovery_key(response.content),
            load_recovery_key(recovery_key_path(self.data)),
        )
        self.assertIn("attachment", response.headers["content-disposition"])

    def test_encrypted_backup_can_be_staged_with_the_live_recovery_key(self):
        encrypted = self.client.get("/api/backup").content
        response = self.client.post(
            "/api/backup/restore",
            files={
                "file": (
                    "backup.alles-backup",
                    encrypted,
                    "application/vnd.alles.backup",
                )
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "staged")

    def test_andromeda_saved_search_survives_encrypted_export_and_staging(self):
        with closing(sqlite3.connect(self.data / "aide.db")) as conn:
            conn.execute(
                "CREATE TABLE andromeda_saved_searches ("
                "id TEXT PRIMARY KEY, query TEXT, results_json TEXT, overview_json TEXT, "
                "evidence_json TEXT, model_json TEXT)"
            )
            conn.execute(
                "INSERT INTO andromeda_saved_searches VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "saved-1",
                    "current package version",
                    '[{"url":"https://example.com"}]',
                    '{"status":"ready"}',
                    '[{"id":"s1","passages":["exact passage"]}]',
                    '{"model":"local"}',
                ),
            )
            conn.commit()

        encrypted = self.client.get("/api/backup").content
        response = self.client.post(
            "/api/backup/restore",
            files={
                "file": (
                    "andromeda.alles-backup",
                    encrypted,
                    "application/vnd.alles.backup",
                )
            },
        )

        self.assertEqual(response.status_code, 202)
        staged_db = (
            staging_root(self.data) / "staged" / response.json()["restore_id"] / "data" / "aide.db"
        )
        with closing(sqlite3.connect(staged_db)) as conn:
            row = conn.execute(
                "SELECT query, evidence_json, model_json FROM andromeda_saved_searches WHERE id = ?",
                ("saved-1",),
            ).fetchone()
        self.assertEqual(row[0], "current package version")
        self.assertIn("exact passage", row[1])
        self.assertIn("local", row[2])

    def test_phase_three_settings_survive_encrypted_export_and_staging(self):
        settings = {
            "today_layout": {
                "order": ["needs_you", "briefs", "today", "in_progress", "shortcuts"],
                "visible": ["needs_you", "today", "shortcuts"],
                "density": "compact",
                "shortcuts": ["tasks", "wiki"],
            },
            "default_chat_behavior": "answer_only",
            "owner_instructions": "keep answers compact",
            "model_roles": {
                "aide_chat": {"endpoint_id": "local", "model": "chat"},
                "andromeda": {"endpoint_id": "local", "model": "search"},
                "jarvis": {"endpoint_id": "local", "model": "work"},
            },
        }
        (self.data / "settings.json").write_text(json.dumps(settings), "utf-8")

        encrypted = self.client.get("/api/backup").content
        response = self.client.post(
            "/api/backup/restore",
            files={
                "file": (
                    "phase-three.alles-backup",
                    encrypted,
                    "application/vnd.alles.backup",
                )
            },
        )

        self.assertEqual(response.status_code, 202)
        staged = (
            staging_root(self.data)
            / "staged"
            / response.json()["restore_id"]
            / "data"
            / "settings.json"
        )
        self.assertEqual(json.loads(staged.read_text("utf-8")), settings)

    def test_encrypted_backup_accepts_a_separately_uploaded_recovery_key(self):
        external = self.base / "external-data"
        external.mkdir()
        self._make_db(external / "aide.db", value="external")
        (external / "vault").mkdir()
        (external / "files").mkdir()
        external_key = load_or_create_recovery_key(external)
        plain = self.base / "external.zip"
        encrypted = self.base / "external.alles-backup"
        create_recovery_archive(external, plain)
        encrypt_recovery_archive(plain, encrypted, external_key)

        response = self.client.post(
            "/api/backup/restore",
            files={
                "file": (
                    "external.alles-backup",
                    encrypted.read_bytes(),
                    "application/vnd.alles.backup",
                ),
                "recovery_key": (
                    "alles-recovery-key.txt",
                    recovery_key_document(external_key),
                    "text/plain",
                ),
            },
        )
        self.assertEqual(response.status_code, 202)

    def test_encrypted_backup_rejects_a_different_inner_recovery_key(self):
        external = self.base / "mismatched-data"
        external.mkdir()
        self._make_db(external / "aide.db", value="external")
        inner_key = load_or_create_recovery_key(external)
        outer_key = bytes(value ^ 0xFF for value in inner_key)
        plain = self.base / "mismatched.zip"
        encrypted = self.base / "mismatched.alles-backup"
        create_recovery_archive(external, plain)
        encrypt_recovery_archive(plain, encrypted, outer_key)

        response = self.client.post(
            "/api/backup/restore",
            files={
                "file": (
                    "mismatched.alles-backup",
                    encrypted.read_bytes(),
                    "application/vnd.alles.backup",
                ),
                "recovery_key": (
                    "alles-recovery-key.txt",
                    recovery_key_document(outer_key),
                    "text/plain",
                ),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list((staging_root(self.data) / "staged").glob("*")), [])


if __name__ == "__main__":
    unittest.main()
