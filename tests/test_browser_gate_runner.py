"""Runner regressions for isolation, server identity and child-process cleanup."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "browser_gate_runner", ROOT / "scripts/run_browser_gates.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

import browser_gate_safety as safety  # noqa: E402


class BrowserGateRunnerTest(unittest.TestCase):
    def setUp(self):
        # These tests mock both child processes; reserving a real listening port
        # adds a sandbox dependency without exercising the runner contract.
        self.port = patch.object(runner, "free_port", return_value=12345)
        self.port.start()
        self.addCleanup(self.port.stop)

    def test_owned_child_starts_with_network_isolation(self):
        with runner.owned_data() as (data, run_id):
            env = runner.isolated_environment(data, run_id, 1234, data)
            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import socket; print(getattr(socket, '_alles_loopback_only', False))",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(child.stdout.strip(), "True")
            self.assertTrue((data / "network-isolation.jsonl").is_file())

    def test_libraries_with_their_own_network_stack_cannot_load(self):
        # ddgs talks through primp's rust sockets, which the python socket guard never sees
        with runner.owned_data() as (data, run_id):
            env = runner.isolated_environment(data, run_id, 1234, data)
            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import importlib\n"
                    "for name in ('ddgs', 'primp', 'duckduckgo_search'):\n"
                    "    try:\n"
                    "        importlib.import_module(name); print(name, 'loaded')\n"
                    "    except ImportError:\n"
                    "        print(name, 'blocked')\n",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
                cwd=ROOT,
            )
            self.assertEqual(
                child.stdout.split(),
                ["ddgs", "blocked", "primp", "blocked", "duckduckgo_search", "blocked"],
            )
            blocks = (data / "outbound-blocks.jsonl").read_text()
            self.assertIn("native-network-import", blocks)

    def test_startup_hook_exits_when_ownership_proof_changes(self):
        with runner.owned_data() as (data, run_id):
            env = runner.isolated_environment(data, run_id, 1234, data)
            (data / ".alles-test-owner").write_text("wrong-run")
            child = subprocess.run(
                [sys.executable, "-c", "print('test body must not execute')"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(child.returncode, 78)
            self.assertNotIn("test body must not execute", child.stdout)

    def test_nested_owned_environment_keeps_trusted_hook(self):
        with runner.owned_data() as (parent, parent_id):
            outer = runner.isolated_environment(parent, parent_id, 1234, parent)
            with (
                patch.dict(os.environ, outer, clear=True),
                runner.owned_data() as (child, child_id),
            ):
                inner = runner.isolated_environment(child, child_id, 4321, child)
                self.assertEqual(inner["PYTHONPATH"], str(child / ".browser-network"))
                self.assertNotIn(str(parent), inner["PYTHONPATH"])
                self.assertTrue((child / ".browser-network/sitecustomize.py").is_file())

    def test_scenario_collector_preserves_list_and_wrapped_reports(self):
        scenario = {
            "scenario_id": "knowledge.markdown-attributes",
            "profile": "390",
            "status": "passed",
        }
        common = {"gate": "markdown-attributes", "artifacts": "/tmp/evidence"}
        expected = [{**scenario, **common, "profiles": ["390"]}]
        for evidence in ([scenario], {"scenarios": [scenario]}):
            with self.subTest(evidence=evidence):
                self.assertEqual(
                    runner.scenario_evidence({**common, "scenarios": evidence}), expected
                )

    def test_scenario_collector_rejects_malformed_report_entries(self):
        for evidence in ("invalid", ["invalid"], {"scenarios": "invalid"}):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                runner.scenario_evidence({"scenarios": evidence})

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
        for private in ("DEEPSEEK_API_KEY", "SECRET_KEY", "HTTP_PROXY"):
            self.assertNotIn(private, env)
        self.assertEqual(env["PYTHONPATH"], "/tmp/owned/.browser-network")

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

    def test_gate_keeps_explicit_control_evidence_separate_from_workflows(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            controls = [{"control_id": "synthetic-control", "status": "failed", "profile": "phone"}]
            child = Mock(returncode=0)
            child.poll.return_value = 0

            def finish(**_kwargs):
                (output / "smoke-phone/controls.json").write_text(json.dumps(controls))
                return 0

            child.wait.side_effect = finish
            with (
                patch.object(runner, "build_fingerprint", return_value="current"),
                patch.object(runner, "acceptance_fingerprint", return_value="contract"),
                patch.object(runner, "wait_for_server"),
                patch.object(runner.subprocess, "Popen", return_value=child),
            ):
                result = runner.run_gate("smoke-phone", output, 5, 5)
            self.assertEqual(result.get("controls"), controls)
            self.assertNotIn("scenarios", result)

    def test_suite_preserves_control_failures_without_inventing_control_passes(self):
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)

            def gate(name, *_args):
                result = self.fake_gate(name)
                if name == "smoke-phone":
                    result["controls"] = [{"control_id": "synthetic-control", "status": "failed"}]
                return result

            self.invoke_main(output, gate)
            report = json.loads((output / "results.json").read_text())
            self.assertEqual(
                report.get("controls"),
                [
                    {
                        "control_id": "synthetic-control",
                        "status": "failed",
                        "profiles": ["phone"],
                        "gate": "smoke-phone",
                        "artifacts": "synthetic",
                    }
                ],
            )

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


class BrowserNetworkIsolationTest(unittest.TestCase):
    def assert_blocked_before_transport(self, original, operation):
        original.reset_mock()
        denied = None
        try:
            operation()
        except OSError as exc:
            denied = exc
        original.assert_not_called()
        self.assertIsNotNone(denied)
        self.assertIn("loopback", str(denied))

    def test_reverse_lookup_blocks_remote_and_preserves_loopback(self):
        with tempfile.TemporaryDirectory() as raw, contextlib.ExitStack() as stack:
            original = stack.enter_context(
                patch.object(socket, "gethostbyaddr", return_value="owned")
            )
            stack.enter_context(patch.object(safety.BrowserNetworkGuard, "_install_playwright"))
            guard = safety.BrowserNetworkGuard(Path(raw))
            guard.install()
            stack.callback(guard.close)
            for host in (
                "example.invalid",
                "203.0.113.7",
                "2001:db8::7",
                "::ffff:203.0.113.7",
                "localhost.evil.invalid",
            ):
                with self.subTest(remote=host):
                    self.assert_blocked_before_transport(
                        original, lambda: socket.gethostbyaddr(host)
                    )
            for host, expected in (
                ("127.0.0.1", "127.0.0.1"),
                ("::1", "::1"),
                ("::ffff:127.0.0.1", "::ffff:127.0.0.1"),
                (b"aide.localhost", "127.0.0.1"),
            ):
                with self.subTest(local=host):
                    original.reset_mock()
                    self.assertEqual(socket.gethostbyaddr(host), "owned")
                    original.assert_called_once_with(expected)

    def test_name_lookup_blocks_remote_and_preserves_loopback_sockaddrs(self):
        with tempfile.TemporaryDirectory() as raw, contextlib.ExitStack() as stack:
            original = stack.enter_context(
                patch.object(socket, "getnameinfo", return_value="owned")
            )
            stack.enter_context(patch.object(safety.BrowserNetworkGuard, "_install_playwright"))
            guard = safety.BrowserNetworkGuard(Path(raw))
            guard.install()
            stack.callback(guard.close)
            for address in (
                ("example.invalid", 53),
                ("203.0.113.7", 53),
                ("2001:db8::7", 53, 0, 0),
                ("::ffff:203.0.113.7", 53, 0, 0),
            ):
                for flags in (0, socket.NI_NUMERICHOST | socket.NI_NUMERICSERV):
                    with self.subTest(remote=address, flags=flags):
                        self.assert_blocked_before_transport(
                            original, lambda: socket.getnameinfo(address, flags)
                        )
            for address, expected in (
                (("127.0.0.1", 1234), ("127.0.0.1", 1234)),
                (("aide.localhost", 1234), ("127.0.0.1", 1234)),
                (("::1", 1234, 2, 3), ("::1", 1234, 2, 3)),
                (("aide.localhost", 1234, 2, 3), ("::1", 1234, 2, 3)),
            ):
                with self.subTest(local=address):
                    original.reset_mock()
                    self.assertEqual(socket.getnameinfo(address, socket.NI_NUMERICSERV), "owned")
                    original.assert_called_once_with(expected, socket.NI_NUMERICSERV)

    @unittest.skipUnless(hasattr(socket.socket, "sendmsg"), "sendmsg is unavailable")
    def test_sendmsg_blocks_remote_and_preserves_local_arguments(self):
        with tempfile.TemporaryDirectory() as raw, contextlib.ExitStack() as stack:
            original = stack.enter_context(patch.object(socket.socket, "sendmsg", return_value=5))
            stack.enter_context(patch.object(safety.BrowserNetworkGuard, "_install_playwright"))
            guard = safety.BrowserNetworkGuard(Path(raw))
            guard.install()
            stack.callback(guard.close)
            buffers = [b"owned"]
            ancillary = [(socket.SOL_SOCKET, 0, b"synthetic")]
            for family, address in (
                (socket.AF_INET, ("example.invalid", 53)),
                (socket.AF_INET, ("203.0.113.7", 53)),
                (socket.AF_INET6, ("2001:db8::7", 53, 0, 0)),
                (socket.AF_INET6, ("::ffff:203.0.113.7", 53, 0, 0)),
            ):
                with self.subTest(remote=address):
                    sock = SimpleNamespace(family=family)
                    self.assert_blocked_before_transport(
                        original,
                        lambda: socket.socket.sendmsg(sock, buffers, ancillary, 0, address),
                    )
            for family, args, expected in (
                (socket.AF_INET, ([], 0, ("127.0.0.1", 1234)), ([], 0, ("127.0.0.1", 1234))),
                (socket.AF_INET, ([], 0, ("aide.localhost", 1234)), ([], 0, ("127.0.0.1", 1234))),
                (
                    socket.AF_INET6,
                    ([], 0, ("aide.localhost", 1234, 2, 3)),
                    ([], 0, ("::1", 1234, 2, 3)),
                ),
                (
                    socket.AF_UNIX,
                    (ancillary, 0, "/tmp/owned.sock"),
                    (ancillary, 0, "/tmp/owned.sock"),
                ),
                (socket.AF_UNIX, (ancillary, 0), (ancillary, 0)),
                (socket.AF_UNIX, (), ()),
            ):
                with self.subTest(family=family, local=args):
                    sock = SimpleNamespace(family=family)
                    original.reset_mock()
                    self.assertEqual(socket.socket.sendmsg(sock, buffers, *args), 5)
                    original.assert_called_once_with(sock, buffers, *expected)

    def test_url_policy_rejects_remote_hosts_and_scheme_relative_escape(self):
        for url in (
            "http://127.0.0.1:1234/",
            "https://aide.localhost/",
            "http://[::1]/",
            "about:blank",
            "data:text/plain,owned",
        ):
            with self.subTest(url=url):
                self.assertTrue(safety.loopback_url(url))
        for url in (
            "https://example.invalid/",
            "//example.invalid/path",
            "http://localhost.evil.invalid/",
            "http://127.0.0.1@example.invalid/",
        ):
            with self.subTest(url=url):
                self.assertFalse(safety.loopback_url(url))

    def test_python_transport_blocks_before_dns_connect_or_datagram(self):
        with tempfile.TemporaryDirectory() as raw, contextlib.ExitStack() as stack:
            dns = stack.enter_context(patch.object(socket, "getaddrinfo", return_value=[]))
            connect = stack.enter_context(patch.object(socket.socket, "connect", return_value=None))
            datagram = stack.enter_context(patch.object(socket.socket, "sendto", return_value=1))
            stack.enter_context(patch.object(safety.BrowserNetworkGuard, "_install_playwright"))
            guard = safety.BrowserNetworkGuard(Path(raw))
            guard.install()
            stack.callback(guard.close)
            with socket.socket() as sock:
                for operation in (
                    lambda: socket.getaddrinfo("example.invalid", 443),
                    lambda: sock.connect(("203.0.113.7", 443)),
                    lambda: sock.sendto(b"owned", ("203.0.113.7", 53)),
                ):
                    with self.assertRaisesRegex(OSError, "loopback"):
                        operation()
                dns.assert_not_called()
                connect.assert_not_called()
                datagram.assert_not_called()
                socket.getaddrinfo("aide.localhost", 1234)
                self.assertEqual(dns.call_args.args[0], "127.0.0.1")
                sock.connect(("127.0.0.1", 1234))
                connect.assert_called_once()
            records = [
                json.loads(line)
                for line in (Path(raw) / "outbound-blocks.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(records), 3)

    def test_unowned_data_cannot_install_startup_hook(self):
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaisesRegex(RuntimeError, "owned"):
                safety.prepare_network_isolation(Path(raw), "missing-proof")
            self.assertFalse((Path(raw) / ".browser-network").exists())

    def test_playwright_api_and_route_fetch_are_guarded_before_transport(self):
        from playwright._impl._fetch import APIRequestContext
        from playwright._impl._network import Route

        calls = []

        async def fetch(
            instance, request=None, url=None, method=None, headers=None, data=None, **kwargs
        ):
            calls.append(url or request.url)
            return "synthetic response"

        async def run():
            context = SimpleNamespace(_alles_guard_base_url="http://127.0.0.1:1234/")
            for url in ("https://example.invalid/", "//example.invalid/"):
                with self.assertRaises(OSError):
                    await APIRequestContext._inner_fetch(context, None, url)
            request = SimpleNamespace(url="https://example.invalid/", method="GET", headers={})
            with self.assertRaises(OSError):
                await APIRequestContext._inner_fetch(context, request, None)
            self.assertEqual(calls, [])
            self.assertEqual(
                await APIRequestContext._inner_fetch(context, None, "/health"), "synthetic response"
            )
            self.assertEqual(calls, ["/health"])

            async def wrap(callback):
                return await callback()

            context._inner_fetch = lambda *args, **kwargs: APIRequestContext._inner_fetch(
                context, *args, **kwargs
            )
            route = SimpleNamespace(
                request=request,
                _context=SimpleNamespace(request=context),
                _connection=SimpleNamespace(wrap_api_call=wrap),
            )
            with self.assertRaises(OSError):
                await Route.fetch(route)
            self.assertEqual(calls, ["/health"])

        with (
            tempfile.TemporaryDirectory() as raw,
            patch.object(APIRequestContext, "_inner_fetch", fetch),
        ):
            original_route_fetch = Route.fetch
            guard = safety.BrowserNetworkGuard(Path(raw))
            guard.install()
            try:
                asyncio.run(run())
                # Route.fetch uses the same guarded implementation rather than a public API wrapper.
                self.assertIs(Route.fetch, original_route_fetch)
            finally:
                guard.close()

    def test_late_route_continue_cannot_bypass_boundary_but_fulfill_is_unchanged(self):
        from playwright._impl._network import Route

        continued = []

        async def proceed(instance, url=None, **kwargs):
            continued.append(url or instance.request.url)

        async def run():
            route = SimpleNamespace(
                request=SimpleNamespace(url="http://127.0.0.1:1234/"), abort=AsyncMock()
            )
            await Route.continue_(route, url="https://example.invalid/")
            route.abort.assert_awaited_once_with("blockedbyclient")
            self.assertEqual(continued, [])
            await Route.continue_(route)
            self.assertEqual(continued, [route.request.url])

        with tempfile.TemporaryDirectory() as raw, patch.object(Route, "continue_", proceed):
            fulfill = Route.fulfill
            guard = safety.BrowserNetworkGuard(Path(raw))
            guard.install()
            try:
                asyncio.run(run())
                self.assertIs(Route.fulfill, fulfill)
            finally:
                guard.close()

    def test_every_playwright_engine_uses_rejecting_proxy_without_chromium_flags_on_webkit(self):
        from playwright._impl._browser_type import BrowserType

        launches = []

        async def launch(instance, args=None, proxy=None, **kwargs):
            launches.append((instance.name, args, proxy))

        proxy = {"server": "http://127.0.0.1:12345", "bypass": "localhost"}

        async def run():
            for engine in ("chromium", "webkit", "firefox"):
                await BrowserType.launch(
                    SimpleNamespace(name=engine),
                    args=["--owned"],
                    proxy={"server": "http://example.invalid"},
                )

        with tempfile.TemporaryDirectory() as raw, patch.object(BrowserType, "launch", launch):
            guard = safety.BrowserNetworkGuard(Path(raw))
            with patch.object(guard, "_proxy_settings", return_value=proxy):
                guard.install()
                try:
                    asyncio.run(run())
                finally:
                    guard.close()
        for engine, args, actual_proxy in launches:
            self.assertEqual(actual_proxy, proxy)
            self.assertIn("--owned", args)
            self.assertEqual(
                any("host-resolver-rules" in arg for arg in args), engine == "chromium"
            )

    def test_new_page_persistent_and_api_contexts_use_proxy_without_impl_callbacks(self):
        from playwright._impl._browser import Browser
        from playwright._impl._browser_type import BrowserType
        from playwright._impl._fetch import APIRequest

        contexts = []
        proxy = {"server": "http://127.0.0.1:12345", "bypass": "localhost"}

        async def create(instance, proxy=None, baseURL=None, **kwargs):
            page = SimpleNamespace()
            context = SimpleNamespace(
                request=SimpleNamespace(), route=AsyncMock(), new_page=AsyncMock(return_value=page)
            )
            contexts.append((context, proxy))
            return context

        async def persistent(instance, userDataDir, proxy=None, baseURL=None, args=None, **kwargs):
            return await create(instance, proxy=proxy, baseURL=baseURL)

        async def create_api(instance, proxy=None, baseURL=None, **kwargs):
            context = SimpleNamespace()
            contexts.append((context, proxy))
            return context

        async def wrap(callback, **kwargs):
            return await callback()

        async def run():
            browser = SimpleNamespace(_connection=SimpleNamespace(wrap_api_call=wrap))
            browser.new_context = lambda **kwargs: Browser.new_context(browser, **kwargs)
            page = await Browser.new_page(browser, baseURL="http://127.0.0.1:1234")
            self.assertIs(page._owned_context, contexts[0][0])
            await BrowserType.launch_persistent_context(
                SimpleNamespace(name="webkit"), "/owned", baseURL="http://127.0.0.1:1234"
            )
            await APIRequest.new_context(SimpleNamespace(), baseURL="http://127.0.0.1:1234")

        with tempfile.TemporaryDirectory() as raw, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(Browser, "new_context", create))
            stack.enter_context(patch.object(BrowserType, "launch_persistent_context", persistent))
            stack.enter_context(patch.object(APIRequest, "new_context", create_api))
            guard = safety.BrowserNetworkGuard(Path(raw))
            stack.enter_context(patch.object(guard, "_proxy_settings", return_value=proxy))
            guard.install()
            stack.callback(guard.close)
            asyncio.run(run())
        self.assertEqual(len(contexts), 3)
        for index, (context, actual_proxy) in enumerate(contexts):
            self.assertEqual(actual_proxy, proxy)
            target = context.request if index < 2 else context
            self.assertEqual(target._alles_guard_base_url, "http://127.0.0.1:1234")
            if index < 2:
                # Impl RouteHandler dispatch differs between sync and async
                # Playwright. The mandatory proxy needs no such callback.
                context.route.assert_not_called()

    def test_proxy_rejects_connect_without_forwarding_or_logging_paths(self):
        with tempfile.TemporaryDirectory() as raw, contextlib.ExitStack() as stack:
            server = Mock(server_port=12345)
            factory = stack.enter_context(
                patch.object(safety, "ThreadingHTTPServer", return_value=server)
            )
            stack.enter_context(patch.object(safety.threading, "Thread", return_value=Mock()))
            guard = safety.BrowserNetworkGuard(Path(raw))
            stack.callback(guard.close)
            self.assertEqual(guard._proxy_settings()["server"], "http://127.0.0.1:12345")
            self.assertEqual(guard._proxy_settings()["server"], "http://127.0.0.1:12345")
            factory.assert_called_once()
            handler_type = factory.call_args.args[1]
            handler = object.__new__(handler_type)
            handler.path = "https://example.invalid/private-query?secret=synthetic"
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.do_CONNECT()
            handler.send_response.assert_called_once_with(403, "fixture outbound access blocked")
            self.assertTrue(handler.close_connection)
            evidence = (Path(raw) / "outbound-blocks.jsonl").read_text()
            self.assertEqual(json.loads(evidence)["host"], "example.invalid")
            self.assertNotIn("private-query", evidence)


if __name__ == "__main__":
    unittest.main()
