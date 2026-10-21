import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ModulePreloadTest(unittest.TestCase):
    def test_index_lists_every_startup_module(self):
        # a stale list sends startup back to a dozen round trips deep
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "modulepreload.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()
