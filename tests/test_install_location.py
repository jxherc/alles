"""ALLES_HOME: the whole native install in one folder, for example on an external drive."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from services import native_install

ROOT = Path(__file__).resolve().parent.parent

# launchctl as it really answers (checked on macOS 27, nov 2): print on an unknown label exits 113
# with "Could not find service"; bootstrap takes any plist; a spawn whose program or log folder is
# missing ends with EX_CONFIG (78) and nothing gets created
FAKE_LAUNCHD = r"""
import os, plistlib, subprocess
from pathlib import Path


class Launchd:
    def __init__(self):
        self.loaded = {}
        self.spawns = []

    def __call__(self, command, **_kwargs):
        def done(code=0, out="", err=""):
            return subprocess.CompletedProcess(command, code, out, err)

        if command[0] != "launchctl":
            return done(127, err="not found")
        action, target = command[1], command[2]
        label = target.rsplit("/", 1)[-1]
        if action == "print":
            if label in self.loaded:
                return done(out=f"{target} = {{\n\tstate = running\n}}\n")
            return done(113, err=f'Bad request.\nCould not find service "{label}" in domain for user gui: {os.getuid()}\n')
        if action == "bootstrap":
            with open(command[3], "rb") as handle:
                plist = plistlib.load(handle)
            self.loaded[plist["Label"]] = plist
            return done()
        if action == "kickstart":
            plist = self.loaded.get(label)
            if plist is None:
                return done(113, err="Could not find service")
            program = Path(plist["ProgramArguments"][0])
            logs = [Path(plist[key]).parent for key in ("StandardOutPath", "StandardErrorPath") if key in plist]
            ok = os.access(program, os.X_OK) and all(folder.is_dir() for folder in logs)
            self.spawns.append(0 if ok else 78)
            return done()
        if action == "bootout":
            if self.loaded.pop(label, None) is None:
                return done(3, err="Boot-out failed: 3: No such process")
            return done()
        return done(1, err="unknown")
