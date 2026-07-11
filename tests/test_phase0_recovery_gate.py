import hashlib
import io
import os
import shutil
import socket
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import cli
from services.backup_recovery import create_recovery_archive, current_schema_version, staging_root
from services.recovery_crypto import (
    encrypt_recovery_archive,
    load_or_create_recovery_key,
    recovery_key_document,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhaseZeroRecoveryGateTest(unittest.TestCase):
    def test_encrypted_repository_and_exported_key_recover_after_source_is_destroyed(self):
        """Exercise the Phase 0 gate without access to the source installation."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source-install" / "data"
            repository = base / "backup-repository"
            key_store = base / "owner-key-store"
            clean_target = base / "clean-release" / "data"
            for path in (source, repository, key_store, clean_target):
                path.mkdir(parents=True)
            for root in (source, clean_target):
                (root / "vault" / "Notes").mkdir(parents=True)
                (root / "files").mkdir()
                self.assertTrue(cli._run_recovery_probe(root, passes=1))

            note = source / "vault" / "Notes" / "recovery-gate.md"
            managed_file = source / "files" / "recovery-gate.bin"
            note.write_text("# recovery gate\n\nsynthetic content\n", "utf-8")
            managed_file.write_bytes(b"alles-phase-zero\x00recovery-gate")
            expected_hashes = {
                "vault/Notes/recovery-gate.md": _sha256(note),
                "files/recovery-gate.bin": _sha256(managed_file),
            }

            database = source / "aide.db"
            with (
                closing(sqlite3.connect(database)) as writer,
                closing(sqlite3.connect(database)) as old_reader,
            ):
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("CREATE TABLE phase0_gate_rows (value TEXT NOT NULL)")
                writer.execute("INSERT INTO phase0_gate_rows VALUES ('before-reader')")
                writer.commit()
                old_reader.execute("PRAGMA journal_mode=WAL")
                old_reader.execute("BEGIN")
                self.assertEqual(
                    old_reader.execute("SELECT COUNT(*) FROM phase0_gate_rows").fetchone()[0],
                    1,
                )
                writer.execute("INSERT INTO phase0_gate_rows VALUES ('committed-in-wal')")
                writer.commit()
                self.assertTrue((source / "aide.db-wal").exists())

                key = load_or_create_recovery_key(source)
                plaintext = base / "staged-recovery.zip"
                encrypted = repository / "phase-zero.alles-backup"
                exported_key = key_store / "alles-recovery-key.txt"
                create_recovery_archive(source, plaintext)
                encrypt_recovery_archive(plaintext, encrypted, key)
                exported_key.write_bytes(recovery_key_document(key))
                plaintext.unlink()

            self.assertTrue(encrypted.is_file())
            self.assertTrue(exported_key.is_file())
            shutil.rmtree(source.parent)
            self.assertFalse(source.exists())

            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ALLES_DATA": str(clean_target),
                        "ALLES_DB": "",
                        "ALLES_HOST": "127.0.0.1",
                        "AUTH_ENABLED": "false",
                        "PYTHON_DOTENV_DISABLED": "1",
                        "PORT": str(port),
                    },
                ),
                mock.patch.object(cli, "PID_FILE", clean_target / "alles.pid"),
                mock.patch.object(cli, "LOG_FILE", clean_target / "alles-server.log"),
                mock.patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertTrue(
                    cli.cmd_restore(("stage", str(encrypted), "--key", str(exported_key)))
                )
                staged_root = staging_root(clean_target) / "staged"
                restore_ids = [path.name for path in staged_root.iterdir() if path.is_dir()]
                self.assertEqual(len(restore_ids), 1)
                self.assertTrue(cli.cmd_restore(("apply", restore_ids[0])))

            self.assertFalse(source.exists())
            self.assertTrue(cli._run_recovery_probe(clean_target, passes=1))
            with closing(sqlite3.connect(clean_target / "aide.db")) as recovered:
                self.assertEqual(
                    recovered.execute("SELECT COUNT(*) FROM phase0_gate_rows").fetchone()[0],
                    2,
                )
                self.assertEqual(recovered.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertIsNone(recovered.execute("PRAGMA foreign_key_check").fetchone())
                history = recovered.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
                self.assertEqual(
                    [row[0] for row in history],
                    list(range(1, current_schema_version() + 1)),
                )
            for relative, expected in expected_hashes.items():
                self.assertEqual(_sha256(clean_target / relative), expected)


if __name__ == "__main__":
    unittest.main()
