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

    def test_dot_resolves_to_root_by_default(self):
        with mock.patch.object(at, "_settings", lambda: {}):
            self.assertEqual(at._resolve("."), at.ROOT.resolve())

    def test_nested_relative_under_cwd(self):
        tmp = tempfile.mkdtemp()
        with mock.patch.object(at, "_settings", lambda: {"agent_cwd": tmp}):
            result = at._resolve("a/b/c.py")
            self.assertEqual(result, (Path(tmp) / "a" / "b" / "c.py").resolve())

    def test_secret_paths_flagged(self):
        # .ssh, .env etc must be recognised regardless of cwd
        self.assertTrue(at._is_secret_path("/home/user/.ssh/id_rsa"))
        self.assertTrue(at._is_secret_path("/app/.env"))
        self.assertTrue(at._is_secret_path("/data/credentials.json"))
        self.assertTrue(at._is_secret_path("/cert/server.pem"))

    def test_normal_paths_not_flagged(self):
        self.assertFalse(at._is_secret_path("/home/user/code/app.py"))
        self.assertFalse(at._is_secret_path("C:/projects/alles/routes/money.py"))

    def test_guard_path_blocks_secret(self):
        with mock.patch.object(at, "_settings", lambda: {}):
            err = at._guard_path("/home/user/.ssh/id_rsa")
        self.assertIsNotNone(err)
        self.assertIn("blocked", err)

    def test_guard_path_allows_normal(self):
        with mock.patch.object(at, "_settings", lambda: {}):
            err = at._guard_path("/home/user/code/app.py")
        self.assertIsNone(err)

    def test_agent_allow_secrets_bypasses_block(self):
        with mock.patch.object(at, "_settings", lambda: {"agent_allow_secrets": True}):
            err = at._guard_path("/home/user/.ssh/id_rsa")
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
