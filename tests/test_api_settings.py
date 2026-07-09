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
        cs.save_settings({
            "auth_password_hash": "x",
            "vault_verifier": "y",
            "vault_pw_b64": "z",
            "vault_biometric_key": "bio",
            "vault_2fa_totp": {"main": "totp"},
            "journal_passcode": "pass",
            "mail_oauth_client_secret": "oauth",
            "openai_api_key": "sk-openai",
            "tavily_api_key": "tv",
            "brave_api_key": "br",
            "google_pse_api_key": "gp",
            "serper_api_key": "sp",
            "notify_discord_webhook": "https://discord.com/api/webhooks/123/abc",
            "notify_telegram_token": "tg",
        })
        s = self.client.get("/api/settings").json()
        for secret in (
            "auth_password_hash",
            "vault_verifier",
            "vault_pw_b64",
            "vault_biometric_key",
            "vault_2fa_totp",
            "journal_passcode",
            "mail_oauth_client_secret",
            "openai_api_key",
            "tavily_api_key",
            "brave_api_key",
            "google_pse_api_key",
            "serper_api_key",
            "notify_discord_webhook",
            "notify_telegram_token",
        ):
            self.assertNotIn(secret, s)
        self.assertTrue(s["openai_api_key_configured"])
        self.assertTrue(s["notify_discord_webhook_configured"])

    def test_patch_response_strips_secret_but_persists_it(self):
        r = self.client.patch("/api/settings", json={"openai_api_key": "sk-live"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertNotIn("openai_api_key", body)
        self.assertTrue(body["openai_api_key_configured"])
        self.assertEqual(cs.load_settings()["openai_api_key"], "sk-live")

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
        self.assertNotIn("notify_discord_webhook", s)
        self.assertTrue(s["notify_discord_webhook_configured"])
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
