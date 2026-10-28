import asyncio
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from core.tool_path import extend_tool_path
from services import dependencies
from tests._client import ApiTest

VERSION = "v24.22.1"
NAME = f"node-{VERSION}-linux-x64"


def _tarball() -> bytes:
    """a node tarball whose node prints its version, the way the real one does"""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        script = f"#!/bin/sh\necho {VERSION}\n".encode()
        info = tarfile.TarInfo(f"{NAME}/bin/node")
        info.size, info.mode = len(script), 0o755
        tar.addfile(info, io.BytesIO(script))
    return out.getvalue()


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"HOME": self.tmp.name, "XDG_CACHE_HOME": ""})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.root = self.home / ".cache" / "alles"


class NodeInstallTests(Cache):
    def run_install(self, tarball=None, sums_hash=None):
        data = tarball or _tarball()
        index = [
            {"version": "v25.1.0", "lts": False, "files": ["linux-x64"]},
            {"version": "v24.99.0", "lts": "Krypton", "files": ["osx-arm64-tar"]},
            {"version": VERSION, "lts": "Krypton", "files": ["linux-x64", "osx-arm64-tar"]},
        ]
        sums = f"{sums_hash or hashlib.sha256(data).hexdigest()}  {NAME}.tar.gz\n"
        texts = {
            f"{dependencies.NODE_DIST}/index.json": json.dumps(index),
            f"{dependencies.NODE_DIST}/{VERSION}/SHASUMS256.txt": sums,
        }

        def download(url, dest):
            self.assertEqual(url, f"{dependencies.NODE_DIST}/{VERSION}/{NAME}.tar.gz")
            Path(dest).write_bytes(data)
            return hashlib.sha256(data).hexdigest()

        with (
            mock.patch.object(
                dependencies, "_node_target", return_value=("linux", "x64", "linux-x64")
            ),
            mock.patch.object(dependencies, "_get_text", side_effect=lambda url: texts[url]),
            mock.patch.object(dependencies, "_download", side_effect=download),
        ):
            return dependencies.install_node()

    def test_installs_the_newest_lts_for_this_machine_and_points_node_at_it(self):
        self.assertEqual(self.run_install(), VERSION)
        self.assertEqual((self.root / "node").resolve(), (self.root / f"node-{VERSION}").resolve())
        self.assertTrue((self.root / "node" / "bin" / "node").exists())
        env = {"PATH": "/usr/bin:/bin"}
        extend_tool_path(env, self.home)
        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(self.root / "node" / "bin"))
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith(".")], [])

    def test_a_checksum_mismatch_installs_nothing(self):
        with self.assertRaisesRegex(dependencies.DependencyError, "checksum"):
            self.run_install(sums_hash="0" * 64)
        self.assertFalse((self.root / "node").exists())
        self.assertFalse((self.root / f"node-{VERSION}").exists())

    def test_a_node_that_cannot_run_here_is_refused(self):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as tar:
            info = tarfile.TarInfo(f"{NAME}/bin/node")
            info.size, info.mode = 0, 0o755
            tar.addfile(info, io.BytesIO(b""))
        with self.assertRaises(dependencies.DependencyError):
            self.run_install(tarball=out.getvalue())
        self.assertFalse((self.root / "node").exists())

    def test_a_newer_install_replaces_the_old_one(self):
        old = self.root / "node-v22.0.0"
        (old / "bin").mkdir(parents=True)
        self.run_install()
        self.assertFalse(old.exists())

    def test_lts_choice_skips_current_releases_and_other_platforms(self):
        index = [
            {"version": "v25.0.0", "lts": False, "files": ["linux-x64"]},
            {"version": "v24.1.0", "lts": "Krypton", "files": ["linux-arm64"]},
            {"version": "v24.0.0", "lts": "Krypton", "files": ["linux-x64"]},
        ]
        self.assertEqual(dependencies._latest_lts(index, "linux-x64"), "v24.0.0")
        with self.assertRaises(dependencies.DependencyError):
            dependencies._latest_lts(index, "osx-x64-tar")


