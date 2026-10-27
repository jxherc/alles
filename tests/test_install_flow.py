"""The one-line install: trimmed downloads, step output, settings file, linger and access."""

import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cli
from services import cli_ui, native_install

ROOT = Path(__file__).resolve().parent.parent


class StepOutputTest(unittest.TestCase):
    def _steps(self):
        stream = io.StringIO()
        return stream, cli_ui.Steps(
            {"folders": "folders", "packages": "python packages"}, cli_ui.Style(stream)
        )

    def test_piped_output_is_plain_lines_with_one_mark_per_step(self):
        stream, steps = self._steps()
        steps.handle("folders", "start")
        steps.handle("folders", "done", "/somewhere")
        steps.handle("packages", "start")
        steps.handle("packages", "update", "12 downloaded")
        steps.handle("packages", "warn", "slow mirror")
        steps.close()
        text = stream.getvalue()
        self.assertNotIn("\033", text)
        self.assertEqual(text.count("folders"), 1)
        self.assertIn("! python packages", text)
        self.assertIn("slow mirror", text)

    def test_a_failure_names_the_step_and_shows_the_tool_output(self):
        stream, steps = self._steps()
        steps.handle("packages", "start")
        steps.handle("packages", "log", "ERROR: no matching distribution")
        steps.fail("stopped safely: could not build the private Python environment")
        text = stream.getvalue()
        self.assertIn(f"{steps.style.mark_bad} python packages", text)
        self.assertIn("stopped safely", text)
        self.assertIn("no matching distribution", text)


