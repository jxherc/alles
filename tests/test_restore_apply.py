import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.restore_apply import (
    RestoreApplyError,
    begin_manual_rollback,
    begin_restore_operation,
    complete_restore_operation,
    discard_completed_restore,
    maintenance_lock_path,
    recover_interrupted_restore,
    rollback_restore_operation,
    swap_in_staged,
)


class RestoreApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.live = self.base / "data"
        self.live.mkdir()
        (self.live / "marker.txt").write_text("old", "utf-8")
        self.staged = self.base / ".data-recovery" / "staged" / ("a" * 32) / "data"
        self.staged.mkdir(parents=True)
        (self.staged / "marker.txt").write_text("new", "utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_successful_swap_keeps_rollback_and_releases_lock_after_health(self):
        operation = begin_restore_operation(self.live, "a" * 32)
        self.assertTrue(maintenance_lock_path(self.live).is_file())

        swap_in_staged(operation, self.staged)

        self.assertEqual((self.live / "marker.txt").read_text("utf-8"), "new")
        self.assertEqual((operation.rollback_data / "marker.txt").read_text("utf-8"), "old")
        self.assertTrue(maintenance_lock_path(self.live).exists())

        complete_restore_operation(operation)

        self.assertFalse(maintenance_lock_path(self.live).exists())
        self.assertTrue(operation.rollback_data.is_dir())
        journal = json.loads(operation.journal_path.read_text("utf-8"))
        self.assertEqual(journal["state"], "applied")

    def test_failed_health_rolls_back_old_data_and_keeps_failed_candidate(self):
        operation = begin_restore_operation(self.live, "a" * 32)
        swap_in_staged(operation, self.staged)

        failed = rollback_restore_operation(operation, reason="health-check-failed")

        self.assertEqual((self.live / "marker.txt").read_text("utf-8"), "old")
        self.assertEqual((failed / "marker.txt").read_text("utf-8"), "new")
        self.assertFalse(operation.rollback_data.exists())
        self.assertFalse(maintenance_lock_path(self.live).exists())
        journal = json.loads(operation.journal_path.read_text("utf-8"))
        self.assertEqual(journal["state"], "rolled_back")

    def test_second_rename_failure_restores_live_data_before_returning(self):
        operation = begin_restore_operation(self.live, "a" * 32)
        real_replace = os.replace

        def fail_second(source, destination):
            if Path(source) == self.staged.resolve():
                raise OSError("simulated stage rename failure")
            return real_replace(source, destination)

        with mock.patch("services.restore_apply.os.replace", side_effect=fail_second):
            with self.assertRaises(RestoreApplyError):
                swap_in_staged(operation, self.staged)

        self.assertEqual((self.live / "marker.txt").read_text("utf-8"), "old")
        self.assertFalse(maintenance_lock_path(self.live).exists())

    def test_recover_after_crash_with_live_missing_restores_the_rollback(self):
        operation = begin_restore_operation(self.live, "a" * 32)
        operation.rollback_data.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.live, operation.rollback_data)

        result = recover_interrupted_restore(self.live)

        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual((self.live / "marker.txt").read_text("utf-8"), "old")
        self.assertFalse(maintenance_lock_path(self.live).exists())

    def test_recover_after_candidate_swap_prefers_the_original_data(self):
        operation = begin_restore_operation(self.live, "a" * 32)
        swap_in_staged(operation, self.staged)

        result = recover_interrupted_restore(self.live)

        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual((self.live / "marker.txt").read_text("utf-8"), "old")
        failed = Path(result["failed_data"])
        self.assertEqual((failed / "marker.txt").read_text("utf-8"), "new")

    def test_recover_after_applied_journal_only_releases_stale_lock(self):
        operation = begin_restore_operation(self.live, "a" * 32)
        swap_in_staged(operation, self.staged)
        # Simulate the final durable journal write happening just before a crash.
        journal = json.loads(operation.journal_path.read_text("utf-8"))
        journal["state"] = "applied"
        operation.journal_path.write_text(json.dumps(journal), "utf-8")

        result = recover_interrupted_restore(self.live)

        self.assertEqual(result["status"], "applied")
        self.assertEqual((self.live / "marker.txt").read_text("utf-8"), "new")
        self.assertTrue(operation.rollback_data.is_dir())
        self.assertFalse(maintenance_lock_path(self.live).exists())

    def test_manual_rollback_of_applied_operation_is_available(self):
        operation = begin_restore_operation(self.live, "a" * 32)
        swap_in_staged(operation, self.staged)
        complete_restore_operation(operation)

        resumed = begin_manual_rollback(self.live, operation.operation_id)
        failed = rollback_restore_operation(resumed, reason="manual-rollback")

        self.assertEqual((self.live / "marker.txt").read_text("utf-8"), "old")
        self.assertEqual((failed / "marker.txt").read_text("utf-8"), "new")

    def test_accepting_completed_restore_discards_only_rollback_and_journal(self):
        operation = begin_restore_operation(self.live, "a" * 32)
        swap_in_staged(operation, self.staged)
        complete_restore_operation(operation)

        discard_completed_restore(self.live, operation.operation_id)

        self.assertEqual((self.live / "marker.txt").read_text("utf-8"), "new")
        self.assertFalse(operation.rollback_data.parent.exists())
        self.assertFalse(operation.journal_path.exists())

    def test_ids_and_existing_maintenance_lock_are_rejected(self):
        with self.assertRaises(RestoreApplyError):
            begin_restore_operation(self.live, "../escape")
        operation = begin_restore_operation(self.live, "a" * 32)
        with self.assertRaisesRegex(RestoreApplyError, "already active"):
            begin_restore_operation(self.live, "b" * 32)
        with self.assertRaises(RestoreApplyError):
            begin_manual_rollback(self.live, "../escape")
        self.assertTrue(operation.journal_path.is_file())


if __name__ == "__main__":
    unittest.main()
