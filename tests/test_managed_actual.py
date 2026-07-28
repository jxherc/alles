import hashlib
import json
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from services import actual_bridge, managed_actual


class ManagedActualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_data_dir = managed_actual.data_dir
        managed_actual.data_dir = lambda: Path(self.tmp.name)
        self.cold_absence = mock.patch.object(
            managed_actual, "_cold_operation_absent", return_value=True
        )
        self.cold_absence.start()
        root = managed_actual.root_dir()
        self._make_app(root / "app", "bridge")
        manifest = {
            **managed_actual._manifest(),
            "bundle_sha256": managed_actual._installed_bundle_digest(),
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def tearDown(self):
        self.cold_absence.stop()
        managed_actual.data_dir = self.original_data_dir
        self.tmp.cleanup()

    def test_interprocess_lock_can_be_constructed_without_register_at_fork(self):
        with mock.patch.object(managed_actual.os, "register_at_fork", None):
            lock = managed_actual._InterprocessRLock()

        self.assertIsInstance(lock, managed_actual._InterprocessRLock)

    def test_status_is_loopback_owned_and_version_pinned(self):
        value = managed_actual.status(
            probe=lambda: False,
            process_alive=lambda _pid: False,
            node_status=lambda: {"available": True, "version": "22.17.0"},
        )
        self.assertTrue(value["installed"])
        self.assertEqual(value["bind"], "127.0.0.1:5007")
        self.assertEqual(value["version"], "26.7.0")
        self.assertFalse(value["running"])

    def test_listener_ownership_requires_the_managed_pid_on_the_loopback_port(self):
        owned = mock.Mock(returncode=0, stdout="p123\nn127.0.0.1:5007\n")
        spoofed = mock.Mock(returncode=0, stdout="p999\nn127.0.0.1:5007\n")
        self.assertTrue(managed_actual._listener_owned_by(123, runner=lambda *_a, **_k: owned))
        self.assertFalse(managed_actual._listener_owned_by(123, runner=lambda *_a, **_k: spoofed))

    def test_cold_absence_requires_clear_listener_and_server_process_scans(self):
        no_listener = mock.Mock(returncode=1, stdout="", stderr="")
        listener = mock.Mock(returncode=0, stdout="p321\n", stderr="")
        scan_failed = mock.Mock(returncode=2, stdout="", stderr="permission denied")
        self.assertEqual(managed_actual._listener_pids(runner=lambda *_a, **_k: no_listener), set())
        self.assertEqual(managed_actual._listener_pids(runner=lambda *_a, **_k: listener), {321})
        self.assertIsNone(managed_actual._listener_pids(runner=lambda *_a, **_k: scan_failed))

        script = (
            managed_actual.app_dir()
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        ).resolve()
        clear_processes = mock.Mock(returncode=0, stdout="12 node /tmp/other.js\n")
        managed_process = mock.Mock(returncode=0, stdout=f"654 node {script}\n")
        self.assertEqual(
            managed_actual._managed_server_pids(runner=lambda *_a, **_k: clear_processes),
            set(),
        )
        self.assertEqual(
            managed_actual._managed_server_pids(runner=lambda *_a, **_k: managed_process),
            {654},
        )

    def test_linux_listener_ownership_uses_proc_without_lsof(self):
        proc = Path(self.tmp.name) / "proc"
        (proc / "net").mkdir(parents=True)
        header = "sl local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n"
        listener = (
            "0: 0100007F:138F 00000000:0000 0A 00000000:00000000 00:00000000 "
            "00000000 1000 0 4242 1\n"
        )
        (proc / "net" / "tcp").write_text(header + listener, "ascii")
        (proc / "net" / "tcp6").write_text(header, "ascii")
        (proc / "321" / "fd").mkdir(parents=True)
        (proc / "321" / "fd" / "3").symlink_to("socket:[4242]")

        inodes = managed_actual._linux_listener_inodes(5007, proc_root=proc)

        self.assertEqual(inodes, {"4242"})
        self.assertEqual(
            managed_actual._linux_listener_pids(inodes, proc_root=proc),
            {321},
        )

        (proc / "654" / "fd").mkdir(parents=True)
        (proc / "654" / "fd" / "4").symlink_to("socket:[4242]")
        self.assertEqual(
            managed_actual._linux_listener_pids(inodes, proc_root=proc),
            {321, 654},
        )

    def test_linux_listener_rejects_any_additional_owner(self):
        with (
            mock.patch.object(managed_actual.sys, "platform", "linux"),
            mock.patch.object(managed_actual, "_linux_listener_inodes", return_value={"4242"}),
            mock.patch.object(managed_actual, "_linux_listener_pids", return_value={321, 654}),
        ):
            self.assertFalse(managed_actual._listener_owned_by(321))

    def test_node_support_starts_at_the_locked_22_12_floor(self):
        def result(version):
            return mock.Mock(returncode=0, stdout=f"v{version}\n")

        self.assertFalse(
            managed_actual._node_status(runner=lambda *_a, **_k: result("22.11.0"))["available"]
        )
        self.assertTrue(
            managed_actual._node_status(runner=lambda *_a, **_k: result("22.12.0"))["available"]
        )
        self.assertTrue(
            managed_actual._node_status(runner=lambda *_a, **_k: result("23.0.0"))["available"]
        )

    def test_install_candidate_enforces_the_full_node_floor(self):
        destination = Path(self.tmp.name) / "candidate"
        versions = {
            "api": managed_actual.VERSION,
            "cli": managed_actual.VERSION,
            "sync_server": managed_actual.VERSION,
            "node": "22.11.0",
        }
        with (
            mock.patch.object(managed_actual, "_copy_bundle"),
            self.assertRaisesRegex(managed_actual.ManagedActualError, "22.12"),
        ):
            managed_actual._install_candidate(
                destination,
                runner=lambda *_a, **_k: mock.Mock(returncode=0),
                bridge_call=lambda *_a, **_k: versions,
            )

    def test_install_candidate_removes_npm_executable_links_after_scripts_run(self):
        destination = Path(self.tmp.name) / "candidate"

        def install(_command, **_kwargs):
            executable_links = destination / "node_modules" / ".bin"
            executable_links.mkdir(parents=True)
            (destination / "node_modules" / "tool.js").write_text("tool", encoding="utf-8")
            (executable_links / "tool").symlink_to("../tool.js")
            return mock.Mock(returncode=0)

        runner = mock.Mock(side_effect=install)
        versions = {
            "api": managed_actual.VERSION,
            "cli": managed_actual.VERSION,
            "sync_server": managed_actual.VERSION,
            "node": "22.12.0",
        }
        with mock.patch.object(managed_actual, "_copy_bundle"):
            managed_actual._install_candidate(
                destination,
                runner=runner,
                bridge_call=lambda *_a, **_k: versions,
            )
        self.assertNotIn("--no-bin-links", runner.call_args.args[0])
        self.assertFalse((destination / "node_modules" / ".bin").exists())
        self.assertEqual(list(path for path in destination.rglob("*") if path.is_symlink()), [])

    def test_install_candidate_rejects_symlinks_outside_npm_bin_directories(self):
        destination = Path(self.tmp.name) / "candidate"

        def install(_command, **_kwargs):
            modules = destination / "node_modules"
            modules.mkdir(parents=True)
            (modules / "unsafe").symlink_to(Path(self.tmp.name), target_is_directory=True)
            return mock.Mock(returncode=0)

        with (
            mock.patch.object(
                managed_actual, "_copy_bundle", side_effect=lambda path: path.mkdir()
            ),
            self.assertRaisesRegex(managed_actual.ManagedActualError, "unsafe symlink"),
        ):
            managed_actual._install_candidate(
                destination,
                runner=install,
                bridge_call=mock.Mock(),
            )

    def test_install_rejects_symlinked_managed_data_directory(self):
        outside = Path(self.tmp.name) / "outside-server-data"
        outside.mkdir()
        managed_actual.server_data_dir().symlink_to(outside, target_is_directory=True)
        start = mock.Mock()
        with (
            mock.patch.object(
                managed_actual,
                "_node_status",
                return_value={"available": True, "version": "22.17.0"},
            ),
            self.assertRaisesRegex(managed_actual.ManagedActualError, "server-data"),
        ):
            managed_actual.install(start_fn=start)
        start.assert_not_called()
        self.assertEqual(list(outside.iterdir()), [])

    def test_start_and_bridge_reject_symlinked_managed_data_directory(self):
        outside = Path(self.tmp.name) / "outside-client-data"
        outside.mkdir()
        managed_actual.client_data_dir().symlink_to(outside, target_is_directory=True)
        popen = mock.Mock()
        with self.assertRaisesRegex(managed_actual.ManagedActualError, "client-data"):
            managed_actual.start(popen=popen, probe=lambda: False)
        popen.assert_not_called()
        bridge = mock.Mock()
        with self.assertRaisesRegex(managed_actual.ManagedActualError, "client-data"):
            managed_actual.bridge_request({}, bridge_call=bridge)
        bridge.assert_not_called()
        self.assertEqual(list(outside.iterdir()), [])

    def test_bridge_request_holds_the_lifecycle_lock_until_the_bridge_finishes(self):
        entered = threading.Event()
        release = threading.Event()
        lifecycle_acquired = threading.Event()
        results = []
        errors = []

        def bridge(*_args, **_kwargs):
            entered.set()
            release.wait(2)
            return {"ok": True}

        def request():
            try:
                results.append(managed_actual.bridge_request({}, bridge_call=bridge))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        def lifecycle_operation():
            with managed_actual._SERVICE_LOCK:
                lifecycle_acquired.set()

        with (
            mock.patch.object(managed_actual, "_trusted_install", return_value=True),
            mock.patch.object(managed_actual, "status", return_value={"healthy": True}),
            mock.patch.object(managed_actual, "_managed_password", return_value="x" * 32),
        ):
            worker = threading.Thread(target=request, daemon=True)
            worker.start()
            self.assertTrue(entered.wait(1))
            contender = threading.Thread(target=lifecycle_operation, daemon=True)
            contender.start()
            try:
                self.assertFalse(lifecycle_acquired.wait(0.05))
            finally:
                release.set()
            worker.join(2)
            contender.join(2)

        self.assertFalse(worker.is_alive())
        self.assertFalse(contender.is_alive())
        self.assertTrue(lifecycle_acquired.is_set())
        self.assertEqual(results, [{"ok": True}])
        self.assertEqual(errors, [])

    def test_bridge_request_reuses_one_install_integrity_verification(self):
        trusted = mock.Mock(return_value=True)
        service_status = mock.Mock(return_value={"healthy": True})
        bridge = mock.Mock(return_value={"ok": True})
        with (
            mock.patch.object(managed_actual, "_trusted_install", trusted),
            mock.patch.object(managed_actual, "status", service_status),
            mock.patch.object(managed_actual, "_managed_password", return_value="x" * 32),
        ):
            result = managed_actual.bridge_request({}, bridge_call=bridge)

        self.assertEqual(result, {"ok": True})
        trusted.assert_called_once_with()
        service_status.assert_called_once_with(trusted_install=True)

    def test_bridge_request_preserves_internal_cleanup_identity_on_a_safe_error(self):
        bridge_error = actual_bridge.ActualBridgeError(
            "Actual bridge operation failed with private details withheld",
            code="actual_stage_cleanup_required",
            details={"staged_budget": {"budget_id": "budget-private", "sync_id": "sync-private"}},
        )
        with (
            mock.patch.object(managed_actual, "_trusted_install", return_value=True),
            mock.patch.object(managed_actual, "status", return_value={"healthy": True}),
            mock.patch.object(managed_actual, "_managed_password", return_value="x" * 32),
            self.assertRaises(managed_actual.ManagedActualError) as raised,
        ):
            managed_actual.bridge_request(
                {"command": "migrate"},
                bridge_call=mock.Mock(side_effect=bridge_error),
            )

        self.assertEqual(raised.exception.details, bridge_error.details)
        self.assertNotIn("budget-private", str(raised.exception))

    def test_lifecycle_lock_blocks_another_process_for_the_same_data_root(self):
        lock_path = managed_actual.root_dir() / ".operation.lock"
        script = (
            "import fcntl, os, sys; "
            "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600); "
            "print('ready', flush=True); "
            "fcntl.flock(fd, fcntl.LOCK_EX); "
            "print('acquired', flush=True)"
        )
        with managed_actual._SERVICE_LOCK:
            child = subprocess.Popen(
                [sys.executable, "-c", script, str(lock_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(lambda: child.poll() is None and child.kill())
            readable, _, _ = select.select([child.stdout], [], [], 5)
            self.assertEqual(readable, [child.stdout])
            self.assertEqual(child.stdout.readline().strip(), "ready")
            readable, _, _ = select.select([child.stdout], [], [], 0.1)
            self.assertEqual(readable, [])
        stdout, stderr = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, stderr)
        self.assertEqual(stdout.strip(), "acquired")

    def test_missing_fcntl_keeps_the_module_usable_and_fails_the_lifecycle_closed(self):
        lock = managed_actual._InterprocessRLock()
        with mock.patch.object(managed_actual, "fcntl", None):
            for _attempt in range(2):
                with self.assertRaisesRegex(
                    managed_actual.ManagedActualError,
                    "unavailable on this platform",
                ):
                    lock.acquire()

    def test_pid_ownership_fails_closed_when_the_command_is_unreadable(self):
        root = Path(self.tmp.name) / "managed"
        script = (
            root
            / "app"
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        )
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("server", encoding="utf-8")
        (root / "server.pid.json").write_text(
            '{"pid":123,"server_script":"' + str(script.resolve()) + '"}',
            encoding="utf-8",
        )
        with (
            mock.patch.object(managed_actual, "root_dir", return_value=root),
            mock.patch.object(managed_actual, "app_dir", return_value=root / "app"),
        ):
            self.assertIsNone(
                managed_actual._owned_pid(
                    process_alive=lambda _pid: True,
                    process_command=lambda _pid: "",
                )
            )

    def test_process_ownership_accepts_canonical_path_alias(self):
        real = Path(self.tmp.name) / "real"
        alias = Path(self.tmp.name) / "alias"
        real.mkdir()
        script = real / "actual-server.js"
        script.write_text("server", encoding="utf-8")
        alias.symlink_to(real, target_is_directory=True)
        self.assertTrue(
            managed_actual._command_owns_script(
                f"node {alias / 'actual-server.js'}",
                str(script.resolve()),
            )
        )

    def test_process_ownership_rejects_commands_that_only_mention_the_script(self):
        script = str(
            (
                managed_actual.app_dir()
                / "node_modules"
                / "@actual-app"
                / "sync-server"
                / "build"
                / "bin"
                / "actual-server.js"
            ).resolve()
        )
        for command in (
            ("python3", script),
            ("node", "/tmp/wrapper.js", script),
            f"vim {script}",
            f"node /tmp/wrapper.js {script}",
        ):
            with self.subTest(command=command):
                self.assertFalse(managed_actual._command_owns_script(command, script))

    def test_pid_ownership_preserves_a_server_script_argument_with_spaces(self):
        root = Path(self.tmp.name) / "managed actual"
        script = (
            root
            / "app"
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        )
        script.parent.mkdir(parents=True)
        script.write_text("server", encoding="utf-8")
        (root / "server.pid.json").write_text(
            json.dumps({"pid": 123, "server_script": str(script.resolve())}),
            encoding="utf-8",
        )
        with (
            mock.patch.object(managed_actual, "root_dir", return_value=root),
            mock.patch.object(managed_actual, "app_dir", return_value=root / "app"),
        ):
            self.assertEqual(
                managed_actual._owned_pid(
                    process_alive=lambda _pid: True,
                    process_command=lambda _pid: ("node", str(script)),
                ),
                123,
            )
            self.assertTrue(
                managed_actual._command_owns_script(
                    f"node {script}",
                    str(script.resolve()),
                )
            )

    def test_bootstrap_generates_private_managed_password_once(self):
        calls = []

        class Response:
            def __init__(self, value):
                self.value = value

            def raise_for_status(self):
                return None

            def json(self):
                return self.value

        class Client:
            @staticmethod
            def get(*_args, **_kwargs):
                return Response({"status": "ok", "data": {"bootstrapped": False}})

            @staticmethod
            def post(_url, **kwargs):
                calls.append(kwargs["json"])
                return Response({"status": "ok"})

        managed_actual._ensure_bootstrap(client=Client, ownership_check=lambda: True)
        self.assertEqual(len(calls), 1)
        self.assertGreaterEqual(len(calls[0]["password"]), 32)
        self.assertEqual(managed_actual._managed_password(), calls[0]["password"])
        self.assertEqual(managed_actual.auth_file().stat().st_mode & 0o777, 0o600)

    def test_bootstrapped_service_without_managed_password_fails_closed(self):
        class Response:
            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {"status": "ok", "data": {"bootstrapped": True}}

        class Client:
            get = staticmethod(lambda *_args, **_kwargs: Response())

        with self.assertRaisesRegex(
            managed_actual.ManagedActualError, "authentication file is missing"
        ):
            managed_actual._ensure_bootstrap(client=Client, ownership_check=lambda: True)
        self.assertFalse(managed_actual.auth_file().exists())

    def test_bootstrap_never_sends_a_password_without_listener_ownership(self):
        client = mock.Mock()
        with self.assertRaisesRegex(
            managed_actual.ManagedActualError, "ownership could not be proven"
        ):
            managed_actual._ensure_bootstrap(client=client, ownership_check=lambda: False)
        client.get.assert_not_called()
        client.post.assert_not_called()
        self.assertFalse(managed_actual.auth_file().exists())

    def test_install_finalization_failure_removes_the_published_app_and_manifest(self):
        root = managed_actual.root_dir()
        managed_actual._remove_path(managed_actual.app_dir())
        (root / "manifest.json").unlink()

        def install_candidate(destination, **_kwargs):
            self._make_app(destination, "candidate")

        with (
            mock.patch.object(
                managed_actual,
                "_node_status",
                return_value={"available": True, "version": "22.17.0"},
            ),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(
                managed_actual, "_atomic_json", side_effect=OSError("manifest failed")
            ),
            self.assertRaisesRegex(OSError, "manifest failed"),
        ):
            managed_actual.install(start_fn=mock.Mock())
        self.assertFalse(managed_actual.app_dir().exists())
        self.assertFalse((root / "manifest.json").exists())

    def test_install_repairs_an_owned_app_with_a_missing_server_entrypoint(self):
        root = managed_actual.root_dir()
        server_script = (
            managed_actual.app_dir()
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        )
        server_script.unlink()
        self.assertFalse(managed_actual.status()["installed"])

        def install_candidate(destination, **_kwargs):
            self._make_reviewed_app(destination)

        start = mock.Mock()
        with (
            mock.patch.object(
                managed_actual,
                "_node_status",
                return_value={"available": True, "version": "22.17.0"},
            ),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "_ensure_bootstrap"),
        ):
            result = managed_actual.install(start_fn=start)
        self.assertTrue(result["installed"])
        self.assertTrue(server_script.is_file())
        self.assertEqual(
            (managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"),
            managed_actual.actual_bridge.bridge_script().read_text("utf-8"),
        )
        start.assert_called_once_with()
        self.assertFalse(any(root.glob(".repair-*-previous-*")))

    def test_install_repairs_a_managed_app_with_a_tampered_bundle(self):
        bridge = managed_actual.app_dir() / "bridge.mjs"
        bridge.write_text("tampered", encoding="utf-8")
        self.assertFalse(managed_actual.status()["installed"])

        def install_candidate(destination, **_kwargs):
            self._make_reviewed_app(destination)

        with (
            mock.patch.object(
                managed_actual,
                "_node_status",
                return_value={"available": True, "version": "22.17.0"},
            ),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "_ensure_bootstrap"),
        ):
            result = managed_actual.install(start_fn=mock.Mock())
        self.assertTrue(result["installed"])
        self.assertEqual(managed_actual._installed_bundle_digest(), managed_actual._bundle_digest())

    def test_bridge_clears_only_categories_owned_by_the_managed_group(self):
        source = actual_bridge.bridge_script().read_text("utf-8")
        clear_block = source.split("if (request.action === 'clear_budget')", 1)[1].split(
            "throw new Error(`unsupported Actual write action", 1
        )[0]
        self.assertIn("managedCategoryGroupName(request)", clear_block)
        self.assertIn("item.group_id === groupMatches[0].id", clear_block)
        self.assertIn("Actual budget category is not owned by Alles", clear_block)
        self.assertLess(
            clear_block.index("categoryMatches.length"), clear_block.index("setBudgetAmount")
        )

    def test_install_repair_refuses_to_swap_over_a_markerless_managed_server(self):
        bridge = managed_actual.app_dir() / "bridge.mjs"
        bridge.write_text("tampered markerless app", encoding="utf-8")

        def install_candidate(destination, **_kwargs):
            self._make_reviewed_app(destination)

        managed_actual._cold_operation_absent.return_value = False
        start = mock.Mock()
        with (
            mock.patch.object(
                managed_actual,
                "_node_status",
                return_value={"available": True, "version": "22.17.0"},
            ),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            self.assertRaisesRegex(managed_actual.ManagedActualColdState, "process absence"),
        ):
            managed_actual.install(start_fn=start)

        start.assert_not_called()
        self.assertEqual(bridge.read_text("utf-8"), "tampered markerless app")
        self.assertFalse(any(managed_actual.root_dir().glob(".repair-app-previous-*")))

    def test_install_integrity_rejects_and_repairs_tampered_dependency_contents(self):
        dependency = managed_actual.app_dir() / "node_modules" / "@actual-app" / "api" / "index.js"
        dependency.write_text("tampered dependency", encoding="utf-8")
        self.assertFalse(managed_actual.status()["installed"])

        def install_candidate(destination, **_kwargs):
            self._make_reviewed_app(destination)

        with (
            mock.patch.object(
                managed_actual,
                "_node_status",
                return_value={"available": True, "version": "22.17.0"},
            ),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "_ensure_bootstrap"),
        ):
            result = managed_actual.install(start_fn=mock.Mock())
        self.assertTrue(result["installed"])
        self.assertNotEqual(dependency.read_text("utf-8"), "tampered dependency")

    def test_running_repair_stops_before_swap_and_restores_the_old_running_app_on_failure(self):
        bridge = managed_actual.app_dir() / "bridge.mjs"
        bridge.write_text("tampered running app", encoding="utf-8")
        events = []

        def install_candidate(destination, **_kwargs):
            self._make_reviewed_app(destination)

        def stop():
            events.append(("stop", bridge.read_text("utf-8")))

        def start():
            events.append(("start", bridge.read_text("utf-8")))

        reviewed_bridge = managed_actual.actual_bridge.bridge_script().read_text("utf-8")
        with (
            mock.patch.object(
                managed_actual,
                "_node_status",
                return_value={"available": True, "version": "22.17.0"},
            ),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "_owned_pid", return_value=45678),
            mock.patch.object(
                managed_actual,
                "_ensure_bootstrap",
                side_effect=managed_actual.ManagedActualError("bootstrap failed"),
            ),
            self.assertRaisesRegex(
                managed_actual.ManagedActualRollback,
                "previous managed app was restored",
            ),
        ):
            managed_actual.install(start_fn=start, stop_fn=stop)

        self.assertEqual(
            events,
            [
                ("stop", "tampered running app"),
                ("start", reviewed_bridge),
                ("stop", reviewed_bridge),
                ("start", "tampered running app"),
            ],
        )
        self.assertEqual(bridge.read_text("utf-8"), "tampered running app")

    def test_start_marker_failure_terminates_and_forgets_the_child(self):
        script = (
            managed_actual.app_dir()
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        )
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("server", encoding="utf-8")
        process = mock.Mock(pid=45678)
        process.poll.return_value = None
        process.wait.return_value = 0
        with (
            mock.patch.object(managed_actual, "_atomic_json", side_effect=OSError("marker failed")),
            self.assertRaisesRegex(
                managed_actual.ManagedActualError, "marker could not be persisted"
            ),
        ):
            managed_actual.start(
                popen=lambda *_args, **_kwargs: process,
                probe=lambda: False,
                listener_owner=lambda _pid: False,
                sleep=lambda _seconds: None,
            )
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)
        self.assertNotIn(process.pid, managed_actual._CHILDREN)
        self.assertFalse((managed_actual.root_dir() / "server.pid.json").exists())

    def test_stop_reaps_an_owned_child_as_soon_as_it_exits(self):
        child = mock.Mock()
        child.poll.return_value = 0
        child.wait.return_value = 0
        managed_actual._CHILDREN[45679] = child
        sleeper = mock.Mock()
        try:
            with (
                mock.patch.object(managed_actual, "_owned_pid", return_value=45679),
                mock.patch.object(managed_actual.os, "kill") as kill,
            ):
                result = managed_actual.stop(
                    process_alive=lambda _pid: True,
                    sleep=sleeper,
                )
        finally:
            managed_actual._CHILDREN.pop(45679, None)
        self.assertFalse(result["running"])
        kill.assert_called_once_with(45679, managed_actual.signal.SIGTERM)
        child.poll.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=1)
        sleeper.assert_not_called()

    def test_stop_treats_a_sigterm_process_lookup_race_as_success(self):
        marker = managed_actual.root_dir() / "server.pid.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{}", encoding="utf-8")
        with (
            mock.patch.object(managed_actual, "_owned_pid", return_value=45680),
            mock.patch.object(
                managed_actual.os,
                "kill",
                side_effect=ProcessLookupError("already exited"),
            ),
        ):
            result = managed_actual.stop()
        self.assertFalse(result["running"])
        self.assertFalse(marker.exists())

    def test_stop_treats_a_sigkill_process_lookup_race_as_success(self):
        marker = managed_actual.root_dir() / "server.pid.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{}", encoding="utf-8")
        kills = []

        def kill(_pid, sig):
            kills.append(sig)
            if sig == managed_actual.signal.SIGKILL:
                raise ProcessLookupError("exited before kill")

        with (
            mock.patch.object(managed_actual, "_owned_pid", return_value=45681),
            mock.patch.object(managed_actual.os, "kill", side_effect=kill),
        ):
            result = managed_actual.stop(
                process_alive=lambda _pid: True,
                sleep=lambda _seconds: None,
            )
        self.assertFalse(result["running"])
        self.assertEqual(kills, [managed_actual.signal.SIGTERM, managed_actual.signal.SIGKILL])
        self.assertFalse(marker.exists())

    def test_stop_waits_for_an_untracked_process_after_sigkill(self):
        marker = managed_actual.root_dir() / "server.pid.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{}", encoding="utf-8")
        alive_checks = 0

        def process_alive(_pid):
            nonlocal alive_checks
            alive_checks += 1
            return alive_checks < 103

        sleeper = mock.Mock()
        with (
            mock.patch.object(managed_actual, "_owned_pid", return_value=45682),
            mock.patch.object(managed_actual.os, "kill") as kill,
        ):
            result = managed_actual.stop(process_alive=process_alive, sleep=sleeper)
        self.assertFalse(result["running"])
        self.assertEqual(kill.call_args_list[-1].args, (45682, managed_actual.signal.SIGKILL))
        self.assertGreaterEqual(alive_checks, 103)
        self.assertFalse(marker.exists())

    def test_stop_retains_ownership_when_sigkill_exit_cannot_be_confirmed(self):
        marker = managed_actual.root_dir() / "server.pid.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{}", encoding="utf-8")
        with (
            mock.patch.object(managed_actual, "_owned_pid", return_value=45683),
            mock.patch.object(managed_actual.os, "kill"),
            self.assertRaisesRegex(managed_actual.ManagedActualError, "did not exit"),
        ):
            managed_actual.stop(
                process_alive=lambda _pid: True,
                sleep=lambda _seconds: None,
            )
        self.assertTrue(marker.exists())

    def test_cold_backup_hashes_server_cache_and_migration_export(self):
        root = managed_actual.root_dir()
        for relative, payload in (
            ("server-data/server-files/account.sqlite", b"server"),
            ("client-data/budget/db.sqlite", b"client"),
            ("migration-exports/run.json", b"snapshot"),
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        folder = managed_actual.backups_dir() / backup["backup_id"]
        manifest = json.loads((folder / "manifest.json").read_text("utf-8"))
        expected = hashlib.sha256(b"server").hexdigest()
        self.assertEqual(
            manifest["files"]["server-data/server-files/account.sqlite"]["sha256"], expected
        )
        self.assertEqual(managed_actual.verify_backup(backup["backup_id"])["files"], 3)

    def test_cold_backup_and_restore_reject_an_unowned_or_unknown_writer(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        stop = mock.Mock()
        start = mock.Mock()
        with self.assertRaisesRegex(managed_actual.ManagedActualColdState, "could not be proven"):
            managed_actual.backup(
                status_fn=lambda: {"running": False},
                stop_fn=stop,
                start_fn=start,
                absence_check=lambda: False,
            )
        stop.assert_not_called()
        start.assert_not_called()

        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
            absence_check=lambda: True,
        )
        live.write_text("current value", encoding="utf-8")
        with self.assertRaisesRegex(managed_actual.ManagedActualColdState, "could not be proven"):
            managed_actual.restore(
                backup["backup_id"],
                status_fn=lambda: {"running": False},
                stop_fn=stop,
                start_fn=start,
                verify_fn=mock.Mock(),
                absence_check=lambda: False,
            )
        self.assertEqual(live.read_text("utf-8"), "current value")
        stop.assert_not_called()
        start.assert_not_called()

    def test_cold_backup_aborts_if_a_writer_appears_before_copy(self):
        live = managed_actual.server_data_dir() / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("stable value", encoding="utf-8")
        checks = iter((True, False))
        start = mock.Mock()
        with self.assertRaisesRegex(managed_actual.ManagedActualColdState, "could not be proven"):
            managed_actual.backup(
                status_fn=lambda: {"running": True},
                stop_fn=lambda: None,
                start_fn=start,
                absence_check=lambda: next(checks),
            )
        start.assert_not_called()
        self.assertEqual(live.read_text("utf-8"), "stable value")
        self.assertEqual(list(managed_actual.backups_dir().iterdir()), [])

    def test_cold_backup_restarts_a_previously_running_service_once_absence_is_proven(self):
        checks = iter((False, True))
        states = iter(({"running": True}, {"running": False}))
        start = mock.Mock()
        with self.assertRaisesRegex(managed_actual.ManagedActualColdState, "could not be proven"):
            managed_actual.backup(
                status_fn=lambda: next(states),
                stop_fn=lambda: None,
                start_fn=start,
                absence_check=lambda: next(checks),
            )
        start.assert_called_once_with()

    def test_cold_restore_aborts_if_a_writer_appears_before_swap(self):
        live = managed_actual.server_data_dir() / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("selected value", encoding="utf-8")
        selected = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
            absence_check=lambda: True,
        )
        live.write_text("current value", encoding="utf-8")
        checks = iter((True, True, True, True, True, True, False))
        start = mock.Mock()
        verify = mock.Mock()
        with self.assertRaisesRegex(managed_actual.ManagedActualColdState, "could not be proven"):
            managed_actual.restore(
                selected["backup_id"],
                status_fn=lambda: {"running": False},
                stop_fn=lambda: None,
                start_fn=start,
                verify_fn=verify,
                absence_check=lambda: next(checks),
            )
        start.assert_not_called()
        verify.assert_not_called()
        self.assertEqual(live.read_text("utf-8"), "current value")
        self.assertEqual(len(list(managed_actual.backups_dir().iterdir())), 2)
        self.assertEqual(list(managed_actual.root_dir().glob(".*.partial")), [])

    def test_cold_restore_restarts_a_previously_running_service_before_swap(self):
        live = managed_actual.server_data_dir() / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("selected value", encoding="utf-8")
        selected = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
            absence_check=lambda: True,
        )
        live.write_text("current value", encoding="utf-8")
        check_count = 0

        def cold_absent():
            nonlocal check_count
            check_count += 1
            return check_count != 7

        states = iter(({"running": True}, {"running": False}))
        stop = mock.Mock()
        start = mock.Mock()

        with self.assertRaisesRegex(managed_actual.ManagedActualColdState, "could not be proven"):
            managed_actual.restore(
                selected["backup_id"],
                status_fn=lambda: next(states),
                stop_fn=stop,
                start_fn=start,
                verify_fn=mock.Mock(),
                absence_check=cold_absent,
            )

        stop.assert_called_once_with()
        start.assert_called_once_with()
        self.assertEqual(check_count, 8)
        self.assertEqual(live.read_text("utf-8"), "current value")

    def test_backup_rejects_source_symlinks_before_stopping(self):
        root = managed_actual.root_dir()
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "private.sqlite").write_text("private", encoding="utf-8")
        (root / "server-data").symlink_to(outside, target_is_directory=True)
        events = []
        with self.assertRaisesRegex(managed_actual.ManagedActualError, "unsafe symlink"):
            managed_actual.backup(
                status_fn=lambda: {"running": True},
                stop_fn=lambda: events.append("stop"),
                start_fn=lambda: events.append("start"),
            )
        self.assertEqual(events, [])

    def test_backup_rejects_a_symlink_introduced_during_the_copy(self):
        root = managed_actual.root_dir()
        source = root / "server-data" / "account.sqlite"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("managed", encoding="utf-8")
        outside = Path(self.tmp.name) / "outside.sqlite"
        outside.write_text("private", encoding="utf-8")
        real_copytree = managed_actual.shutil.copytree
        events = []

        def copytree(source_root, destination, *args, **kwargs):
            if Path(source_root) == managed_actual.server_data_dir():
                source.unlink()
                source.symlink_to(outside)
            return real_copytree(source_root, destination, *args, **kwargs)

        with (
            mock.patch.object(managed_actual.shutil, "copytree", side_effect=copytree),
            self.assertRaisesRegex(managed_actual.ManagedActualError, "unsafe symlink"),
        ):
            managed_actual.backup(
                status_fn=lambda: {"running": True},
                stop_fn=lambda: events.append("stop"),
                start_fn=lambda: events.append("start"),
            )
        self.assertEqual(events, ["stop", "start"])
        self.assertEqual(list(managed_actual.backups_dir().iterdir()), [])

    def test_backup_rejects_unsafe_output_directory_before_stopping(self):
        root = managed_actual.root_dir()
        (root / "backups").write_text("not a directory", encoding="utf-8")
        events = []
        with self.assertRaisesRegex(managed_actual.ManagedActualError, "backups"):
            managed_actual.backup(
                status_fn=lambda: {"running": True},
                stop_fn=lambda: events.append("stop"),
                start_fn=lambda: events.append("start"),
            )
        self.assertEqual(events, [])

    def test_backup_recovers_when_stop_raises_after_the_service_exits(self):
        events = []
        states = iter(({"running": True}, {"running": False}))

        def stop_after_exit():
            events.append("stop")
            raise managed_actual.ManagedActualError("marker cleanup failed")

        with self.assertRaisesRegex(managed_actual.ManagedActualError, "marker cleanup failed"):
            managed_actual.backup(
                status_fn=lambda: next(states),
                stop_fn=stop_after_exit,
                start_fn=lambda: events.append("start"),
            )
        self.assertEqual(events, ["stop", "start"])

    def test_tampered_backup_is_rejected_before_restore(self):
        root = managed_actual.root_dir()
        path = root / "server-data" / "account.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"before")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        copied = (
            managed_actual.backups_dir() / backup["backup_id"] / "server-data" / "account.sqlite"
        )
        copied.write_bytes(b"tampered")
        with self.assertRaisesRegex(managed_actual.ManagedActualError, "hash"):
            managed_actual.verify_backup(backup["backup_id"])

    def test_restore_rejects_a_backup_mutated_while_its_snapshot_is_staged(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        live.write_text("current value", encoding="utf-8")
        selected = managed_actual.backups_dir() / backup["backup_id"]
        real_copytree = managed_actual.shutil.copytree
        status = mock.Mock(return_value={"running": False})

        def copytree(source, destination, *args, **kwargs):
            if Path(source) == selected:
                (selected / "server-data" / "value.txt").write_text(
                    "mutated after verification", encoding="utf-8"
                )
            return real_copytree(source, destination, *args, **kwargs)

        with (
            mock.patch.object(managed_actual.shutil, "copytree", side_effect=copytree),
            self.assertRaisesRegex(managed_actual.ManagedActualError, "hash"),
        ):
            managed_actual.restore(
                backup["backup_id"],
                verify_fn=mock.Mock(),
                status_fn=status,
                stop_fn=lambda: None,
                start_fn=lambda: None,
            )
        status.assert_not_called()
        self.assertEqual(live.read_text("utf-8"), "current value")
        self.assertEqual(list(root.glob(".restore-source-*")), [])

    def test_restore_recovers_when_initial_stop_raises_after_the_service_exits(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        live.write_text("current value", encoding="utf-8")
        events = []
        states = iter(({"running": True}, {"running": False}))

        def stop_after_exit():
            events.append("stop")
            raise managed_actual.ManagedActualError("marker cleanup failed")

        with self.assertRaisesRegex(managed_actual.ManagedActualError, "marker cleanup failed"):
            managed_actual.restore(
                backup["backup_id"],
                verify_fn=mock.Mock(),
                status_fn=lambda: next(states),
                stop_fn=stop_after_exit,
                start_fn=lambda: events.append("start"),
            )
        self.assertEqual(events, ["stop", "start"])
        self.assertEqual(live.read_text("utf-8"), "current value")

    def test_restore_swaps_only_managed_data_and_keeps_a_recovery_copy(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        live.write_text("current value", encoding="utf-8")
        result = managed_actual.restore(
            backup["backup_id"],
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
            verify_fn=lambda: {"ok": True},
        )
        self.assertEqual(live.read_text("utf-8"), "backup value")
        recovery = managed_actual.backups_dir() / result["recovery_backup_id"]
        self.assertEqual(
            (recovery / "server-data" / "value.txt").read_text("utf-8"), "current value"
        )

    def test_stopped_restore_starts_only_for_readback_then_stops_again(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        live.write_text("current value", encoding="utf-8")
        events = []
        managed_actual.restore(
            backup["backup_id"],
            status_fn=lambda: {"running": False},
            start_fn=lambda: events.append("start"),
            verify_fn=lambda: events.append("verify") or {"ok": True},
            stop_fn=lambda: events.append("stop"),
        )
        self.assertEqual(events, ["start", "verify", "stop"])

    def test_restore_rejects_malformed_readback_and_restores_current_data(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        for readback in ({}, {"ok": 0}, {"ok": None}):
            with self.subTest(readback=readback):
                live.write_text("backup value", encoding="utf-8")
                backup = managed_actual.backup(
                    status_fn=lambda: {"running": False},
                    stop_fn=lambda: None,
                    start_fn=lambda: None,
                )
                live.write_text("current value", encoding="utf-8")

                with self.assertRaisesRegex(
                    managed_actual.ManagedActualRollback,
                    "prior managed Actual data was restored",
                ):
                    managed_actual.restore(
                        backup["backup_id"],
                        status_fn=lambda: {"running": False},
                        stop_fn=lambda: None,
                        start_fn=lambda: None,
                        verify_fn=lambda readback=readback: readback,
                    )

                self.assertEqual(live.read_text("utf-8"), "current value")
                self.assertEqual(list(root.glob(".restore-previous-*")), [])

    def test_successful_restore_reports_cleanup_work_without_becoming_a_false_failure(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        live.write_text("current value", encoding="utf-8")
        real_remove = managed_actual._remove_path

        def remove(path):
            if path.name.startswith(".restore-previous-"):
                raise OSError("cleanup busy")
            return real_remove(path)

        with mock.patch.object(managed_actual, "_remove_path", side_effect=remove):
            result = managed_actual.restore(
                backup["backup_id"],
                status_fn=lambda: {"running": False},
                stop_fn=lambda: None,
                start_fn=lambda: None,
                verify_fn=lambda: {"ok": True},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(live.read_text("utf-8"), "backup value")
        self.assertEqual(len(result["cleanup_pending"]), 1)
        self.assertTrue(result["cleanup_pending"][0].startswith(".restore-previous-"))

    def test_restore_preparation_failure_restarts_original_without_mutation(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        live.write_text("current value", encoding="utf-8")
        events = []
        with (
            mock.patch.object(
                managed_actual,
                "backup",
                side_effect=managed_actual.ManagedActualError("recovery failed"),
            ),
            self.assertRaisesRegex(managed_actual.ManagedActualRollback, "preparation failed"),
        ):
            managed_actual.restore(
                backup["backup_id"],
                verify_fn=mock.Mock(),
                status_fn=lambda: {"running": True},
                stop_fn=lambda: events.append("stop"),
                start_fn=lambda: events.append("start"),
            )
        self.assertEqual(events, ["stop", "start"])
        self.assertEqual(live.read_text("utf-8"), "current value")

    def test_restore_stop_failure_preserves_prior_tree_before_filesystem_rollback(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        live.write_text("current value", encoding="utf-8")
        stop_calls = 0

        def stop():
            nonlocal stop_calls
            stop_calls += 1
            if stop_calls == 2:
                raise managed_actual.ManagedActualError("cannot stop target")

        with self.assertRaisesRegex(managed_actual.ManagedActualRollback, "could not be stopped"):
            managed_actual.restore(
                backup["backup_id"],
                status_fn=lambda: {"running": True},
                stop_fn=stop,
                start_fn=lambda: None,
                verify_fn=lambda: {"ok": False},
            )
        self.assertEqual(live.read_text("utf-8"), "backup value")
        previous = list(root.glob(".restore-previous-*"))
        self.assertEqual(len(previous), 1)
        self.assertEqual(
            (previous[0] / "server-data" / "value.txt").read_text("utf-8"),
            "current value",
        )

    def test_restore_filesystem_rollback_failure_retains_previous_tree(self):
        root = managed_actual.root_dir()
        live = root / "server-data" / "value.txt"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("backup value", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        live.write_text("current value", encoding="utf-8")
        with (
            mock.patch.object(managed_actual, "_remove_path", side_effect=OSError("disk failed")),
            self.assertRaisesRegex(managed_actual.ManagedActualRollback, "rollback was incomplete"),
        ):
            managed_actual.restore(
                backup["backup_id"],
                status_fn=lambda: {"running": False},
                stop_fn=lambda: None,
                start_fn=lambda: None,
                verify_fn=lambda: {"ok": False},
            )
        previous = list(root.glob(".restore-previous-*"))
        self.assertEqual(len(previous), 1)
        self.assertEqual(
            (previous[0] / "server-data" / "value.txt").read_text("utf-8"),
            "current value",
        )

    def test_early_restore_copy_failure_does_not_delete_untouched_live_directories(self):
        root = managed_actual.root_dir()
        names = ("server-data", "client-data", "migration-exports")
        for name in names:
            path = root / name / "value.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"backup {name}", encoding="utf-8")
        backup = managed_actual.backup(
            status_fn=lambda: {"running": False},
            stop_fn=lambda: None,
            start_fn=lambda: None,
        )
        for name in names:
            (root / name / "value.txt").write_text(f"current {name}", encoding="utf-8")
        real_copytree = managed_actual.shutil.copytree

        def copytree(source, destination, *args, **kwargs):
            source = Path(source)
            if source.name == "server-data" and source.parent.name.startswith(".restore-source-"):
                raise OSError("selected restore copy failed")
            return real_copytree(source, destination, *args, **kwargs)

        with (
            mock.patch.object(managed_actual.shutil, "copytree", side_effect=copytree),
            self.assertRaisesRegex(
                managed_actual.ManagedActualRollback, "prior managed Actual data was restored"
            ),
        ):
            managed_actual.restore(
                backup["backup_id"],
                status_fn=lambda: {"running": False},
                stop_fn=lambda: None,
                start_fn=lambda: None,
                verify_fn=lambda: {"ok": True},
            )
        for name in names:
            self.assertEqual(
                (root / name / "value.txt").read_text("utf-8"),
                f"current {name}",
            )

    def _make_app(self, path: Path, marker: str) -> None:
        (path / "node_modules" / "@actual-app" / "api").mkdir(parents=True)
        (path / "node_modules" / "@actual-app" / "api" / "index.js").write_text(
            marker, encoding="utf-8"
        )
        script = (
            path
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        )
        script.parent.mkdir(parents=True)
        script.write_text("server", encoding="utf-8")
        for name in ("package.json", "package-lock.json", "THIRD_PARTY.md"):
            (path / name).write_text(marker, encoding="utf-8")
        (path / "bridge.mjs").write_text(marker, encoding="utf-8")

    def _make_reviewed_app(self, path: Path) -> None:
        managed_actual._copy_bundle(path)
        (path / "node_modules" / "@actual-app" / "api").mkdir(parents=True)
        (path / "node_modules" / "@actual-app" / "api" / "index.js").write_text(
            "reviewed api", encoding="utf-8"
        )
        script = (
            path
            / "node_modules"
            / "@actual-app"
            / "sync-server"
            / "build"
            / "bin"
            / "actual-server.js"
        )
        script.parent.mkdir(parents=True)
        script.write_text("server", encoding="utf-8")

    def _write_rollback_manifest(self, manifest: dict) -> dict:
        install_sha256, install_files = managed_actual._artifact_digest_at(
            managed_actual.root_dir() / ".rollback-app"
        )
        value = {
            **manifest,
            "bundle_sha256": managed_actual._bundle_digest_at(
                managed_actual.root_dir() / ".rollback-app"
            ),
            "install_sha256": install_sha256,
            "install_files": install_files,
        }
        managed_actual._atomic_json(managed_actual.rollback_manifest_file(), value)
        return value

    def test_pair_move_reverts_app_when_manifest_move_fails(self):
        root = managed_actual.root_dir()
        source_app = root / "pair-source-app"
        source_manifest = root / "pair-source.json"
        target_app = root / "pair-target-app"
        target_manifest = root / "pair-target.json"
        self._make_app(source_app, "source")
        source_manifest.write_text("{}", encoding="utf-8")
        real_replace = managed_actual.os.replace

        def replace(source, target):
            if Path(source) == source_manifest:
                raise OSError("manifest move failed")
            return real_replace(source, target)

        with (
            mock.patch.object(managed_actual.os, "replace", side_effect=replace),
            self.assertRaisesRegex(OSError, "manifest move failed"),
        ):
            managed_actual._replace_pair(
                source_app,
                source_manifest,
                target_app,
                target_manifest,
            )
        self.assertTrue(source_app.is_dir())
        self.assertTrue(source_manifest.is_file())
        self.assertFalse(target_app.exists())
        self.assertFalse(target_manifest.exists())

    def test_rollback_swaps_the_app_and_its_exact_manifest_as_a_pair(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        target_manifest = {**managed_actual._manifest(), "bundle_sha256": "previous"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "previous bridge")
        target_manifest = self._write_rollback_manifest(target_manifest)

        with mock.patch.object(managed_actual, "status", return_value={"running": False}):
            result = managed_actual.rollback()

        self.assertEqual(result["update"], "rolled_back")
        self.assertEqual(
            (managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "previous bridge"
        )
        self.assertEqual((rollback_app / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual(managed_actual._read_json(root / "manifest.json"), target_manifest)
        self.assertEqual(
            managed_actual._read_json(managed_actual.rollback_manifest_file()), current_manifest
        )

    def test_rollback_refuses_to_swap_over_a_markerless_managed_server(self):
        root = managed_actual.root_dir()
        current_manifest = managed_actual._read_json(root / "manifest.json")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "previous bridge")
        self._write_rollback_manifest(managed_actual._manifest())
        managed_actual._cold_operation_absent.return_value = False

        with (
            mock.patch.object(managed_actual, "status", return_value={"running": False}),
            self.assertRaisesRegex(managed_actual.ManagedActualColdState, "process absence"),
        ):
            managed_actual.rollback()

        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual((rollback_app / "bridge.mjs").read_text("utf-8"), "previous bridge")
        self.assertEqual(managed_actual._read_json(root / "manifest.json"), current_manifest)

    def test_update_refuses_to_swap_over_a_markerless_managed_server(self):
        root = managed_actual.root_dir()
        current_manifest = managed_actual._read_json(root / "manifest.json")

        def install_candidate(path, **_kwargs):
            self._make_app(path, "candidate bridge")

        managed_actual._cold_operation_absent.return_value = False
        with (
            mock.patch.object(managed_actual, "_bundle_digest", return_value="new-bundle"),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "status", return_value={"running": False}),
            self.assertRaisesRegex(managed_actual.ManagedActualRollback, "before app replacement"),
        ):
            managed_actual.update()

        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual(managed_actual._read_json(root / "manifest.json"), current_manifest)
        self.assertFalse((root / ".rollback-app").exists())

    def test_rollback_rejects_a_tampered_bundle_before_stopping_or_swapping(self):
        root = managed_actual.root_dir()
        current_manifest = {
            **managed_actual._manifest(),
            "bundle_sha256": managed_actual._installed_bundle_digest(),
        }
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "previous bridge")
        self._write_rollback_manifest(managed_actual._manifest())
        (rollback_app / "bridge.mjs").write_text("tampered", encoding="utf-8")
        stop = mock.Mock()
        with (
            mock.patch.object(managed_actual, "stop", stop),
            self.assertRaisesRegex(managed_actual.ManagedActualError, "no complete"),
        ):
            managed_actual.rollback()
        stop.assert_not_called()
        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")

    def test_rollback_rejects_symlinked_install_path_components(self):
        root = managed_actual.root_dir()
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "previous bridge")
        self._write_rollback_manifest(managed_actual._manifest())
        outside_modules = root / ".outside-node-modules"
        (rollback_app / "node_modules").rename(outside_modules)
        (rollback_app / "node_modules").symlink_to(outside_modules, target_is_directory=True)
        self.assertFalse(managed_actual._install_artifacts_at(rollback_app))

        stop = mock.Mock()
        with (
            mock.patch.object(managed_actual, "stop", stop),
            self.assertRaisesRegex(managed_actual.ManagedActualError, "no complete"),
        ):
            managed_actual.rollback()
        stop.assert_not_called()
        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")

    def test_update_and_rollback_accept_the_supported_previous_version(self):
        root = managed_actual.root_dir()
        old_manifest = {
            **managed_actual._manifest(),
            "bundle_sha256": managed_actual._installed_bundle_digest(),
        }
        (root / "manifest.json").write_text(json.dumps(old_manifest), encoding="utf-8")

        def install_candidate(path, **_kwargs):
            self._make_app(path, "new bridge")

        with (
            mock.patch.object(managed_actual, "VERSION", "26.8.0"),
            mock.patch.object(managed_actual, "_bundle_digest", return_value="new-bundle"),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "status", return_value={"running": False}),
        ):
            updated = managed_actual.update()
            self.assertEqual(updated["update"], "updated")
            self.assertEqual(managed_actual._read_json(root / "manifest.json")["version"], "26.8.0")
            rolled_back = managed_actual.rollback()
            self.assertEqual(rolled_back["update"], "rolled_back")
        self.assertEqual(managed_actual._read_json(root / "manifest.json")["version"], "26.7.0")

    def test_failed_update_recovers_running_state_after_an_uncertain_stop(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")

        def install_candidate(path, **_kwargs):
            self._make_app(path, "candidate bridge")

        with (
            mock.patch.object(managed_actual, "_trusted_install", return_value=True),
            mock.patch.object(managed_actual, "_bundle_digest", return_value="new-bundle"),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(
                managed_actual,
                "status",
                side_effect=[{"running": True}, {"running": False}],
            ),
            mock.patch.object(
                managed_actual,
                "stop",
                side_effect=managed_actual.ManagedActualError("stop timed out after exit"),
            ),
            mock.patch.object(managed_actual, "start", return_value={"running": True}) as start,
            self.assertRaisesRegex(managed_actual.ManagedActualRollback, "stop did not complete"),
        ):
            managed_actual.update()

        start.assert_called_once()
        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual(managed_actual._read_json(root / "manifest.json"), current_manifest)

    def test_successful_update_reports_cleanup_work_without_becoming_a_false_failure(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        older_manifest = {**managed_actual._manifest(), "bundle_sha256": "older"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "older bridge")
        managed_actual._atomic_json(managed_actual.rollback_manifest_file(), older_manifest)

        def install_candidate(path, **_kwargs):
            self._make_app(path, "candidate bridge")

        real_remove = managed_actual._remove_path

        def remove(path):
            if path.name.startswith(".rollback-app-previous-"):
                raise OSError("cleanup busy")
            return real_remove(path)

        with (
            mock.patch.object(managed_actual, "_trusted_install", return_value=True),
            mock.patch.object(managed_actual, "_bundle_digest", return_value="new-bundle"),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "status", return_value={"running": False}),
            mock.patch.object(managed_actual, "_remove_path", side_effect=remove),
        ):
            result = managed_actual.update()

        self.assertEqual(result["update"], "updated")
        self.assertEqual(len(result["cleanup_pending"]), 1)
        self.assertTrue(result["cleanup_pending"][0].startswith(".rollback-app-previous-"))
        self.assertEqual(
            (managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "candidate bridge"
        )

    def test_failed_rollback_recovers_running_state_after_an_uncertain_initial_stop(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        target_manifest = {**managed_actual._manifest(), "bundle_sha256": "previous"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "previous bridge")
        target_manifest = self._write_rollback_manifest(target_manifest)

        with (
            mock.patch.object(
                managed_actual,
                "status",
                side_effect=[{"running": True}, {"running": False}],
            ),
            mock.patch.object(
                managed_actual,
                "stop",
                side_effect=managed_actual.ManagedActualError("stop timed out after exit"),
            ),
            mock.patch.object(managed_actual, "start", return_value={"running": True}) as start,
            self.assertRaisesRegex(
                managed_actual.ManagedActualRollback, "running state was recovered"
            ),
        ):
            managed_actual.rollback()

        start.assert_called_once()
        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual((rollback_app / "bridge.mjs").read_text("utf-8"), "previous bridge")
        self.assertEqual(managed_actual._read_json(root / "manifest.json"), current_manifest)

    def test_failed_running_rollback_restores_and_restarts_the_current_pair(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        target_manifest = {**managed_actual._manifest(), "bundle_sha256": "previous"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "previous bridge")
        target_manifest = self._write_rollback_manifest(target_manifest)

        with (
            mock.patch.object(managed_actual, "status", return_value={"running": True}),
            mock.patch.object(managed_actual, "stop"),
            mock.patch.object(
                managed_actual,
                "start",
                side_effect=[
                    managed_actual.ManagedActualError("candidate failed"),
                    {"running": True},
                ],
            ) as start,
        ):
            with self.assertRaisesRegex(
                managed_actual.ManagedActualRollback, "current app was restored"
            ):
                managed_actual.rollback()

        self.assertEqual(start.call_count, 2)
        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual((rollback_app / "bridge.mjs").read_text("utf-8"), "previous bridge")
        self.assertEqual(managed_actual._read_json(root / "manifest.json"), current_manifest)
        self.assertEqual(
            managed_actual._read_json(managed_actual.rollback_manifest_file()), target_manifest
        )

    def test_failed_rollback_restores_the_current_pair_after_target_stop_failure(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        target_manifest = {**managed_actual._manifest(), "bundle_sha256": "previous"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "previous bridge")
        target_manifest = self._write_rollback_manifest(target_manifest)
        stop_calls = 0

        def stop():
            nonlocal stop_calls
            stop_calls += 1
            if stop_calls == 2:
                raise managed_actual.ManagedActualError("candidate could not stop")

        managed_actual._cold_operation_absent.side_effect = [True, False]
        with (
            mock.patch.object(managed_actual, "status", return_value={"running": True}),
            mock.patch.object(managed_actual, "stop", side_effect=stop),
            mock.patch.object(
                managed_actual,
                "start",
                side_effect=managed_actual.ManagedActualError("candidate failed"),
            ) as start,
            self.assertRaisesRegex(managed_actual.ManagedActualRollback, "recovery was incomplete"),
        ):
            managed_actual.rollback()

        self.assertEqual(stop_calls, 2)
        self.assertEqual(start.call_count, 1)
        self.assertEqual(
            (managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "previous bridge"
        )
        staged_apps = [path for path in root.glob(".rollback-current-*") if path.is_dir()]
        staged_manifests = [
            path for path in root.glob(".rollback-current-*.json") if path.is_file()
        ]
        self.assertEqual(len(staged_apps), 1)
        self.assertEqual(len(staged_manifests), 1)
        self.assertEqual((staged_apps[0] / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual(managed_actual._read_json(staged_manifests[0]), current_manifest)
        self.assertFalse(rollback_app.exists())
        self.assertFalse(managed_actual.rollback_manifest_file().exists())

    def test_failed_rollback_restores_current_when_target_stop_raises_after_exit(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        target_manifest = {**managed_actual._manifest(), "bundle_sha256": "previous"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "previous bridge")
        target_manifest = self._write_rollback_manifest(target_manifest)

        with (
            mock.patch.object(
                managed_actual,
                "status",
                side_effect=[{"running": True}, {"running": False}],
            ),
            mock.patch.object(
                managed_actual,
                "stop",
                side_effect=[
                    {"running": False},
                    managed_actual.ManagedActualError("candidate stop timed out after exit"),
                ],
            ) as stop,
            mock.patch.object(
                managed_actual,
                "start",
                side_effect=[
                    managed_actual.ManagedActualError("candidate failed"),
                    {"running": True},
                ],
            ) as start,
            self.assertRaisesRegex(
                managed_actual.ManagedActualRollback, "recovery reported errors"
            ),
        ):
            managed_actual.rollback()

        self.assertEqual(stop.call_count, 2)
        self.assertEqual(start.call_count, 2)
        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual((rollback_app / "bridge.mjs").read_text("utf-8"), "previous bridge")
        self.assertEqual(managed_actual._read_json(root / "manifest.json"), current_manifest)
        self.assertEqual(
            managed_actual._read_json(managed_actual.rollback_manifest_file()), target_manifest
        )

    def test_failed_update_restores_current_and_prior_rollback_pairs(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        previous_manifest = {**managed_actual._manifest(), "bundle_sha256": "older"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        rollback_app = root / ".rollback-app"
        self._make_app(rollback_app, "older bridge")
        managed_actual._atomic_json(managed_actual.rollback_manifest_file(), previous_manifest)

        def install_candidate(path, **_kwargs):
            self._make_app(path, "candidate bridge")
            return {"api": managed_actual.VERSION}

        with (
            mock.patch.object(managed_actual, "_trusted_install", return_value=True),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "status", return_value={"running": True}),
            mock.patch.object(managed_actual, "stop"),
            mock.patch.object(
                managed_actual,
                "start",
                side_effect=[
                    managed_actual.ManagedActualError("candidate failed"),
                    {"running": True},
                ],
            ) as start,
        ):
            with self.assertRaisesRegex(
                managed_actual.ManagedActualRollback, "previous locked app was restored"
            ):
                managed_actual.update()

        self.assertEqual(start.call_count, 2)
        self.assertEqual((managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual((rollback_app / "bridge.mjs").read_text("utf-8"), "older bridge")
        self.assertEqual(managed_actual._read_json(root / "manifest.json"), current_manifest)
        self.assertEqual(
            managed_actual._read_json(managed_actual.rollback_manifest_file()), previous_manifest
        )

    def test_failed_update_preserves_staged_previous_app_when_candidate_will_not_stop(self):
        root = managed_actual.root_dir()
        current_manifest = {**managed_actual._manifest(), "bundle_sha256": "current"}
        (root / "manifest.json").write_text(json.dumps(current_manifest), encoding="utf-8")
        stop_calls = 0

        def install_candidate(path, **_kwargs):
            self._make_app(path, "candidate bridge")

        def stop():
            nonlocal stop_calls
            stop_calls += 1
            if stop_calls == 2:
                raise managed_actual.ManagedActualError("candidate could not stop")

        managed_actual._cold_operation_absent.side_effect = [True, False]
        with (
            mock.patch.object(managed_actual, "_trusted_install", return_value=True),
            mock.patch.object(managed_actual, "_bundle_digest", return_value="new-bundle"),
            mock.patch.object(managed_actual, "_install_candidate", side_effect=install_candidate),
            mock.patch.object(managed_actual, "status", return_value={"running": True}),
            mock.patch.object(managed_actual, "stop", side_effect=stop),
            mock.patch.object(
                managed_actual,
                "start",
                side_effect=managed_actual.ManagedActualError("candidate failed"),
            ) as start,
            self.assertRaisesRegex(managed_actual.ManagedActualRollback, "recovery was incomplete"),
        ):
            managed_actual.update()

        self.assertEqual(stop_calls, 2)
        self.assertEqual(start.call_count, 1)
        self.assertEqual(
            (managed_actual.app_dir() / "bridge.mjs").read_text("utf-8"), "candidate bridge"
        )
        self.assertEqual((root / ".rollback-app" / "bridge.mjs").read_text("utf-8"), "bridge")
        self.assertEqual(
            managed_actual._read_json(root / ".rollback-manifest.json"), current_manifest
        )


if __name__ == "__main__":
    unittest.main()
