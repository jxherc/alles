import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cli


class CliSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pid_patch = mock.patch.object(cli, "PID_FILE", self.root / "alles.pid")
        self.log_patch = mock.patch.object(cli, "LOG_FILE", self.root / "alles.log")
        self.pid_patch.start()
        self.log_patch.start()

    def tearDown(self):
        self.log_patch.stop()
        self.pid_patch.stop()
        self.tmp.cleanup()

    def test_start_refuses_busy_untracked_port(self):
        with (
            mock.patch.object(cli, "_deps_ok", return_value=True),
            mock.patch.object(cli, "_pid", return_value=None),
            mock.patch.object(cli, "_running", return_value=False),
            mock.patch.object(cli, "_port_open", return_value=True),
            mock.patch.object(cli, "_kill_port", create=True) as kill_port,
            mock.patch.object(cli.subprocess, "Popen") as popen,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            cli.cmd_start()

        kill_port.assert_not_called()
        popen.assert_not_called()

    def test_start_refuses_unfinished_restore_before_launching(self):
        maintenance = self.root / "maintenance.json"
        maintenance.write_text("{}", "utf-8")
        with (
            mock.patch("services.restore_apply.maintenance_lock_path", return_value=maintenance),
            mock.patch.object(cli, "_deps_ok", return_value=True),
            mock.patch.object(cli.subprocess, "Popen") as popen,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = cli.cmd_start()

        self.assertFalse(result)
        popen.assert_not_called()

    def test_start_refuses_unfinished_update_before_launching(self):
        maintenance = self.root / "update-maintenance.json"
        maintenance.write_text("{}", "utf-8")
        with (
            mock.patch(
                "services.restore_apply.maintenance_lock_path", return_value=self.root / "none"
            ),
            mock.patch("services.update_safety.update_lock_path", return_value=maintenance),
            mock.patch("services.update_safety.update_start_allowed", return_value=False),
            mock.patch.object(cli, "_deps_ok", return_value=True),
            mock.patch.object(cli.subprocess, "Popen") as popen,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = cli.cmd_start()

        self.assertFalse(result)
        popen.assert_not_called()

    def test_runtime_dir_uses_alles_data(self):
        isolated = self.root / "isolated-data"
        with mock.patch.dict(cli.os.environ, {"ALLES_DATA": str(isolated)}):
            self.assertEqual(cli._runtime_dir(), isolated)

    def test_stop_refuses_busy_untracked_port(self):
        with (
            mock.patch.object(cli, "_pid", return_value=None),
            mock.patch.object(cli, "_running", return_value=False),
            mock.patch.object(cli, "_port_open", return_value=True),
            mock.patch.object(cli, "_kill_port", create=True) as kill_port,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            cli.cmd_stop()

        kill_port.assert_not_called()

    def test_stop_refuses_pid_that_is_not_verified_as_alles(self):
        (self.root / "alles.pid").write_text("4321")
        with (
            mock.patch.object(cli, "_pid", return_value=4321),
            mock.patch.object(cli, "_running", return_value=True),
            mock.patch.object(cli, "_alles_process", create=True, return_value=None),
            mock.patch.object(cli.os, "kill") as os_kill,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            cli.cmd_stop()

        os_kill.assert_not_called()

    def test_owned_process_gets_graceful_stop(self):
        proc = mock.Mock()
        proc.is_running.return_value = False
        with (
            mock.patch.object(cli, "_pid", return_value=4321),
            mock.patch.object(cli, "_running", return_value=True),
            mock.patch.object(cli, "_alles_process", create=True, return_value=proc),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            cli.cmd_stop()

        proc.terminate.assert_called_once_with()
        proc.wait.assert_called_once()
        proc.kill.assert_not_called()

    def test_process_ownership_requires_this_app_and_working_directory(self):
        proc = mock.Mock()
        proc.cwd.return_value = str(cli.ROOT)
        proc.cmdline.return_value = ["python3", str(cli.ROOT / "app.py")]
        fake_psutil = SimpleNamespace(Process=mock.Mock(return_value=proc))
        with mock.patch.dict(sys.modules, {"psutil": fake_psutil}):
            self.assertIs(cli._alles_process(4321), proc)

        proc.cwd.return_value = str(self.root)
        with mock.patch.dict(sys.modules, {"psutil": fake_psutil}):
            self.assertIsNone(cli._alles_process(4321))

    def test_update_refuses_dirty_worktree(self):
        checkout = self.root / "checkout"
        (checkout / ".git").mkdir(parents=True)
        dirty = SimpleNamespace(returncode=0, stdout=" M app.py\n")
        with (
            mock.patch.object(cli, "ROOT", checkout),
            mock.patch.object(cli.subprocess, "run", return_value=dirty) as run,
            mock.patch.object(cli, "cmd_restart") as restart,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            cli.cmd_update()

        self.assertEqual(run.call_args.args[0], ["git", "status", "--porcelain"])
        restart.assert_not_called()

    def test_update_stops_and_locks_before_exact_backup_then_switches(self):
        checkout = self.root / "checkout"
        (checkout / ".git").mkdir(parents=True)
        (checkout / "requirements.txt").write_text("same", "utf-8")
        (checkout / "pyproject.toml").write_text("same", "utf-8")
        old_head = "a" * 40
        new_head = "b" * 40
        update_dir = self.root / "updates"
        state_path = update_dir / "latest.json"
        live = self.root / "update-live"
        live.mkdir()
        calls = []
        head = {"value": old_head}

        def fake_git(args, capture=True):
            calls.append(("git", *args))
            if args[:2] == ["rev-parse", "HEAD"]:
                return SimpleNamespace(returncode=0, stdout=head["value"] + "\n")
            if args[:2] == ["rev-parse", "@{upstream}"]:
                return SimpleNamespace(returncode=0, stdout=new_head + "\n")
            if args[:2] == ["worktree", "add"]:
                stage = Path(args[-2]) if args[-1] == new_head else Path(args[-1])
                stage.mkdir(parents=True)
                (stage / "requirements.txt").write_text("same", "utf-8")
                (stage / "pyproject.toml").write_text("same", "utf-8")
            if args[:2] == ["merge", "--ff-only"]:
                head["value"] = new_head
            return SimpleNamespace(returncode=0, stdout="")

        owner = mock.Mock()
        rollback = SimpleNamespace(restore_id="c" * 32, manifest={"locations": []})
        candidate = SimpleNamespace(restore_id="d" * 32, data_dir=self.root / "candidate")
        operation = SimpleNamespace(operation_id="e" * 32)

        def stopped():
            calls.append(("stop",))
            return True

        def locked():
            calls.append(("lock",))

        owner.acquire.side_effect = locked

        def staged(*args):
            calls.append(("backup",))
            return rollback, candidate, self.root / "pre-update.alles-backup"

        with (
            mock.patch.object(cli, "ROOT", checkout),
            mock.patch.object(cli, "_runtime_dir", return_value=live),
            mock.patch.object(cli, "_git", side_effect=fake_git),
            mock.patch.object(cli, "_update_paths", return_value=(update_dir, state_path)),
            mock.patch.object(cli, "_load_update_state", return_value=None),
            mock.patch.object(cli, "_restore_server_state", return_value=False),
            mock.patch.object(cli, "_stop_for_restore", side_effect=stopped),
            mock.patch.object(cli, "_stage_update_data", side_effect=staged),
            mock.patch.object(cli, "_coverage_issues", return_value=[]),
            mock.patch.object(cli, "_run_recovery_probe", return_value=True),
            mock.patch.object(cli, "_write_update_state"),
            mock.patch.object(cli, "_remove_update_worktree"),
            mock.patch.object(
                cli.subprocess, "run", return_value=SimpleNamespace(returncode=0)
            ) as run_process,
            mock.patch("services.instance_lock.InstanceLock", return_value=owner),
            mock.patch("services.update_safety.begin_update"),
            mock.patch("services.update_safety.finish_update"),
            mock.patch("services.restore_apply.begin_restore_operation", return_value=operation),
            mock.patch("services.restore_apply.swap_in_staged"),
            mock.patch("services.restore_apply.complete_restore_operation"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = cli.cmd_update()

        self.assertTrue(result)
        self.assertLess(calls.index(("stop",)), calls.index(("lock",)))
        self.assertLess(calls.index(("lock",)), calls.index(("backup",)))
        merge_index = next(
            i for i, call in enumerate(calls) if call[:3] == ("git", "merge", "--ff-only")
        )
        self.assertLess(calls.index(("backup",)), merge_index)
        self.assertGreaterEqual(calls.count(("git", "status", "--porcelain")), 3)
        compile_args = run_process.call_args_list[0].args[0]
        self.assertIn("cli.py", compile_args)
        self.assertTrue(
            any(
                call.args[0][-3:] == ["cli.py", "update", "probe"]
                for call in run_process.call_args_list
            )
        )

    def test_post_merge_dirty_checkout_never_starts_data_swap(self):
        checkout = self.root / "dirty-after-merge-checkout"
        (checkout / ".git").mkdir(parents=True)
        (checkout / "requirements.txt").write_text("same", "utf-8")
        (checkout / "pyproject.toml").write_text("same", "utf-8")
        live = self.root / "dirty-after-merge-live"
        live.mkdir()
        old_head = "a" * 40
        new_head = "b" * 40
        update_dir = self.root / "dirty-after-merge-updates"
        state_path = update_dir / "latest.json"
        head = {"value": old_head}

        def fake_git(args, capture=True):
            if args[:2] == ["rev-parse", "HEAD"]:
                return SimpleNamespace(returncode=0, stdout=head["value"] + "\n")
            if args[:2] == ["rev-parse", "@{upstream}"]:
                return SimpleNamespace(returncode=0, stdout=new_head + "\n")
            if args[:2] == ["worktree", "add"]:
                stage = Path(args[-2])
                stage.mkdir(parents=True)
                (stage / "requirements.txt").write_text("same", "utf-8")
                (stage / "pyproject.toml").write_text("same", "utf-8")
            if args[:2] == ["merge", "--ff-only"]:
                head["value"] = new_head
            return SimpleNamespace(returncode=0, stdout="")

        rollback = SimpleNamespace(restore_id="c" * 32, manifest={"locations": []})
        candidate = SimpleNamespace(restore_id="d" * 32, data_dir=self.root / "dirty-candidate")
        owner = mock.Mock()
        with (
            mock.patch.object(cli, "ROOT", checkout),
            mock.patch.object(cli, "_runtime_dir", return_value=live),
            mock.patch.object(cli, "_git", side_effect=fake_git),
            mock.patch.object(cli, "_update_paths", return_value=(update_dir, state_path)),
            mock.patch.object(cli, "_load_update_state", return_value=None),
            mock.patch.object(cli, "_restore_server_state", return_value=False),
            mock.patch.object(cli, "_stop_for_restore", return_value=True),
            mock.patch.object(
                cli,
                "_stage_update_data",
                return_value=(rollback, candidate, self.root / "pre-update.alles-backup"),
            ),
            mock.patch.object(cli, "_coverage_issues", return_value=[]),
            mock.patch.object(cli, "_updated_checkout_ready", return_value=False) as postcheck,
            mock.patch.object(cli, "_write_update_state"),
            mock.patch.object(cli, "_remove_update_worktree"),
            mock.patch.object(cli, "_rollback_update", return_value=False),
            mock.patch.object(cli.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
            mock.patch("services.instance_lock.InstanceLock", return_value=owner),
            mock.patch("services.update_safety.begin_update"),
            mock.patch("services.restore_apply.begin_restore_operation") as begin_restore,
            mock.patch("services.restore_apply.swap_in_staged") as swap,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = cli.cmd_update()

        self.assertFalse(result)
        postcheck.assert_called_once_with(new_head)
        begin_restore.assert_not_called()
        swap.assert_not_called()

    def test_restore_apply_refuses_external_database_override(self):
        with (
            mock.patch.dict(cli.os.environ, {"ALLES_DB": str(self.root / "other.db")}),
            mock.patch("services.backup_recovery.verify_staged_recovery") as verify,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = cli.cmd_restore(("apply", "a" * 32))

        self.assertFalse(result)
        verify.assert_not_called()

    def test_restore_apply_success_leaves_a_previously_stopped_server_stopped(self):
        staged = SimpleNamespace(
            state="prepared",
            data_dir=self.root / "staged-data",
            manifest={"locations": []},
        )
        operation = SimpleNamespace(operation_id="b" * 32)
        owner_lock = mock.Mock()
        with (
            mock.patch.dict(cli.os.environ, {"ALLES_DB": ""}),
            mock.patch.object(cli, "_runtime_dir", return_value=self.root),
            mock.patch.object(cli, "_restore_server_state", return_value=False),
            mock.patch.object(cli, "_stop_for_restore", return_value=True),
            mock.patch.object(cli, "_coverage_issues", return_value=[]),
            mock.patch.object(cli, "_run_recovery_probe", return_value=True),
            mock.patch(
                "services.backup_recovery.verify_staged_recovery", return_value=staged
            ) as verify,
            mock.patch("services.instance_lock.InstanceLock", return_value=owner_lock),
            mock.patch("services.restore_apply.begin_restore_operation", return_value=operation),
            mock.patch("services.restore_apply.mark_restore_state"),
            mock.patch("services.restore_apply.swap_in_staged") as swap,
            mock.patch("services.restore_apply.complete_restore_operation") as complete,
            mock.patch.object(cli, "cmd_start") as start,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = cli.cmd_restore(("apply", "a" * 32))

        self.assertTrue(result)
        self.assertEqual(verify.call_count, 2)
        swap.assert_called_once_with(operation, staged.data_dir)
        complete.assert_called_once_with(operation)
        start.assert_not_called()
        owner_lock.acquire.assert_called_once_with()
        owner_lock.release.assert_called_once_with()

    def test_restore_health_failure_rolls_back_and_restarts_old_server(self):
        staged = SimpleNamespace(
            state="prepared",
            data_dir=self.root / "staged-data",
            manifest={"locations": []},
        )
        operation = SimpleNamespace(operation_id="b" * 32)
        owner_lock = mock.Mock()
        with (
            mock.patch.dict(cli.os.environ, {"ALLES_DB": ""}),
            mock.patch.object(cli, "_runtime_dir", return_value=self.root),
            mock.patch.object(cli, "_restore_server_state", return_value=True),
            mock.patch.object(cli, "_stop_for_restore", return_value=True),
            mock.patch.object(cli, "_coverage_issues", return_value=[]),
            mock.patch.object(cli, "_run_recovery_probe", return_value=False),
            mock.patch("services.backup_recovery.verify_staged_recovery", return_value=staged),
            mock.patch("services.instance_lock.InstanceLock", return_value=owner_lock),
            mock.patch("services.restore_apply.begin_restore_operation", return_value=operation),
            mock.patch("services.restore_apply.mark_restore_state"),
            mock.patch("services.restore_apply.swap_in_staged"),
            mock.patch("services.restore_apply.rollback_restore_operation") as rollback,
            mock.patch("services.restore_apply.complete_restore_operation") as complete,
            mock.patch.object(cli, "cmd_start", return_value=True) as start,
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            result = cli.cmd_restore(("apply", "a" * 32))

        self.assertFalse(result)
        rollback.assert_called_once_with(operation, reason="installed-health-check-failed")
        complete.assert_not_called()
        start.assert_called_once_with()
        self.assertEqual(owner_lock.acquire.call_count, 2)
        self.assertEqual(owner_lock.release.call_count, 2)

    def test_preflight_remaps_included_roots_inside_candidate_then_sets_final_paths(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        settings = candidate / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "vault_dir": "/old/live/vault",
                    "files_dir": "/old/live/files",
                    "photos_dir": "/external/photos",
                }
            ),
            "utf-8",
        )
        staged = SimpleNamespace(
            data_dir=candidate,
            manifest={
                "database": {"applied_migrations": [{"version": 17, "name": "x"}]},
                "locations": [
                    {"role": "vault", "included": True, "storage": "data", "subpath": "vault"},
                    {"role": "files", "included": True, "storage": "data", "subpath": "files"},
                    {"role": "photos", "included": False, "storage": None, "subpath": None},
                ],
            },
        )

        def inspect_probe(path, *, passes):
            current = json.loads((path / "settings.json").read_text("utf-8"))
            self.assertTrue(Path(current["vault_dir"]).is_relative_to(candidate.resolve()))
            self.assertTrue(Path(current["files_dir"]).is_relative_to(candidate.resolve()))
            self.assertNotIn("photos_dir", current)
            self.assertEqual(passes, 2)
            return True

        final_root = self.root / "final-data"
        with mock.patch.object(cli, "_run_recovery_probe", side_effect=inspect_probe):
            cli._prepare_staged_candidate(staged, final_root)

        final = json.loads(settings.read_text("utf-8"))
        self.assertEqual(final["vault_dir"], str((final_root / "vault").resolve()))
        self.assertEqual(final["files_dir"], str((final_root / "files").resolve()))
        self.assertEqual(final["photos_dir"], "/external/photos")


if __name__ == "__main__":
    unittest.main()
