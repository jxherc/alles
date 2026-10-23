import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

import cli
from services.backup_recovery import (
    create_recovery_archive,
    current_schema_version,
    refresh_prepared_recovery,
    stage_recovery_archive,
    verify_staged_recovery,
)
from services.recovery_crypto import (
    encrypt_recovery_archive,
    load_or_create_recovery_key,
    recovery_key_document,
)
from services.restore_apply import maintenance_lock_path


class RecoveryPreflightIntegrationTest(unittest.TestCase):
    def test_direct_app_start_refuses_an_unfinished_restore_before_creating_a_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "data"
            live.mkdir()
            lock = maintenance_lock_path(live)
            lock.parent.mkdir(parents=True)
            lock.write_text("{}", "utf-8")
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            env = os.environ.copy()
            env.update(
                {
                    "ALLES_DATA": str(live),
                    "ALLES_DB": str(live / "aide.db"),
                    "ALLES_HOST": "127.0.0.1",
                    "AUTH_ENABLED": "false",
                    "PORT": str(port),
                }
            )
            env.pop("ALLES_RECOVERY_PREFLIGHT", None)
            proc = subprocess.run(
                [sys.executable, "app.py"],
                cwd=Path(__file__).parent.parent,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse((live / "aide.db").exists())

    def test_real_app_migrates_and_health_checks_twice_in_isolated_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            live = base / "data"
            live.mkdir()
            (live / "vault").mkdir()
            (live / "files").mkdir()
            self.assertTrue(cli._run_recovery_probe(live, passes=1))

            archive = base / "backup.zip"
            create_recovery_archive(live, archive)
            staged = stage_recovery_archive(archive, live)

            cli._prepare_staged_candidate(staged, live)
            prepared = refresh_prepared_recovery(live, staged.restore_id)
            verified = verify_staged_recovery(live, staged.restore_id)

            self.assertEqual(prepared.state, "prepared")
            self.assertEqual(verified.state, "prepared")
            self.assertFalse((prepared.data_dir / "aide.db-wal").exists())
            self.assertFalse((prepared.data_dir / "aide.db-shm").exists())
            with closing(sqlite3.connect(prepared.data_dir / "aide.db")) as conn:
                versions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(versions[-1], current_schema_version())
            self.assertEqual(versions, list(range(1, current_schema_version() + 1)))
            self.assertEqual(integrity, "ok")

    def test_full_cli_apply_uses_real_probes_and_keeps_the_original_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            live = base / "data"
            source = base / "source"
            for root in (live, source):
                root.mkdir()
                (root / "vault").mkdir()
                (root / "files").mkdir()
                self.assertTrue(cli._run_recovery_probe(root, passes=1))

            for root, value in ((live, "old"), (source, "new")):
                with closing(sqlite3.connect(root / "aide.db")) as conn:
                    conn.execute("CREATE TABLE restore_marker (value TEXT)")
                    conn.execute("INSERT INTO restore_marker VALUES (?)", (value,))
                    conn.commit()

            archive = base / "source-backup.zip"
            encrypted = base / "source-backup.alles-backup"
            exported_key = base / "alles-recovery-key.txt"
            key = load_or_create_recovery_key(source)
            create_recovery_archive(source, archive)
            encrypt_recovery_archive(archive, encrypted, key)
            exported_key.write_bytes(recovery_key_document(key))
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]

            with (
                mock.patch.dict(
                    cli.os.environ,
                    {"ALLES_DATA": str(live), "ALLES_DB": "", "PORT": str(port)},
                ),
                mock.patch.object(cli, "PID_FILE", live / "alles.pid"),
                mock.patch.object(cli, "LOG_FILE", live / "alles-server.log"),
                mock.patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertTrue(
                    cli.cmd_restore(("stage", str(encrypted), "--key", str(exported_key)))
                )
                stage_ids = [path.name for path in (base / ".data-recovery" / "staged").iterdir()]
                self.assertEqual(len(stage_ids), 1)
                applied = cli.cmd_restore(("apply", stage_ids[0]))

            self.assertTrue(applied)
            with closing(sqlite3.connect(live / "aide.db")) as conn:
                self.assertEqual(
                    conn.execute("SELECT value FROM restore_marker").fetchone()[0], "new"
                )

            journals = list((base / ".data-recovery" / "operations").glob("*.json"))
            self.assertEqual(len(journals), 1)
            journal = json.loads(journals[0].read_text("utf-8"))
            self.assertEqual(journal["state"], "applied")
            rollback = base / ".data-recovery" / "rollbacks" / journal["operation_id"] / "data"
            with closing(sqlite3.connect(rollback / "aide.db")) as conn:
                self.assertEqual(
                    conn.execute("SELECT value FROM restore_marker").fetchone()[0], "old"
                )


if __name__ == "__main__":
    unittest.main()
