import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import caldav_sync as cd


class CaldavSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(cd, "CFG_PATH", Path(self.tmp.name) / "caldav.json")
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def test_event_ics_all_day_uses_value_date(self):
        # an all-day event must be DTSTART;VALUE=DATE:YYYYMMDD, NOT a timed midnight event
        ics = cd._event_ics("u1", "Birthday", "2026-06-23T00:00:00", True)
        self.assertIn("DTSTART;VALUE=DATE:20260623", ics)
        self.assertNotIn("T000000", ics)  # not a timed event
        self.assertIn("SUMMARY:Birthday", ics)

    def test_event_ics_timed_keeps_time(self):
        ics = cd._event_ics("u2", "Meeting", "2026-06-23T14:30:00", False)
        self.assertIn("DTSTART:20260623T143000", ics)
        self.assertNotIn("VALUE=DATE", ics)

    def test_event_ics_timed_includes_end_and_description(self):
        # without DTEND a pushed event loses its end time on the next pull (round-trip data loss)
        ics = cd._event_ics(
            "u3", "Meeting", "2026-06-23T14:30:00", False,
            end_dt="2026-06-23T15:30:00", description="quarterly sync",
        )
        self.assertIn("DTEND:20260623T153000", ics)
        self.assertIn("DESCRIPTION:quarterly sync", ics)

    def test_event_ics_all_day_end_is_exclusive(self):
        # stored end is the inclusive last day; RFC all-day DTEND is exclusive → +1 day
        ics = cd._event_ics("u4", "Trip", "2026-07-01T00:00:00", True, end_dt="2026-07-03")
        self.assertIn("DTEND;VALUE=DATE:20260704", ics)  # jul 3 inclusive → jul 4 exclusive

    def test_event_ics_no_end_omits_dtend(self):
        ics = cd._event_ics("u5", "Solo", "2026-06-23T14:30:00", False)
        self.assertNotIn("DTEND", ics)

    def test_save_keeps_password_when_blank(self):
        cd.save_cfg({"url": "u1", "username": "me", "password": "secret"})
        cd.save_cfg({"url": "u2", "username": "me", "password": ""})  # editing without re-typing pw
        cfg = cd.load_cfg()
        self.assertEqual(cfg["url"], "u2")
        self.assertEqual(cfg["password"], "secret")  # preserved

    def test_status_shape(self):
        s = cd.status()
        self.assertIn("available", s)
        self.assertIn("connected", s)
        self.assertFalse(s["connected"])  # nothing configured

    def test_sync_is_graceful(self):
        # no caldav lib and/or no config → an {"error": ...} dict, never a crash
        r = cd.sync()
        self.assertIn("error", r)

    def test_save_and_load_roundtrip(self):
        cfg = {"url": "https://cal.example.com", "username": "bob", "password": "hunter2"}
        cd.save_cfg(cfg)
        loaded = cd.load_cfg()
        self.assertEqual(loaded["url"], "https://cal.example.com")
        self.assertEqual(loaded["username"], "bob")
        self.assertEqual(loaded["password"], "hunter2")

    def test_load_cfg_missing_returns_empty(self):
        # no file written yet → empty dict
        self.assertEqual(cd.load_cfg(), {})

    def test_status_connected_when_all_fields_present(self):
        cd.save_cfg({"url": "https://u", "username": "u", "password": "p"})
        s = cd.status()
        self.assertTrue(s["connected"])

    def test_status_not_connected_when_password_missing(self):
        cd.save_cfg({"url": "https://u", "username": "u", "password": ""})
        s = cd.status()
        self.assertFalse(s["connected"])

    def test_status_exposes_url_and_username(self):
        cd.save_cfg({"url": "https://dav.mine.com", "username": "alice", "password": "x"})
        s = cd.status()
        self.assertEqual(s["url"], "https://dav.mine.com")
        self.assertEqual(s["username"], "alice")

    def test_save_overwrites_url_keeps_old_password(self):
        cd.save_cfg({"url": "old", "username": "me", "password": "oldpw"})
        cd.save_cfg({"url": "new", "username": "me", "password": ""})
        self.assertEqual(cd.load_cfg()["url"], "new")
        self.assertEqual(cd.load_cfg()["password"], "oldpw")


if __name__ == "__main__":
    unittest.main()
