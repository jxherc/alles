import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from core import auth
from services import server_policy
from tests._client import ApiTest


class ServerPolicyServiceTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="alles-server-policy-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data_patch = mock.patch("services.server_policy.data_dir", return_value=self.root)
        self.data_patch.start()

    def tearDown(self):
        self.data_patch.stop()
        super().tearDown()

    @staticmethod
    def _owned_text():
        return json.dumps({"control_mode": "owned_only", "host_services": []})

    @staticmethod
    def _allow_text():
        return json.dumps(
            {
                "control_mode": "allowlisted_host",
                "host_services": [{"manager": "launchd", "id": "com.example.indexer"}],
            }
        )

    def test_missing_invalid_and_unsafe_files_fail_closed(self):
        missing = server_policy.read()
        self.assertFalse(missing["valid"])
        self.assertEqual(missing["policy"], server_policy.DEFAULT_POLICY)

        path = server_policy.policy_path()
        path.write_text("not json", encoding="utf-8")
        path.chmod(0o600)
        invalid = server_policy.read()
        self.assertFalse(invalid["valid"])
        self.assertEqual(invalid["policy"]["control_mode"], "owned_only")

        path.write_text(self._owned_text(), encoding="utf-8")
        path.chmod(0o644)
        unsafe = server_policy.read()
        self.assertFalse(unsafe["valid"])
        self.assertEqual(unsafe["error_code"], "unsafe_policy_permissions")

    def test_schema_rejects_commands_unknown_fields_wildcards_and_duplicates(self):
        bad = [
            {"control_mode": "allowlisted_host", "host_services": [], "command": "id"},
            {
                "control_mode": "allowlisted_host",
                "host_services": [{"manager": "launchd", "id": "*"}],
            },
            {
                "control_mode": "allowlisted_host",
                "host_services": [
                    {"manager": "systemd", "id": "worker.service"},
                    {"manager": "systemd", "id": "worker.service"},
                ],
            },
            {
                "control_mode": "owned_only",
                "host_services": [{"manager": "systemd", "id": "worker.service"}],
            },
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(server_policy.ServerPolicyError):
                server_policy.validate(value)

    def test_save_is_owner_only_canonical_and_failed_save_keeps_previous_file(self):
        saved = server_policy.save(self._owned_text())
        path = server_policy.policy_path()
        self.assertTrue(saved["valid"])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        before = path.read_bytes()
        with self.assertRaises(server_policy.ServerPolicyError):
            server_policy.save('{"control_mode":"owned_only","host_services":[],"path":"/tmp"}')
        self.assertEqual(path.read_bytes(), before)

    def test_symlink_policy_is_rejected_without_replacing_target(self):
        outside = self.root / "outside.json"
        outside.write_text(self._owned_text(), encoding="utf-8")
        outside.chmod(0o600)
        server_policy.policy_path().symlink_to(outside)
        with self.assertRaises(server_policy.ServerPolicyError) as raised:
            server_policy.save(self._owned_text())
        self.assertEqual(raised.exception.code, "unsafe_policy_file")
        self.assertTrue(server_policy.policy_path().is_symlink())

    def test_api_widening_requires_loopback_device_password_reauth_and_phrase(self):
        body = {"policy": self._allow_text(), "confirmation": "allow host services"}
        remote = self.client.put("/api/system/policy", json=body)
        self.assertEqual(remote.status_code, 403)
        self.assertEqual(remote.json()["code"], "loopback_required")

        with (
            mock.patch("routes.system.server_policy.is_loopback_client", return_value=True),
            mock.patch("routes.system.access_profile", return_value="device"),
        ):
            no_password = self.client.put("/api/system/policy", json=body)
        self.assertEqual(no_password.status_code, 403)
        self.assertEqual(no_password.json()["code"], "owner_password_required")

        token = auth.create_session_token()
        auth.store_token(token)
        self.client.cookies.set("aide_session", token)
        try:
            with (
                mock.patch("app.auth_enabled", return_value=True),
                mock.patch("core.settings.auth_enabled", return_value=True),
                mock.patch("routes.system.auth_enabled", return_value=True),
                mock.patch("routes.system.server_policy.is_loopback_client", return_value=True),
                mock.patch("routes.system.access_profile", return_value="device"),
            ):
                wrong = self.client.put(
                    "/api/system/policy", json={**body, "confirmation": "yes"}
                )
                accepted = self.client.put("/api/system/policy", json=body)
        finally:
            self.client.cookies.clear()
            auth.revoke_token(token)
        self.assertEqual(wrong.status_code, 409)
        self.assertEqual(wrong.json()["code"], "confirmation_required")
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["policy"]["control_mode"], "allowlisted_host")

    def test_host_action_uses_only_the_exact_allowlisted_command(self):
        server_policy.save(self._allow_text())
        completed = mock.Mock(returncode=0, stdout="", stderr="")
        with (
            mock.patch("services.server_policy.platform.system", return_value="Darwin"),
            mock.patch("services.server_policy.subprocess.run", return_value=completed) as run,
        ):
            result = server_policy.control_host_service(
                "launchd", "com.example.indexer", "restart"
            )
        self.assertTrue(result["accepted"])
        run.assert_called_once_with(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.example.indexer"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        with self.assertRaises(server_policy.ServerPolicyError):
            server_policy.control_host_service("launchd", "com.example.other", "restart")