"""


def _builder(source: Path, destination: Path) -> Path:
    destination.mkdir(parents=True)
    for item in source.iterdir():
        (destination / item.name).write_bytes(item.read_bytes())
    python = destination / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    (destination / ".venv" / "pyvenv.cfg").write_text("home = test\n", "utf-8")
    # the fake interpreter prints what the dispatcher handed it, so the test can read it back
    python.write_text(
        '#!/bin/sh\necho "ALLES_HOME=$ALLES_HOME"\necho "ALLES_PORT=${ALLES_PORT:-}"\n'
        'echo "XDG_CACHE_HOME=$XDG_CACHE_HOME"\necho "ALLES_NATIVE_ROOT=$ALLES_NATIVE_ROOT"\n'
        'echo "PORT=${PORT:-}"\necho "ARGS=$*"\n',
        "utf-8",
    )
    python.chmod(0o755)
    return python


class InstallHomeLayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-install-home-")
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.drive = self.root / "drive" / "Alles"

    def tearDown(self):
        self.tmp.cleanup()

    def test_everything_but_the_launcher_and_service_lives_in_alles_home(self):
        for system in ("Darwin", "Linux"):
            layout = native_install.platform_layout(
                system, home=self.home, install_home=self.drive, port=8463
            )
            self.assertEqual(layout.files_default, self.drive)
            self.assertEqual(layout.vault_default, self.drive / "Docs")
            self.assertEqual(layout.support_root, self.drive / ".alles")
            self.assertEqual(layout.data_root, self.drive / ".alles" / "data")
            self.assertEqual(layout.runtime_root, self.drive / ".alles" / "runtime")
            self.assertEqual(layout.config_file, self.drive / ".alles" / "alles.env")
            self.assertEqual(layout.launcher, self.home / ".local" / "bin" / "alles")
            self.assertTrue(self.home in layout.service_definition.parents)
            self.assertEqual(layout.port, 8463)

    def test_no_alles_home_keeps_the_usual_places(self):
        with (
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("ALLES_HOME", None)
            os.environ.pop("ALLES_PORT", None)
            layout = native_install.platform_layout("Darwin")
        self.assertIsNone(layout.install_home)
        self.assertEqual(layout.port, 6769)
        self.assertEqual(layout.files_default, self.home / "Alles")
        self.assertEqual(
            layout.support_root, self.home / "Library" / "Application Support" / "Alles"
        )

    def test_the_environment_picks_the_location_and_refuses_bad_values(self):
        with (
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.dict(os.environ, {"ALLES_HOME": str(self.drive), "ALLES_PORT": "8463"}),
        ):
            layout = native_install.platform_layout("Darwin")
        self.assertEqual(layout.install_home, self.drive)
        self.assertEqual(layout.port, 8463)
        for env, words in (
            ({"ALLES_HOME": "relative/Alles"}, "full path"),
            ({"ALLES_HOME": str(self.drive), "ALLES_PORT": "80"}, "1024 to 65535"),
            ({"ALLES_HOME": str(self.drive), "ALLES_PORT": "lots"}, "1024 to 65535"),
        ):
            with (
                mock.patch.object(Path, "home", return_value=self.home),
                mock.patch.dict(os.environ, env),
                self.assertRaisesRegex(native_install.NativeInstallError, words),
            ):
                native_install.platform_layout("Darwin")

    def test_a_drive_that_is_not_mounted_is_refused_before_anything_is_made(self):
        missing = Path("/Volumes") / f"alles-missing-{uuid.uuid4().hex[:8]}" / "Alles"
        layout = native_install.platform_layout("Darwin", home=self.home, install_home=missing)
        with self.assertRaisesRegex(native_install.NativeInstallError, "isn't connected"):
            native_install.check_install_home(layout)
        # an empty folder left in /Volumes by an unplugged drive is not the drive either
        fake = Path("/Volumes") / "Stale" / "Alles"
        with (
            mock.patch.object(native_install.os.path, "ismount", return_value=False),
            self.assertRaisesRegex(native_install.NativeInstallError, "isn't connected"),
        ):
            native_install.check_install_home(
                native_install.platform_layout("Darwin", home=self.home, install_home=fake)
            )
        linux = native_install.platform_layout("Linux", home=self.home, install_home=missing)
        with self.assertRaisesRegex(native_install.NativeInstallError, "doesn't exist"):
            native_install.check_install_home(linux)
        with self.assertRaisesRegex(native_install.NativeInstallError, "isn't connected"):
            native_install.install(
                self.root,
                layout,
                release_builder=_builder,
                release_probe=lambda _release, _python: True,
                install_source={"kind": "unavailable"},
                runner=lambda *_a, **_k: self.fail("nothing may run"),
            )
        self.assertFalse(missing.parent.exists())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_default_program_files_have_no_location_lines(self):
        layout = native_install.platform_layout("Darwin", home=self.home)
        dispatcher = native_install._dispatcher_source(layout).decode()
        self.assertNotIn("ALLES_HOME", dispatcher)
        self.assertNotIn("ALLES_PORT", dispatcher)
        self.assertIn("export PORT=6769;", dispatcher)
        plist = native_install._service_source(layout).decode()
        self.assertIn(f"<string>{layout.dispatcher}</string>", plist)
        self.assertIn("StandardOutPath", plist)


class InstallHomeLauncherTest(unittest.TestCase):
    """The launcher stays on the startup disk; it runs here as real sh."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="alles-install-launcher-")
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / "home"
        self.drive = self.root / "drive" / "Alles"
        self.layout = native_install.platform_layout(
            "Darwin", home=self.home, install_home=self.drive
        )
        self.layout.launcher.parent.mkdir(parents=True)
        self.layout.launcher.write_bytes(native_install._launcher_source(self.layout))
        self.layout.launcher.chmod(0o700)
        # a sleep that returns at once, so the wait loop turns in milliseconds
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "sleep").write_text("#!/bin/sh\nexit 0\n", "utf-8")
        (self.bin / "sleep").chmod(0o755)
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin"}

    def tearDown(self):
        self.tmp.cleanup()

    def _plug_in(self):
        self.layout.data_root.mkdir(parents=True)
        self.layout.runtime_root.mkdir(parents=True)
        self.layout.dispatcher.write_text('#!/bin/sh\necho "served $*"\n', "utf-8")
        self.layout.dispatcher.chmod(0o700)

    def test_a_command_says_the_drive_is_missing_and_creates_nothing(self):
        result = subprocess.run(
            ["sh", str(self.layout.launcher), "status"],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"alles: {self.drive} isn't there", result.stderr)
        self.assertFalse(self.drive.parent.exists())

    def test_the_service_waits_for_the_drive_then_logs_to_it(self):
        waiting = subprocess.Popen(
            ["sh", str(self.layout.launcher), "__serve__"],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.5)
            self.assertIsNone(waiting.poll(), "the service must wait, not start or quit")
            self.assertFalse(self.drive.parent.exists(), "waiting must not make the folder")
            self._plug_in()
            self.assertEqual(waiting.wait(timeout=30), 0)
        finally:
            if waiting.poll() is None:
                waiting.kill()
                waiting.wait()
        log = (self.layout.data_root / "alles-service.log").read_text("utf-8")
        self.assertEqual(log, "served __serve__\n")

    def test_with_the_drive_a_command_goes_straight_through(self):
        self._plug_in()
        result = subprocess.run(
            ["sh", str(self.layout.launcher), "status"],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout), (0, "served status\n"))


