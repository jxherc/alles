import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cli
from services import cli_ui, native_install
from services.backup_recovery import EXTERNAL_VAULT_SUBPATH


class StatusReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-cli-status-")
        self.root = Path(self.tmp.name)
        self.layout = native_install.platform_layout("Linux", home=self.root)
        self.layout.runtime_root.mkdir(parents=True)
        self.layout.data_root.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self, commit="a" * 40):
        return {
            "release_id": commit,
            "source": {
                "kind": "archive",
                "repository": "jxherc/alles",
                "branch": "main",
                "commit": commit,
            },
            "release_commits": {commit: commit},
        }

    def test_status_names_the_release_and_the_way_back_from_the_last_update(self):
        new, old = "b" * 40, "a" * 40
        (self.layout.releases / new).mkdir(parents=True)
        (self.layout.releases / new / ".alles-owned-release.json").write_text("{}")
        self.layout.current_release.write_text(new + "\n")
        self.layout.previous_release.write_text(old + "\n")
        state_path = cli._native_update_state_path(self.layout.data_root.resolve())
        state_path.parent.mkdir(parents=True, exist_ok=True)
        cli._write_update_state(
            state_path,
            {
                "kind": "native",
                "phase": "applied",
                "update_id": "e" * 32,
                "old_release": old,
                "new_release": new,
                "old_commit": old,
                "new_commit": new,
                "was_running": True,
            },
        )
        with (
            mock.patch.object(cli, "_native_layout", return_value=self.layout),
            mock.patch.object(native_install, "_load_manifest", return_value=self._manifest(new)),
            mock.patch.object(native_install, "latest_release_commit", return_value="c" * 40),
            mock.patch(
                "services.service_manager.status",
                return_value={"available": True, "running": True},
            ),
            mock.patch.object(cli, "_health_ok", return_value=True),
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            self.assertTrue(cli.cmd_status())

        text = output.getvalue()
        self.assertIn("release bbbbbbb · installed ", text)
        self.assertIn("bbbbbbb is on; alles update rollback goes back to aaaaaaa", text)
        # keeping an update is not a job for the owner: the next update does it
        self.assertNotIn("alles update accept", text)
        self.assertIn("ccccccc is ready: alles update", text)
        self.assertIn("jxherc/alles main", text)
        self.assertNotIn("\033[", text)  # piped output stays plain

    def test_a_service_that_keeps_dying_is_not_called_running_or_stopped(self):
        # nov 5: after a reboot macOS kept the service off the external drive; launchd started it
        # 461 times and status said "running"
        commit = "b" * 40
        (self.layout.releases / commit).mkdir(parents=True)
        self.layout.current_release.write_text(commit + "\n")
        with (
            mock.patch.object(cli, "_native_layout", return_value=self.layout),
            mock.patch.object(
                native_install, "_load_manifest", return_value=self._manifest(commit)
            ),
            mock.patch.object(native_install, "latest_release_commit", return_value=commit),
            mock.patch(
                "services.service_manager.status",
                return_value={"available": True, "running": False, "starts": 461, "last_exit": 1},
            ),
            mock.patch.object(cli, "_health_ok", return_value=False),
            mock.patch.object(cli, "_on_mac_drive", return_value=True),
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            cli.cmd_status()
        text = output.getvalue()
        self.assertIn("not starting", text)
        self.assertIn("exits right away (exit 1, 461 starts)", text)
        # an install from before the drive launcher: restart puts it in, then macOS asks
        self.assertIn("run alles restart, then click Allow for alles-server", text)
        self.assertNotIn("start it with", text)

    def test_an_update_stopped_halfway_says_how_to_roll_back(self):
        state_path = cli._native_update_state_path(self.layout.data_root.resolve())
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("not json")
        with mock.patch.object(native_install, "update_check", return_value={"waiting": False}):
            lines = cli._native_update_lines(self.layout)
        self.assertEqual(
            lines, [(False, "update", "an update stopped halfway: alles update rollback")]
        )

    def test_the_update_check_asks_at_most_every_six_hours_and_never_installs(self):
        manifest = self._manifest()
        with (
            mock.patch.object(native_install, "_load_manifest", return_value=manifest),
            mock.patch.object(
                native_install, "latest_release_commit", return_value="d" * 40
            ) as latest,
        ):
            first = native_install.update_check(self.layout, now=1000.0)
            again = native_install.update_check(self.layout, now=1000.0 + 3600)
            later = native_install.update_check(self.layout, now=1000.0 + 7 * 3600)

        self.assertTrue(first["waiting"])
        self.assertEqual(first["latest"], "d" * 40)
        self.assertEqual(again, first)
        self.assertEqual(latest.call_count, 2)
        self.assertEqual(later["checked_at"], 1000.0 + 7 * 3600)
        saved = json.loads((self.layout.runtime_root / "update-check.json").read_text())
        self.assertEqual(saved["latest"], "d" * 40)

    def test_an_answer_about_another_release_is_asked_again(self):
        # the install moved from a to b since the last check, which still names b's predecessor
        native_install.remember_latest(self.layout, "9" * 40, "a" * 40)
        with (
            mock.patch.object(
                native_install, "_load_manifest", return_value=self._manifest("b" * 40)
            ),
            mock.patch.object(
                native_install, "latest_release_commit", return_value="b" * 40
            ) as latest,
        ):
            check = native_install.update_check(self.layout)
        latest.assert_called_once()
        self.assertFalse(check["waiting"])

    def test_an_unreachable_release_source_is_reported_not_raised(self):
        with (
            mock.patch.object(native_install, "_load_manifest", return_value=self._manifest()),
            mock.patch.object(
                native_install,
                "latest_release_commit",
                side_effect=native_install.NativeInstallError("could not be checked"),
            ),
        ):
            check = native_install.update_check(self.layout, refresh=True)
        self.assertFalse(check["waiting"])
        self.assertEqual(check["error"], "could not be checked")


class DoctorFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-cli-doctor-")
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.docs = self.root / "Alles" / "Vault"
        self.files = self.root / "Alles" / "Files"
        self.docs.mkdir(parents=True)
        self.files.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _checks(self, settings):
        with (
            mock.patch.dict(os.environ, {"ALLES_DATA": str(self.data)}),
            mock.patch("core.settings.load_settings", return_value=settings),
        ):
            return {label: (ok, detail) for ok, label, detail in cli._folder_checks()}

    def test_outside_folders_that_exist_and_take_writes_pass(self):
        checks = self._checks({"vault_dir": str(self.docs), "files_dir": str(self.files)})
        self.assertEqual(checks["docs folder"][0], True)
        self.assertEqual(checks["files folder"][0], True)
        self.assertNotIn("leftover copy", checks)
        self.assertEqual(list(self.docs.iterdir()), [])  # the write probe leaves nothing

    def test_a_docs_folder_pointing_at_an_update_copy_fails(self):
        copy = self.data / EXTERNAL_VAULT_SUBPATH
        copy.mkdir()
        checks = self._checks({"vault_dir": str(copy), "files_dir": str(self.files)})
        self.assertIs(checks["docs folder"][0], False)
        self.assertIn("update's copy", checks["docs folder"][1])
        self.assertIs(checks["leftover copy"][0], False)

    def test_a_missing_folder_fails(self):
        checks = self._checks({"vault_dir": str(self.root / "gone"), "files_dir": str(self.files)})
        self.assertIs(checks["docs folder"][0], False)
        self.assertIn("missing", checks["docs folder"][1])


class ToolsAndCompletionTest(unittest.TestCase):
    def _state(self, ready):
        async def state(dep_id):
            done = dep_id in ready
            return {
                "id": dep_id,
                "name": dep_id,
                "state": "ready" if done else "missing",
                "detail": f"{dep_id} ok" if done else f"{dep_id} isn't installed",
                "error": "",
                "can_install": not done,
            }

        return state

    def test_tools_lists_each_and_names_the_install_command_for_the_missing(self):
        with (
            mock.patch("services.dependencies.state", side_effect=self._state({"node"})),
            mock.patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            self.assertTrue(cli.cmd_tools())
        self.assertIn("node ok", out.getvalue())
        self.assertIn("install them: alles tools install pi browser", out.getvalue())

    def test_tools_install_installs_only_what_is_missing_node_first(self):
        installed = []
        ready = {"node"}

        def install(dep_id):
            installed.append(dep_id)
            ready.add(dep_id)

        with (
            mock.patch("services.dependencies.state", side_effect=self._state(ready)),
            mock.patch.object(cli, "_install_tool", side_effect=install),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertTrue(cli.cmd_tools(["install", "all"]))
        self.assertEqual(installed, ["pi", "browser"])

    def _install_needing(self, fix, *, tty, answer="y", runs=0):
        from services import dependencies

        calls = []

        def install(dep_id):
            calls.append(dep_id)
            if len(calls) == 1:
                raise dependencies.DependencyError("node needs the libatomic1 package", fix=fix)

        with (
            mock.patch("services.dependencies.state", side_effect=self._state(set())),
            mock.patch.object(cli, "_install_tool", side_effect=install),
            mock.patch("sys.stdin.isatty", return_value=tty),
            mock.patch("builtins.input", return_value=answer),
            mock.patch.object(cli.subprocess, "call", return_value=runs) as call,
            mock.patch("sys.stdout", new_callable=io.StringIO) as out,
        ):
            cli.cmd_tools(["install", "node"])
        return calls, call, out.getvalue()

    def test_a_system_package_is_named_and_run_only_on_a_yes(self):
        fix = ["sudo", "apt-get", "install", "-y", "libatomic1"]
        calls, call, out = self._install_needing(fix, tty=True)
        call.assert_called_once_with(fix)
        self.assertEqual(calls, ["node", "node"])
        self.assertEqual(out.count("sudo apt-get install -y libatomic1"), 1)
        calls, call, _ = self._install_needing(fix, tty=True, answer="n")
        call.assert_not_called()
        self.assertEqual(calls, ["node"])

    def test_without_a_keyboard_the_command_is_printed_not_run(self):
        fix = ["sudo", "apt-get", "install", "-y", "libatomic1"]
        calls, call, out = self._install_needing(fix, tty=False)
        call.assert_not_called()
        self.assertEqual(out.count("sudo apt-get install -y libatomic1"), 1)

    def test_completion_offers_every_command(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertTrue(cli.cmd_completion(["bash"]))
        for name in cli.COMMANDS:
            self.assertIn(name, out.getvalue())


class StyleTest(unittest.TestCase):
    def test_piped_output_has_no_escape_codes(self):
        out = io.StringIO()
        ui = cli_ui.Style(out)
        ui.header("status", ("release abc1234",))
        ui.say(ui.bar(0.5, 10))
        self.assertEqual(out.getvalue(), "\n  alles  status\n  release abc1234\n\n[#####-----]\n")

    def test_a_color_terminal_header_is_the_purple_name_and_no_logo(self):
        class Tty(io.StringIO):
            encoding = "utf-8"

            def isatty(self):
                return True

        out = Tty()
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color", "COLORTERM": "truecolor"}):
            os.environ.pop("NO_COLOR", None)
            ui = cli_ui.Style(out)
            ui.header("status", ("release abc1234",))
        # favicon.svg's purple, bold, on the name; the owner asked for no logo, so no
        # background colours or block glyphs
        self.assertEqual(
            out.getvalue(),
            "\n  \033[1;38;2;129;140;248malles\033[0m  status\n  release abc1234\n\n",
        )


if __name__ == "__main__":
    unittest.main()


class QuickCheckTest(unittest.TestCase):
    """nov 5: config and folders hashed ~22,000 release files twice (2 to 6 s on the drive)."""

    def _calls(self, command, args):
        seen = []

        def layout(*, files=True):
            seen.append(files)
            return None

        with mock.patch.object(cli, "_native_layout", side_effect=layout):
            with mock.patch("sys.stdout", new=io.StringIO()):
                try:
                    command(args)
                except Exception:
                    pass
        return seen

    def test_config_and_showing_folders_skip_the_file_hashes(self):
        self.assertEqual(self._calls(cli.cmd_config, ("path",))[:1], [False])
        self.assertEqual(self._calls(cli.cmd_folders, ())[:1], [False])

    def test_moving_folders_still_checks_every_file(self):
        self.assertEqual(self._calls(cli.cmd_folders, ("move",))[:1], [True])
