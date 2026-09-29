import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import core.settings
from services import automatic_backup, encrypted_backup
from services.backup_recovery import staging_root


class AutomaticBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-auto-backup-")
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.destination = self.root / "backups"
        self.settings = self.root / "settings.json"
        self.settings_patch = mock.patch.object(core.settings, "_SETTINGS_FILE", self.settings)
        self.settings_patch.start()
        self.env_patch = mock.patch.dict("os.environ", {"ALLES_DATA": str(self.data)})
        self.env_patch.start()
        core.settings._clear_settings_cache()

    def tearDown(self):
        core.settings._clear_settings_cache()
        self.env_patch.stop()
        self.settings_patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def _encrypted(_root, artifact):
        from services.recovery_crypto import MAGIC

        artifact.write_bytes(MAGIC + b"not-plaintext")
        return artifact

    def _enable(self):
        core.settings.save_settings(
            {
                "automatic_backup_enabled": True,
                "automatic_backup_dir": str(self.destination),
            }
        )

    def test_disabled_job_does_nothing(self):
        result = automatic_backup.run_if_due(creator=self._encrypted)
        self.assertEqual(result["status"], "disabled")
        self.assertFalse(self.destination.exists())

    def test_due_job_publishes_only_encrypted_artifact(self):
        self._enable()
        now = datetime(2026, 7, 20, 1, 2, 3, tzinfo=UTC)
        result = automatic_backup.run_if_due(now=now, creator=self._encrypted)
        self.assertTrue(result["created"])
        files = list(self.destination.iterdir())
        self.assertEqual(len(files), 1)
        self.assertIn(automatic_backup._owner_id(self.data), files[0].name)
        self.assertTrue(files[0].name.endswith(".alles-backup"))
        self.assertFalse(any("partial" in path.name or path.suffix == ".zip" for path in files))
        self.assertEqual(
            core.settings.load_settings()["automatic_backup_last_success"],
            "2026-07-20T01:02:03Z",
        )

    def test_default_creator_produces_restorable_encrypted_backup(self):
        from services.backup_recovery import stage_recovery_archive
        from services.recovery_crypto import (
            decrypt_recovery_container,
            is_encrypted_recovery,
            load_recovery_key,
            recovery_key_path,
        )

        with closing(sqlite3.connect(self.data / "aide.db")) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', '')")
            conn.commit()
        (self.data / "backup-marker.txt").write_text("private-backup-marker", "utf-8")
        self.destination.mkdir(mode=0o755)
        self.destination.chmod(0o755)
        self._enable()

        observed_plaintext = []
        original_encrypt = encrypted_backup.encrypt_recovery_archive

        def inspect_plaintext(source, *args, **kwargs):
            observed_plaintext.append((source.parent, source.parent.stat().st_mode & 0o077))
            return original_encrypt(source, *args, **kwargs)

        with mock.patch.object(
            encrypted_backup, "encrypt_recovery_archive", side_effect=inspect_plaintext
        ):
            result = automatic_backup.run_if_due(now=datetime(2026, 7, 20, tzinfo=UTC))

        artifact = self.destination / result["filename"]
        self.assertEqual(len(observed_plaintext), 1)
        self.assertNotEqual(observed_plaintext[0][0], self.destination)
        if os.name != "nt":
            self.assertEqual(observed_plaintext[0][1], 0)
        self.assertEqual(
            list((staging_root(self.data) / "automatic-backup-work").iterdir()),
            [],
        )
        self.assertTrue(is_encrypted_recovery(artifact))
        self.assertNotIn(b"private-backup-marker", artifact.read_bytes())
        self.assertFalse(any(path.suffix == ".zip" for path in self.destination.iterdir()))
        plaintext = self.root / "restored.zip"
        decrypt_recovery_container(
            artifact,
            plaintext,
            load_recovery_key(recovery_key_path(self.data)),
        )
        with zipfile.ZipFile(plaintext) as backup:
            self.assertEqual(
                backup.read("payload/data/backup-marker.txt"),
                b"private-backup-marker",
            )
            self.assertIn("payload/data/aide.db", backup.namelist())
        staged = stage_recovery_archive(plaintext, self.data)
        self.assertEqual(
            (staged.data_dir / "backup-marker.txt").read_text("utf-8"),
            "private-backup-marker",
        )

    def test_job_runs_at_most_daily_without_force(self):
        self._enable()
        now = datetime(2026, 7, 20, tzinfo=UTC)
        automatic_backup.run_if_due(now=now, creator=self._encrypted)
        result = automatic_backup.run_if_due(now=now + timedelta(hours=23), creator=self._encrypted)
        self.assertEqual(result["status"], "not-due")
        self.assertEqual(len(list(self.destination.iterdir())), 1)

    def test_abandoned_work_is_removed_even_when_not_due_or_disabled(self):
        work_root = staging_root(self.data) / "automatic-backup-work"
        work_root.mkdir(parents=True, mode=0o700)
        owner_id = automatic_backup._owner_id(self.data)
        abandoned = work_root / f"alles-auto-{owner_id}-{uuid.uuid4().hex}"
        abandoned.mkdir(mode=0o700)
        (abandoned / "private.zip").write_bytes(b"synthetic plaintext")
        unrelated = work_root / f"alles-auto-0000000000000000-{uuid.uuid4().hex}"
        unrelated.mkdir(mode=0o700)
        self._enable()
        now = datetime(2026, 7, 20, tzinfo=UTC)
        core.settings.save_settings({"automatic_backup_last_success": now.isoformat()})

        result = automatic_backup.run_if_due(now=now, creator=self._encrypted)

        self.assertEqual(result["status"], "not-due")
        self.assertFalse(abandoned.exists())
        self.assertTrue(unrelated.is_dir())

        disabled_work = work_root / f"alles-auto-{owner_id}-{uuid.uuid4().hex}"
        disabled_work.mkdir(mode=0o700)
        core.settings.save_settings({"automatic_backup_enabled": False})
        result = automatic_backup.run_if_due(now=now, creator=self._encrypted)
        self.assertEqual(result["status"], "disabled")
        self.assertFalse(disabled_work.exists())
        self.assertTrue(unrelated.is_dir())

    def test_process_death_leaves_plaintext_only_in_private_work_until_next_check(self):
        with closing(sqlite3.connect(self.data / "aide.db")) as conn:
            conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
            conn.execute(
                "CREATE TABLE schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
            )
            conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', '')")
            conn.commit()
        self.destination.mkdir(mode=0o755)
        self.destination.chmod(0o755)
        child = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "from unittest import mock\n"
            "from services import automatic_backup, encrypted_backup\n"
            "with mock.patch.object(encrypted_backup, 'encrypt_recovery_archive', "
            "side_effect=lambda *_a, **_kw: os._exit(77)):\n"
            "    automatic_backup._automatic_creator(Path(sys.argv[1]), Path(sys.argv[2]))\n"
        )
        env = os.environ.copy()
        env["ALLES_DATA"] = str(self.data)
        env.pop("ALLES_DB", None)
        result = subprocess.run(
            [sys.executable, "-c", child, str(self.data), str(self.destination / "partial")],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        self.assertEqual(result.returncode, 77, result.stderr)
        self.assertEqual(list(self.destination.iterdir()), [])
        work_root = staging_root(self.data) / "automatic-backup-work"
        abandoned = list(work_root.iterdir())
        self.assertEqual(len(abandoned), 1)
        self.assertEqual(len(list(abandoned[0].glob("*.zip"))), 1)
        if os.name != "nt":
            self.assertEqual(abandoned[0].stat().st_mode & 0o077, 0)

        self.assertEqual(automatic_backup.run_if_due()["status"], "disabled")
        self.assertEqual(list(work_root.iterdir()), [])

    def test_future_success_timestamp_is_due_after_clock_correction(self):
        self._enable()
        now = datetime(2026, 7, 20, tzinfo=UTC)
        core.settings.save_settings(
            {"automatic_backup_last_success": (now + timedelta(days=90)).isoformat()}
        )
        result = automatic_backup.run_if_due(now=now, creator=self._encrypted)
        self.assertTrue(result["created"])

    def test_retention_always_keeps_the_artifact_created_by_this_run(self):
        from services.recovery_crypto import MAGIC

        self._enable()
        self.destination.mkdir()
        owner_id = automatic_backup._owner_id(self.data)
        for day in range(8):
            future = self.destination / (
                f"alles-auto-{owner_id}-209901{day + 1:02d}T000000Z-{day:08x}.alles-backup"
            )
            future.write_bytes(MAGIC + b"future")
        result = automatic_backup.run_if_due(
            now=datetime(2026, 7, 20, tzinfo=UTC), force=True, creator=self._encrypted
        )
        self.assertTrue((self.destination / result["filename"]).is_file())
        self.assertEqual(len(list(self.destination.glob("*.alles-backup"))), 7)

    def test_retention_removes_only_old_owned_artifacts(self):
        self._enable()
        unrelated = self.destination / "owner-file.txt"
        self.destination.mkdir()
        unrelated.write_text("keep", "utf-8")
        another_install = (
            self.destination / "alles-auto-0000000000000000-20260701T000000Z-00000000.alles-backup"
        )
        another_install.write_bytes(b"another installation")
        start = datetime(2026, 7, 1, tzinfo=UTC)
        for day in range(9):
            automatic_backup.run_if_due(
                now=start + timedelta(days=day), force=True, creator=self._encrypted
            )
        backups = [
            path
            for path in self.destination.iterdir()
            if automatic_backup._owner_id(self.data) in path.name
            and path.name.endswith(".alles-backup")
        ]
        self.assertEqual(len(backups), 7)
        self.assertEqual(unrelated.read_text("utf-8"), "keep")
        self.assertTrue(another_install.is_file())

    def test_due_state_is_rechecked_after_the_process_lock_is_acquired(self):
        self._enable()
        now = datetime(2026, 7, 20, tzinfo=UTC)

        original_acquire = automatic_backup._BackupProcessLock.acquire

        def acquire_after_other_process(lock):
            core.settings.save_settings(
                {"automatic_backup_last_success": now.isoformat().replace("+00:00", "Z")}
            )
            return original_acquire(lock)

        creator = mock.Mock(side_effect=self._encrypted)
        with mock.patch.object(
            automatic_backup._BackupProcessLock,
            "acquire",
            acquire_after_other_process,
        ):
            result = automatic_backup.run_if_due(now=now, creator=creator)

        self.assertEqual(result["status"], "not-due")
        creator.assert_not_called()

    def test_destination_inside_data_is_refused(self):
        core.settings.save_settings(
            {
                "automatic_backup_enabled": True,
                "automatic_backup_dir": str(self.data / "backups"),
            }
        )
        with self.assertRaisesRegex(automatic_backup.AutomaticBackupError, "outside Alles data"):
            automatic_backup.run_if_due(creator=self._encrypted)

    def test_destination_containing_private_work_is_refused(self):
        core.settings.save_settings(
            {
                "automatic_backup_enabled": True,
                "automatic_backup_dir": str(self.root),
            }
        )
        creator = mock.Mock(side_effect=self._encrypted)
        with self.assertRaisesRegex(automatic_backup.AutomaticBackupError, "private backup work"):
            automatic_backup.run_if_due(creator=creator)
        creator.assert_not_called()

    def test_permissive_existing_work_directory_is_refused(self):
        if os.name == "nt":
            self.skipTest("POSIX file modes are unavailable")
        work_root = staging_root(self.data) / "automatic-backup-work"
        work_root.mkdir(parents=True, mode=0o700)
        work_root.chmod(0o755)
        self._enable()
        with self.assertRaisesRegex(
            automatic_backup.AutomaticBackupError, "work directory is unsafe"
        ):
            automatic_backup.run_if_due(creator=self._encrypted)
        self.assertFalse(self.destination.exists())

    def test_cleanup_error_still_releases_the_job_lock(self):
        self._enable()

        def fail_after_write(_root, artifact):
            artifact.write_bytes(b"partial")
            raise RuntimeError("creator failed")

        with mock.patch.object(Path, "unlink", side_effect=OSError("cleanup failed")):
            with self.assertRaisesRegex(OSError, "cleanup failed"):
                automatic_backup.run_if_due(creator=fail_after_write)

        self.assertTrue(automatic_backup._LOCK.acquire(blocking=False))
        automatic_backup._LOCK.release()


if __name__ == "__main__":
    unittest.main()
