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


if __name__ == "__main__":
    unittest.main()
