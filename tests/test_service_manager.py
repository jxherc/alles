import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import service_manager as sm


class ServiceManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.services = self.data / "services"
        self.services.mkdir(parents=True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = mock.patch.dict(os.environ, {"ALLES_DATA": str(self.data)})
        self.home_patch = mock.patch.object(sm, "_home_dir", return_value=self.home)
        self.project_patch = mock.patch.object(sm, "_project_root", return_value=self.root / "code")
        self.env.start()
        self.home_patch.start()
        self.project_patch.start()

    def tearDown(self):
        self.project_patch.stop()
        self.home_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def _result(returncode=0, stdout=""):
        return subprocess.CompletedProcess([], returncode, stdout, "")

    def _compose(self):
        root = self.services / "search"
        root.mkdir()
        (root / "compose.yaml").write_text("services:\n  search:\n    image: example@sha256:abc\n")
        return sm.register_owned_service(
            service_id="search",
            name="managed search",
            manager="compose",
            root=root,
            project="alles-search",
            compose_service="search",
        )

    def test_compose_control_uses_fixed_arguments_without_shell(self):
        service = self._compose()
        runner = mock.Mock(return_value=self._result(stdout="container-id\n"))
        result = sm.control("search", "restart", runner=runner)
        self.assertTrue(result["ok"])
        self.assertEqual(
            runner.call_args.args[0],
            [
                "docker",
                "compose",
                "--project-directory",
                service.root,
                "--project-name",
                "alles-search",
                "restart",
                "search",
            ],
        )

    def test_registration_writes_private_matching_markers(self):
        service = self._compose()
        local = Path(service.root) / sm._OWNER_FILE
        registry = sm._registry_dir() / "search.json"
        self.assertEqual(json.loads(local.read_text()), json.loads(registry.read_text()))
        if os.name != "nt":
            self.assertEqual(local.stat().st_mode & 0o777, 0o600)
            self.assertEqual(registry.stat().st_mode & 0o777, 0o600)

    def test_changed_definition_revokes_control(self):
        service = self._compose()
        Path(service.definition).write_text("changed")
        runner = mock.Mock(return_value=self._result())
        with self.assertRaisesRegex(sm.ServiceOwnershipError, "changed"):
            sm.control("search", "stop", runner=runner)
        runner.assert_not_called()

    def test_compose_status_requires_a_running_container_id(self):
        self._compose()
        stopped = sm.status("search", runner=mock.Mock(return_value=self._result(stdout="")))
        running = sm.status(
            "search", runner=mock.Mock(return_value=self._result(stdout="container-id\n"))
        )
        self.assertFalse(stopped["running"])
        self.assertTrue(running["running"])

    def test_missing_manager_keeps_ownership_but_disables_actions(self):
        self._compose()
        rows = sm.list_services(runner=mock.Mock(side_effect=FileNotFoundError("docker")))
        self.assertTrue(rows[0]["owned"])
        self.assertFalse(rows[0]["available"])
        self.assertEqual(rows[0]["actions"], [])

    def test_mismatched_root_marker_revokes_control(self):
        service = self._compose()
        marker = Path(service.root) / sm._OWNER_FILE
        value = json.loads(marker.read_text())
        value["owner_id"] = "other"
        marker.write_text(json.dumps(value))
        runner = mock.Mock(return_value=self._result())
        with self.assertRaisesRegex(sm.ServiceOwnershipError, "do not match"):
            sm.control("search", "start", runner=runner)
        runner.assert_not_called()

    def test_symlinked_registry_marker_is_rejected(self):
        self._compose()
        registry = sm._registry_dir() / "search.json"
        target = self.root / "replacement.json"
        target.write_text(registry.read_text())
        registry.unlink()
        registry.symlink_to(target)
        with self.assertRaisesRegex(sm.ServiceOwnershipError, "unsafe"):
            sm.status("search", runner=mock.Mock())

    def test_symlinked_registry_directory_disables_all_actions(self):
        target = self.root / "fake-registry"
        target.mkdir()
        sm._registry_dir().symlink_to(target, target_is_directory=True)
        rows = sm.list_services(runner=mock.Mock())
        self.assertEqual(rows[0]["service_id"], "registry")
        self.assertFalse(rows[0]["owned"])
        self.assertEqual(rows[0]["actions"], [])

    def test_invalid_or_unowned_roots_are_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "compose.yaml").write_text("services: {}")
        with self.assertRaisesRegex(ValueError, "outside"):
            sm.register_owned_service(
                service_id="search",
                name="search",
                manager="compose",
                root=outside,
                project="alles-search",
                compose_service="search",
            )

    def test_command_shaped_identifiers_are_rejected(self):
        root = self.services / "unsafe"
        root.mkdir()
        (root / "compose.yaml").write_text("services: {}")
        with self.assertRaisesRegex(ValueError, "Compose service"):
            sm.register_owned_service(
                service_id="unsafe",
                name="unsafe",
                manager="compose",
                root=root,
                project="alles-unsafe",
                compose_service="search;rm",
            )

    def test_subprocess_environment_does_not_copy_provider_secrets(self):
        with mock.patch.dict(
            os.environ,
            {"PATH": "/bin", "HOME": str(self.home), "OPENAI_API_KEY": "private"},
            clear=True,
        ):
            env = sm._environment()
        self.assertEqual(env, {"PATH": "/bin", "HOME": str(self.home)})

    def test_systemd_user_command_is_typed(self):
        root = self.services / "worker"
        root.mkdir()
        unit_dir = self.home / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        (unit_dir / "alles-worker.service").write_text("[Service]\nExecStart=/fixed/worker\n")
        sm.register_owned_service(
            service_id="worker",
            name="worker",
            manager="systemd-user",
            root=root,
            unit="alles-worker.service",
        )
        runner = mock.Mock(return_value=self._result(stdout="active\n"))
        with mock.patch.object(sm.platform, "system", return_value="Linux"):
            status = sm.status("worker", runner=runner)
        self.assertTrue(status["running"])
        self.assertTrue(status["available"])
        self.assertEqual(
            runner.call_args.args[0],
            [
                "systemctl",
                "--user",
                "show",
                "alles-worker.service",
                "--property=ActiveState",
                "--value",
            ],
        )

    def test_launchd_command_is_typed(self):
        root = self.services / "helper"
        root.mkdir()
        unit_dir = self.home / "Library" / "LaunchAgents"
        unit_dir.mkdir(parents=True)
        (unit_dir / "app.alles.helper.plist").write_text("<plist></plist>")
        sm.register_owned_service(
            service_id="helper",
            name="helper",
            manager="launchd",
            root=root,
            unit="app.alles.helper",
        )
        runner = mock.Mock(return_value=self._result())
        with mock.patch.object(sm.platform, "system", return_value="Darwin"):
            sm.control("helper", "stop", runner=runner)
        self.assertEqual(
            runner.call_args.args[0],
            ["launchctl", "kill", "SIGTERM", f"gui/{os.getuid()}/app.alles.helper"],
        )

    def test_list_marks_tampered_service_unowned_without_running_it(self):
        service = self._compose()
        Path(service.definition).write_text("tampered")
        runner = mock.Mock()
        rows = sm.list_services(runner=runner)
        self.assertEqual(rows[0]["owned"], False)
        self.assertEqual(rows[0]["available"], False)
        self.assertEqual(rows[0]["actions"], [])
        runner.assert_not_called()

    def test_unregister_removes_only_matching_markers_and_keeps_data(self):
        service = self._compose()
        data = Path(service.root) / "private-data"
        data.write_text("keep")
        result = sm.unregister_owned_service("search")
        self.assertTrue(result["ok"])
        self.assertFalse((Path(service.root) / sm._OWNER_FILE).exists())
        self.assertFalse((sm._registry_dir() / "search.json").exists())
        self.assertEqual(data.read_text(), "keep")

    def test_unregister_refuses_tampered_service(self):
        service = self._compose()
        Path(service.definition).write_text("tampered")
        with self.assertRaises(sm.ServiceOwnershipError):
            sm.unregister_owned_service("search")
        self.assertTrue((Path(service.root) / sm._OWNER_FILE).exists())


if __name__ == "__main__":
    unittest.main()