class StateTests(Cache):
    def test_node_states(self):
        with mock.patch("services.pi_agent.node_version", return_value=None):
            self.assertEqual(dependencies._node_state()["state"], "missing")
        with mock.patch("services.pi_agent.node_version", return_value=(20, 11)):
            row = dependencies._node_state()
            self.assertEqual(
                (row["state"], row["version"], row["can_install"]), ("outdated", "20.11", True)
            )
        with mock.patch("services.pi_agent.node_version", return_value=(24, 22)):
            row = dependencies._node_state()
            self.assertEqual((row["state"], row["version"]), ("ready", "24.22"))

    def test_pi_needs_node_cannot_install_but_missing_and_failed_can(self):
        def pi(state, **extra):
            return {"state": state, "version": "", "wanted": "1.3.0", **extra}

        with mock.patch("services.pi_agent.status", return_value=pi("needs_node")):
            self.assertFalse(dependencies._pi_state()["can_install"])
        with mock.patch("services.pi_agent.status", return_value=pi("failed", error="npm broke")):
            row = dependencies._pi_state()
            self.assertEqual((row["error"], row["can_install"]), ("npm broke", True))
        with mock.patch("services.pi_agent.status", return_value=pi("missing")):
            self.assertTrue(dependencies._pi_state()["can_install"])

    def test_searxng_without_docker_says_so_and_links_the_install_page(self):
        with mock.patch.object(dependencies, "find_tool", return_value=None):
            row = dependencies._searxng_state()
        self.assertEqual(row["state"], "needs_docker")
        self.assertEqual(row["link"], dependencies.DOCKER_URL)
        self.assertNotIn("can_install", row)

    def test_searxng_with_docker_installs_and_when_stopped_starts(self):
        info = {
            "available": True,
            "installed": False,
            "running": False,
            "healthy": False,
            "version": "1",
        }
        with (
            mock.patch.object(dependencies, "find_tool", return_value="/usr/bin/docker"),
            mock.patch("services.managed_searxng.status", return_value=info),
        ):
            self.assertEqual(dependencies._searxng_state()["state"], "missing")
            info.update(installed=True)
            self.assertEqual(dependencies._searxng_state()["state"], "stopped")
            info.update(running=True, healthy=True)
            self.assertEqual(dependencies._searxng_state()["state"], "ready")
            info.update(available=False)
            self.assertEqual(dependencies._searxng_state()["state"], "docker_off")


class BrowserTests(Cache):
    def tearDown(self):
        sys.path[:] = [p for p in sys.path if not p.startswith(self.tmp.name)]

    def test_playwright_is_found_in_the_cache_folder_when_it_is_not_importable(self):
        packages = self.root / "browser-packages"
        (packages / "playwright").mkdir(parents=True)
        (self.root / "browser-browsers" / "chromium-1200").mkdir(parents=True)
        (self.root / "browser-browsers" / "chromium-1200" / "INSTALLATION_COMPLETE").write_text("")
        real = dependencies.importlib.util.find_spec
        with (
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(
                dependencies.importlib.util,
                "find_spec",
                side_effect=lambda n: None if n == "playwright" else real(n),
            ),
        ):
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            dependencies.prepare_browser()
            self.assertEqual(sys.path[-1], str(packages))
            self.assertEqual(
                os.environ["PLAYWRIGHT_BROWSERS_PATH"], str(self.root / "browser-browsers")
            )
            dependencies.prepare_browser()
            self.assertEqual(sys.path.count(str(packages)), 1)

    def test_nothing_changes_when_playwright_imports_normally_and_nothing_was_installed(self):
        before = list(sys.path)
        with mock.patch.dict(os.environ):
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            dependencies.prepare_browser()
            self.assertEqual(sys.path, before)
            self.assertNotIn("PLAYWRIGHT_BROWSERS_PATH", os.environ)

    def test_install_pins_playwright_into_the_cache_then_downloads_chromium_there(self):
        calls = []

        def fake_run(command, what, timeout, env=None):
            calls.append((command, env))
            if "pip" in command or command[0].endswith("uv"):
                (self.root / "browser-packages.partial" / "playwright").mkdir(parents=True)
            return ""

        real = dependencies.importlib.util.find_spec
        with (
            mock.patch.object(dependencies, "_run", side_effect=fake_run),
            mock.patch.object(dependencies, "prepare_browser"),
            mock.patch.object(
                dependencies.importlib.util,
                "find_spec",
                side_effect=lambda n: None if n == "playwright" else real(n),
            ),
            mock.patch.object(
                dependencies,
                "_pip_command",
                side_effect=lambda t: [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--target",
                    str(t),
                    f"playwright=={dependencies.PLAYWRIGHT_VERSION}",
                ],
            ),
        ):
            dependencies.install_browser()
        pip, chromium, launch = calls
        self.assertIn(f"playwright=={dependencies.PLAYWRIGHT_VERSION}", pip[0])
        self.assertTrue((self.root / "browser-packages" / "playwright").is_dir())
        self.assertFalse((self.root / "browser-packages.partial").exists())
        self.assertEqual(chromium[0][-3:], ["playwright", "install", "chromium"])
        self.assertEqual(
            chromium[1]["PLAYWRIGHT_BROWSERS_PATH"], str(self.root / "browser-browsers")
        )
        self.assertIn(str(self.root / "browser-packages"), chromium[1]["PYTHONPATH"])
        self.assertEqual(launch[0][1], "-c")

    def test_missing_system_libraries_give_the_exact_command_to_run(self):
        def fake_run(command, what, timeout, env=None):
            if command[1] == "-c":
                raise dependencies.DependencyError(
                    "error while loading shared libraries: libnss3.so"
                )
            return ""

        with (
            mock.patch.object(dependencies, "_run", side_effect=fake_run),
            mock.patch.object(dependencies, "prepare_browser"),
            mock.patch.object(dependencies.importlib.util, "find_spec", return_value=object()),
        ):
            with self.assertRaises(dependencies.DependencyError) as caught:
                dependencies.install_browser()
        message = str(caught.exception)
        self.assertIn("sudo", message)
        self.assertIn("-m playwright install-deps chromium", message)

    def test_a_failed_pip_leaves_no_half_installed_packages(self):
        def fake_run(command, what, timeout, env=None):
            (self.root / "browser-packages.partial").mkdir(parents=True)
            raise dependencies.DependencyError("no matching distribution")

        real = dependencies.importlib.util.find_spec
        with (
            mock.patch.object(dependencies, "_run", side_effect=fake_run),
            mock.patch.object(dependencies, "_pip_command", return_value=["pip"]),
            mock.patch.object(
                dependencies.importlib.util,
                "find_spec",
                side_effect=lambda n: None if n == "playwright" else real(n),
            ),
        ):
            with self.assertRaisesRegex(dependencies.DependencyError, "no matching"):
                dependencies.install_browser()
        self.assertFalse((self.root / "browser-packages.partial").exists())
        self.assertFalse((self.root / "browser-packages").exists())


class JobTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.addCleanup(lambda: dependencies._jobs["node"].update(task=None, error=""))
        patch = mock.patch.object(
            dependencies,
            "_node_state",
            return_value={"state": "missing", "detail": "", "can_install": True},
        )
        patch.start()
        self.addCleanup(patch.stop)
        dependencies._STATES["node"] = dependencies._node_state

    async def test_one_install_at_a_time_per_dependency(self):
        gate, started, calls = threading.Event(), threading.Event(), []

        def slow():
            calls.append(1)
            started.set()
            gate.wait(1)

        with mock.patch.dict(dependencies._installers, {"node": slow}):
            first = await dependencies.install("node")
            self.assertEqual(first["state"], "installing")
            await asyncio.to_thread(started.wait, 5)
            again = await dependencies.install("node")
            self.assertEqual(again["state"], "installing")
            gate.set()
            await dependencies._jobs["node"]["task"]
        self.assertEqual(len(calls), 1)

    async def test_a_failure_keeps_its_last_line_until_the_next_try(self):
        def broken():
            raise dependencies.DependencyError("the node download failed (ConnectError)")

        with mock.patch.dict(dependencies._installers, {"node": broken}):
            await dependencies.install("node")
            await dependencies._jobs["node"]["task"]
            row = await dependencies.state("node")
            self.assertEqual(row["state"], "failed")
            self.assertEqual(row["error"], "the node download failed (ConnectError)")
            self.assertTrue(row["can_install"])
        with mock.patch.dict(dependencies._installers, {"node": lambda: None}):
            await dependencies.install("node")
            await dependencies._jobs["node"]["task"]
            self.assertEqual((await dependencies.state("node"))["error"], "")

    async def test_an_unexpected_crash_still_ends_as_a_sentence(self):
        def crash():
            raise RuntimeError("boom")

        with mock.patch.dict(dependencies._installers, {"node": crash}):
            await dependencies.install("node")
            await dependencies._jobs["node"]["task"]
        row = await dependencies.state("node")
        self.assertEqual(row["state"], "failed")
        self.assertIn("RuntimeError", row["error"])
        self.assertNotIn("boom", row["error"])


class RouteTests(ApiTest):
    def test_list_has_one_row_per_dependency_with_the_agreed_fields(self):
        rows = {
            i: {"state": "missing", "detail": "x", "can_install": True} for i in dependencies.IDS
        }
        with mock.patch.dict(
            dependencies._STATES, {i: lambda i=i: rows[i] for i in dependencies.IDS}
        ):
            response = self.client.get("/api/system/dependencies")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([row["id"] for row in body], list(dependencies.IDS))
        for row in body:
            self.assertEqual(
                set(row),
                {"id", "name", "state", "version", "detail", "error", "can_install"}
                | ({"link"} & set(row)),
            )

    def test_install_starts_in_the_background_and_unknown_ids_are_refused(self):
        gate = threading.Event()
        with (
            mock.patch.dict(dependencies._installers, {"browser": lambda: gate.wait(1)}),
            mock.patch.dict(
                dependencies._STATES,
                {"browser": lambda: {"state": "missing", "detail": "", "can_install": True}},
            ),
        ):
            response = self.client.post("/api/system/dependencies/browser/install")
            gate.set()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "installing")
        self.assertEqual(
            self.client.post("/api/system/dependencies/docker/install").status_code, 422
        )
        dependencies._jobs["browser"].update(task=None, error="")
