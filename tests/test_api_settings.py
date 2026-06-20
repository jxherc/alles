import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cs
from tests._client import ApiTest


class SettingsApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(cs, "_SETTINGS_FILE", Path(self._tmp.name) / "settings.json")
        self._p.start()  # don't touch the real data/settings.json

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()
        super().tearDown()

    def test_get_returns_a_dict_of_defaults(self):
        s = self.client.get("/api/settings").json()
        self.assertIsInstance(s, dict)
        self.assertGreater(len(s), 0)

    def test_get_strips_secrets(self):
        cs.save_settings({"auth_password_hash": "x", "vault_verifier": "y", "vault_pw_b64": "z"})
        s = self.client.get("/api/settings").json()
        for secret in ("auth_password_hash", "vault_verifier", "vault_pw_b64"):
            self.assertNotIn(secret, s)

    def test_patch_persists_ai_defaults(self):
        r = self.client.patch(
            "/api/settings",
            json={
                "default_model": "deepseek-v4-pro",
                "context_limit": 42,
                "stream_thinking": False,
            },
        )
        self.assertEqual(r.status_code, 200)
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["default_model"], "deepseek-v4-pro")
        self.assertEqual(s["context_limit"], 42)
        self.assertEqual(s["stream_thinking"], False)

    def test_patch_appearance_theme_and_accent(self):
        self.client.patch("/api/settings", json={"theme": "light", "accent": "#ff0000"})
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["theme"], "light")  # synced across subdomains via the server
        self.assertEqual(s["accent"], "#ff0000")
        # and they can be reset
        self.client.patch("/api/settings", json={"theme": "", "accent": ""})
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["theme"], "")
        self.assertEqual(s["accent"], "")

    def test_unknown_keys_ignored(self):
        self.client.patch("/api/settings", json={"totally_made_up_key": "x"})
        self.assertNotIn("totally_made_up_key", self.client.get("/api/settings").json())

    def test_patch_notification_settings(self):
        r = self.client.patch(
            "/api/settings",
            json={
                "notify_discord_webhook": "https://discord.com/api/webhooks/123/abc",
                "notify_on_agent_done": True,
            },
        )
        self.assertEqual(r.status_code, 200)
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["notify_discord_webhook"], "https://discord.com/api/webhooks/123/abc")
        self.assertTrue(s["notify_on_agent_done"])

    def test_patch_calendar_settings(self):
        r = self.client.patch(
            "/api/settings",
            json={
                "cal_default_view": "week",
                "cal_week_start": "mon",
                "cal_default_duration_min": 60,
            },
        )
        self.assertEqual(r.status_code, 200)
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["cal_default_view"], "week")
        self.assertEqual(s["cal_week_start"], "mon")
        self.assertEqual(s["cal_default_duration_min"], 60)

    def test_patch_multiple_writes_accumulate(self):
        # two separate patches both stick — second doesn't erase first
        self.client.patch("/api/settings", json={"username": "alice"})
        self.client.patch("/api/settings", json={"theme": "light"})
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["username"], "alice")
        self.assertEqual(s["theme"], "light")

    def test_patch_bool_flags(self):
        self.client.patch(
            "/api/settings",
            json={"memory_auto_inject": True, "tts_auto_play": False, "auto_compact": True},
        )
        s = self.client.get("/api/settings").json()
        self.assertTrue(s["memory_auto_inject"])
        self.assertFalse(s["tts_auto_play"])
        self.assertTrue(s["auto_compact"])

    def test_patch_agent_permission_mode(self):
        self.client.patch("/api/settings", json={"agent_permission_mode": "approve"})
        s = self.client.get("/api/settings").json()
        self.assertEqual(s["agent_permission_mode"], "approve")

    def test_options_endpoint(self):
        r = self.client.get("/api/automations/options")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("triggers", d)
        self.assertIn("actions", d)
        self.assertGreater(len(d["triggers"]), 0)
