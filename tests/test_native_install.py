import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import native_install


class NativeInstallLayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-native-install-")
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.home = self.home.resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_macos_layout_separates_runtime_data_and_visible_locations(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        self.assertEqual(
            layout.runtime_root,
            self.home / "Library" / "Application Support" / "Alles" / "runtime",
        )
        self.assertEqual(
            layout.data_root,
            self.home / "Library" / "Application Support" / "Alles" / "data",
        )
        self.assertEqual(layout.vault_default, self.home / "Alles" / "Vault")
        self.assertEqual(layout.files_default, self.home / "Alles" / "Files")
        self.assertEqual(layout.manager, "launchd")
        self.assertEqual(layout.unit, "app.alles.server")

    def test_linux_layout_honors_xdg_roots(self):
        data_home = (self.root / "xdg-data").resolve()
        config_home = (self.root / "xdg-config").resolve()
        layout = native_install.platform_layout(
            "Linux",
            home=self.home,
            xdg_data_home=data_home,
            xdg_config_home=config_home,
        )
        self.assertEqual(layout.runtime_root, data_home / "alles" / "runtime")
        self.assertEqual(layout.data_root, data_home / "alles" / "data")
        self.assertEqual(
            layout.service_definition,
            config_home / "systemd" / "user" / "alles-server.service",
        )
        self.assertEqual(layout.manager, "systemd-user")

    def test_linux_default_layout_reads_xdg_roots_from_the_environment(self):
        data_home = (self.root / "env-data").resolve()
        config_home = (self.root / "env-config").resolve()
        with (
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.dict(
                os.environ,
                {
                    "XDG_DATA_HOME": str(data_home),
                    "XDG_CONFIG_HOME": str(config_home),
                },
            ),
        ):
            layout = native_install.platform_layout("Linux")

        self.assertEqual(layout.support_root, data_home / "alles")
        self.assertEqual(
            layout.service_definition,
            config_home / "systemd" / "user" / "alles-server.service",
        )

    def test_linux_default_layout_ignores_relative_xdg_environment_roots(self):
        with (
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.dict(
                os.environ,
                {"XDG_DATA_HOME": "relative-data", "XDG_CONFIG_HOME": "relative-config"},
            ),
        ):
            layout = native_install.platform_layout("Linux")

        self.assertEqual(layout.support_root, self.home / ".local" / "share" / "alles")
        self.assertEqual(
            layout.service_definition,
            self.home / ".config" / "systemd" / "user" / "alles-server.service",
        )

    def test_linux_service_and_dispatcher_preserve_installed_xdg_roots(self):
        data_home = (self.root / "custom-data").resolve()
        config_home = (self.root / "custom-config").resolve()
        layout = native_install.platform_layout(
            "Linux",
            home=self.home,
            xdg_data_home=data_home,
            xdg_config_home=config_home,
        )

        service = native_install._service_source(layout).decode("utf-8")
        dispatcher = native_install._dispatcher_source(layout).decode("utf-8")

        self.assertIn(f'Environment=XDG_DATA_HOME="{data_home}"', service)
        self.assertIn(f'Environment=XDG_CONFIG_HOME="{config_home}"', service)
        self.assertIn("Environment=PORT=6769", service)
        self.assertIn(f"export XDG_DATA_HOME={data_home}", dispatcher)
        self.assertIn(f"export XDG_CONFIG_HOME={config_home}", dispatcher)
        self.assertIn("export PORT=6769", dispatcher)

    def test_macos_service_pins_the_native_port(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        service = native_install._service_source(layout).decode("utf-8")

        self.assertIn("<key>PORT</key><string>6769</string>", service)

    def test_linux_service_escapes_literal_percent_signs_in_paths(self):
        data_home = (self.root / "data%owner").resolve()
        config_home = (self.root / "config%owner").resolve()
        layout = native_install.platform_layout(
            "Linux",
            home=self.home,
            xdg_data_home=data_home,
            xdg_config_home=config_home,
        )

        service = native_install._service_source(layout).decode("utf-8")

        self.assertNotIn("data%owner", service)
        self.assertNotIn("config%owner", service)
        self.assertIn("data%%owner", service)
        self.assertIn("config%%owner", service)

    def test_unknown_platform_is_rejected(self):
        with self.assertRaisesRegex(native_install.NativeInstallError, "macOS and Linux"):
            native_install.platform_layout("Windows", home=self.home)

    def test_dispatcher_disables_bytecode_writes_for_the_sealed_release(self):
        layout = native_install.platform_layout("Linux", home=self.home)
        source = native_install._dispatcher_source(layout).decode("utf-8")
        self.assertIn('exec "$python" -B "$root/app.py"', source)
        self.assertIn('exec "$python" -B "$root/cli.py"', source)

    def test_macos_service_removal_accepts_an_already_unloaded_agent(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if command[1] == "bootout":
                return subprocess.CompletedProcess(
                    command, 3, "", "Boot-out failed: 3: No such process"
                )
            return subprocess.CompletedProcess(command, 113, "", "Could not find service in domain")

        native_install._disable_service(layout, runner)

        self.assertEqual([command[1] for command in calls], ["bootout", "print"])

    def test_clean_tracked_source_records_exact_update_authority(self):
        responses = ["a" * 40, "origin/main", "", "https://example.test/alles.git"]
        with mock.patch.object(native_install, "_git_text", side_effect=responses):
            result = native_install.source_metadata(self.root)
        self.assertEqual(
            result,
            {
                "kind": "git",
                "url": "https://example.test/alles.git",
                "branch": "main",
                "commit": "a" * 40,
            },
        )

    def test_source_metadata_fails_closed_when_cleanliness_cannot_be_checked(self):
        responses = ["a" * 40, "origin/main", None]
        with mock.patch.object(native_install, "_git_text", side_effect=responses):
            self.assertEqual(native_install.source_metadata(self.root), {"kind": "unavailable"})


class NativeInstallLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-native-lifecycle-")
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.home = self.home.resolve()
        self.layout = native_install.platform_layout("Linux", home=self.home)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in ("app.py", "cli.py", "requirements.txt", "requirements.lock"):
            (self.source / name).write_text(f"# {name}\n", "utf-8")
        (self.source / "core").mkdir()
        (self.source / "core" / "__init__.py").write_text("", "utf-8")
        self.commands = []
        self.home_patch = mock.patch.object(
            native_install.service_manager, "_home_dir", return_value=self.home
        )
        self.home_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def _result(returncode=0, stdout=""):
        return subprocess.CompletedProcess([], returncode, stdout, "")

    def _runner(self, command, **_kwargs):
        self.commands.append(list(command))
        return self._result()

    def _builder(self, source, destination):
        destination.mkdir(parents=True)
        for item in source.iterdir():
            if item.is_dir():
                target = destination / item.name
                target.mkdir()
                for child in item.iterdir():
                    (target / child.name).write_bytes(child.read_bytes())
            else:
                (destination / item.name).write_bytes(item.read_bytes())
        python = destination / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        (destination / ".venv" / "pyvenv.cfg").write_text("home = test\n", "utf-8")
        python.write_text("#!/bin/sh\nexit 0\n", "utf-8")
        python.chmod(0o755)
        return python

    def _symlink_builder(self, source, destination):
        python = self._builder(source, destination)
        target = python.with_name("python3")
        python.replace(target)
        python.symlink_to(target.name)
        return python

    def test_standard_venv_python_symlink_is_accepted(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            result = native_install.install(
                self.source,
                self.layout,
                release_id="symlink-venv",
                release_builder=self._symlink_builder,
                release_probe=lambda _release, _python: True,
                install_source={"kind": "unavailable"},
                runner=self._runner,
            )

        self.assertEqual(result["release_id"], "symlink-venv")
        installed_python = self.layout.releases / "symlink-venv" / ".venv" / "bin" / "python"
        self.assertTrue(installed_python.is_symlink())
        self.assertTrue(installed_python.is_file())

    def test_default_release_builder_never_dereferences_source_symlinks(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "private.txt").write_text("owner data", "utf-8")
        link = self.source / "core" / "outside-link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        destination = self.root / "unsafe-stage"

        with (
            mock.patch("services.credits.verify_release_notice_set"),
            self.assertRaisesRegex(native_install.NativeInstallError, "unsafe symlink"),
        ):
            native_install.build_release(self.source, destination)

        copied_link = destination / "core" / "outside-link"
        self.assertTrue(copied_link.is_symlink())
        self.assertEqual(os.readlink(copied_link), str(outside))
        self.assertEqual((outside / "private.txt").read_text("utf-8"), "owner data")

    def test_clean_install_writes_owned_release_launcher_and_service(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            result = native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                install_source={"kind": "unavailable"},
                runner=self._runner,
            )

        self.assertEqual(result["release_id"], "test-1")
        manifest = json.loads(self.layout.manifest.read_text("utf-8"))
        self.assertEqual(manifest["data_root"], str(self.layout.data_root))
        self.assertEqual(manifest["source"], {"kind": "unavailable"})
        self.assertEqual(self.layout.current_release.read_text("utf-8").strip(), "test-1")
        self.assertTrue((self.layout.releases / "test-1" / ".alles-owned-release.json").is_file())
        self.assertTrue(self.layout.launcher.is_file())
        self.assertTrue(self.layout.service_definition.is_file())
        self.assertTrue((self.layout.service_root / ".alles-owned-service.json").is_file())
        self.assertFalse(self.layout.vault_default.exists())
        self.assertFalse(self.layout.files_default.exists())
        self.assertIn(
            ["systemctl", "--user", "enable", "--now", "alles-server.service"],
            self.commands,
        )

    def test_install_rejects_a_symlinked_native_data_directory(self):
        outside = self.root / "outside-data"
        outside.mkdir()
        self.layout.data_root.parent.mkdir(parents=True)
        try:
            self.layout.data_root.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        with (
            mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}),
            self.assertRaisesRegex(native_install.NativeInstallError, "unsafe data root"),
        ):
            native_install.install(
                self.source,
                self.layout,
                release_id="unsafe-data-root",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                install_source={"kind": "unavailable"},
                runner=self._runner,
            )

        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(self.layout.manifest.exists())

    def test_install_rejects_incomplete_git_source_before_publishing(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            with self.assertRaisesRegex(native_install.NativeInstallError, "source metadata"):
                native_install.install(
                    self.source,
                    self.layout,
                    release_id="invalid-source",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "git", "url": "https://example.test/alles.git"},
                    runner=self._runner,
                )

        self.assertFalse(self.layout.manifest.exists())
        self.assertFalse(self.layout.launcher.exists())
        self.assertFalse(self.layout.service_definition.exists())
        self.assertNotIn(
            ["systemctl", "--user", "enable", "--now", "alles-server.service"],
            self.commands,
        )

    def test_install_refuses_an_unowned_launcher(self):
        self.layout.launcher.parent.mkdir(parents=True)
        self.layout.launcher.write_text("owner script", "utf-8")
        with self.assertRaisesRegex(native_install.NativeInstallError, "launcher"):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
        self.assertEqual(self.layout.launcher.read_text("utf-8"), "owner script")

    def test_install_refuses_preexisting_release_pointers(self):
        self.layout.runtime_root.mkdir(parents=True)
        for path, label in (
            (self.layout.current_release, "current release pointer"),
            (self.layout.previous_release, "previous release pointer"),
        ):
            with self.subTest(label=label):
                path.write_text("unowned\n", "utf-8")
                with self.assertRaisesRegex(native_install.NativeInstallError, label):
                    native_install.install(
                        self.source,
                        self.layout,
                        release_id="test-1",
                        release_builder=self._builder,
                        release_probe=lambda _release, _python: True,
                        runner=self._runner,
                    )
                path.unlink()

    def test_install_rejects_symlinked_staging_before_running_builder(self):
        self.layout.runtime_root.mkdir(parents=True, mode=0o700)
        outside = self.root / "outside-stage"
        outside.mkdir()
        sentinel = outside / "owner.txt"
        sentinel.write_text("keep", "utf-8")
        self.layout.staging.symlink_to(outside, target_is_directory=True)
        builder = mock.Mock(side_effect=AssertionError("builder must not run"))

        with self.assertRaisesRegex(native_install.NativeInstallError, "staging"):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )

        builder.assert_not_called()
        self.assertEqual(sentinel.read_text("utf-8"), "keep")

    def test_failed_probe_publishes_nothing_and_preserves_data(self):
        self.layout.data_root.mkdir(parents=True)
        private = self.layout.data_root / "private.txt"
        private.write_text("keep", "utf-8")
        with self.assertRaisesRegex(native_install.NativeInstallError, "health probe"):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: False,
                runner=self._runner,
            )
        self.assertEqual(private.read_text("utf-8"), "keep")
        self.assertFalse(self.layout.manifest.exists())
        self.assertFalse(self.layout.launcher.exists())
        self.assertFalse(self.layout.service_definition.exists())

    def test_failed_service_enable_always_attempts_idempotent_disable(self):
        with (
            mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}),
            mock.patch.object(
                native_install,
                "_enable_service",
                side_effect=native_install._ServiceEnableError("start", acquired=True),
            ),
            mock.patch.object(native_install, "_disable_service") as disable,
        ):
            with self.assertRaisesRegex(native_install.NativeInstallError, "start"):
                native_install.install(
                    self.source,
                    self.layout,
                    release_id="partial-service",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=self._runner,
                )
        disable.assert_called_once_with(self.layout, self._runner)

    def test_failed_service_disable_preserves_the_owned_install_for_recovery(self):
        with (
            mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}),
            mock.patch.object(
                native_install,
                "_enable_service",
                side_effect=native_install._ServiceEnableError("start", acquired=True),
            ),
            mock.patch.object(
                native_install,
                "_disable_service",
                side_effect=native_install.NativeInstallError("disable"),
            ),
        ):
            with self.assertRaisesRegex(native_install.NativeInstallError, "start"):
                native_install.install(
                    self.source,
                    self.layout,
                    release_id="disable-blocked",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=self._runner,
                )

        self.assertTrue(self.layout.manifest.is_file())
        self.assertTrue(self.layout.launcher.is_file())
        self.assertTrue(self.layout.service_definition.is_file())
        self.assertTrue((self.layout.releases / "disable-blocked").is_dir())

    def test_failed_install_preserves_owned_record_when_release_cleanup_cannot_finish(self):
        original_remove = native_install._remove_owned_release

        def refuse_release_cleanup(path):
            if path == self.layout.releases / "cleanup-blocked":
                raise native_install.NativeInstallError("release ownership changed")
            return original_remove(path)

        with (
            mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}),
            mock.patch.object(
                native_install,
                "_enable_service",
                side_effect=native_install._ServiceEnableError(
                    "original start failure", acquired=True
                ),
            ),
            mock.patch.object(native_install, "_disable_service"),
            mock.patch.object(
                native_install,
                "_remove_owned_release",
                side_effect=refuse_release_cleanup,
            ),
        ):
            with self.assertRaisesRegex(
                native_install.NativeInstallError, "original start failure"
            ):
                native_install.install(
                    self.source,
                    self.layout,
                    release_id="cleanup-blocked",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=self._runner,
                )

        self.assertTrue(self.layout.manifest.is_file())
        self.assertTrue(self.layout.launcher.is_file())
        self.assertTrue((self.layout.releases / "cleanup-blocked").is_dir())
        manifest = json.loads(self.layout.manifest.read_text("utf-8"))
        self.assertTrue(manifest["uninstalling"])
        self.assertTrue(manifest["service_disabled"])
        self.assertTrue(manifest["service_unregistered"])
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            result = native_install.uninstall_keep_data(self.layout, runner=self._runner)
        self.assertTrue(result["data_kept"])

    def test_failed_launchd_bootstrap_cleans_up_a_job_found_by_the_probe(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        commands = []
        print_count = 0

        def runner(command, **_kwargs):
            nonlocal print_count
            commands.append(list(command))
            if command[1] == "print":
                print_count += 1
                if print_count == 1:
                    return self._result(113, "Could not find service")
                return self._result(0, "service = loaded")
            return self._result(5 if command[1] == "bootstrap" else 0)

        with mock.patch.dict(os.environ, {"ALLES_DATA": str(layout.data_root)}):
            with self.assertRaisesRegex(native_install.NativeInstallError, "service install"):
                native_install.install(
                    self.source,
                    layout,
                    release_id="bootstrap-failed",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=runner,
                )

        self.assertEqual(
            [command[1] for command in commands],
            ["print", "bootstrap", "print", "bootout"],
        )

    def test_failed_launchd_bootstrap_leaves_a_definitively_absent_job_alone(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        commands = []

        def runner(command, **_kwargs):
            commands.append(list(command))
            if command[1] == "bootstrap":
                return self._result(5)
            if command[1] == "print":
                return self._result(113, "Could not find service")
            return self._result()

        with mock.patch.dict(os.environ, {"ALLES_DATA": str(layout.data_root)}):
            with self.assertRaisesRegex(native_install.NativeInstallError, "service install"):
                native_install.install(
                    self.source,
                    layout,
                    release_id="bootstrap-absent",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=runner,
                )

        self.assertEqual([command[1] for command in commands], ["print", "bootstrap", "print"])

    def test_install_never_boots_out_a_preexisting_launchd_job(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        commands = []

        def runner(command, **_kwargs):
            commands.append(list(command))
            return self._result(0, "service = preexisting")

        with mock.patch.dict(os.environ, {"ALLES_DATA": str(layout.data_root)}):
            with self.assertRaisesRegex(native_install.NativeInstallError, "already exists"):
                native_install.install(
                    self.source,
                    layout,
                    release_id="preexisting-service",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=runner,
                )

        self.assertEqual([command[1] for command in commands], ["print"])

    def test_timed_out_launchd_preflight_does_not_touch_an_unknown_service(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        commands = []

        def runner(command, **_kwargs):
            commands.append(list(command))
            if command[1] == "print":
                raise subprocess.TimeoutExpired(command, 60)
            return self._result()

        with mock.patch.dict(os.environ, {"ALLES_DATA": str(layout.data_root)}):
            with self.assertRaisesRegex(native_install.NativeInstallError, "service preflight"):
                native_install.install(
                    self.source,
                    layout,
                    release_id="bootstrap-uncertain",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=runner,
                )

        self.assertEqual([command[1] for command in commands], ["print"])

    def test_failed_launchd_start_disables_the_acquired_service(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        commands = []

        def runner(command, **_kwargs):
            commands.append(list(command))
            return self._result(5 if command[1] == "kickstart" else 0)

        with mock.patch.dict(os.environ, {"ALLES_DATA": str(layout.data_root)}):
            with self.assertRaisesRegex(native_install.NativeInstallError, "service start"):
                native_install.install(
                    self.source,
                    layout,
                    release_id="kickstart-failed",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=runner,
                )

        self.assertEqual(
            [command[1] for command in commands],
            ["print", "bootstrap", "kickstart", "bootout"],
        )

    def test_failed_linux_reload_cleans_up_without_disabling_an_unacquired_service(self):
        commands = []

        def runner(command, **_kwargs):
            commands.append(list(command))
            if command[-1] == "daemon-reload":
                return self._result(1)
            return self._result()

        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            with self.assertRaisesRegex(native_install.NativeInstallError, "service reload"):
                native_install.install(
                    self.source,
                    self.layout,
                    release_id="reload-failed",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: True,
                    install_source={"kind": "unavailable"},
                    runner=runner,
                )

        self.assertFalse(any("disable" in command for command in commands))
        self.assertFalse(self.layout.manifest.exists())
        self.assertFalse(self.layout.launcher.exists())
        self.assertFalse((self.layout.releases / "reload-failed").exists())

    def test_uninstall_removes_only_owned_program_files_and_keeps_data(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            private = self.layout.data_root / "private.txt"
            private.write_text("keep", "utf-8")
            self.layout.vault_default.mkdir(parents=True)
            (self.layout.vault_default / "note.md").write_text("keep", "utf-8")
            result = native_install.uninstall_keep_data(self.layout, runner=self._runner)

        self.assertTrue(result["data_kept"])
        self.assertEqual(private.read_text("utf-8"), "keep")
        self.assertEqual((self.layout.vault_default / "note.md").read_text("utf-8"), "keep")
        self.assertFalse(self.layout.runtime_root.exists())
        self.assertFalse(self.layout.launcher.exists())
        self.assertFalse(self.layout.service_definition.exists())
        self.assertEqual(
            self.commands[-1],
            ["systemctl", "--user", "daemon-reload"],
        )

    def test_uninstall_resumes_after_the_post_removal_service_reload_fails(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-resume-uninstall",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            reloads = 0
            disable_calls = 0

            def interrupted_runner(command, **_kwargs):
                nonlocal disable_calls, reloads
                if "disable" in command:
                    disable_calls += 1
                if command[-1] == "daemon-reload":
                    reloads += 1
                    if reloads == 2:
                        return self._result(returncode=1)
                return self._result()

            with self.assertRaisesRegex(native_install.NativeInstallError, "service reload"):
                native_install.uninstall_keep_data(self.layout, runner=interrupted_runner)

            self.assertFalse(self.layout.service_definition.exists())
            manifest = json.loads(self.layout.manifest.read_text("utf-8"))
            self.assertTrue(manifest["uninstalling"])
            result = native_install.uninstall_keep_data(self.layout, runner=self._runner)

        self.assertTrue(result["data_kept"])
        self.assertEqual(disable_calls, 1)
        self.assertFalse(self.layout.runtime_root.exists())

    def test_uninstall_retry_keeps_failing_closed_when_service_ownership_is_unproven(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-unregister-ownership",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            ownership_error = native_install.service_manager.ServiceOwnershipError(
                "service registry is no longer trusted"
            )
            with mock.patch.object(
                native_install.service_manager,
                "unregister_owned_service",
                side_effect=ownership_error,
            ):
                with self.assertRaisesRegex(
                    native_install.service_manager.ServiceOwnershipError,
                    "registry is no longer trusted",
                ):
                    native_install.uninstall_keep_data(self.layout, runner=self._runner)
                with self.assertRaisesRegex(
                    native_install.service_manager.ServiceOwnershipError,
                    "registry is no longer trusted",
                ):
                    native_install.uninstall_keep_data(self.layout, runner=self._runner)

        manifest = json.loads(self.layout.manifest.read_text("utf-8"))
        self.assertTrue(manifest["service_unregister_started"])
        self.assertNotIn("service_unregistered", manifest)
        self.assertTrue(self.layout.launcher.exists())
        self.assertTrue(self.layout.service_definition.exists())
        self.assertTrue(self.layout.releases.joinpath("test-unregister-ownership").exists())

    def test_uninstall_refuses_a_changed_current_release_pointer(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            self.layout.current_release.write_text("other-release\n", "utf-8")

            with self.assertRaisesRegex(
                native_install.NativeInstallError, "current release pointer"
            ):
                native_install.uninstall_keep_data(self.layout, runner=self._runner)

        self.assertTrue(self.layout.manifest.exists())
        self.assertTrue(self.layout.service_definition.exists())
        self.assertTrue(self.layout.releases.joinpath("test-1").exists())

    def test_uninstall_removes_owned_empty_release_directories(self):
        def builder(source, destination):
            python = self._builder(source, destination)
            (destination / ".venv" / "include" / "empty").mkdir(parents=True)
            return python

        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-empty",
                release_builder=builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.uninstall_keep_data(self.layout, runner=self._runner)

        self.assertFalse(self.layout.runtime_root.exists())

    def test_uninstall_reconciles_an_interrupted_release_activation(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            with (
                mock.patch.object(native_install, "_save_active_release", side_effect=SystemExit),
                self.assertRaises(SystemExit),
            ):
                native_install.activate_release(self.layout, "test-2")
            journal = self.layout.runtime_root / native_install._RELEASE_TRANSACTION
            self.assertTrue(journal.exists())

            native_install.uninstall_keep_data(self.layout, runner=self._runner)

        self.assertFalse(journal.exists())
        self.assertFalse(self.layout.runtime_root.exists())

    def test_uninstall_removes_a_verified_staged_candidate(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            staged = native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            self.assertTrue(staged.is_dir())
            native_install.uninstall_keep_data(self.layout, runner=self._runner)

        self.assertFalse(self.layout.runtime_root.exists())

    def test_uninstall_refuses_tampered_launcher_without_removing_anything(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            self.layout.launcher.write_text("tampered", "utf-8")
            with self.assertRaisesRegex(native_install.NativeInstallError, "launcher changed"):
                native_install.uninstall_keep_data(self.layout, runner=self._runner)

        self.assertTrue(self.layout.runtime_root.exists())
        self.assertTrue(self.layout.service_definition.exists())
        self.assertEqual(self.layout.launcher.read_text("utf-8"), "tampered")

    def test_verify_rejects_a_file_added_outside_the_release_manifest(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
        injected = self.layout.releases / "test-1" / ".venv" / "lib" / "site-packages"
        injected.mkdir(parents=True)
        (injected / "sitecustomize.py").write_text("raise SystemExit\n", "utf-8")

        with self.assertRaisesRegex(native_install.NativeInstallError, "contents changed"):
            native_install.verify_install(self.layout)

    def test_stage_activate_rollback_and_accept_release(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            staged = native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            self.assertEqual(staged.name, "test-2")
            native_install.activate_release(self.layout, "test-2")
            self.assertEqual(self.layout.current_release.read_text().strip(), "test-2")
            self.assertEqual(self.layout.previous_release.read_text().strip(), "test-1")
            self.assertEqual(
                json.loads(self.layout.manifest.read_text())["release_id"],
                "test-2",
            )

            restored = native_install.rollback_release(self.layout)
            self.assertEqual(restored, "test-1")
            self.assertEqual(self.layout.current_release.read_text().strip(), "test-1")
            self.assertEqual(self.layout.previous_release.read_text().strip(), "test-2")

            self.assertEqual(native_install.rollback_release(self.layout), "test-2")
            removed = native_install.accept_release(self.layout)

        self.assertEqual(removed, "test-1")
        self.assertFalse((self.layout.releases / "test-1").exists())
        self.assertTrue((self.layout.releases / "test-2").exists())
        self.assertFalse(self.layout.previous_release.exists())

    def test_rollback_restores_the_previous_release_source_commit(self):
        old_commit = "a" * 40
        new_commit = "b" * 40
        source = {
            "kind": "git",
            "url": "https://example.test/alles.git",
            "branch": "main",
            "commit": old_commit,
        }
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                install_source=source,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id=new_commit,
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            native_install.activate_release(self.layout, new_commit, source_commit=new_commit)
            native_install.rollback_release(self.layout)

        manifest = json.loads(self.layout.manifest.read_text("utf-8"))
        self.assertEqual(manifest["release_id"], "test-1")
        self.assertEqual(manifest["source"]["commit"], old_commit)
        self.assertEqual(manifest["release_commits"]["test-1"], old_commit)
        self.assertEqual(manifest["release_commits"][new_commit], new_commit)

    def test_verify_recovers_activation_interrupted_before_manifest_publish(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            with (
                mock.patch.object(native_install, "_save_active_release", side_effect=SystemExit),
                self.assertRaises(SystemExit),
            ):
                native_install.activate_release(self.layout, "test-2")

            self.assertTrue(
                (self.layout.runtime_root / native_install._RELEASE_TRANSACTION).is_file()
            )
            recovered = native_install.verify_install(self.layout)

        self.assertEqual(recovered["release_id"], "test-2")
        self.assertEqual(self.layout.current_release.read_text().strip(), "test-2")
        self.assertEqual(self.layout.previous_release.read_text().strip(), "test-1")
        self.assertFalse((self.layout.runtime_root / native_install._RELEASE_TRANSACTION).exists())

    def test_accept_release_resumes_after_the_previous_tree_was_removed(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            native_install.activate_release(self.layout, "test-2")
            native_install._remove_owned_release(self.layout.releases / "test-1")

            removed = native_install.accept_release(self.layout, expected_previous="test-1")

        self.assertEqual(removed, "test-1")
        self.assertFalse(self.layout.previous_release.exists())

    def test_accept_release_resumes_after_quarantined_file_removal_is_interrupted(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            native_install.activate_release(self.layout, "test-2")
            original_unlink = Path.unlink
            removed_one = False

            def interrupted_unlink(path, *args, **kwargs):
                nonlocal removed_one
                if ".remove-test-1" in path.parts and path.name != native_install._RELEASE_FILES:
                    if removed_one:
                        raise SystemExit("simulated interruption")
                    removed_one = True
                return original_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "unlink", new=interrupted_unlink),
                self.assertRaisesRegex(SystemExit, "simulated interruption"),
            ):
                native_install.accept_release(self.layout)

            journal = self.layout.runtime_root / native_install._RELEASE_REMOVAL
            quarantine = self.layout.staging / ".remove-test-1"
            self.assertTrue(journal.is_file())
            self.assertTrue(quarantine.is_dir())
            self.assertFalse((self.layout.releases / "test-1").exists())

            removed = native_install.accept_release(
                self.layout,
                expected_previous="test-1",
            )

        self.assertEqual(removed, "test-1")
        self.assertFalse(journal.exists())
        self.assertFalse(quarantine.exists())
        self.assertFalse(self.layout.previous_release.exists())

    def test_accept_release_reconciles_a_removed_previous_tree_without_an_expected_id(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            native_install.activate_release(self.layout, "test-2")
            journal = self.layout.runtime_root / native_install._RELEASE_REMOVAL
            original_unlink = Path.unlink

            def interrupt_journal_removal(path, *args, **kwargs):
                if path == journal:
                    raise SystemExit("simulated journal interruption")
                return original_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "unlink", new=interrupt_journal_removal),
                self.assertRaisesRegex(SystemExit, "simulated journal interruption"),
            ):
                native_install.accept_release(self.layout)

            self.assertTrue(journal.is_file())
            self.assertFalse((self.layout.releases / "test-1").exists())
            removed = native_install.accept_release(self.layout)

        self.assertEqual(removed, "test-1")
        self.assertFalse(journal.exists())
        self.assertFalse(self.layout.previous_release.exists())

    def test_accept_release_resumes_after_tree_removal_before_pointer_unlink(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            native_install.activate_release(self.layout, "test-2")
            original_unlink = Path.unlink

            def interrupt_pointer_unlink(path, *args, **kwargs):
                if path == self.layout.previous_release:
                    raise SystemExit("simulated pointer interruption")
                return original_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "unlink", new=interrupt_pointer_unlink),
                self.assertRaisesRegex(SystemExit, "simulated pointer interruption"),
            ):
                native_install.accept_release(self.layout)

            journal = self.layout.runtime_root / native_install._RELEASE_REMOVAL
            self.assertTrue(journal.is_file())
            self.assertFalse((self.layout.releases / "test-1").exists())
            self.assertEqual(self.layout.previous_release.read_text().strip(), "test-1")

            removed = native_install.accept_release(self.layout)

        self.assertEqual(removed, "test-1")
        self.assertFalse(journal.exists())
        self.assertFalse(self.layout.previous_release.exists())

    def test_uninstall_reconciles_accepted_release_removed_before_pointer_unlink(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            native_install.activate_release(self.layout, "test-2")
            original_unlink = Path.unlink

            def interrupt_pointer_unlink(path, *args, **kwargs):
                if path == self.layout.previous_release:
                    raise SystemExit("simulated pointer interruption")
                return original_unlink(path, *args, **kwargs)

            with (
                mock.patch.object(Path, "unlink", new=interrupt_pointer_unlink),
                self.assertRaisesRegex(SystemExit, "simulated pointer interruption"),
            ):
                native_install.accept_release(self.layout)

            journal = self.layout.runtime_root / native_install._RELEASE_REMOVAL
            self.assertTrue(journal.is_file())
            self.assertFalse((self.layout.releases / "test-1").exists())
            self.assertEqual(self.layout.previous_release.read_text().strip(), "test-1")

            result = native_install.uninstall_keep_data(self.layout, runner=self._runner)

        self.assertTrue(result["data_kept"])
        self.assertFalse(journal.exists())
        self.assertFalse(self.layout.runtime_root.exists())

    def test_activation_restores_manifest_after_a_post_commit_manifest_error(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            original = native_install._save_active_release

            def committed_then_failed(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("directory fsync failed")

            with (
                mock.patch.object(
                    native_install,
                    "_save_active_release",
                    side_effect=committed_then_failed,
                ),
                self.assertRaisesRegex(OSError, "directory fsync failed"),
            ):
                native_install.activate_release(self.layout, "test-2")

        self.assertEqual(self.layout.current_release.read_text().strip(), "test-1")
        self.assertFalse(self.layout.previous_release.exists())
        self.assertEqual(json.loads(self.layout.manifest.read_text())["release_id"], "test-1")

    def test_rollback_restores_manifest_after_a_post_commit_manifest_error(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            native_install.activate_release(self.layout, "test-2")
            original = native_install._save_active_release

            def committed_then_failed(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("directory fsync failed")

            with (
                mock.patch.object(
                    native_install,
                    "_save_active_release",
                    side_effect=committed_then_failed,
                ),
                self.assertRaisesRegex(OSError, "directory fsync failed"),
            ):
                native_install.rollback_release(self.layout)

        self.assertEqual(self.layout.current_release.read_text().strip(), "test-2")
        self.assertEqual(self.layout.previous_release.read_text().strip(), "test-1")
        self.assertEqual(json.loads(self.layout.manifest.read_text())["release_id"], "test-2")

    def test_activation_keeps_journal_when_manifest_restore_fails(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            original_atomic_json = native_install._atomic_json

            def fail_source_manifest_restore(path, value, *args, **kwargs):
                if path == self.layout.manifest and value.get("release_id") == "test-1":
                    raise OSError("manifest restore failed")
                return original_atomic_json(path, value, *args, **kwargs)

            with (
                mock.patch.object(
                    native_install,
                    "_save_active_release",
                    side_effect=OSError("manifest publish failed"),
                ),
                mock.patch.object(
                    native_install,
                    "_atomic_json",
                    side_effect=fail_source_manifest_restore,
                ),
                self.assertRaisesRegex(OSError, "manifest restore failed"),
            ):
                native_install.activate_release(self.layout, "test-2")

            journal = self.layout.runtime_root / native_install._RELEASE_TRANSACTION
            self.assertTrue(journal.is_file())
            recovered = native_install.verify_install(self.layout)

        self.assertEqual(recovered["release_id"], "test-1")
        self.assertFalse(journal.exists())

    def test_rollback_keeps_journal_when_manifest_restore_fails(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            native_install.stage_update_release(
                self.source,
                self.layout,
                release_id="test-2",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
            )
            native_install.activate_release(self.layout, "test-2")
            original_atomic_json = native_install._atomic_json

            def fail_source_manifest_restore(path, value, *args, **kwargs):
                if path == self.layout.manifest and value.get("release_id") == "test-2":
                    raise OSError("manifest restore failed")
                return original_atomic_json(path, value, *args, **kwargs)

            with (
                mock.patch.object(
                    native_install,
                    "_save_active_release",
                    side_effect=OSError("manifest publish failed"),
                ),
                mock.patch.object(
                    native_install,
                    "_atomic_json",
                    side_effect=fail_source_manifest_restore,
                ),
                self.assertRaisesRegex(OSError, "manifest restore failed"),
            ):
                native_install.rollback_release(self.layout)

            journal = self.layout.runtime_root / native_install._RELEASE_TRANSACTION
            self.assertTrue(journal.is_file())
            recovered = native_install.verify_install(self.layout)

        self.assertEqual(recovered["release_id"], "test-2")
        self.assertFalse(journal.exists())

    def test_release_removal_rejects_a_symlinked_directory_ancestor(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
        release = self.layout.releases / "test-1"
        external = self.root / "relocated-venv"
        (release / ".venv").rename(external)
        (release / ".venv").symlink_to(external, target_is_directory=True)

        with self.assertRaisesRegex(native_install.NativeInstallError, "contents changed"):
            native_install._remove_owned_release(release)

        self.assertTrue((external / "bin" / "python").is_file())

    def test_failed_update_probe_keeps_current_release_untouched(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            with self.assertRaisesRegex(native_install.NativeInstallError, "health probe"):
                native_install.stage_update_release(
                    self.source,
                    self.layout,
                    release_id="test-2",
                    release_builder=self._builder,
                    release_probe=lambda _release, _python: False,
                )

        self.assertEqual(self.layout.current_release.read_text().strip(), "test-1")
        self.assertFalse((self.layout.releases / "test-2").exists())
        self.assertFalse(self.layout.previous_release.exists())

    def test_stage_update_refuses_a_pending_release_removal_journal(self):
        with mock.patch.dict(os.environ, {"ALLES_DATA": str(self.layout.data_root)}):
            native_install.install(
                self.source,
                self.layout,
                release_id="test-1",
                release_builder=self._builder,
                release_probe=lambda _release, _python: True,
                runner=self._runner,
            )
            with (
                mock.patch.object(
                    native_install,
                    "_load_release_removal",
                    return_value={"release_id": "test-2", "phase": "quarantined"},
                ),
                mock.patch.object(native_install, "build_release") as builder,
                self.assertRaisesRegex(
                    native_install.NativeInstallError,
                    "finish the interrupted release removal",
                ),
            ):
                native_install.stage_update_release(
                    self.source,
                    self.layout,
                    release_id="test-2",
                    release_builder=builder,
                    release_probe=lambda _release, _python: True,
                )

        builder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
