import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import managed_companions


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Runner:
    def __init__(self):
        self.commands = []
        self.fail = set()

    def __call__(self, command, timeout=120):
        self.commands.append(list(command))
        verb = command[-1]
        if verb in self.fail:
            return Result(1, stderr="failed")
        if command[:3] == ["docker", "compose", "version"]:
            return Result(stdout="2.35.1\n")
        if "ps" in command:
            return Result(stdout="")
        return Result()


class ManagedCompanionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="alles-companions-")
        self.root = Path(self.temp.name)
        self.runner = Runner()
        self.patches = [
            mock.patch("services.managed_companions.data_dir", return_value=self.root),
            mock.patch("services.managed_companion_clients.data_dir", return_value=self.root),
            mock.patch("services.service_manager.data_dir", return_value=self.root),
            mock.patch("services.secretstore._KEY_FILE", self.root / "secret.key"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def prepare(self, service_id="adguard-home"):
        return managed_companions.prepare(service_id, runner=self.runner)

    def test_prepare_pulls_pinned_image_without_starting(self):
        result = self.prepare()
        compose = managed_companions.root_dir("adguard-home") / "compose.yaml"
        self.assertIn("adguard/adguardhome:v0.107.78", compose.read_text("utf-8"))
        self.assertTrue(result["prepared"])
        self.assertTrue(any(command[-1] == "pull" for command in self.runner.commands))
        self.assertFalse(any("up" in command for command in self.runner.commands))

    def test_prepare_refuses_modified_definition(self):
        self.prepare()
        compose = managed_companions.root_dir("adguard-home") / "compose.yaml"
        compose.write_text(compose.read_text("utf-8") + "# changed\n", "utf-8")
        with self.assertRaisesRegex(managed_companions.ManagedCompanionError, "changed outside"):
            self.prepare()

    def test_preflight_rejects_wildcard_and_occupied_dns(self):
        self.prepare()
        with self.assertRaisesRegex(managed_companions.ManagedCompanionError, "exact"):
            managed_companions.preflight("adguard-home", bind="0.0.0.0", runner=self.runner)
        result = managed_companions.preflight(
            "adguard-home",
            bind="127.0.0.1",
            runner=self.runner,
            port_free=lambda _bind, _port, protocol: protocol != socket.SOCK_DGRAM,
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"][1]["ok"])

    def test_activation_requires_exact_phrase(self):
        self.prepare()
        with self.assertRaisesRegex(managed_companions.ManagedCompanionError, "does not match"):
            managed_companions.activate(
                "adguard-home",
                bind="127.0.0.1",
                ports={"dns": 5353},
                admin_username="admin",
                admin_password="correct horse battery staple",
                confirmation="yes",
                runner=self.runner,
                port_free=lambda *_args: True,
                probe=lambda _service: True,
            )

    def test_adguard_activation_redacts_secret_and_rollback_restores_config(self):
        self.prepare()
        config = managed_companions.root_dir("adguard-home") / "conf" / "AdGuardHome.yaml"
        config.write_text("old: config\n", "utf-8")
        result = managed_companions.activate(
            "adguard-home",
            bind="127.0.0.1",
            ports={"dns": 5353},
            admin_username="admin",
            admin_password="correct horse battery staple",
            confirmation="activate adguard dns",
            runner=self.runner,
            port_free=lambda *_args: True,
            probe=lambda _service: True,
        )
        self.assertTrue(result["activated"])
        self.assertNotIn("correct horse", config.read_text("utf-8"))
        manifest = (managed_companions.root_dir("adguard-home") / "manifest.json").read_text(
            "utf-8"
        )
        self.assertNotIn("correct horse", manifest)
        managed_companions.rollback("adguard-home", runner=self.runner)
        self.assertEqual(config.read_text("utf-8"), "old: config\n")

    def test_probe_failure_restores_files_and_stops(self):
        self.prepare("nginx-proxy-manager")
        env = managed_companions.root_dir("nginx-proxy-manager") / ".env"
        before = env.read_text("utf-8")
        with self.assertRaisesRegex(managed_companions.ManagedCompanionError, "health probe"):
            managed_companions.activate(
                "nginx-proxy-manager",
                bind="127.0.0.1",
                ports={"http": 8080, "https": 8443},
                admin_username="owner@example.test",
                admin_password="correct horse battery staple",
                confirmation="activate nginx proxy",
                runner=self.runner,
                port_free=lambda *_args: True,
                probe=lambda _service: False,
                wait=0,
            )
        self.assertEqual(env.read_text("utf-8"), before)
        self.assertTrue(any(command[-1] == "down" for command in self.runner.commands))

    def test_nginx_activation_never_places_admin_secret_in_environment(self):
        self.prepare("nginx-proxy-manager")
        result = managed_companions.activate(
            "nginx-proxy-manager",
            bind="127.0.0.1",
            ports={"http": 8080, "https": 8443},
            admin_username="owner@example.test",
            admin_password="correct horse battery staple",
            confirmation="activate nginx proxy",
            runner=self.runner,
            port_free=lambda *_args: True,
            probe=lambda _service: True,
            npm_admin=lambda *_args: {"created": True},
        )
        env = (managed_companions.root_dir("nginx-proxy-manager") / ".env").read_text("utf-8")
        self.assertNotIn("owner@example.test", env)
        self.assertNotIn("correct horse", env)
        self.assertNotIn("INITIAL_ADMIN", env)
        self.assertEqual(result["admin_setup"], "alles_generated")

    def activate_npm(self, **extra):
        values = {
            "bind": "127.0.0.1",
            "ports": {"http": 8080, "https": 8443},
            "admin_username": "",
            "admin_password": "",
            "confirmation": "activate nginx proxy",
            "runner": self.runner,
            "port_free": lambda *_args: True,
            "probe": lambda _service: True,
        }
        values.update(extra)
        return managed_companions.activate("nginx-proxy-manager", **values)

    def test_nginx_activation_generates_the_first_admin_when_none_is_given(self):
        self.prepare("nginx-proxy-manager")
        made = []
        self.activate_npm(npm_admin=lambda email, password: made.append((email, password)))
        self.assertEqual(made[0][0], "admin@alles.local")
        self.assertGreaterEqual(len(made[0][1]), 18)
        manifest = (managed_companions.root_dir("nginx-proxy-manager") / "manifest.json").read_text(
            "utf-8"
        )
        self.assertNotIn(made[0][1], manifest)

    def test_nginx_activation_uses_the_admin_the_owner_typed(self):
        self.prepare("nginx-proxy-manager")
        made = []
        self.activate_npm(
            admin_username="owner@example.test",
            admin_password="correct horse battery staple",
            npm_admin=lambda email, password: made.append((email, password)),
        )
        self.assertEqual(made, [("owner@example.test", "correct horse battery staple")])

    def test_nginx_activation_refuses_a_short_password_before_starting(self):
        self.prepare("nginx-proxy-manager")
        with self.assertRaisesRegex(managed_companions.ManagedCompanionError, "12 characters"):
            self.activate_npm(admin_password="short")
        self.assertFalse(any("up" in command for command in self.runner.commands))

    def test_nginx_stays_up_when_the_admin_setup_call_fails(self):
        self.prepare("nginx-proxy-manager")

        def broken(*_args):
            raise managed_companions.managed_companion_clients.CompanionClientError("nope")

        result = self.activate_npm(npm_admin=broken)
        self.assertTrue(result["activated"])

    def test_health_wait_retries_until_the_admin_api_answers(self):
        answers = iter([False, False, True])
        waits = []
        ok = managed_companions._wait_healthy(
            "nginx-proxy-manager", lambda _service: next(answers), 60, sleep=waits.append
        )
        self.assertTrue(ok)
        self.assertEqual(len(waits), 2)

    def test_health_wait_gives_up_after_the_limit(self):
        self.assertFalse(
            managed_companions._wait_healthy(
                "nginx-proxy-manager", lambda _service: False, 0, sleep=lambda _s: None
            )
        )

    def test_nginx_probe_asks_the_api_not_the_page(self):
        calls = []

        def get(url, **_kwargs):
            calls.append(url)
            return mock.Mock(status_code=200)

        with mock.patch("services.managed_companions.httpx.get", get):
            self.assertTrue(managed_companions._probe("nginx-proxy-manager"))
        self.assertEqual(calls, ["http://127.0.0.1:8181/api/"])

    def test_start_failure_says_why(self):
        self.prepare("nginx-proxy-manager")

        def run(command, timeout=120):
            if command[-2:] == ["up", "-d"]:
                return Result(
                    1,
                    stderr="Creating\nBind for 127.0.0.1:8181 failed: port is already allocated\n",
                )
            return self.runner(command, timeout)

        with self.assertRaisesRegex(
            managed_companions.ManagedCompanionError, "port is already allocated"
        ):
            self.activate_npm(runner=run)

    def test_preflight_refuses_tampered_ownership(self):
        self.prepare()
        marker = self.root / "owned-services" / "adguard-home.json"
        payload = json.loads(marker.read_text("utf-8"))
        payload["owner_id"] = "tampered"
        marker.write_text(json.dumps(payload), "utf-8")
        with self.assertRaisesRegex(
            managed_companions.ManagedCompanionError, "markers do not match"
        ):
            managed_companions.preflight(
                "adguard-home",
                bind="127.0.0.1",
                runner=self.runner,
                port_free=lambda *_args: True,
            )


if __name__ == "__main__":
    unittest.main()
