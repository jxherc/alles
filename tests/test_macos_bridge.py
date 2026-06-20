import sys
import unittest

from services import macos_bridge as mb
from tests._client import ApiTest

_NOT_MAC = sys.platform != "darwin"

_ICAL_SAMPLE = """\
• Standup
    today at 9:00 AM - 9:15 AM
• Dentist
    tomorrow at 2:00 PM
• Ship 11a
"""


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


class MacCapabilitiesTest(unittest.TestCase):
    def test_capabilities_shape(self):
        cap = mb.capabilities()
        for k in ("platform", "available", "keychain", "eventkit", "photokit", "icloud"):
            self.assertIn(k, cap)

    def test_capabilities_available_matches_platform(self):
        self.assertEqual(mb.capabilities()["available"], sys.platform == "darwin")

    def test_icloud_dir_off_darwin(self):
        if _NOT_MAC:
            self.assertIsNone(mb.icloud_drive_dir())


class MacIcalParseTest(unittest.TestCase):
    def test_parse_ical_basic(self):
        rows = mb._parse_ical_output(_ICAL_SAMPLE)
        self.assertEqual(rows[0]["title"], "Standup")
        self.assertIn("9:00", rows[0]["detail"])

    def test_parse_ical_empty(self):
        self.assertEqual(mb._parse_ical_output(""), [])

    def test_parse_ical_multiple(self):
        rows = mb._parse_ical_output(_ICAL_SAMPLE)
        self.assertEqual([r["title"] for r in rows], ["Standup", "Dentist", "Ship 11a"])


class MacApiTest(ApiTest):
    def test_api_status_has_available(self):
        st = self.client.get("/api/macos/status").json()
        self.assertIn("available", st)
        self.assertEqual(st["available"], sys.platform == "darwin")

    def test_api_calendar_503_off_darwin(self):
        if _NOT_MAC:
            self.assertEqual(self.client.post("/api/macos/calendar").status_code, 503)


if __name__ == "__main__":
    unittest.main()
