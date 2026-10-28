import os
import tempfile
import unittest
from pathlib import Path

from core.tool_path import extend_tool_path


def _node(root: Path, version: str) -> Path:
    bin_dir = root / ".nvm" / "versions" / "node" / version / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "node").write_text("")
    return bin_dir


class ToolPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_bare_service_path_finds_nvm_node_first(self):
        _node(self.home, "v20.1.0")
        newest = _node(self.home, "v24.22.1")
        (self.home / ".local" / "bin").mkdir(parents=True)
        env = {"PATH": "/usr/bin:/bin"}
        extend_tool_path(env, self.home)
        parts = env["PATH"].split(os.pathsep)
        self.assertEqual(parts[0], str(newest))
        self.assertIn(str(self.home / ".local" / "bin"), parts)
        self.assertLess(parts.index(str(newest)), parts.index("/usr/bin"))

    def test_nvm_default_alias_wins_over_the_newest(self):
        chosen = _node(self.home, "v20.11.0")
        _node(self.home, "v24.22.1")
        (self.home / ".nvm" / "alias").mkdir(parents=True)
        (self.home / ".nvm" / "alias" / "default").write_text("20\n")
        env = {"PATH": "/usr/bin"}
        extend_tool_path(env, self.home)
        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(chosen))

    def test_nothing_is_added_twice_or_when_missing(self):
        bin_dir = _node(self.home, "v24.0.0")
        env = {"PATH": f"{bin_dir}:/usr/bin"}
        extend_tool_path(env, self.home)
        parts = env["PATH"].split(os.pathsep)
        self.assertEqual(parts.count(str(bin_dir)), 1)
        self.assertNotIn(str(self.home / ".volta" / "bin"), parts)
        extend_tool_path(env, self.home)
        self.assertEqual(env["PATH"].split(os.pathsep), parts)

    def test_runs_with_only_the_standard_library(self):
        import subprocess
        import sys

        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import core.tool_path as t; print(t.extend_tool_path({'PATH': '/usr/bin'}))",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
