import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import core.settings
from services import automatic_backup


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

    def test_job_runs_at_most_daily_without_force(self):
        self._enable()
        now = datetime(2026, 7, 20, tzinfo=UTC)
        automatic_backup.run_if_due(now=now, creator=self._encrypted)
        result = automatic_backup.run_if_due(now=now + timedelta(hours=23), creator=self._encrypted)
        self.assertEqual(result["status"], "not-due")
        self.assertEqual(len(list(self.destination.iterdir())), 1)

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
