# `unittest discover -s tests` imports test files as top-level modules in sorted order, so
# tests/__init__.py (the throwaway ALLES_DATA) only ran once some file imported `tests`. by then
# test_browser_passwords had already bound core.database to the owner's real data/aide.db.
# this file sorts first and sets the throwaway data before any app import. keep the name.
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tests  # noqa: F401

REPO_DATA = (Path(__file__).resolve().parent.parent / "data").resolve()


def _inside_repo_data(path) -> bool:
    resolved = Path(path).resolve()
    return resolved == REPO_DATA or REPO_DATA in resolved.parents


class DataIsolationTest(unittest.TestCase):
    def test_app_never_binds_the_real_data_folder(self):
        import core.database
        import core.settings

        for path in (
            core.database.DB_PATH,
            core.settings._SETTINGS_FILE,
            core.settings.data_dir(),
        ):
            self.assertFalse(_inside_repo_data(path), path)

    def test_a_unittest_run_without_throwaway_data_refuses_the_real_folder(self):
        repo = REPO_DATA.parent
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "test_guard.py").write_text(
                "import unittest\n"
                "import core.settings\n"
                "class T(unittest.TestCase):\n"
                "    def test_x(self):\n"
                "        pass\n",
                encoding="utf-8",
            )
            env = {k: v for k, v in os.environ.items() if not k.startswith("ALLES_")}
            env["PYTHONPATH"] = str(repo)
            done = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", tmp],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("tests need throwaway data", done.stderr)

    def test_this_file_sorts_before_every_other_test_file(self):
        here = Path(__file__).resolve()
        first = sorted(p.name for p in here.parent.glob("test*.py"))[0]
        self.assertEqual(first, here.name)


if __name__ == "__main__":
    unittest.main()
