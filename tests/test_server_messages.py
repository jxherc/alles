import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "static" / "locales" / "server"


class ServerMessagesTest(unittest.TestCase):
    def test_every_server_message_is_listed_and_translated(self):
        # a new HTTPException or service error needs its line in every language's file
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "server_messages.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_files_stay_small_enough_to_fetch_on_a_language_switch(self):
        for path in SERVER.glob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))
            self.assertLess(path.stat().st_size, 400_000, path.name)


if __name__ == "__main__":
    unittest.main()
