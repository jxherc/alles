import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cli
from services import native_install, update_safety
from services.backup_recovery import staging_root


class NativeUpdateCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-native-update-cli-")
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.updates = self.root / "updates"
        self.releases = self.root / "releases"
        self.releases.mkdir()
        self.previous = self.root / "previous-release"
        self.layout = SimpleNamespace(
            data_root=self.data,
            releases=self.releases,
            previous_release=self.previous,
        )
        self.old = "a" * 40
        self.new = "b" * 40
        self.manifest = {
            "release_id": "old-release",
            "source": {
                "kind": "git",
                "url": "https://example.test/alles.git",
                "branch": "main",
                "commit": self.old,
            },
        }
        self.source = self.root / "source"
        self.source.mkdir()
        self.release = self.releases / self.new
        self.release.mkdir()
        self.python = self.release / ".venv" / "bin" / "python"
        self.python.parent.mkdir(parents=True)
        self.python.write_text("", "utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_native_install_prints_the_owned_service_endpoint(self):
        layout = SimpleNamespace()
        installed = {"runtime_root": "/owned/runtime", "data_root": "/owned/data"}
        with (
            mock.patch.object(cli, "IS_WIN", False),
            mock.patch.object(native_install, "platform_layout", return_value=layout),
            mock.patch.object(native_install, "install", return_value=installed) as install,
            mock.patch.object(
                cli,
                "_native_service_endpoint",
                return_value=(6769, "http://127.0.0.1:6769"),
            ) as endpoint,
            mock.patch("builtins.print") as output,
        ):
            self.assertTrue(cli.cmd_install())

        install.assert_called_once_with(
            cli.ROOT,
            layout,
            release_probe=cli._native_install_probe,
        )
        endpoint.assert_called_once_with(layout)
        output.assert_any_call("setup: http://127.0.0.1:6769")

    def _patches(self, *, healthy=True):
        rollback = SimpleNamespace(restore_id="c" * 32, manifest={"locations": []})
        candidate_dir = self.root / "candidate"
        candidate_dir.mkdir(exist_ok=True)
        candidate = SimpleNamespace(restore_id="d" * 32, data_dir=candidate_dir)
        operation = SimpleNamespace(operation_id="e" * 32)
        lock = mock.Mock()
        return (
            rollback,
            candidate,
            operation,
            lock,
            [
                mock.patch.object(
                    cli, "_update_paths", return_value=(self.updates, self.updates / "latest.json")
                ),
                mock.patch.object(
                    cli, "_fetch_native_update_source", return_value=(self.source, self.new)
                ),
                mock.patch("services.native_install.verify_install", return_value=self.manifest),
                mock.patch(
                    "services.native_install.stage_update_release", return_value=self.release
                ),
                mock.patch("services.native_install.activate_release"),
                mock.patch.object(cli, "_native_candidate_control_plane_ok", return_value=True),
                mock.patch.object(cli, "_native_service_running", return_value=True),
                mock.patch.object(cli, "_native_stop_service"),
                mock.patch.object(
                    cli,
                    "_stage_update_data",
                    return_value=(rollback, candidate, self.root / "rollback.alles-backup"),
                ),
                mock.patch.object(cli, "_coverage_issues", return_value=[]),
                mock.patch.object(cli, "_run_recovery_probe", return_value=healthy),
                mock.patch.object(cli, "_native_start_service_healthy", return_value=True),
                mock.patch("services.instance_lock.InstanceLock", return_value=lock),
                mock.patch(
                    "services.restore_apply.begin_restore_operation", return_value=operation
                ),
                mock.patch("services.restore_apply.swap_in_staged"),
                mock.patch("services.restore_apply.complete_restore_operation"),
                mock.patch("services.update_safety.begin_update"),
                mock.patch("services.update_safety.finish_update"),
                mock.patch("sys.stdout"),
            ],
        )

    def _state(self, phase="applied"):
        return {
            "kind": "native",
            "phase": phase,
            "update_id": "e" * 32,
            "old_release": "old-release",
            "new_release": self.new,
            "old_commit": self.old,
            "new_commit": self.new,
            "was_running": True,
        }

    def test_checkout_timeout_is_reported_as_a_safe_update_failure(self):
        resolved = subprocess.CompletedProcess([], 0, f"{self.new}\trefs/heads/main\n", "")
        with mock.patch.object(
            cli.subprocess,
            "run",
            side_effect=[resolved, subprocess.TimeoutExpired(["git", "init"], 300)],
        ):
            with self.assertRaisesRegex(RuntimeError, "downloaded safely"):
                cli._fetch_native_update_source(self.manifest, self.updates)

        self.assertEqual(list(self.updates.glob(".native-source-*")), [])

    def test_native_update_stages_data_switches_release_and_keeps_rollback_state(self):
        rollback, candidate, operation, lock, patches = self._patches(healthy=True)
        with patches[0]:
            with patches[1]:
                with patches[2] as verify, patches[3] as stage, patches[4] as activate:
                    with patches[5], patches[6], patches[7], patches[8] as stage_data:
                        with patches[9], patches[10] as probe, patches[11] as start:
                            with (
                                patches[12],
                                patches[13],
                                patches[14] as swap,
                                patches[15] as complete,
                            ):
                                with patches[16] as begin, patches[17] as finish, patches[18]:
                                    lifecycle = []
                                    start.side_effect = lambda _layout: (
                                        lifecycle.append("start") or True
                                    )
                                    finish.side_effect = lambda *_args: lifecycle.append("finish")
                                    result = cli._cmd_native_update(self.layout)

        self.assertTrue(result)
        verify.assert_called()
        stage.assert_called_once()
        stage_data.assert_called_once_with(
            self.data.resolve(),
            self.release,
            self.updates,
            python_path=self.python,
            artifact_callback=mock.ANY,
        )
        swap.assert_called_once_with(operation, candidate.data_dir)
        activate.assert_called_once_with(self.layout, self.new, source_commit=self.new)
        probe.assert_called_once_with(
            self.data.resolve(), passes=1, app_root=self.release, python_path=self.python
        )
        complete.assert_called_once_with(operation)
        start.assert_called_once_with(self.layout)
        begin.assert_called_once()
        finish.assert_called_once()
        self.assertEqual(lifecycle, ["start", "finish"])
        self.assertTrue(lock.acquire.called)
        state = cli._load_native_update_state(self.updates / "native-latest.json")
        self.assertEqual(state["phase"], "applied")
        self.assertEqual(state["restore_id"], rollback.restore_id)

    def test_native_update_refuses_to_overlap_another_update_command(self):
        held = update_safety.UpdateCommandLock(self.data).acquire()
        try:
            with mock.patch.object(cli, "_cmd_native_update_locked") as update:
                result = cli._cmd_native_update(self.layout)
        finally:
            held.release()

        self.assertFalse(result)
        update.assert_not_called()

    def test_native_update_publishes_recovery_state_before_acquiring_marker(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=True)
        calls = []
        with ExitStack() as stack:
            entered = [stack.enter_context(patch) for patch in patches]
            entered[16].side_effect = lambda *_args: calls.append("begin")
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "_write_update_state",
                    side_effect=lambda _path, state: calls.append(
                        f"write:{state['phase']}" if state else "clear"
                    ),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "_create_native_update_state",
                    side_effect=lambda _path, state: calls.append(f"write:{state['phase']}"),
                )
            )
            result = cli._cmd_native_update(self.layout)

        self.assertTrue(result)
        self.assertLess(calls.index("write:preparing"), calls.index("begin"))

    def test_native_update_publishes_staged_artifacts_before_coverage_rejection(self):
        rollback, candidate, _operation, _lock, patches = self._patches(healthy=True)
        state_path = self.updates / "native-latest.json"

        def reject_coverage(_staged):
            state = cli._load_native_update_state(state_path)
            self.assertEqual(state["phase"], "data_staged")
            self.assertEqual(state["restore_id"], rollback.restore_id)
            self.assertEqual(state["candidate_id"], candidate.restore_id)
            self.assertEqual(state["backup"], str(self.root / "rollback.alles-backup"))
            return ["external photos"]

        with ExitStack() as stack:
            entered = [stack.enter_context(patch) for patch in patches]
            entered[9].side_effect = reject_coverage
            finish_rollback = stack.enter_context(
                mock.patch.object(cli, "_native_finish_rollback", return_value=True)
            )
            result = cli._cmd_native_update(self.layout)

        self.assertFalse(result)
        finish_rollback.assert_called_once()
        self.assertEqual(finish_rollback.call_args.args[1]["phase"], "data_staged")

    def test_native_update_persists_service_stop_intent_before_stopping(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=True)
        state_path = self.updates / "native-latest.json"

        def assert_stop_intent(_layout):
            self.assertEqual(cli._load_native_update_state(state_path)["phase"], "stopping_service")

        with ExitStack() as stack:
            entered = [stack.enter_context(patch) for patch in patches]
            entered[7].side_effect = assert_stop_intent
            result = cli._cmd_native_update(self.layout)

        self.assertTrue(result)

    def test_native_update_persists_completed_service_stop_before_staging(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=True)
        state_path = self.updates / "native-latest.json"

        def assert_service_stopped(_live, _release, _updates, **_kwargs):
            self.assertEqual(cli._load_native_update_state(state_path)["phase"], "service_stopped")
            return patches_result

        patches_result = (
            SimpleNamespace(restore_id="c" * 32, manifest={"locations": []}),
            SimpleNamespace(restore_id="d" * 32, data_dir=self.root / "candidate"),
            self.root / "rollback.alles-backup",
        )
        patches_result[1].data_dir.mkdir(exist_ok=True)
        with ExitStack() as stack:
            entered = [stack.enter_context(patch) for patch in patches]
            entered[8].side_effect = assert_service_stopped
            result = cli._cmd_native_update(self.layout)

        self.assertTrue(result)

    def test_native_update_persists_each_staged_identity_before_staging_can_interrupt(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=True)
        backup = self.updates / "owned-run" / "pre-update.alles-backup"

        def interrupted_stage(_live, _release, _updates, *, python_path, artifact_callback):
            self.assertEqual(python_path, self.python)
            artifact_callback(backup=str(backup))
            artifact_callback(restore_id="c" * 32)
            raise SystemExit("staging interrupted")

        with ExitStack() as stack:
            entered = [stack.enter_context(patch) for patch in patches]
            entered[8].side_effect = interrupted_stage
            with self.assertRaisesRegex(SystemExit, "staging interrupted"):
                cli._cmd_native_update(self.layout)

        state = cli._load_native_update_state(self.updates / "native-latest.json")
        self.assertEqual(state["phase"], "service_stopped")
        self.assertEqual(state["backup"], str(backup))
        self.assertEqual(state["restore_id"], "c" * 32)
        self.assertNotIn("candidate_id", state)

    def test_interruption_during_native_staging_leaves_recoverable_state_and_marker(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=True)
        with ExitStack() as stack:
            for index, patcher in enumerate(patches):
                if index not in {3, 16}:
                    stack.enter_context(patcher)
            stack.enter_context(
                mock.patch(
                    "services.native_install.stage_update_release",
                    side_effect=SystemExit("simulated power loss"),
                )
            )
            with self.assertRaisesRegex(SystemExit, "power loss"):
                cli._cmd_native_update(self.layout)

        state = cli._load_native_update_state(self.updates / "native-latest.json")
        self.assertEqual(state["phase"], "preparing")
        self.assertTrue(update_safety.update_start_allowed(self.data, state["update_id"]))
        update_safety.finish_update(self.data, state["update_id"])

    def test_native_update_keeps_maintenance_active_through_service_startup(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=True)
        calls = []
        with ExitStack() as stack:
            entered = [stack.enter_context(patch) for patch in patches]
            entered[11].side_effect = lambda _layout: calls.append("start") or True
            entered[17].side_effect = lambda *_args: calls.append("finish")
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "_write_update_state",
                    side_effect=lambda _path, state: calls.append(
                        f"write:{state['phase']}" if state else "clear"
                    ),
                )
            )
            result = cli._cmd_native_update(self.layout)

        self.assertTrue(result)
        self.assertLess(calls.index("write:applied"), calls.index("start"))
        self.assertLess(calls.index("start"), calls.index("finish"))

    def test_native_lock_conflict_never_rolls_back_an_unowned_update(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=True)
        with ExitStack() as stack:
            for index, patch in enumerate(patches):
                if index != 16:
                    stack.enter_context(patch)
            begin = stack.enter_context(
                mock.patch(
                    "services.update_safety.begin_update",
                    side_effect=update_safety.UpdateSafetyError("another update owns the lock"),
                )
            )
            rollback = stack.enter_context(mock.patch.object(cli, "_native_finish_rollback"))
            discard = stack.enter_context(
                mock.patch("services.native_install.discard_inactive_release")
            )
            result = cli._cmd_native_update(self.layout)

        self.assertFalse(result)
        begin.assert_called_once()
        rollback.assert_not_called()
        discard.assert_not_called()

    def test_rejected_native_candidate_releases_the_update_marker(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=True)
        real_begin = update_safety.begin_update
        real_finish = update_safety.finish_update
        with ExitStack() as stack:
            entered = [stack.enter_context(patch) for patch in patches]
            entered[16].side_effect = real_begin
            entered[17].side_effect = real_finish
            entered[5].return_value = False
            discard = stack.enter_context(
                mock.patch("services.native_install.discard_inactive_release")
            )
            result = cli._cmd_native_update(self.layout)

        self.assertFalse(result)
        entered[16].assert_called_once()
        entered[17].assert_called_once()
        discard.assert_called_once_with(self.layout, self.new)

    def test_native_rollback_discards_transient_recovery_artifacts_before_state(self):
        state_path = self.updates / "native-latest.json"
        backup = self.updates / "owned-run" / "pre-update.alles-backup"
        backup.parent.mkdir(parents=True)
        backup.write_bytes(b"owned encrypted backup")
        state = {
            **self._state("rolled_back"),
            "restore_id": "c" * 32,
            "candidate_id": "d" * 32,
            "operation_id": "f" * 32,
            "backup": str(backup),
            "was_running": False,
        }
        cli._write_update_state(state_path, state)
        update_safety.begin_update(self.data, state["update_id"])
        recovery = staging_root(self.data)
        (recovery / "staged" / state["restore_id"]).mkdir(parents=True)
        (recovery / "staged" / state["candidate_id"]).mkdir(parents=True)
        operation = recovery / "operations" / f"{state['operation_id']}.json"
        operation.parent.mkdir(parents=True)
        operation.write_text("{}", "utf-8")
        with (
            mock.patch.object(cli, "_native_rollback_update", return_value=True),
            mock.patch(
                "services.backup_recovery.discard_consumed_staged_recovery"
            ) as discard_consumed,
            mock.patch("services.backup_recovery.discard_staged_recovery") as discard_staged,
            mock.patch("services.restore_apply.discard_completed_restore") as discard_operation,
        ):
            result = cli._native_finish_rollback(self.layout, state, state_path)

        self.assertTrue(result)
        self.assertEqual(
            discard_consumed.call_args_list,
            [
                mock.call(self.data, state["candidate_id"]),
                mock.call(self.data, state["restore_id"]),
            ],
        )
        discard_operation.assert_called_once_with(self.data, state["operation_id"])
        discard_staged.assert_not_called()
        self.assertFalse(backup.exists())
        self.assertFalse(state_path.exists())
        self.assertFalse(update_safety.update_lock_path(self.data).exists())

    def test_native_rollback_discards_an_unconsumed_preflight_as_a_staged_recovery(self):
        state_path = self.updates / "native-latest.json"
        state = {
            **self._state("data_staged"),
            "restore_id": "c" * 32,
            "candidate_id": "d" * 32,
            "was_running": False,
        }
        cli._write_update_state(state_path, state)
        update_safety.begin_update(self.data, state["update_id"])
        recovery = staging_root(self.data)
        (recovery / "staged" / state["restore_id"]).mkdir(parents=True)
        (recovery / "staged" / state["candidate_id"] / "data").mkdir(parents=True)

        with (
            mock.patch.object(cli, "_native_rollback_update", return_value=True),
            mock.patch(
                "services.backup_recovery.discard_consumed_staged_recovery"
            ) as discard_consumed,
            mock.patch("services.backup_recovery.discard_staged_recovery") as discard_staged,
        ):
            result = cli._native_finish_rollback(self.layout, state, state_path)

        self.assertTrue(result)
        discard_consumed.assert_called_once_with(self.data, state["restore_id"])
        self.assertEqual(
            discard_staged.call_args_list,
            [
                mock.call(self.data, state["candidate_id"]),
            ],
        )
        self.assertFalse(state_path.exists())
        self.assertFalse(update_safety.update_lock_path(self.data).exists())

    def test_native_health_failure_runs_automatic_rollback(self):
        _rollback, _candidate, _operation, _lock, patches = self._patches(healthy=False)
        with patches[0]:
            with patches[1]:
                with patches[2], patches[3], patches[4]:
                    with patches[5], patches[6], patches[7], patches[8]:
                        with patches[9], patches[10], patches[11]:
                            with patches[12], patches[13], patches[14], patches[15]:
                                with patches[16], patches[17], patches[18]:
                                    with mock.patch.object(
                                        cli, "_native_finish_rollback", return_value=True
                                    ) as rollback:
                                        result = cli._cmd_native_update(self.layout)

        self.assertFalse(result)
        rollback.assert_called_once()

    def test_preparing_rollback_discards_candidate_without_stopping_live_service(self):
        state_path = self.updates / "native-latest.json"
        state = self._state("preparing")
        self.release.mkdir(exist_ok=True)
        with (
            mock.patch(
                "services.native_install.verify_install",
                return_value={"release_id": state["old_release"]},
            ),
            mock.patch("services.native_install.discard_inactive_release") as discard,
            mock.patch.object(cli, "_native_stop_service") as stop,
            mock.patch.object(cli, "_native_restore_update_data") as restore,
        ):
            result = cli._native_rollback_update(self.layout, state, state_path)

        self.assertTrue(result)
        stop.assert_not_called()
        restore.assert_not_called()
        discard.assert_called_once_with(self.layout, state["new_release"])
        self.assertEqual(cli._load_native_update_state(state_path)["phase"], "rolled_back")

    def test_service_stopped_rollback_does_not_restore_data_that_was_never_swapped(self):
        state_path = self.updates / "native-latest.json"
        state = {
            **self._state("service_stopped"),
            "restore_id": "c" * 32,
            "was_running": True,
        }
        with (
            mock.patch.object(cli, "_native_stop_service"),
            mock.patch.object(cli, "_native_restore_update_data") as restore,
            mock.patch(
                "services.native_install.verify_install",
                return_value={"release_id": state["old_release"]},
            ),
            mock.patch("services.native_install.discard_inactive_release") as discard,
        ):
            result = cli._native_rollback_update(self.layout, state, state_path)

        self.assertTrue(result)
        restore.assert_not_called()
        discard.assert_called_once_with(self.layout, state["new_release"])
        self.assertEqual(cli._load_native_update_state(state_path)["phase"], "rolled_back")

    def test_data_staged_rollback_does_not_restore_data_that_was_never_swapped(self):
        state_path = self.updates / "native-latest.json"
        state = {
            **self._state("data_staged"),
            "restore_id": "c" * 32,
            "candidate_id": "d" * 32,
            "was_running": True,
        }
        with (
            mock.patch.object(cli, "_native_stop_service"),
            mock.patch.object(cli, "_native_restore_update_data") as restore,
            mock.patch(
                "services.native_install.verify_install",
                return_value={"release_id": state["old_release"]},
            ),
            mock.patch("services.native_install.discard_inactive_release") as discard,
        ):
            result = cli._native_rollback_update(self.layout, state, state_path)

        self.assertTrue(result)
        restore.assert_not_called()
        discard.assert_called_once_with(self.layout, state["new_release"])
        self.assertEqual(cli._load_native_update_state(state_path)["phase"], "rolled_back")

    def test_preparing_finish_does_not_restart_an_already_live_service(self):
        state = self._state("preparing")
        with (
            mock.patch.object(cli, "_native_rollback_update", return_value=True),
            mock.patch.object(cli, "_native_complete_rollback", return_value=True),
            mock.patch.object(cli, "_native_start_service_healthy") as start,
            mock.patch.object(cli, "_native_clear_rollback_state", return_value=True),
        ):
            result = cli._native_finish_rollback(
                self.layout, state, self.updates / "native-latest.json"
            )

        self.assertTrue(result)
        start.assert_not_called()

    def test_stopping_service_finish_does_not_restart_when_stop_never_completed(self):
        state = self._state("stopping_service")
        with (
            mock.patch.object(cli, "_native_service_running", return_value=True),
            mock.patch.object(cli, "_native_complete_rollback", return_value=True),
            mock.patch.object(cli, "_native_start_service_healthy") as start,
            mock.patch.object(cli, "_native_clear_rollback_state", return_value=True),
            mock.patch(
                "services.native_install.verify_install", return_value={"release_id": "old-release"}
            ),
            mock.patch("services.native_install.discard_inactive_release"),
        ):
            result = cli._native_finish_rollback(
                self.layout, state, self.updates / "native-latest.json"
            )

        self.assertTrue(result)
        start.assert_not_called()

    def test_stopping_service_finish_restarts_when_stop_completed_before_phase_write(self):
        state = self._state("stopping_service")
        with (
            mock.patch.object(cli, "_native_service_running", return_value=False),
            mock.patch.object(cli, "_native_stop_service"),
            mock.patch.object(cli, "_native_restore_update_data", return_value=True),
            mock.patch.object(cli, "_native_complete_rollback", return_value=True),
            mock.patch.object(cli, "_native_start_service_healthy", return_value=True) as start,
            mock.patch.object(cli, "_native_clear_rollback_state", return_value=True),
            mock.patch(
                "services.native_install.verify_install", return_value={"release_id": "old-release"}
            ),
            mock.patch("services.native_install.discard_inactive_release"),
        ):
            result = cli._native_finish_rollback(
                self.layout, state, self.updates / "native-latest.json"
            )

        self.assertTrue(result)
        start.assert_called_once_with(self.layout)

    def test_native_service_checks_ignore_the_callers_port_override(self):
        with (
            mock.patch("services.native_install.verify_install", return_value=self.manifest),
            mock.patch.object(cli, "_native_service_running", return_value=False),
            mock.patch.object(cli, "_port_open", side_effect=[False, False]) as port_open,
            mock.patch.dict("os.environ", {"PORT": "7777"}),
        ):
            cli._native_stop_service(self.layout)

        self.assertEqual([call.args for call in port_open.call_args_list], [(6769,), (6769,)])

        with (
            mock.patch("services.native_install.verify_install", return_value=self.manifest),
            mock.patch("services.service_manager.control"),
            mock.patch.object(cli, "_native_service_running", return_value=True),
            mock.patch.object(cli, "_health_endpoint_ok", return_value=True) as health,
            mock.patch.dict("os.environ", {"PORT": "7777"}),
        ):
            self.assertTrue(cli._native_start_service_healthy(self.layout))

        health.assert_called_once_with(timeout=1, base_url="http://127.0.0.1:6769")

    def test_health_endpoint_rejects_redirects_and_proxy_inheritance(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.geturl.return_value = "http://attacker.test/health"
        response.read.return_value = b'{"ok": true}'
        opener = mock.Mock()
        opener.open.return_value = response

        with mock.patch("urllib.request.build_opener", return_value=opener) as build:
            self.assertFalse(cli._health_endpoint_ok(base_url="http://127.0.0.1:6769"))

        self.assertEqual(build.call_args.args[0].proxies, {})
        opener.open.assert_called_once_with("http://127.0.0.1:6769/health", timeout=3)

    def test_accept_and_rollback_share_the_native_command_mutex(self):
        command_lock = mock.Mock()
        with (
            mock.patch("services.update_safety.UpdateCommandLock", return_value=command_lock),
            mock.patch.object(cli, "_cmd_native_update_accept_locked", return_value=True) as accept,
        ):
            self.assertTrue(cli._cmd_native_update_accept(self.layout))
        command_lock.acquire.assert_called_once_with()
        command_lock.release.assert_called_once_with()
        accept.assert_called_once_with(self.layout)

        command_lock.reset_mock()
        with (
            mock.patch("services.update_safety.UpdateCommandLock", return_value=command_lock),
            mock.patch.object(
                cli, "_cmd_native_update_rollback_locked", return_value=True
            ) as rollback,
        ):
            self.assertTrue(cli._cmd_native_update_rollback(self.layout))
        command_lock.acquire.assert_called_once_with()
        command_lock.release.assert_called_once_with()
        rollback.assert_called_once_with(self.layout)

    def test_manual_rollback_resumes_the_exact_saved_native_update(self):
        state_path = self.updates / "native-latest.json"
        cli._write_update_state(state_path, self._state())
        with mock.patch.object(
            cli, "_update_paths", return_value=(self.updates, self.updates / "latest.json")
        ):
            with mock.patch("services.update_safety.begin_update") as begin:
                with mock.patch.object(cli, "_native_finish_rollback", return_value=True) as finish:
                    with mock.patch("sys.stdout"):
                        result = cli._cmd_native_update_rollback(self.layout)

        self.assertTrue(result)
        begin.assert_called_once_with(self.data, "e" * 32)
        finish.assert_called_once_with(self.layout, self._state(), state_path)

    def test_interrupted_data_swap_recovers_only_its_exact_restore_operation(self):
        operation = SimpleNamespace(operation_id="f" * 32)
        state = {
            **self._state("data_swapping"),
            "operation_id": operation.operation_id,
            "restore_id": "c" * 32,
        }
        lock = mock.Mock()
        with mock.patch("services.instance_lock.InstanceLock", return_value=lock):
            with mock.patch(
                "services.restore_apply.active_restore_operation", return_value=operation
            ):
                with mock.patch(
                    "services.restore_apply.recover_interrupted_restore",
                    return_value={"status": "rolled_back"},
                ) as recover:
                    with mock.patch.object(cli, "_apply_staged_restore") as fallback:
                        result = cli._native_restore_update_data(state, self.data)

        self.assertTrue(result)
        recover.assert_called_once_with(self.data)
        fallback.assert_not_called()
        lock.acquire.assert_called_once()
        lock.release.assert_called_once()

    def test_interrupted_data_swap_refuses_an_unrelated_restore_operation(self):
        state = {
            **self._state("data_swapping"),
            "operation_id": "f" * 32,
            "restore_id": "c" * 32,
        }
        unrelated = SimpleNamespace(operation_id="1" * 32)
        lock = mock.Mock()
        with mock.patch("services.instance_lock.InstanceLock", return_value=lock):
            with mock.patch(
                "services.restore_apply.active_restore_operation", return_value=unrelated
            ):
                with mock.patch.object(cli, "_apply_staged_restore") as fallback:
                    result = cli._native_restore_update_data(state, self.data)

        self.assertFalse(result)
        fallback.assert_not_called()
        lock.release.assert_called_once()

    def test_missing_saved_operation_id_recovers_the_matching_active_swap(self):
        operation = SimpleNamespace(operation_id="f" * 32, restore_id="d" * 32)
        state = {
            **self._state("data_staged"),
            "candidate_id": operation.restore_id,
            "restore_id": "c" * 32,
        }
        lock = mock.Mock()
        with mock.patch("services.instance_lock.InstanceLock", return_value=lock):
            with mock.patch(
                "services.restore_apply.active_restore_operation", return_value=operation
            ):
                with mock.patch(
                    "services.restore_apply.recover_interrupted_restore",
                    return_value={"status": "rolled_back"},
                ) as recover:
                    with mock.patch.object(cli, "_apply_staged_restore") as fallback:
                        result = cli._native_restore_update_data(state, self.data)

        self.assertTrue(result)
        self.assertEqual(state["operation_id"], operation.operation_id)
        recover.assert_called_once_with(self.data)
        fallback.assert_not_called()
        lock.release.assert_called_once()

    def test_completed_interrupted_rollback_clears_its_exact_markers(self):
        state_path = self.updates / "native-latest.json"
        state = self._state("rolled_back")
        cli._write_update_state(state_path, state)
        update_safety.begin_update(self.data, state["update_id"])
        with mock.patch.object(
            cli, "_update_paths", return_value=(self.updates, self.updates / "latest.json")
        ):
            with mock.patch.object(cli, "_native_start_service_healthy", return_value=True):
                with mock.patch("sys.stdout"):
                    result = cli._cmd_native_update_rollback(self.layout)

        self.assertTrue(result)
        self.assertFalse(state_path.exists())
        self.assertFalse(update_safety.update_lock_path(self.data).exists())

    def test_interrupted_rollback_keeps_retry_state_until_service_restarts(self):
        state_path = self.updates / "native-latest.json"
        state = self._state("rolled_back")
        cli._write_update_state(state_path, state)
        with (
            mock.patch.object(
                cli, "_update_paths", return_value=(self.updates, self.updates / "latest.json")
            ),
            mock.patch.object(cli, "_native_complete_rollback", return_value=True),
            mock.patch.object(cli, "_native_start_service_healthy", return_value=False),
            mock.patch("sys.stdout"),
        ):
            result = cli._cmd_native_update_rollback(self.layout)

        self.assertFalse(result)
        self.assertEqual(cli._load_native_update_state(state_path)["phase"], "rolled_back")

    def test_interrupted_untouched_rollback_does_not_restart_service(self):
        state_path = self.updates / "native-latest.json"
        state = {
            **self._state("rolled_back"),
            "service_was_untouched": True,
            "was_running": True,
        }
        cli._write_update_state(state_path, state)
        with (
            mock.patch.object(
                cli, "_update_paths", return_value=(self.updates, self.updates / "latest.json")
            ),
            mock.patch.object(cli, "_native_complete_rollback", return_value=True),
            mock.patch.object(cli, "_native_start_service_healthy") as start,
            mock.patch.object(cli, "_native_clear_rollback_state", return_value=True),
        ):
            result = cli._cmd_native_update_rollback(self.layout)

        self.assertTrue(result)
        start.assert_not_called()

    def test_accept_clears_transient_state_but_keeps_encrypted_backup(self):
        state_path = self.updates / "native-latest.json"
        backup = self.updates / "rollback.alles-backup"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b"encrypted rollback")
        state = {**self._state(), "backup": str(backup)}
        cli._write_update_state(state_path, state)
        with mock.patch.object(
            cli, "_update_paths", return_value=(self.updates, self.updates / "latest.json")
        ):
            with mock.patch(
                "services.native_install.verify_install", return_value={"release_id": self.new}
            ):
                with mock.patch("services.native_install.accept_release") as accept:
                    with mock.patch(
                        "services.recovery_crypto.is_encrypted_recovery", return_value=True
                    ):
                        with mock.patch("sys.stdout"):
                            result = cli._cmd_native_update_accept(self.layout)

        self.assertTrue(result)
        accept.assert_called_once_with(self.layout, expected_previous="old-release")
        self.assertFalse(state_path.exists())
        self.assertEqual(backup.read_bytes(), b"encrypted rollback")

    def test_accept_failure_keeps_recovery_state_for_a_safe_retry(self):
        state_path = self.updates / "native-latest.json"
        backup = self.updates / "rollback.alles-backup"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b"encrypted rollback")
        restore_id = "c" * 32
        staged = staging_root(self.data) / "staged" / restore_id
        staged.mkdir(parents=True)
        cli._write_update_state(
            state_path,
            {**self._state(), "backup": str(backup), "restore_id": restore_id},
        )
        with (
            mock.patch.object(
                cli,
                "_update_paths",
                return_value=(self.updates, self.updates / "latest.json"),
            ),
            mock.patch(
                "services.native_install.verify_install", return_value={"release_id": self.new}
            ),
            mock.patch(
                "services.native_install.accept_release",
                side_effect=OSError("release removal failed"),
            ),
            mock.patch("services.recovery_crypto.is_encrypted_recovery", return_value=True),
            mock.patch("sys.stdout"),
        ):
            result = cli._cmd_native_update_accept(self.layout)

        self.assertFalse(result)
        self.assertTrue(staged.exists())
        self.assertEqual(cli._load_native_update_state(state_path)["phase"], "accepting")

    def test_accepting_state_retries_an_already_finalized_release_acceptance(self):
        state_path = self.updates / "native-latest.json"
        backup = self.updates / "rollback.alles-backup"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(b"encrypted rollback")
        cli._write_update_state(
            state_path,
            {**self._state("accepting"), "backup": str(backup)},
        )
        with (
            mock.patch.object(
                cli,
                "_update_paths",
                return_value=(self.updates, self.updates / "latest.json"),
            ),
            mock.patch(
                "services.native_install.verify_install", return_value={"release_id": self.new}
            ),
            mock.patch(
                "services.native_install.accept_release", return_value="old-release"
            ) as accept,
            mock.patch("services.recovery_crypto.is_encrypted_recovery", return_value=True),
            mock.patch("sys.stdout"),
        ):
            result = cli._cmd_native_update_accept(self.layout)

        self.assertTrue(result)
        accept.assert_called_once_with(self.layout, expected_previous="old-release")
        self.assertFalse(state_path.exists())
        self.assertEqual(backup.read_bytes(), b"encrypted rollback")


if __name__ == "__main__":
    unittest.main()