class TrimmedReleaseTest(unittest.TestCase):
    def test_release_copy_leaves_out_what_gitattributes_leaves_out(self):
        ignored = set()
        for line in (ROOT / ".gitattributes").read_text("utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == "export-ignore" and parts[0].count("/") == 1:
                ignored.add(parts[0].strip("/"))
        self.assertEqual(ignored, set(native_install._DEV_ONLY))

        ignore = native_install._release_ignore(ROOT)
        top = ignore(os.fspath(ROOT), ["tests", "docs", "core", "static", "LICENSE", "install.sh"])
        self.assertEqual(top, {"tests", "docs", "install.sh"})
        scripts = ignore(
            os.path.join(ROOT, "scripts"), ["local_voice_worker.py", "server_messages.py"]
        )
        self.assertEqual(scripts, {"server_messages.py"})

    def test_every_release_notice_file_survives_the_trim(self):
        notices = json.loads((ROOT / "credits" / "release-notice-files.json").read_text("utf-8"))
        for name in notices["files"]:
            first = Path(name).parts[0]
            self.assertNotIn(first, native_install._DEV_ONLY, name)


class NativeInstallStepsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-install-flow-")
        self.root = Path(self.tmp.name)
        self.home = (self.root / "home").resolve()
        self.home.mkdir()
        self.layout = native_install.platform_layout("Linux", home=self.home)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in ("app.py", "cli.py", "requirements.txt", "requirements.lock"):
            (self.source / name).write_text(f"# {name}\n", "utf-8")
        self.commands = []
        self.patch = mock.patch.object(
            native_install.service_manager, "_home_dir", return_value=self.home
        )
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _runner(self, command, **_kwargs):
        self.commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    @staticmethod
    def _builder(source, destination):
        destination.mkdir(parents=True)
        python = destination / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        (destination / ".venv" / "pyvenv.cfg").write_text("home = test\n", "utf-8")
        python.write_text("#!/bin/sh\nexit 0\n", "utf-8")
        python.chmod(0o755)
        (destination / "app.py").write_text("", "utf-8")
        return python

    def _install(self, **extra):
        events = []
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            result = native_install.install(
                self.source,
                self.layout,
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
                progress=lambda step, state, detail="": events.append((step, state)),
                **extra,
            )
        return result, events

    def test_steps_run_in_order_and_linger_is_turned_on(self):
        result, events = self._install(install_source={"kind": "unavailable"}, release_id="r1")
        self.assertEqual(
            events,
            [
                ("folders", "start"),
                ("folders", "done"),
                ("check", "start"),
                ("check", "done"),
                ("service", "start"),
                ("service", "done"),
                ("linger", "start"),
                ("linger", "done"),
            ],
        )
        self.assertTrue(result["keeps_running"])
        self.assertTrue(
            any(command[:2] == ["loginctl", "enable-linger"] for command in self.commands)
        )

    def test_systemd_seeing_the_new_unit_file_does_not_block_the_install(self):
        # systemctl show reports a unit as loaded once its file is on disk
        def systemd(command, **_kwargs):
            self.commands.append(list(command))
            if command[:3] == ["systemctl", "--user", "show"]:
                exists = self.layout.service_definition.exists()
                return subprocess.CompletedProcess(
                    command, 0, "loaded" if exists else "not-found", ""
                )
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            result = native_install.install(
                self.source,
                self.layout,
                release_id="r1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                install_source={"kind": "unavailable"},
                runner=systemd,
            )
        self.assertTrue(result["ok"])
        self.assertIn(
            ["systemctl", "--user", "enable", "--now", "alles-server.service"], self.commands
        )

    def test_settings_file_gets_a_secret_once_and_stays_private(self):
        result, _ = self._install(install_source={"kind": "unavailable"}, release_id="r1")
        config = self.layout.config_file
        self.assertEqual(config, self.home / ".config" / "alles" / "alles.env")
        self.assertTrue(result["config_created"])
        text = config.read_text("utf-8")
        self.assertRegex(text, r"(?m)^SECRET_KEY=[0-9a-f]{64}$")
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertFalse(native_install._write_settings_file(self.layout))
        self.assertEqual(config.read_text("utf-8"), text)
        dispatcher = self.layout.dispatcher.read_text("utf-8")
        self.assertIn("export ALLES_CONFIG=", dispatcher)
        self.assertIn(
            "Environment=ALLES_CONFIG=", self.layout.service_definition.read_text("utf-8")
        )

    def test_an_archive_install_names_its_release_after_the_commit(self):
        commit = "ab" * 20
        source = {
            "kind": "archive",
            "repository": "jxherc/alles",
            "branch": "main",
            "commit": commit,
        }
        result, _ = self._install(install_source=source)
        self.assertEqual(result["release_id"], commit[:12])
        manifest = json.loads(self.layout.manifest.read_text("utf-8"))
        self.assertEqual(manifest["source"], source)
        self.assertEqual(manifest["release_commits"], {commit[:12]: commit})

    def test_archive_source_metadata_is_checked(self):
        with self.assertRaises(native_install.NativeInstallError):
            native_install._validated_source_metadata(
                {
                    "kind": "archive",
                    "repository": "x; rm -rf /",
                    "branch": "main",
                    "commit": "a" * 40,
                },
                error="bad",
            )


class LingerTest(unittest.TestCase):
    def _runner(self, answers):
        calls = []

        def run(command, **_kwargs):
            calls.append(command)
            code, out = answers.get(tuple(command[:3]), (1, ""))
            return subprocess.CompletedProcess(command, code, out, "")

        return calls, run

    def test_linger_already_on_needs_nothing(self):
        import pwd

        user = pwd.getpwuid(os.getuid()).pw_name
        calls, run = self._runner({("loginctl", "show-user", user): (0, "yes\n")})
        self.assertTrue(native_install._keep_running_after_logout(run))
        self.assertEqual(len(calls), 1)

    def test_falls_back_to_passwordless_sudo_and_reports_failure(self):
        calls, run = self._runner({("sudo", "-n", "loginctl"): (0, "")})
        self.assertTrue(native_install._keep_running_after_logout(run))
        self.assertEqual(calls[-1][:3], ["sudo", "-n", "loginctl"])
        _, refused = self._runner({})
        self.assertFalse(native_install._keep_running_after_logout(refused))


class SettingsFileLoadTest(unittest.TestCase):
    def test_the_app_reads_the_installed_settings_file(self):
        from core import settings

        with tempfile.TemporaryDirectory(prefix="alles-config-") as directory:
            config = Path(directory) / "alles.env"
            config.write_text("ALLES_CONFIG_PROBE=from-the-file\n", "utf-8")
            environ = {k: v for k, v in os.environ.items() if k != "PYTHON_DOTENV_DISABLED"}
            environ["ALLES_CONFIG"] = str(config)
            with mock.patch.dict(os.environ, environ, clear=True):
                settings.load_owner_config()
                self.assertEqual(os.environ.get("ALLES_CONFIG_PROBE"), "from-the-file")


class CliInstallHelpersTest(unittest.TestCase):
    def test_install_source_comes_from_install_sh(self):
        values = {
            "ALLES_INSTALL_REPOSITORY": "jxherc/alles",
            "ALLES_INSTALL_BRANCH": "main",
            "ALLES_INSTALL_COMMIT": "AB" * 20,
        }
        with mock.patch.dict(cli.os.environ, values):
            self.assertEqual(
                cli._install_source_from_env(),
                {
                    "kind": "archive",
                    "repository": "jxherc/alles",
                    "branch": "main",
                    "commit": "ab" * 20,
                },
            )
        script = (ROOT / "install.sh").read_text("utf-8")
        for name in values:
            self.assertIn(name, script)

    def test_launcher_folder_goes_on_path_once(self):
        with tempfile.TemporaryDirectory(prefix="alles-home-") as directory:
            home = Path(directory)
            launcher = home / ".local" / "bin" / "alles"
            with (
                mock.patch.dict(
                    cli.os.environ, {"HOME": str(home), "SHELL": "/bin/zsh", "PATH": "/usr/bin"}
                ),
                mock.patch.object(cli.Path, "home", return_value=home),
            ):
                self.assertEqual(cli._put_launcher_on_path(launcher), home / ".zshrc")
                self.assertIsNone(cli._put_launcher_on_path(launcher))
            self.assertEqual((home / ".zshrc").read_text("utf-8").count(".local/bin"), 1)
            with mock.patch.dict(cli.os.environ, {"PATH": f"{launcher.parent}:/usr/bin"}):
                self.assertIsNone(cli._put_launcher_on_path(launcher))

    def test_the_installer_imports_on_plain_python(self):
        # install.sh runs `cli.py install` before alles has any packages; -S hides site-packages
        probe = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); import cli, services.native_install, services.cli_ui",
                str(ROOT),
            ],
            env={"PATH": os.environ.get("PATH", ""), "ALLES_DATA": tempfile.gettempdir()},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_install_sh_is_valid_sh(self):
        result = subprocess.run(
            ["sh", "-n", str(ROOT / "install.sh")], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class AccessCommandTest(unittest.TestCase):
    def _run(self, choice, *, settings, auth=False, passwords=()):
        saved = []
        with (
            mock.patch("core.settings.auth_enabled", return_value=auth),
            mock.patch("core.settings.load_settings", return_value=settings),
            mock.patch("core.settings.save_settings", side_effect=saved.append),
            mock.patch("core.auth.hash_password", side_effect=lambda pw: f"hashed:{pw}"),
            mock.patch("getpass.getpass", side_effect=list(passwords)),
            mock.patch.object(cli.sys.stdin, "isatty", return_value=True),
            mock.patch.object(cli, "_native_layout", return_value=None),
            mock.patch.object(cli, "_restart_for_settings", return_value=True),
            mock.patch.object(
                cli, "_reachable_addresses", return_value=[("100.64.0.9", "tailscale")]
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            ok = cli.cmd_access([choice])
        return ok, saved, output.getvalue()

    def test_lan_asks_for_a_password_then_opens_to_other_devices(self):
        ok, saved, text = self._run(
            "lan",
            settings={},
            passwords=("short", "short", "a-long-password-1", "a-long-password-1"),
        )
        self.assertTrue(ok)
        self.assertEqual(
            saved[0], {"auth_password_hash": "hashed:a-long-password-1", "auth_enabled": True}
        )
        self.assertEqual(saved[1]["access_profile"], "lan")
        self.assertIn("too short", text)
        self.assertIn("http://100.64.0.9:6769", text)

    def test_device_closes_it_again_without_asking(self):
        ok, saved, _ = self._run("device", settings={}, auth=True)
        self.assertTrue(ok)
        self.assertEqual(
            saved,
            [
                {
                    "access_profile": "device",
                    "public_url": "",
                    "base_domain": "",
                    "trusted_hosts": "",
                    "forwarded_allow_ips": "",
                }
            ],
        )


class ArchiveUpdateTest(unittest.TestCase):
    def _archive(self, commit):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz", pax_headers={"comment": commit}) as bundle:
            data = b"print('alles')\n"
            info = tarfile.TarInfo(f"alles-{commit}/app.py")
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
        return buffer.getvalue()

    def test_same_commit_means_up_to_date_and_a_new_one_is_unpacked(self):
        old, new = "a" * 40, "b" * 40
        source = {"kind": "archive", "repository": "jxherc/alles", "branch": "main", "commit": old}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with tempfile.TemporaryDirectory(prefix="alles-update-") as directory:
            update_dir = Path(directory)
            with mock.patch("urllib.request.urlopen", return_value=Response(old.encode())):
                self.assertEqual(
                    cli._fetch_native_update_source({"source": source}, update_dir), (None, old)
                )
            replies = [Response(new.encode()), Response(self._archive(new))]
            with mock.patch("urllib.request.urlopen", side_effect=replies):
                checkout, target = cli._fetch_native_update_source({"source": source}, update_dir)
            self.assertEqual(target, new)
            self.assertEqual((checkout / "app.py").read_text("utf-8"), "print('alles')\n")
            self.assertTrue(re.fullmatch(r"\.native-source-[0-9a-f]{32}", checkout.name))


class NativeRollbackResumeTest(unittest.TestCase):
    """A rollback that restored the data and then failed must not restore it a second time."""

    def test_a_retry_after_restoring_the_data_finishes_without_restoring_again(self):
        with tempfile.TemporaryDirectory(prefix="alles-rollback-") as directory:
            root = Path(directory)
            layout = SimpleNamespace(
                data_root=root / "data",
                releases=root / "releases",
                previous_release=root / "previous-release",
            )
            layout.data_root.mkdir()
            (layout.releases / "new").mkdir(parents=True)
            state_path = root / "state.json"
            state = {
                "kind": "native",
                "phase": "data_swapped",
                "update_id": "a" * 32,
                "old_release": "old",
                "new_release": "new",
                "old_commit": "b" * 40,
                "new_commit": "c" * 40,
            }
            discard = mock.Mock(
                side_effect=[native_install.NativeInstallError("release changed"), None]
            )
            restore = mock.Mock(return_value=True)
            with (
                mock.patch.object(cli, "_native_stop_service"),
                mock.patch.object(
                    native_install, "verify_install", return_value={"release_id": "old"}
                ),
                mock.patch.object(native_install, "discard_inactive_release", discard),
                mock.patch.object(cli, "_native_restore_update_data", restore),
                mock.patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertFalse(cli._native_rollback_update(layout, state, state_path))
                saved = json.loads(state_path.read_text("utf-8"))
                self.assertEqual(saved["phase"], "data_restored")
                self.assertTrue(cli._native_rollback_update(layout, saved, state_path))
            restore.assert_called_once()
            self.assertEqual(json.loads(state_path.read_text("utf-8"))["phase"], "rolled_back")


class NativeRollbackBookkeepingTest(unittest.TestCase):
    def test_a_rolled_back_update_operation_does_not_block_finishing(self):
        from services.backup_recovery import staging_root

        with tempfile.TemporaryDirectory(prefix="alles-bookkeeping-") as directory:
            live = Path(directory) / "data"
            live.mkdir()
            operations = staging_root(live) / "operations"
            operations.mkdir(parents=True)
            (operations / ("a" * 32 + ".json")).write_text(
                json.dumps({"state": "rolled_back"}), "utf-8"
            )
            state = {"update_id": "b" * 32, "operation_id": "a" * 32}
            layout = SimpleNamespace(data_root=live)
            (live / "lock").write_text("", "utf-8")
            with (
                mock.patch("services.restore_apply.discard_completed_restore") as discard,
                mock.patch("services.update_safety.update_lock_path", return_value=live / "lock"),
                mock.patch("services.update_safety.finish_update") as finish,
                mock.patch("sys.stdout", new_callable=io.StringIO),
            ):
                self.assertTrue(
                    cli._native_complete_rollback(layout, state, Path(directory) / "u" / "s.json")
                )
            discard.assert_not_called()
            finish.assert_called_once_with(live, "b" * 32)


class ReleaseProbeBytecodeTest(unittest.TestCase):
    """Checks that run a published release's python must not write bytecode into it."""

    def test_control_plane_probe_writes_no_bytecode(self):
        seen = {}

        def run(command, **kwargs):
            seen.update(kwargs["env"])
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory(prefix="alles-probe-") as directory:
            with mock.patch.object(cli.subprocess, "run", side_effect=run):
                cli._native_candidate_control_plane_ok(
                    Path(directory), Path("python"), Path(directory)
                )
        self.assertEqual(seen.get("PYTHONDONTWRITEBYTECODE"), "1")

    def test_boot_probe_writes_no_bytecode(self):
        seen = {}

        class Stop(Exception):
            pass

        def popen(command, **kwargs):
            seen.update(kwargs["env"])
            raise Stop

        with tempfile.TemporaryDirectory(prefix="alles-boot-") as directory:
            release = Path(directory) / "release"
            release.mkdir()
            (release / "app.py").write_text("", "utf-8")
            with (
                mock.patch.object(cli.subprocess, "Popen", side_effect=popen),
                self.assertRaises(Stop),
            ):
                cli._recovery_probe_once(Path(directory) / "data", app_root=release)
        self.assertEqual(seen.get("PYTHONDONTWRITEBYTECODE"), "1")


if __name__ == "__main__":
    unittest.main()
