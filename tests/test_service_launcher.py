"""alles-server: the compiled program launchd runs for an install on another drive (nov 5).

after a reboot macOS kept the service off the external drive: a shell script can't be allowed to
use a removable volume, a compiled program gets asked about once and remembered."""

import io
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cli
from services import native_install


def _has_compiler() -> bool:
    if sys.platform != "darwin" or shutil.which("xcode-select") is None:
        return False
    return subprocess.run(["xcode-select", "-p"], capture_output=True).returncode == 0


@unittest.skipUnless(_has_compiler(), "needs macOS with apple's command line tools")
class RealLauncherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="alles-server-build-")
        cls.root = Path(cls.tmp.name).resolve()
        cls.binary = cls.root / "bin" / "alles-server"
        if not native_install._build_service_launcher(cls.binary):
            raise AssertionError("the launcher didn't build")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_it_builds_alone_under_its_own_name(self):
        self.assertEqual(sorted(p.name for p in self.binary.parent.iterdir()), ["alles-server"])
        self.assertEqual(self.binary.stat().st_mode & 0o777, 0o700)
        signed = subprocess.run(
            ["codesign", "-dv", str(self.binary)], capture_output=True, text=True
        )
        # the name macOS shows when it asks
        self.assertIn("Identifier=alles-server", signed.stderr)

    def test_a_rebuild_is_the_same_program(self):
        # macOS remembers the answer for these exact bytes; a different build would ask again
        again = self.root / "again" / "alles-server"
        self.assertTrue(native_install._build_service_launcher(again))
        self.assertEqual(again.read_bytes(), self.binary.read_bytes())

    def test_it_hands_back_the_childs_exit(self):
        run = subprocess.run([str(self.binary), "/bin/sh", "-c", "exit 7"], timeout=30)
        self.assertEqual(run.returncode, 7)
        missing = subprocess.run(
            [str(self.binary), str(self.root / "nope")], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("can't start", missing.stderr)
        self.assertEqual(subprocess.run([str(self.binary)], capture_output=True).returncode, 64)

    def test_a_stop_reaches_the_child_and_a_crash_stays_a_crash(self):
        mark = self.root / "stopped"
        script = f"trap 'echo term > {mark}; exit 3' TERM; while :; do sleep 0.05; done"
        running = subprocess.Popen([str(self.binary), "/bin/sh", "-c", script])
        try:
            time.sleep(0.5)
            running.send_signal(signal.SIGTERM)
            self.assertEqual(running.wait(timeout=10), 3)
        finally:
            if running.poll() is None:
                running.kill()
        self.assertEqual(mark.read_text("utf-8"), "term\n")
        # launchd starts it again after a crash, as it did when python was the job itself
        crashed = subprocess.run([str(self.binary), "/bin/sh", "-c", "kill -KILL $$"], timeout=30)
        self.assertEqual(crashed.returncode, 128 + signal.SIGKILL)


class CliRefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-cli-refresh-")
        root = Path(self.tmp.name).resolve()
        self.layout = native_install.platform_layout(
            "Darwin", home=root / "home", install_home=root / "drive" / "Alles"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _restart(self, **refresh):
        with (
            mock.patch.object(cli, "_native_layout", return_value=self.layout),
            mock.patch.object(cli, "_start_safety_allows", return_value=True),
            mock.patch.object(native_install, "refresh_service", **refresh) as refreshed,
            mock.patch("services.service_manager.control") as control,
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            ok = cli.cmd_restart()
        return ok, refreshed, control, output.getvalue()

    def test_restart_moves_an_older_install_onto_the_launcher_and_says_to_allow_it(self):
        ok, refreshed, control, text = self._restart(return_value=True)
        self.assertTrue(ok)
        refreshed.assert_called_once_with(self.layout)
        # the reload started it already
        control.assert_not_called()
        self.assertIn("if macOS asks about alles-server, click Allow", text)

    def test_restart_with_nothing_to_move_restarts_as_before(self):
        ok, _refreshed, control, text = self._restart(return_value=False)
        self.assertTrue(ok)
        control.assert_called_once_with("server", "restart")
        self.assertNotIn("alles-server", text)

    def test_a_failed_move_keeps_the_old_service_and_still_restarts(self):
        error = native_install.NativeInstallError("service reload failed")
        ok, _refreshed, control, text = self._restart(side_effect=error)
        self.assertTrue(ok)
        control.assert_called_once_with("server", "restart")
        self.assertIn("alles kept its service as it was: service reload failed", text)

    def test_an_update_start_after_a_reload_doesnt_kick_launchd_again(self):
        with (
            mock.patch.object(native_install, "refresh_service", return_value=True),
            mock.patch("services.service_manager.control") as control,
            mock.patch.object(cli, "_native_service_endpoint", return_value=(1, "http://x")),
            mock.patch.object(cli, "_native_service_running", return_value=True),
            mock.patch.object(cli, "_health_endpoint_ok", return_value=True),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertTrue(cli._native_start_service_healthy(self.layout))
        control.assert_not_called()

    def test_the_drive_hint_follows_whether_the_launcher_is_there(self):
        self.assertIn("run alles restart, then click Allow", cli._drive_hint(self.layout))
        binary = native_install.service_launcher_path(self.layout)
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n", "utf-8")
        self.assertIn("Privacy & Security › Files & Folders", cli._drive_hint(self.layout))

    def test_only_a_mac_install_outside_home_gets_a_launcher(self):
        home = Path(self.tmp.name) / "home"
        drive = Path(self.tmp.name) / "drive" / "Alles"
        self.assertEqual(
            native_install.service_launcher_path(self.layout),
            home.resolve() / ".local" / "bin" / "alles-server",
        )
        for layout in (
            native_install.platform_layout("Darwin", home=home),
            native_install.platform_layout("Linux", home=home, install_home=drive),
        ):
            self.assertIsNone(native_install.service_launcher_path(layout))


if __name__ == "__main__":
    unittest.main()
