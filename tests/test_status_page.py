"""public status page for watch monitors — served at /status (no auth) when enabled."""

import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from core.database import Monitor, MonitorCheck
from tests._client import ApiTest


class StatusPageTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        self._patcher = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._tmp.name))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        super().tearDown()

    def test_disabled_is_404(self):
        self.assertEqual(self.client.get("/status").status_code, 404)

    def test_enabled_renders_monitors(self):
        d = self.db()
        m = Monitor(name="MySite", url="https://mysite.example.com", kind="http")
        d.add(m)
        d.commit()
        d.add(MonitorCheck(monitor_id=m.id, ok=True, status_code=200, latency_ms=120))
        d.commit()
        d.close()
        core.settings.save_settings({"status_page_enabled": True, "status_page_title": "My Status"})
        r = self.client.get("/status")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("MySite", r.text)
        self.assertIn("My Status", r.text)
        self.assertIn("up", r.text)

    def test_config_roundtrip(self):
        self.assertEqual(
            self.client.put("/api/status/config", json={"enabled": True, "title": "Ops"}).status_code,
            200,
        )
        cfg = self.client.get("/api/status/config").json()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["title"], "Ops")
