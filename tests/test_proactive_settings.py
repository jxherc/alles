import tempfile
from pathlib import Path

import core.settings as cfg
from tests._client import ApiTest


class ProactiveSettingsTests(ApiTest):
    def setUp(self):
        super().setUp()
        # isolate the settings file so we never touch the real data/settings.json
        self._orig_file = cfg._SETTINGS_FILE
        cfg._SETTINGS_FILE = Path(tempfile.mkdtemp()) / "settings.json"

    def tearDown(self):
        cfg._SETTINGS_FILE = self._orig_file
        super().tearDown()

    def test_defaults(self):
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["pidx_proactive_enabled"], False)  # OFF by default
        self.assertEqual(s["pidx_proactive_cat_task"], True)
        self.assertEqual(s["pidx_proactive_every_hours"], 6)

    def test_patch_roundtrip(self):
        self.client.patch("/api/settings", json={"pidx_proactive_enabled": True,
                                                 "pidx_proactive_every_hours": 12})
        s = self.client.get("/api/settings").json()
        self.assertTrue(s["pidx_proactive_enabled"])
        self.assertEqual(s["pidx_proactive_every_hours"], 12)

    def test_category_toggle_persists(self):
        self.client.patch("/api/settings", json={"pidx_proactive_cat_sub": False})
        s = self.client.get("/api/settings").json()
        self.assertFalse(s["pidx_proactive_cat_sub"])
