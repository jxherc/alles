"""ui-0d — boot-state decision + 'no model' copy + 'not running' screen. The decision is a pure
JS function (run through node); the copy/markup contracts are scanned from source."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _state(reachable, authed):
    node = shutil.which("node")
    assert node, "node required"
    code = (
        "import {chooseBootState} from './static/js/bootstate.js';"
        f"process.stdout.write(JSON.stringify(chooseBootState({json.dumps(reachable)},{json.dumps(authed)})));"
    )
    out = subprocess.run(
        [node, "--input-type=module", "-e", code], cwd=str(ROOT), capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


class BootStateTests(unittest.TestCase):
    def test_down_and_no_session_is_notrunning(self):
        self.assertEqual(_state(False, False), "notrunning")

    def test_down_but_cached_session_still_boots(self):
        self.assertEqual(_state(False, True), "boot")

    def test_up_and_not_authed_is_login(self):
        self.assertEqual(_state(True, False), "login")

    def test_up_and_authed_boots(self):
        self.assertEqual(_state(True, True), "boot")

    def test_init_uses_chooseBootState_for_notrunning(self):
        self.assertIn("chooseBootState(reachable, me.authenticated)", APP)
        self.assertIn("_showNotRunning()", APP)

    def test_no_model_copy_simplified(self):
        self.assertNotIn("add one in settings", APP)
        self.assertIn("'no model'", APP)

    def test_notrunning_screen_markup_present(self):
        self.assertIn('id="notrunning-screen"', INDEX)
        self.assertIn('id="notrunning-retry"', INDEX)

    def test_notrunning_message_explains(self):
        self.assertIn("isn't running", INDEX)


if __name__ == "__main__":
    unittest.main()