class InstallHomePlainPythonTest(unittest.TestCase):
    """install.sh runs the installer on a bare python: no site-packages, real launchd answers."""

    def _plain(self, script: str, *args: str, env: dict | None = None):
        return subprocess.run(
            [sys.executable, "-S", "-c", script, str(ROOT), *args],
            env={"PATH": os.environ.get("PATH", ""), **(env or {})},
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def test_install_update_handoff_and_uninstall_keep_the_location(self):
        with tempfile.TemporaryDirectory(prefix="alles-install-plain-") as directory:
            root = Path(directory).resolve()
            source = root / "source"
            source.mkdir()
            for name in ("app.py", "cli.py"):
                (source / name).write_text(f"# {name}\n", "utf-8")
            script = (
                "import sys; sys.path.insert(0, sys.argv[1])\n"
                + FAKE_LAUNCHD
                + r"""
import json
from pathlib import Path
from unittest import mock
from services import native_install, service_manager
# this test drives the macos install; pin the host so a linux ci runner reads the same layout
mock.patch("platform.system", return_value="Darwin").start()

root = Path(sys.argv[2])
home, drive, source = root / "home", root / "drive" / "Alles", root / "source"
home.mkdir()
(root / "drive").mkdir()
layout = native_install.platform_layout("Darwin", home=home, install_home=drive, port=8463)
os.environ["ALLES_DATA"] = str(layout.data_root)


def builder(src, destination):
    destination.mkdir(parents=True)
    for item in src.iterdir():
        (destination / item.name).write_bytes(item.read_bytes())
    python = destination / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    (destination / ".venv" / "pyvenv.cfg").write_text("home = test\n", "utf-8")
    python.write_text(sys.argv[3], "utf-8")
    python.chmod(0o755)
    return python


launchd = Launchd()
with mock.patch.object(service_manager, "_home_dir", return_value=home):
    result = native_install.install(
        source, layout, release_id="first", release_builder=builder,
        release_probe=lambda _r, _p: True, install_source={"kind": "unavailable"},
        runner=launchd,
    )
    plist = launchd.loaded["app.alles.server"]
    # a command, as the owner types it: through the launcher and the dispatcher
    shown = subprocess.run([str(layout.launcher), "status"], capture_output=True, text=True)
    # the update hand-off: the installed release starts the new one with its own environment
    env = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
    for key in ("ALLES_HOME", "ALLES_PORT", "ALLES_NATIVE_ROOT", "ALLES_DATA", "XDG_CACHE_HOME"):
        os.environ[key] = env[key]
    os.environ["HOME"] = str(home)
    again = native_install.current_layout()
    removed = native_install.uninstall_keep_data(again, runner=launchd)
print(json.dumps({
    "spawns": launchd.spawns,
    "program": plist["ProgramArguments"],
    "port": plist["EnvironmentVariables"]["PORT"],
    "log_keys": sorted(k for k in plist if k.startswith("Standard")),
    "status": shown.stdout,
    "again": str(again.runtime_root) if again else None,
    "runtime": str(layout.runtime_root),
    "data_kept": removed["data_root"],
    "left_in_home": sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()),
    "settings": json.loads((layout.data_root / "settings.json").read_text("utf-8")),
}))
"""
            )
            python_text = (
                '#!/bin/sh\necho "ALLES_HOME=$ALLES_HOME"\necho "ALLES_PORT=${ALLES_PORT:-}"\n'
                'echo "XDG_CACHE_HOME=$XDG_CACHE_HOME"\necho "ALLES_NATIVE_ROOT=$ALLES_NATIVE_ROOT"\n'
                'echo "ALLES_DATA=$ALLES_DATA"\necho "ARGS=$*"\n'
            )
            result = self._plain(script, str(root), python_text)
            self.assertEqual(result.returncode, 0, result.stderr)
            found = json.loads(result.stdout.strip().splitlines()[-1])
            home, drive = root / "home", root / "drive" / "Alles"
            # the service starts the launcher on the startup disk, which can always be spawned
            self.assertEqual(found["program"], [str(home / ".local/bin/alles"), "__serve__"])
            self.assertEqual(found["spawns"], [0])
            self.assertEqual(found["log_keys"], [])
            self.assertEqual(found["port"], "8463")
            self.assertIn(f"ALLES_HOME={drive}\n", found["status"])
            self.assertIn("ALLES_PORT=8463\n", found["status"])
            self.assertIn(f"XDG_CACHE_HOME={drive / '.alles' / 'cache'}\n", found["status"])
            self.assertEqual(found["again"], found["runtime"])
            self.assertEqual(found["data_kept"], str(drive / ".alles" / "data"))
            self.assertEqual(found["left_in_home"], [])
            self.assertEqual(
                found["settings"],
                {
                    "automatic_backup_dir": str(drive / ".alles" / "backups"),
                    "files_dir": str(drive),
                    "vault_dir": str(drive / "Docs"),
                },
            )

    def test_the_install_command_refuses_a_missing_drive_on_plain_python(self):
        missing = Path("/Volumes") / f"alles-missing-{uuid.uuid4().hex[:8]}" / "Alles"
        with tempfile.TemporaryDirectory(prefix="alles-install-plain-") as directory:
            home = Path(directory).resolve()
            result = self._plain(
                "import sys, runpy; sys.argv = [sys.argv[1] + '/cli.py', 'install']; "
                "runpy.run_path(sys.argv[0], run_name='__main__')",
                env={"HOME": str(home), "ALLES_HOME": str(missing), "NO_COLOR": "1"},
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("stopped safely", output)
            self.assertRegex(output, "isn't connected|doesn't exist")
            self.assertFalse(missing.parent.exists())
            self.assertEqual(list(home.iterdir()), [])


class OldLauncherTest(unittest.TestCase):
    def test_only_an_exact_checkout_launcher_is_recognised(self):
        import cli

        with tempfile.TemporaryDirectory(prefix="alles-old-launcher-") as directory:
            launcher = Path(directory) / "alles"
            launcher.write_text(
                '#!/usr/bin/env bash\nexec "/usr/bin/python3" "/Users/me/alles/cli.py" "$@"\n',
                "utf-8",
            )
            self.assertEqual(cli._old_launcher_checkout(launcher), "/Users/me/alles")
            launcher.write_text('#!/bin/sh\nexec /somewhere/else "$@"\n', "utf-8")
            self.assertIsNone(cli._old_launcher_checkout(launcher))
            self.assertIsNone(cli._old_launcher_checkout(Path(directory) / "missing"))

    def _install(self, answer: str, *, fails: bool = False):
        import io

        import cli

        old = '#!/usr/bin/env bash\nexec "/usr/bin/python3" "/Users/me/alles/cli.py" "$@"\n'
        with tempfile.TemporaryDirectory(prefix="alles-old-launcher-") as directory:
            root = Path(directory).resolve()
            layout = native_install.platform_layout("Darwin", home=root)
            layout.launcher.parent.mkdir(parents=True)
            layout.launcher.write_text(old, "utf-8")
            seen = []

            def install(_source, chosen, **_kwargs):
                seen.append(chosen.launcher.exists())
                if fails:
                    raise native_install.NativeInstallError("service install failed")
                chosen.launcher.write_text("#!/bin/sh\nexec new\n", "utf-8")
                return {"data_root": str(chosen.data_root), "config_file": ""}

            env = {k: v for k, v in os.environ.items() if not k.startswith("ALLES_INSTALL_")}
            with (
                mock.patch.dict(os.environ, env, clear=True),
                mock.patch.object(native_install, "platform_layout", return_value=layout),
                mock.patch.object(native_install, "install", side_effect=install),
                mock.patch.object(cli.sys.stdin, "isatty", return_value=True),
                mock.patch("builtins.input", return_value=answer),
                mock.patch.object(cli, "_native_service_endpoint", return_value=(6769, "")),
                mock.patch.object(cli, "_wait_for_health", return_value=True),
                mock.patch.object(cli, "_put_launcher_on_path", return_value=None),
                mock.patch.object(cli, "_offer_aide_tools"),
                mock.patch.object(cli, "_ask", side_effect=[answer == "y", False, False]),
                mock.patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                ok = cli.cmd_install()
            leftovers = sorted(p.name for p in layout.launcher.parent.iterdir())
            return ok, seen, layout.launcher.read_text("utf-8"), leftovers, output.getvalue()

    def test_the_install_asks_before_replacing_an_old_checkout_launcher(self):
        ok, seen, text, leftovers, output = self._install("n")
        self.assertFalse(ok)
        self.assertEqual(seen, [])
        self.assertIn("runs /Users/me/alles", output)
        self.assertIn("/Users/me/alles/cli.py", text)

        ok, seen, text, leftovers, _ = self._install("y")
        self.assertTrue(ok)
        self.assertEqual(seen, [False])  # moved aside before the install wrote its own
        self.assertEqual((text, leftovers), ("#!/bin/sh\nexec new\n", ["alles"]))

        ok, seen, text, leftovers, _ = self._install("y", fails=True)
        self.assertFalse(ok)
        self.assertIn("/Users/me/alles/cli.py", text)  # a failed install puts it back
        self.assertEqual(leftovers, ["alles"])


class InstallFromDriveTest(unittest.TestCase):
    """the one-line install started in a folder on another drive installs on that drive."""

    # fake paths: "/" is the startup disk that holds the home folder (device 1), drives are 2
    MOUNTS = {"/", "/Volumes/Drive", "/media/eric/usb", "/run/media/eric/usb", "/mnt/disk"}
    HOME = Path("/Users/eric")

    def _pick(self, folder: str, *, on_home_disk=()):
        def device(path):
            text = str(path)
            return 2 if text in self.MOUNTS - {"/"} - set(on_home_disk) else 1

        return native_install.drive_install_home(
            Path(folder),
            home=self.HOME,
            is_mount=lambda path: str(path) in self.MOUNTS,
            device=device,
        )

    def test_a_folder_on_a_drive_gets_an_alles_folder_inside_it(self):
        for folder in (
            "/Volumes/Drive",
            "/Volumes/Drive/stuff/more",
            "/media/eric/usb",
            "/run/media/eric/usb/stuff",
            "/mnt/disk",
        ):
            with self.subTest(folder=folder):
                self.assertEqual(self._pick(folder), Path(folder) / "Alles")

    def test_an_alles_folder_on_the_drive_is_used_as_it_is(self):
        for folder in ("/Volumes/Drive/Alles", "/media/eric/usb/alles"):
            with self.subTest(folder=folder):
                self.assertEqual(self._pick(folder), Path(folder))

    def test_the_startup_disk_keeps_the_usual_places(self):
        for folder in ("/Users/eric/Downloads", "/Users/eric", "/opt/stuff", "/", "/Volumes"):
            with self.subTest(folder=folder):
                self.assertIsNone(self._pick(folder))
        # a drive folder that really sits on the home folder's disk isn't another drive
        self.assertIsNone(self._pick("/mnt/disk", on_home_disk={"/mnt/disk"}))

    def test_a_drive_that_cannot_be_read_keeps_the_usual_places(self):
        def device(_path):
            raise OSError("gone")

        picked = native_install.drive_install_home(
            Path("/Volumes/Drive"),
            home=self.HOME,
            is_mount=lambda path: str(path) in self.MOUNTS,
            device=device,
        )
        self.assertIsNone(picked)

    def _install(self, env: dict, picked: Path | None):
        import io

        import cli

        seen = {}

        def layout(*_args, **_kwargs):
            seen["home"] = os.environ.get("ALLES_HOME")
            raise native_install.NativeInstallError("stop here")

        clean = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("ALLES_INSTALL_") and k != "ALLES_HOME"
        }
        with (
            mock.patch.dict(os.environ, {**clean, **env}, clear=True),
            mock.patch.object(native_install, "drive_install_home", return_value=picked) as pick,
            mock.patch.object(native_install, "platform_layout", side_effect=layout),
            mock.patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            ok = cli.cmd_install()
        self.assertFalse(ok)
        return seen.get("home"), pick, output.getvalue()

    def test_the_install_command_uses_the_drive_install_sh_started_on(self):
        drive = Path("/Volumes/Drive/Alles")
        home, pick, output = self._install({"ALLES_INSTALL_FROM": "/Volumes/Drive"}, drive)
        self.assertEqual(home, str(drive))
        pick.assert_called_once_with(Path("/Volumes/Drive"))
        self.assertIn("the drive you're in", output)

    def test_the_install_command_keeps_alles_home_and_the_usual_places(self):
        # an ALLES_HOME you typed wins over the folder you're in
        home, pick, _ = self._install(
            {"ALLES_INSTALL_FROM": "/Volumes/Drive", "ALLES_HOME": "/Volumes/Other/Alles"},
            Path("/Volumes/Drive/Alles"),
        )
        self.assertEqual(home, "/Volumes/Other/Alles")
        pick.assert_not_called()
        # started on the startup disk: no ALLES_HOME, so the usual places
        home, _, output = self._install({"ALLES_INSTALL_FROM": "/Users/eric/Downloads"}, None)
        self.assertIsNone(home)
        self.assertNotIn("the drive you're in", output)
        # run without install.sh: nothing to go on
        home, pick, _ = self._install({}, Path("/Volumes/Drive/Alles"))
        self.assertIsNone(home)
        pick.assert_not_called()


if __name__ == "__main__":
    unittest.main()
