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

    def test_status_names_the_release_and_the_pending_accept_with_its_commands(self):
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
        self.assertIn("bbbbbbb waits for your ok: alles update accept", text)
        self.assertIn("or alles update rollback to go back to aaaaaaa", text)
        self.assertIn("ccccccc is ready: alles update", text)
        self.assertIn("jxherc/alles main", text)
        self.assertNotIn("\033[", text)  # piped output stays plain

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

    def test_completion_offers_every_command(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertTrue(cli.cmd_completion(["bash"]))
        for name in cli.COMMANDS:
            self.assertIn(name, out.getvalue())


class StyleTest(unittest.TestCase):
    def test_piped_output_has_no_logo_or_escape_codes(self):
        out = io.StringIO()
        ui = cli_ui.Style(out)
        ui.header("status", ("release abc1234",))
        ui.say(ui.bar(0.5, 10))
        self.assertEqual(out.getvalue(), "\n  alles  status\n  release abc1234\n\n[#####-----]\n")

    def test_a_color_terminal_draws_the_square_and_the_purple_dot(self):
        class Tty(io.StringIO):
            encoding = "utf-8"

            def isatty(self):
                return True

        out = Tty()
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color", "COLORTERM": "truecolor"}):
            os.environ.pop("NO_COLOR", None)
            ui = cli_ui.Style(out)
            ui.header("status")
        text = out.getvalue()
        self.assertIn("48;2;10;10;10;38;2;129;140;248m  ▄▄  ", text)  # favicon.svg colors
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color", "NO_COLOR": "1"}):
            self.assertEqual(cli_ui.Style(Tty()).logo(), [])


if __name__ == "__main__":
    unittest.main()
