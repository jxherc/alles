import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import agent_tools as at


class AgentCwdTest(unittest.TestCase):
    def test_relative_resolves_to_root_by_default(self):
        with mock.patch.object(at, "_settings", lambda: {}):
            self.assertEqual(at._resolve("x.py"), (at.ROOT / "x.py").resolve())

    def test_relative_resolves_to_agent_cwd_when_set(self):
        tmp = tempfile.mkdtemp()
        with mock.patch.object(at, "_settings", lambda: {"agent_cwd": tmp}):
            self.assertEqual(at._resolve("fizzbuzz.py"), (Path(tmp) / "fizzbuzz.py").resolve())

    def test_absolute_path_is_untouched(self):
        tmp = tempfile.mkdtemp()
        ap = str(Path(tmp) / "abs.txt")
        with mock.patch.object(at, "_settings", lambda: {"agent_cwd": "/somewhere/else"}):
            self.assertEqual(at._resolve(ap), Path(ap).resolve())


if __name__ == "__main__":
    unittest.main()
