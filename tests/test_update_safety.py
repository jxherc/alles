import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cli
from services.backup_recovery import (
    discard_consumed_staged_recovery,
    stage_recovery_archive,
    staging_root,
    verify_staged_recovery,
)
from services.recovery_crypto import (
    decrypt_recovery_container,
    encrypt_recovery_archive,
    load_recovery_key,
    recovery_key_path,
)
from services.restore_apply import (
    begin_restore_operation,
    complete_restore_operation,
    maintenance_lock_path,
    swap_in_staged,
)
from services.update_safety import (
    UpdateCommandLock,
    UpdateSafetyError,
    begin_update,
    finish_update,
    update_lock_path,
    update_start_allowed,
)


class UpdateMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_command_lock_excludes_acceptance_and_rollback(self):
        first = UpdateCommandLock(self.data).acquire()
        second = UpdateCommandLock(self.data)
        try:
            with self.assertRaisesRegex(UpdateSafetyError, "another update command"):
                second.acquire()
        finally:
            first.release()
        self.assertIs(second.acquire(), second)
        second.release()

    def test_update_command_lock_refuses_a_symlink_without_touching_its_target(self):
        target = self.root / "owner-file"
        target.write_bytes(b"owner content")
        lock = UpdateCommandLock(self.data)
        lock.path.symlink_to(target)

        with self.assertRaisesRegex(UpdateSafetyError, "another update command"):
            lock.acquire()

        self.assertEqual(target.read_bytes(), b"owner content")

    def test_marker_blocks_every_token_except_its_exact_update(self):
        update_id = "a" * 32
        path = begin_update(self.data, update_id)
        self.assertEqual(path, update_lock_path(self.data))
        self.assertTrue(path.is_file())
        self.assertTrue(update_start_allowed(self.data, update_id))
        self.assertFalse(update_start_allowed(self.data, "b" * 32))
        self.assertFalse(update_start_allowed(self.data, None))

        # The same recovery command can resume its own marker, but a second update cannot.
        self.assertEqual(begin_update(self.data, update_id), path)
        with self.assertRaises(UpdateSafetyError):
            begin_update(self.data, "c" * 32)

        finish_update(self.data, update_id)
        self.assertFalse(path.exists())

    def test_invalid_marker_fails_closed(self):
        path = update_lock_path(self.data)
        path.write_text("not json", "utf-8")
        self.assertFalse(update_start_allowed(self.data, "a" * 32))
        with self.assertRaises(UpdateSafetyError):
            begin_update(self.data, "a" * 32)
        with self.assertRaises(UpdateSafetyError):
            finish_update(self.data, "a" * 32)

    def test_default_update_work_area_stays_outside_checkout(self):
        checkout = self.root / "alles"
        live = checkout / "data"
        live.mkdir(parents=True)
        with mock.patch.object(cli, "ROOT", checkout):
            directory, state = cli._update_paths(live)
        with self.assertRaises(ValueError):
            directory.resolve().relative_to(checkout.resolve())
        self.assertEqual(state.parent, directory)

    def test_reset_refuses_a_concurrent_dirty_tree(self):
        state = {"old_head": "a" * 40, "new_head": "b" * 40, "restore_id": "c" * 32}
        dirty = mock.Mock(returncode=0, stdout="?? new-file\n")
        with (
            mock.patch.object(cli, "_runtime_dir", return_value=self.data),
            mock.patch.object(cli, "_stop_for_restore", return_value=True),
            mock.patch.object(cli, "_git", return_value=dirty),
            mock.patch.object(cli, "_git_value", return_value=state["new_head"]),
            mock.patch.object(cli, "_reset_update_code") as reset,
        ):
            self.assertFalse(cli._rollback_update(state))
        reset.assert_not_called()

    def test_real_git_rollback_restores_old_commit_and_data_snapshot(self):
        repo = self.root / "repo"
        repo.mkdir()

        def git(*args):
            return subprocess.run(
                ["git", *args],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )

        git("init", "-q")
        git("config", "user.name", "jxherc")
        git("config", "user.email", "houjx0103@gmail.com")
        tracked = repo / "version.txt"
        tracked.write_text("old", "utf-8")
        git("add", "version.txt")
        git("commit", "-qm", "old version")
        old_head = git("rev-parse", "HEAD").stdout.strip()

        tracked.write_text("new", "utf-8")
        git("commit", "-qam", "new version")
        new_head = git("rev-parse", "HEAD").stdout.strip()
        live_marker = self.root / "live-marker.txt"
        live_marker.write_text("migrated", "utf-8")
        state = {
            "old_head": old_head,
            "new_head": new_head,
            "restore_id": "c" * 32,
        }

        def restore_snapshot(*args, **kwargs):
            live_marker.write_text("old-data", "utf-8")
            return True

        with (
            mock.patch.object(cli, "ROOT", repo),
            mock.patch.object(cli, "_runtime_dir", return_value=self.data),
            mock.patch.object(cli, "_stop_for_restore", return_value=True),
            mock.patch.object(cli, "_apply_staged_restore", side_effect=restore_snapshot),
        ):
            self.assertTrue(cli._rollback_update(state))

        self.assertEqual(git("rev-parse", "HEAD").stdout.strip(), old_head)
        self.assertEqual(tracked.read_text("utf-8"), "old")
        self.assertEqual(live_marker.read_text("utf-8"), "old-data")

    def test_first_update_creates_key_before_snapshot_and_keeps_backup_decryptable(self):
        live = self.root / "first-key-data"
        (live / "vault").mkdir(parents=True)
        (live / "files").mkdir()
        self.assertTrue(cli._run_recovery_probe(live, passes=1))
        self.assertFalse(recovery_key_path(live).exists())

        update_dir = self.root / "first-key-updates"
        update_dir.mkdir()
        published = []

        def artifact_callback(**artifact):
            published.append(artifact)
            self.assertFalse(Path(artifact["backup"]).exists())
            recovery = staging_root(live) / "staged"
            self.assertFalse((recovery / artifact["restore_id"]).exists())
            self.assertFalse((recovery / artifact["candidate_id"]).exists())

        rollback, candidate, encrypted = cli._stage_update_data(
            live,
            cli.ROOT,
            update_dir,
            artifact_callback=artifact_callback,
        )

        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["restore_id"], rollback.restore_id)
        self.assertEqual(published[0]["candidate_id"], candidate.restore_id)
        self.assertEqual(published[0]["backup"], str(encrypted))

        live_key = load_recovery_key(recovery_key_path(live))
        self.assertEqual(load_recovery_key(recovery_key_path(rollback.data_dir)), live_key)
        self.assertEqual(load_recovery_key(recovery_key_path(candidate.data_dir)), live_key)
        decrypted = self.root / "first-key-decrypted.zip"
        decrypt_recovery_container(encrypted, decrypted, live_key)
        disaster_target = self.root / "first-key-disaster-target"
        disaster_target.mkdir()
        staged = stage_recovery_archive(decrypted, disaster_target)
        self.assertEqual(load_recovery_key(recovery_key_path(staged.data_dir)), live_key)
        verify_staged_recovery(disaster_target, staged.restore_id)

    def test_update_rollback_never_accepts_an_unrelated_restore_recovery(self):
        live = self.root / "unrelated-live"
        live.mkdir()
        (live / "marker.txt").write_text("old", "utf-8")
        update_candidate = self.root / "update-candidate"
        update_candidate.mkdir()
        (update_candidate / "marker.txt").write_text("updated", "utf-8")
        update_operation = begin_restore_operation(live, "1" * 32)
        swap_in_staged(update_operation, update_candidate)
        complete_restore_operation(update_operation)

        unrelated_candidate = self.root / "unrelated-candidate"
        unrelated_candidate.mkdir()
        (unrelated_candidate / "marker.txt").write_text("unrelated", "utf-8")
        unrelated_operation = begin_restore_operation(live, "2" * 32)
        swap_in_staged(unrelated_operation, unrelated_candidate)

        state = {
            "old_head": "a" * 40,
            "new_head": "b" * 40,
            "restore_id": "3" * 32,
            "operation_id": update_operation.operation_id,
            "phase": "applied",
        }
        with (
            mock.patch.object(cli, "_runtime_dir", return_value=live),
            mock.patch.object(cli, "_stop_for_restore", return_value=True),
            mock.patch.object(cli, "_reset_update_code") as reset,
            mock.patch.object(cli, "_apply_staged_restore") as fallback,
        ):
            self.assertFalse(cli._rollback_update(state))

        reset.assert_not_called()
        fallback.assert_not_called()
        self.assertEqual((live / "marker.txt").read_text("utf-8"), "unrelated")
        self.assertTrue(maintenance_lock_path(live).exists())

    def test_preparing_state_without_marker_can_be_safely_cleared(self):
        update_dir = self.root / "missing-marker-update"
        state_path = update_dir / "latest.json"
        state = {
            "phase": "preparing",
            "update_id": "1" * 32,
            "old_head": "a" * 40,
            "new_head": "b" * 40,
            "was_running": False,
        }
        cli._write_update_state(state_path, state)
        clean = mock.Mock(returncode=0, stdout="")
        with (
            mock.patch.object(cli, "_runtime_dir", return_value=self.data),
            mock.patch.object(cli, "_update_paths", return_value=(update_dir, state_path)),
            mock.patch.object(cli, "_git", return_value=clean),
            mock.patch.object(cli, "_git_value", return_value=state["old_head"]),
            mock.patch("sys.stdout"),
        ):
            self.assertTrue(cli._cmd_update_rollback())

        self.assertFalse(state_path.exists())
        self.assertFalse(update_lock_path(self.data).exists())

    def test_never_switched_recovery_reports_restart_failure(self):
        update_dir = self.root / "restart-failure-update"
        state_path = update_dir / "latest.json"
        state = {
            "phase": "preparing",
            "update_id": "2" * 32,
            "old_head": "a" * 40,
            "new_head": "b" * 40,
            "was_running": True,
        }
        cli._write_update_state(state_path, state)
        clean = mock.Mock(returncode=0, stdout="")
        with (
            mock.patch.object(cli, "_runtime_dir", return_value=self.data),
            mock.patch.object(cli, "_update_paths", return_value=(update_dir, state_path)),
            mock.patch.object(cli, "_git", return_value=clean),
            mock.patch.object(cli, "_git_value", return_value=state["old_head"]),
            mock.patch.object(cli, "_restore_server_state", return_value=False),
            mock.patch.object(cli, "cmd_start", return_value=False) as start,
            mock.patch("sys.stdout"),
        ):
            self.assertFalse(cli._cmd_update_rollback())

        start.assert_called_once_with()

    def test_rollback_retry_after_code_reset_and_data_failure(self):
        update_dir = self.root / "retry-update"
        state_path = update_dir / "latest.json"
        state = {
            "phase": "applied",
            "update_id": "4" * 32,
            "old_head": "a" * 40,
            "new_head": "b" * 40,
            "restore_id": "5" * 32,
            "was_running": False,
        }
        cli._write_update_state(state_path, state)
        begin_update(self.data, state["update_id"])
        head = {"value": state["new_head"]}
        clean = mock.Mock(returncode=0, stdout="")

        def reset(commit):
            head["value"] = commit
            return True

        with (
            mock.patch.object(cli, "_runtime_dir", return_value=self.data),
            mock.patch.object(cli, "_update_paths", return_value=(update_dir, state_path)),
            mock.patch.object(cli, "_git", return_value=clean),
            mock.patch.object(cli, "_git_value", side_effect=lambda _args: head["value"]),
            mock.patch.object(cli, "_reset_update_code", side_effect=reset) as reset_code,
            mock.patch.object(cli, "_restore_server_state", return_value=False),
            mock.patch.object(cli, "_stop_for_restore", return_value=True),
            mock.patch.object(cli, "_apply_staged_restore", side_effect=[False, True]) as apply,
            mock.patch("sys.stdout"),
        ):
            self.assertFalse(cli._cmd_update_rollback())
            saved = cli._load_update_state(state_path)
            self.assertEqual(saved["phase"], "rollback_code_restored")
            self.assertEqual(head["value"], state["old_head"])
            self.assertTrue(cli._cmd_update_rollback())

        reset_code.assert_called_once_with(state["old_head"])
        self.assertEqual(apply.call_count, 2)
        self.assertFalse(state_path.exists())
        self.assertFalse(update_lock_path(self.data).exists())

    def test_reset_preserves_edit_created_after_clean_check(self):
        repo = self.root / "race-repo"
        repo.mkdir()

        def git(*args):
            return subprocess.run(
                ["git", *args],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )

        git("init", "-q")
        git("config", "user.name", "jxherc")
        git("config", "user.email", "houjx0103@gmail.com")
        tracked = repo / "version.txt"
        tracked.write_text("old", "utf-8")
        git("add", "version.txt")
        git("commit", "-qm", "old version")
        old_head = git("rev-parse", "HEAD").stdout.strip()
        tracked.write_text("new", "utf-8")
        git("commit", "-qam", "new version")
        new_head = git("rev-parse", "HEAD").stdout.strip()
        status_calls = 0

        def racing_git(args, capture=True):
            nonlocal status_calls
            result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
            if args == ["status", "--porcelain"] and status_calls == 0:
                status_calls += 1
                self.assertFalse(result.stdout.strip())
                tracked.write_text("late user edit", "utf-8")
            return result

        state = {
            "old_head": old_head,
            "new_head": new_head,
            "restore_id": "6" * 32,
            "phase": "applied",
        }
        with (
            mock.patch.object(cli, "ROOT", repo),
            mock.patch.object(cli, "_runtime_dir", return_value=self.data),
            mock.patch.object(cli, "_stop_for_restore", return_value=True),
            mock.patch.object(cli, "_git", side_effect=racing_git),
            mock.patch.object(cli, "_apply_staged_restore") as apply,
        ):
            self.assertFalse(cli._rollback_update(state))

        apply.assert_not_called()
        self.assertEqual(tracked.read_text("utf-8"), "late user edit")
        self.assertEqual(git("rev-parse", "HEAD").stdout.strip(), new_head)

    def test_candidate_with_broken_cli_is_rejected(self):
        candidate = self.root / "broken-cli-candidate"
        update_dir = self.root / "broken-cli-updates"
        candidate.mkdir()
        update_dir.mkdir()
        (candidate / "cli.py").write_text("def broken(:\n", "utf-8")
        self.assertFalse(cli._candidate_update_control_plane_ok(candidate, update_dir))

    def test_update_control_plane_probe_passes(self):
        self.assertTrue(cli._cmd_update_probe())

    def test_accept_keeps_encrypted_backup_and_discards_temporary_copies(self):
        update_dir = self.root / "accept-updates"
        run_dir = update_dir / "run"
        run_dir.mkdir(parents=True)
        state_path = update_dir / "latest.json"
        plaintext = run_dir / "plain.zip"
        encrypted = run_dir / "pre-update.alles-backup"
        plaintext.write_bytes(b"synthetic accepted update")
        encrypt_recovery_archive(plaintext, encrypted, b"k" * 32)
        plaintext.unlink()
        state = {
            "phase": "applied",
            "update_id": "7" * 32,
            "old_head": "a" * 40,
            "new_head": "b" * 40,
            "restore_id": "8" * 32,
            "candidate_id": "9" * 32,
            "operation_id": "c" * 32,
            "backup": str(encrypted),
            "was_running": False,
        }
        cli._write_update_state(state_path, state)
        recovery = staging_root(self.data)
        (recovery / "staged" / state["candidate_id"]).mkdir(parents=True)
        (recovery / "staged" / state["restore_id"]).mkdir(parents=True)
        operation_journal = recovery / "operations" / f"{state['operation_id']}.json"
        operation_journal.parent.mkdir(parents=True)
        operation_journal.write_text("{}", "utf-8")
        clean = mock.Mock(returncode=0, stdout="")

        with (
            mock.patch.object(cli, "_runtime_dir", return_value=self.data),
            mock.patch.object(cli, "_update_paths", return_value=(update_dir, state_path)),
            mock.patch.object(cli, "_git", return_value=clean),
            mock.patch.object(cli, "_git_value", return_value=state["new_head"]),
            mock.patch(
                "services.backup_recovery.discard_consumed_staged_recovery"
            ) as discard_candidate,
            mock.patch("services.backup_recovery.discard_staged_recovery") as discard_rollback,
            mock.patch("services.restore_apply.discard_completed_restore") as discard_operation,
            mock.patch("sys.stdout"),
        ):
            self.assertTrue(cli._cmd_update_accept())

        resolved_data = self.data.resolve()
        discard_candidate.assert_called_once_with(resolved_data, state["candidate_id"])
        discard_operation.assert_called_once_with(resolved_data, state["operation_id"])
        discard_rollback.assert_called_once_with(resolved_data, state["restore_id"])
        self.assertTrue(encrypted.is_file())
        self.assertFalse(state_path.exists())

    def test_consumed_candidate_stage_cleanup_cannot_remove_live_data(self):
        restore_id = "d" * 32
        stage = staging_root(self.data) / "staged" / restore_id
        stage.mkdir(parents=True)
        (stage / "stage.json").write_text('{"restore_id":"' + restore_id + '"}', "utf-8")
        live_marker = self.data / "live.txt"
        live_marker.write_text("keep", "utf-8")

        discard_consumed_staged_recovery(self.data, restore_id)

        self.assertFalse(stage.exists())
        self.assertEqual(live_marker.read_text("utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
