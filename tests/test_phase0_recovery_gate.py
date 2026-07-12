import hashlib
import io
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
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


def _probe_secrets(
    root: Path,
    connector_secret: str,
    setting_secret: str,
    api_output: Path,
    *,
    create: bool,
):
    script = """
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from core.database import Connection, SessionLocal, init_db
from core.settings import load_settings, save_settings

init_db()
connector_secret = os.environ.pop("ALLES_GATE_CONNECTOR_SECRET")
setting_secret = os.environ.pop("ALLES_GATE_SETTING_SECRET")
database = SessionLocal()
try:
    connection = database.query(Connection).filter(Connection.service == "phase-zero").first()
    if os.environ["ALLES_GATE_CREATE"] == "1":
        if connection is not None:
            raise SystemExit(4)
        connection = Connection(
            service="phase-zero",
            token=connector_secret,
            meta=json.dumps({"client_secret": connector_secret, "account": "synthetic"}),
        )
        database.add(connection)
        database.commit()
        save_settings({"openai_api_key": setting_secret})
    elif connection is None or connection.token != connector_secret:
        raise SystemExit(5)
    elif json.loads(connection.meta)["client_secret"] != connector_secret:
        raise SystemExit(6)
    elif load_settings()["openai_api_key"] != setting_secret:
        raise SystemExit(7)
finally:
    database.close()

from app import app

client = TestClient(app)
responses = [client.get("/api/connections"), client.get("/api/settings")]
body = "\\n".join(response.text for response in responses)
if any(response.status_code != 200 for response in responses):
    raise SystemExit(8)
if connector_secret in body or setting_secret in body:
    raise SystemExit(9)
Path(os.environ["ALLES_GATE_API_OUTPUT"]).write_text(body, "utf-8")
"""
    env = os.environ.copy()
    env.update(
        {
            "ALLES_DATA": str(root),
            "ALLES_DB": str(root / "aide.db"),
            "ALLES_GATE_API_OUTPUT": str(api_output),
            "ALLES_GATE_CONNECTOR_SECRET": connector_secret,
            "ALLES_GATE_SETTING_SECRET": setting_secret,
            "ALLES_GATE_CREATE": "1" if create else "0",
            "ALLES_HOST": "127.0.0.1",
            "AUTH_ENABLED": "false",
            "PYTHON_DOTENV_DISABLED": "1",
        }
    )
    env.pop("ALLES_RELOAD", None)
    return subprocess.run(
        [sys.executable or "python3", "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


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

            connector_secret = "phase-zero-private-connector-token"
            setting_secret = "phase-zero-private-settings-token"
            test_secrets = (connector_secret, setting_secret)
            source_api = base / "source-api-response.json"
            connector_setup = _probe_secrets(
                source,
                connector_secret,
                setting_secret,
                source_api,
                create=True,
            )
            self.assertEqual(connector_setup.returncode, 0, connector_setup.stderr)
            for secret in test_secrets:
                self.assertNotIn(secret, connector_setup.stdout + connector_setup.stderr)
                self.assertNotIn(secret, source_api.read_text("utf-8"))
                self.assertNotIn(secret.encode(), (source / "aide.db").read_bytes())
                self.assertNotIn(secret.encode(), (source / "settings.json").read_bytes())

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
                create_recovery_archive(
                    source,
                    plaintext,
                    expected_recovery_key=key,
                )
                with zipfile.ZipFile(plaintext) as archive:
                    for info in archive.infolist():
                        for secret in test_secrets:
                            self.assertNotIn(secret.encode(), archive.read(info))
                encrypt_recovery_archive(plaintext, encrypted, key)
                exported_key.write_bytes(recovery_key_document(key))
                for secret in test_secrets:
                    self.assertNotIn(secret.encode(), encrypted.read_bytes())
                    self.assertNotIn(secret.encode(), exported_key.read_bytes())
                    for database_part in source.glob("aide.db*"):
                        self.assertNotIn(secret.encode(), database_part.read_bytes())
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
                mock.patch("sys.stdout", new_callable=io.StringIO) as restore_output,
            ):
                self.assertTrue(
                    cli.cmd_restore(("stage", str(encrypted), "--key", str(exported_key)))
                )
                staged_root = staging_root(clean_target) / "staged"
                restore_ids = [path.name for path in staged_root.iterdir() if path.is_dir()]
                self.assertEqual(len(restore_ids), 1)
                self.assertTrue(cli.cmd_restore(("apply", restore_ids[0])))

            for secret in test_secrets:
                self.assertNotIn(secret, restore_output.getvalue())

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
            restored_api = base / "restored-api-response.json"
            connector_restore = _probe_secrets(
                clean_target,
                connector_secret,
                setting_secret,
                restored_api,
                create=False,
            )
            self.assertEqual(connector_restore.returncode, 0, connector_restore.stderr)
            for secret in test_secrets:
                self.assertNotIn(secret, connector_restore.stdout + connector_restore.stderr)
                self.assertNotIn(secret, restored_api.read_text("utf-8"))
                self.assertNotIn(secret.encode(), (clean_target / "settings.json").read_bytes())
                for database_part in clean_target.glob("aide.db*"):
                    self.assertNotIn(secret.encode(), database_part.read_bytes())
                for log in base.rglob("*.log"):
                    self.assertNotIn(secret.encode(), log.read_bytes())
            for relative, expected in expected_hashes.items():
                self.assertEqual(_sha256(clean_target / relative), expected)


if __name__ == "__main__":
    unittest.main()
