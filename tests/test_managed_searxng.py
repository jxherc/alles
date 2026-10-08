import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import settings
from services import managed_searxng as ms


class ManagedSearxngTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"ALLES_DATA": self.tmp.name})
        self.env.start()
        self.settings_file = mock.patch.object(
            settings, "_SETTINGS_FILE", Path(self.tmp.name) / "settings.json"
        )
        self.settings_file.start()
        settings._clear_settings_cache()

    def tearDown(self):
        settings._clear_settings_cache()
        self.settings_file.stop()
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def result(code=0, stdout=""):
        return subprocess.CompletedProcess([], code, stdout, "")

    def runner(self, command, _timeout=120):
        if command[:2] == ["docker", "version"]:
            return self.result(stdout="29.6.0\n")
        if "ps" in command:
            return self.result(stdout="container-id\n")
        return self.result()

    def test_install_is_loopback_pinned_private_and_resource_limited(self):
        status = ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)
        self.assertTrue(status["installed"])
        self.assertTrue(status["healthy"])
        compose = (ms.root_dir() / "compose.yaml").read_text()
        self.assertIn(ms.IMAGE, compose)
        self.assertIn('"127.0.0.1:8888:8080"', compose)
        self.assertIn('user: "977:977"', compose)
        self.assertIn("./config:/etc/searxng:ro", compose)
        self.assertIn("cap_drop:\n      - ALL", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("read_only: true", compose)
        self.assertIn("pids_limit: 128", compose)
        self.assertIn("mem_limit: 512m", compose)
        self.assertIn("cpus: 1.0", compose)
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn("driver: local", compose)
        self.assertIn('max-size: "5m"', compose)
        env_file = ms.root_dir() / ".env"
        self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        self.assertIn("SEARXNG_SECRET=", env_file.read_text())
        self.assertEqual(stat.S_IMODE((ms.root_dir() / "config").stat().st_mode), 0o755)
        self.assertEqual(settings.load_settings()["search_provider"], "searxng")
        self.assertIn("duckduckgo", settings.load_settings()["search_fallback_chain"])

    def test_managed_port_can_be_isolated_without_touching_an_existing_service(self):
        with mock.patch.dict(os.environ, {"ALLES_SEARXNG_PORT": "8890"}):
            status = ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)

        compose = (ms.root_dir() / "compose.yaml").read_text()
        self.assertEqual(status["url"], "http://127.0.0.1:8890")
        self.assertEqual(status["bind"], "127.0.0.1:8890")
        self.assertIn('"127.0.0.1:8890:8080"', compose)
        self.assertIn(
            "SEARXNG_BASE_URL=http://127.0.0.1:8890/", (ms.root_dir() / ".env").read_text()
        )

        with mock.patch.dict(os.environ, {"ALLES_SEARXNG_PORT": "8891"}):
            self.assertEqual(ms.managed_url(), "http://127.0.0.1:8890")
            self.assertEqual(
                ms.status(runner=self.runner, probe=lambda: True)["bind"], "127.0.0.1:8890"
            )

    def test_docker_unavailable_is_honest_and_writes_nothing(self):
        def unavailable(command, _timeout=120):
            return self.result(1)

        with self.assertRaisesRegex(ms.ManagedSearxngError, "Docker is unavailable"):
            ms.install(runner=unavailable, probe=lambda: False, allow_unverified=True)
        self.assertFalse(ms.root_dir().exists())

    def test_live_verified_build_reports_managed_install_support(self):
        ms.install(runner=self.runner, probe=lambda: True)
        status = ms.status(runner=self.runner, probe=lambda: False)
        self.assertTrue(status["support_verified"])
        self.assertIn("Live-verified", status["spike_note"])

    def test_failed_pull_keeps_definition_unregistered_for_safe_retry(self):
        def pull_fails(command, _timeout=120):
            if command[:2] == ["docker", "version"]:
                return self.result(stdout="29.6.0\n")
            if "pull" in command:
                return self.result(1)
            if "ps" in command:
                return self.result(stdout="")
            return self.result()

        with self.assertRaisesRegex(ms.ManagedSearxngError, "pull failed"):
            ms.install(runner=pull_fails, probe=lambda: False, allow_unverified=True)
        status = ms.status(runner=pull_fails, probe=lambda: False)
        self.assertFalse(status["installed"])
        self.assertFalse(status["owned"])
        self.assertFalse(status["running"])
        self.assertTrue(ms.root_dir().is_dir())

    def test_failed_health_stops_the_container(self):
        commands = []

        def runner(command, _timeout=120):
            commands.append(command)
            return self.runner(command, _timeout)

        with self.assertRaisesRegex(ms.ManagedSearxngError, "health check"):
            ms.install(runner=runner, probe=lambda: False, allow_unverified=True)
        self.assertTrue(any("stop" in command for command in commands))

    def test_unshared_config_path_fails_before_compose_start_and_allows_install_retry(self):
        commands = []

        def runner(command, _timeout=120):
            commands.append(command)
            if command[:2] == ["docker", "version"]:
                return self.result(stdout="29.6.0\n")
            if command[:2] == ["docker", "run"]:
                return self.result(125)
            return self.result()

        with self.assertRaisesRegex(ms.ManagedSearxngError, "folder shared with Docker"):
            ms.install(runner=runner, probe=lambda: False, allow_unverified=True)

        self.assertTrue(any(command[:2] == ["docker", "run"] for command in commands))
        probe = next(command for command in commands if command[:2] == ["docker", "run"])
        self.assertIn("p.open('rb').read(1)", probe[-1])
        self.assertFalse(any("up" in command for command in commands))
        failed_status = ms.status(runner=runner, probe=lambda: False)
        self.assertFalse(failed_status["installed"])
        self.assertFalse(failed_status["owned"])
        self.assertTrue(ms.root_dir().is_dir())

        retried = ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)
        self.assertTrue(retried["installed"])
        self.assertTrue(retried["healthy"])

    def test_restart_waits_for_loopback_health_before_reporting_success(self):
        ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)
        probes = iter([False, False, True])

        result = ms.control(
            "restart",
            runner=self.runner,
            probe=lambda: next(probes),
            sleep=lambda _seconds: None,
        )

        self.assertTrue(result["running"])
        self.assertTrue(result["healthy"])

    def test_restart_health_failure_stops_the_unhealthy_container(self):
        commands = []

        def runner(command, _timeout=120):
            commands.append(command)
            return self.runner(command, _timeout)

        ms.install(runner=runner, probe=lambda: True, allow_unverified=True)
        with self.assertRaisesRegex(ms.ManagedSearxngError, "failed its loopback health check"):
            ms.control(
                "restart",
                runner=runner,
                probe=lambda: False,
                sleep=lambda _seconds: None,
            )

        self.assertTrue(any("stop" in command for command in commands))

    def test_failed_update_restores_previous_owned_definition(self):
        ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)
        old = (ms.root_dir() / "compose.yaml").read_text()
        probes = iter([True, False])
        with self.assertRaises(ms.ManagedSearxngRollback):
            ms.update(
                image="docker.io/searxng/searxng@sha256:" + "1" * 64,
                version="future-test",
                runner=self.runner,
                probe=lambda: next(probes),
            )
        self.assertEqual((ms.root_dir() / "compose.yaml").read_text(), old)
        self.assertTrue(ms.status(runner=self.runner, probe=lambda: True)["owned"])

    def test_successful_update_can_be_explicitly_rolled_back(self):
        ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)
        updated = ms.update(
            image="docker.io/searxng/searxng@sha256:" + "2" * 64,
            version="future-test",
            runner=self.runner,
            probe=lambda: True,
        )
        self.assertEqual(updated["update"], "updated")
        rolled = ms.rollback(runner=self.runner, probe=lambda: True)
        self.assertEqual(rolled["update"], "rolled_back")
        self.assertEqual(rolled["version"], ms.VERSION)

    def test_uninstall_keeps_definition_config_and_secret(self):
        ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)
        secret = (ms.root_dir() / ".env").read_text()
        result = ms.uninstall_keep_data(runner=self.runner)
        self.assertFalse(result["installed"])
        self.assertTrue(result["data_kept"])
        self.assertEqual((ms.root_dir() / ".env").read_text(), secret)
        self.assertTrue((ms.root_dir() / "config" / "settings.yml").is_file())
        self.assertFalse(ms.status(runner=self.runner, probe=lambda: False)["owned"])

    def test_unowned_changed_definition_cannot_be_adopted(self):
        ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)
        ms.uninstall_keep_data(runner=self.runner)
        (ms.root_dir() / "compose.yaml").write_text("services: {}\n")
        with self.assertRaisesRegex(ms.ManagedSearxngError, "not a trusted"):
            ms.install(runner=self.runner, probe=lambda: True, allow_unverified=True)

    def test_json_search_requires_health_and_validates_result_shape(self):
        unhealthy = mock.patch.object(ms, "status", return_value={"healthy": False})
        with unhealthy, self.assertRaisesRegex(ms.ManagedSearxngError, "not healthy"):
            ms.json_search("alles")

        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"results": [{"url": "https://example.com"}]}
        with (
            mock.patch.object(ms, "status", return_value={"healthy": True}),
            mock.patch("httpx.get", return_value=response) as get,
        ):
            result = ms.json_search("alles")
        self.assertEqual(result, {"ok": True, "results": 1})
        self.assertEqual(get.call_args.kwargs["params"], {"q": "alles", "format": "json"})


if __name__ == "__main__":
    unittest.main()
