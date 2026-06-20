"""ui-7b — CardDAV gains a sync interval (off/hourly/daily) surfaced in status, settable via the
API, preserved across connect/disconnect, and an auto-sync that knows when it's due."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests._client import ApiTest


class CardDavIntervalLogic(unittest.TestCase):
    def setUp(self):
        from services import carddav_sync

        self.cs = carddav_sync
        self.tmp = Path(tempfile.mkdtemp()) / "carddav.json"
        self.p = mock.patch.object(carddav_sync, "_cfg_path", lambda: self.tmp)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_status_defaults_interval_off(self):
        self.assertEqual(self.cs.status()["interval"], "off")

    def test_set_interval_persists_and_shows_in_status(self):
        self.cs.set_interval("daily")
        self.assertEqual(self.cs.status()["interval"], "daily")

    def test_set_interval_rejects_garbage(self):
        self.cs.set_interval("daily")
        self.cs.set_interval("nope")  # ignored
        self.assertEqual(self.cs.status()["interval"], "daily")

    def test_connect_disconnect_preserve_interval(self):
        self.cs.set_interval("hourly")
        self.cs.save_cfg({"url": "https://dav", "username": "u", "password": "p"})
        self.assertEqual(self.cs.status()["interval"], "hourly")
        self.cs.save_cfg({"url": "", "username": "", "password": ""})
        self.assertEqual(self.cs.status()["interval"], "hourly")

    def test_due_for_sync_off_is_never(self):
        self.cs.save_cfg({"url": "https://dav", "username": "u", "password": "p"})
        self.cs.set_interval("off")
        self.assertFalse(self.cs.due_for_sync(10_000_000))

    def test_due_for_sync_needs_connection(self):
        self.cs.set_interval("hourly")  # but no url/username
        self.assertFalse(self.cs.due_for_sync(10_000_000))

    def test_due_for_sync_hourly(self):
        self.cs.save_cfg({"url": "https://dav", "username": "u", "password": "p"})
        self.cs.set_interval("hourly")
        # never synced → due now
        self.assertTrue(self.cs.due_for_sync(10_000_000))
        self.cs.stamp_sync(10_000_000)
        self.assertFalse(self.cs.due_for_sync(10_000_000 + 1800))  # 30 min later, not due
        self.assertTrue(self.cs.due_for_sync(10_000_000 + 3700))  # >1h later, due

    def test_due_for_sync_daily(self):
        self.cs.save_cfg({"url": "https://dav", "username": "u", "password": "p"})
        self.cs.set_interval("daily")
        self.cs.stamp_sync(10_000_000)
        self.assertFalse(self.cs.due_for_sync(10_000_000 + 3600 * 12))
        self.assertTrue(self.cs.due_for_sync(10_000_000 + 3600 * 25))


class CardDavIntervalApi(ApiTest):
    def setUp(self):
        super().setUp()
        from services import carddav_sync

        self.tmp = Path(tempfile.mkdtemp()) / "carddav.json"
        self.p = mock.patch.object(carddav_sync, "_cfg_path", lambda: self.tmp)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        super().tearDown()

    def test_status_endpoint_has_interval(self):
        r = self.client.get("/api/carddav/status")
        self.assertEqual(r.status_code, 200)
        self.assertIn("interval", r.json())

    def test_interval_endpoint_sets_it(self):
        r = self.client.post("/api/carddav/interval", json={"interval": "daily"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["interval"], "daily")
        self.assertEqual(self.client.get("/api/carddav/status").json()["interval"], "daily")


if __name__ == "__main__":
    unittest.main()
