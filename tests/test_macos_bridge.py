import sys
import unittest

from services import macos_bridge as mb


class MacosBridgeTest(unittest.TestCase):
    def test_guards_off_mac(self):
        if sys.platform == "darwin":
            self.skipTest("on a mac — native path would run for real")
        for call in (
            lambda: mb.keychain_set("s", "a", "x"),
            lambda: mb.keychain_get("s", "a"),
            lambda: mb.keychain_delete("s", "a"),
            lambda: mb.export_calendar(),
            lambda: mb.export_reminders(),
        ):
            with self.assertRaises(NotImplementedError):
                call()

    def test_is_mac_reflects_platform(self):
        self.assertEqual(mb.is_mac(), sys.platform == "darwin")


if __name__ == "__main__":
    unittest.main()
