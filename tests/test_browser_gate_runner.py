"""Runner regressions for isolation, server identity and child-process cleanup."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "browser_gate_runner", ROOT / "scripts/run_browser_gates.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class BrowserGateRunnerTest(unittest.TestCase):
    def test_child_environment_cannot_inherit_owner_database_or_credentials(self):
        with patch.dict(
            os.environ,
            {
                "ALLES_DATA": "/owner/data",
                "ALLES_DB": "/owner/private.db",
                "DEEPSEEK_API_KEY": "private",
                "SECRET_KEY": "private",
                "HTTP_PROXY": "http://owner-proxy",
                "PYTHONPATH": "/owner/hooks",
                "HOME": "/test-home",
                "PATH": "/test-path",
            },
            clear=True,
        ):
            env = runner.isolated_environment(
                Path("/tmp/owned"), "proof", 1234, Path("/tmp/evidence")
            )
        self.assertEqual(env["ALLES_DB"], "/tmp/owned/aide.db")
        self.assertEqual(env["ALLES_DATA"], "/tmp/owned")
        self.assertEqual(env["PYTHON_DOTENV_DISABLED"], "1")
        self.assertEqual(env["ALLES_HOST"], "127.0.0.1")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(env["FASTEMBED_CACHE_PATH"], "/tmp/owned/model-cache/fastembed")
        self.assertEqual(env["HF_HOME"], "/tmp/owned/model-cache/huggingface")
        for private in ("DEEPSEEK_API_KEY", "SECRET_KEY", "HTTP_PROXY", "PYTHONPATH"):
            self.assertNotIn(private, env)

    def test_each_gate_gets_unique_owned_data_and_cleanup_after_failure(self):
        seen = []
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                with runner.owned_data() as (data, run_id):
                    self.assertEqual((data / ".alles-test-owner").read_text(), run_id)
                    (data / "synthetic.txt").write_text("test data")
                    seen.append((data, run_id))
                    raise RuntimeError("synthetic failure")
            self.assertFalse(data.exists())
        self.assertNotEqual(seen[0], seen[1])
        self.assertNotEqual(seen[0][1], seen[1][1])

    def test_unrelated_server_identity_fails_without_waiting_or_running_gate(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(
            runner,
            "require_server_ownership",
            side_effect=RuntimeError(
                "target server does not match this browser run's owned throwaway data root"
            ),
        ):
            with patch.object(runner.time, "sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "does not match"):
                    runner.wait_for_server(process, 1234, "expected-id", 30)
        sleep.assert_not_called()

    def test_server_exit_is_reported_before_gate_can_start(self):
        process = Mock(returncode=2)
        process.poll.return_value = 2
        with self.assertRaisesRegex(RuntimeError, "exited during startup"):
            runner.wait_for_server(process, 1234, "proof", 30)

    def test_stop_only_terminates_the_spawned_child(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
        )
        runner.stop_process(process)
        self.assertIsNotNone(process.poll())
        runner.stop_process(process)

    def test_nested_server_cleanup_does_not_signal_the_gate_process_group(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=False
        )
        with patch.object(runner.os, "killpg") as kill_group:
            runner.stop_process(process, process_group=False)
        self.assertIsNotNone(process.poll())
        kill_group.assert_not_called()

    def test_product_changes_invalidate_otherwise_passing_results(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            child = Mock(returncode=0)
            child.wait.return_value = 0
            child.poll.return_value = 0
            with (
                patch.object(runner, "build_fingerprint", side_effect=["before", "after"]),
                patch.object(runner, "wait_for_server"),
                patch.object(runner.subprocess, "Popen", return_value=child),
            ):
                result = runner.run_gate("smoke-desktop", output, 5, 5)
            self.assertEqual(result["status"], "invalidated")
            self.assertTrue(result["temporary_data_removed"])
            self.assertTrue(result["server_stopped"])
            stored = json.loads((output / "smoke-desktop/result.json").read_text())
            self.assertEqual(stored, result)

    def test_gate_timeout_is_failed_and_owned_processes_are_stopped(self):
        with tempfile.TemporaryDirectory() as raw:
            server = Mock()
            server.poll.return_value = 0
            gate = Mock()
            gate.wait.side_effect = subprocess.TimeoutExpired("synthetic gate", 1)
            with (
                patch.object(runner, "build_fingerprint", return_value="same"),
                patch.object(runner, "wait_for_server"),
                patch.object(runner.subprocess, "Popen", side_effect=[server, gate]),
                patch.object(runner, "stop_process") as stop,
            ):
                result = runner.run_gate("smoke-phone", Path(raw), 5, 1)
            self.assertEqual(result["status"], "failed")
            self.assertIn("TimeoutExpired", result["error"])
            self.assertEqual([call.args[0] for call in stop.call_args_list], [gate, server])
            self.assertTrue(result["temporary_data_removed"])

    def fake_gate(self, name, status="passed"):
        return {
            "gate": name,
            "status": status,
            "duration_seconds": 0,
            "artifacts": "synthetic",
            "exit_code": 0 if status == "passed" else 1,
            "build_fingerprint": "current",
            "build_fingerprint_after": "current",
            "acceptance_fingerprint": "contract",
            "acceptance_fingerprint_after": "contract",
            "server_stopped": True,
            "temporary_data_removed": True,
            "scenarios": [{"scenario_id": "home.capture", "status": status}],
        }

    def invoke_main(self, output, fake_run, suite="smoke"):
        with (
            patch.object(sys, "argv", ["runner", "--suite", suite, "--output", str(output)]),
            patch.object(runner, "build_fingerprint", return_value="current"),
            patch.object(runner, "acceptance_fingerprint", return_value="contract"),
            patch.object(runner, "git_text", return_value="synthetic"),
            patch.object(runner, "run_gate", side_effect=fake_run),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return runner.main()

    def test_interruption_preserves_incomplete_report_and_never_writes_passed(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            observations = []

            def gate(name, *_args):
                report = json.loads((output / "results.json").read_text())
                observations.append((report["status"], len(report["results"])))
                if len(observations) == 2:
                    raise KeyboardInterrupt()
                return self.fake_gate(name)

            code = self.invoke_main(output, gate, "full")
            report = json.loads((output / "results.json").read_text())
            self.assertEqual(code, 130)
            self.assertEqual(observations, [("running", 0), ("running", 1)])
            self.assertEqual(report["status"], "interrupted")
            self.assertEqual(len(report["results"]), 1)
            self.assertEqual(report["expected_gates"], list(runner.SUITES["full"]))
            self.assertTrue(report["completed_at"])
            self.assertTrue(report["run_id"])

    def test_failed_profile_evidence_is_preserved_and_normalized(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)

            def gate(name, *_args):
                return self.fake_gate(name, "passed" if name == "smoke-desktop" else "failed")

            self.assertEqual(self.invoke_main(output, gate), 1)
            report = json.loads((output / "results.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(
                [(r["status"], r["profiles"]) for r in report["scenarios"]],
                [("passed", ["desktop"]), ("failed", ["phone"])],
            )

    def test_success_is_written_only_after_all_declared_gates_finish(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)

            def gate(name, *_args):
                self.assertEqual(
                    json.loads((output / "results.json").read_text())["status"], "running"
                )
                return self.fake_gate(name)

            self.assertEqual(self.invoke_main(output, gate), 0)
            report = json.loads((output / "results.json").read_text())
            self.assertEqual(report["status"], "passed")
            self.assertEqual([r["gate"] for r in report["results"]], report["expected_gates"])

    def test_old_evidence_from_a_different_suite_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            path = output / "results.json"
            path.write_text('{"suite":"daily","status":"failed"}')
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                self.invoke_main(output, lambda *_args: self.fail("must not execute a gate"))
            self.assertEqual(json.loads(path.read_text()), {"suite": "daily", "status": "failed"})

    def test_gate_interruption_cleans_children_and_keeps_result_artifacts(self):
        with tempfile.TemporaryDirectory() as raw:
            server, gate = Mock(), Mock()
            server.poll.return_value = 0
            gate.wait.side_effect = KeyboardInterrupt()
            with (
                patch.object(runner, "build_fingerprint", return_value="current"),
                patch.object(runner, "acceptance_fingerprint", return_value="contract"),
                patch.object(runner, "wait_for_server"),
                patch.object(runner.subprocess, "Popen", side_effect=[server, gate]),
                patch.object(runner, "stop_process") as stop,
            ):
                result = runner.run_gate("smoke-phone", Path(raw), 5, 1)
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual([c.args[0] for c in stop.call_args_list], [gate, server])
            self.assertTrue(result["temporary_data_removed"])
            self.assertEqual(
                json.loads((Path(raw) / "smoke-phone/result.json").read_text()), result
            )

    def test_changed_acceptance_contract_invalidates_passing_gate(self):
        with tempfile.TemporaryDirectory() as raw:
            child = Mock()
            child.wait.return_value = 0
            child.poll.return_value = 0
            with (
                patch.object(runner, "build_fingerprint", return_value="current"),
                patch.object(runner, "acceptance_fingerprint", side_effect=["before", "after"]),
                patch.object(runner, "wait_for_server"),
                patch.object(runner.subprocess, "Popen", return_value=child),
            ):
                result = runner.run_gate("smoke-desktop", Path(raw), 5, 5)
            self.assertEqual(result["status"], "invalidated")
            self.assertEqual(result["acceptance_fingerprint_after"], "after")

    def test_explicit_scenario_profiles_are_never_expanded(self):
        result = self.fake_gate("minimal-workflows")
        result["scenarios"][0]["profiles"] = ["desktop"]
        self.assertEqual(runner.scenario_evidence(result)[0]["profiles"], ["desktop"])

    def test_between_gate_source_or_contract_change_cannot_be_hidden_by_reverting(self):
        for field in ("build_fingerprint", "acceptance_fingerprint"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as raw:
                output = Path(raw)

                def gate(name, *_args):
                    result = self.fake_gate(name)
                    if name == "smoke-phone":
                        result[field] = result[field + "_after"] = "different during gate"
                    return result

                self.assertEqual(self.invoke_main(output, gate), 1)
                report = json.loads((output / "results.json").read_text())
                self.assertEqual(report["status"], "invalidated")


if __name__ == "__main__":
    unittest.main()
