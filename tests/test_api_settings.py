import json
import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cs
import services.secretstore as secretstore
from tests._client import ApiTest


class SettingsApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(cs, "_SETTINGS_FILE", Path(self._tmp.name) / "settings.json")
        self._kp = mock.patch.object(secretstore, "_KEY_FILE", Path(self._tmp.name) / "secret.key")
        self._p.start()  # don't touch the real data/settings.json
        self._kp.start()
        secretstore._key = None
        secretstore._key_path = None

    def tearDown(self):
        self._kp.stop()
        self._p.stop()
        self._tmp.cleanup()
        super().tearDown()

    def test_get_returns_a_dict_of_defaults(self):
        s = self.client.get("/api/settings").json()
        self.assertIsInstance(s, dict)
        self.assertGreater(len(s), 0)

    def test_get_strips_secrets(self):
        cs.save_settings(
            {
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
                "notify_telegram_chat_id": "private-chat",
                "outbound_proxy": "https://user:pass@proxy.test:443?token=query-secret",
            }
        )
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
            "notify_telegram_chat_id",
        ):
            self.assertNotIn(secret, s)
        self.assertTrue(s["openai_api_key_configured"])
        self.assertTrue(s["notify_discord_webhook_configured"])
        self.assertTrue(s["notify_telegram_chat_id_configured"])
        self.assertNotIn("pass", s["outbound_proxy"])
        self.assertNotIn("query-secret", s["outbound_proxy"])

    def test_patch_response_strips_secret_but_persists_it(self):
        r = self.client.patch("/api/settings", json={"openai_api_key": "sk-live"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertNotIn("openai_api_key", body)
        self.assertTrue(body["openai_api_key_configured"])
        self.assertEqual(cs.load_settings()["openai_api_key"], "sk-live")
        raw = json.loads(cs._SETTINGS_FILE.read_text("utf-8"))["openai_api_key"]
        self.assertTrue(raw.startswith("enc2:"))
        self.assertNotIn("sk-live", cs._SETTINGS_FILE.read_text("utf-8"))
        self.assertTrue((Path(self._tmp.name) / "secret.key").is_file())

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

    def test_patch_validates_and_persists_model_roles(self):
        roles = {
            "aide_chat": {"endpoint_id": "ep-a", "model": "chat-a"},
            "andromeda": {"endpoint_id": "ep-b", "model": "search-b"},
            "jarvis": {"endpoint_id": "ep-c", "model": "background-c"},
        }
        response = self.client.patch("/api/settings", json={"model_roles": roles})
        self.assertEqual(response.status_code, 200)
        saved = response.json()["model_roles"]
        self.assertEqual(saved["andromeda"]["model"], "search-b")
        self.assertEqual(saved["jarvis"]["fallbacks"], [])

        invalid = self.client.patch(
            "/api/settings", json={"model_roles": {"unknown": {"model": "x"}}}
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json()["code"], "invalid_model_roles")

    def test_plaintext_setting_secret_is_migrated(self):
        cs._SETTINGS_FILE.write_text('{"openai_api_key":"old-plaintext"}', "utf-8")
        cs._clear_settings_cache()
        self.assertEqual(cs.migrate_setting_secrets(), 1)
        raw = json.loads(cs._SETTINGS_FILE.read_text("utf-8"))["openai_api_key"]
        self.assertTrue(raw.startswith("enc2:"))
        self.assertNotIn("old-plaintext", raw)
        self.assertEqual(cs.load_settings()["openai_api_key"], "old-plaintext")

    def test_corrupt_encrypted_setting_fails_closed(self):
        cs._SETTINGS_FILE.write_text('{"openai_api_key":"enc2:0000000000000000:broken"}', "utf-8")
        cs._clear_settings_cache()
        with self.assertRaises(secretstore.SecretStoreError):
            cs.load_settings()

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

    def test_patch_localization_settings(self):
        response = self.client.patch(
            "/api/settings",
            json={"language": "EN", "region": "tw", "timezone": "Asia/Taipei"},
        )
        self.assertEqual(response.status_code, 200)
        saved = response.json()
        self.assertEqual(saved["language"], "en")
        self.assertEqual(saved["region"], "TW")
        self.assertEqual(saved["timezone"], "Asia/Taipei")

    def test_rejects_unreviewed_language_and_invalid_locale_values(self):
        cases = (
            ({"language": "fr"}, "unsupported_language"),
            ({"region": "taiwan"}, "invalid_region"),
            ({"timezone": "Taipei-ish"}, "invalid_timezone"),
        )
        for patch, code in cases:
            with self.subTest(patch=patch):
                response = self.client.patch("/api/settings", json=patch)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], code)

    def test_agent_allowed_roots_are_existing_normalized_folders(self):
        root = Path(self._tmp.name) / "allowed"
        root.mkdir()
        response = self.client.patch("/api/settings", json={"agent_allowed_roots": [str(root)]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["agent_allowed_roots"], [str(root.resolve())])
        rejected = self.client.patch("/api/settings", json={"agent_allowed_roots": ["relative"]})
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.json()["code"], "invalid_agent_root")
        filesystem_root = self.client.patch(
            "/api/settings", json={"agent_allowed_roots": [str(Path(root.anchor))]}
        )
        self.assertEqual(filesystem_root.status_code, 400)
        self.assertEqual(filesystem_root.json()["code"], "invalid_agent_root")
        too_many = self.client.patch(
            "/api/settings", json={"agent_allowed_roots": [str(root)] * 17}
        )
        self.assertEqual(too_many.status_code, 400)
        self.assertEqual(too_many.json()["code"], "invalid_agent_root")

    def test_agent_allowed_roots_require_recent_owner_auth(self):
        from core import auth

        root = Path(self._tmp.name) / "allowed"
        root.mkdir()
        token = auth.create_session_token()
        auth.store_token(token)
        auth._recent_auth[token] = 0
        self.client.cookies.set("aide_session", token)
        try:
            with (
                mock.patch("app.auth_enabled", return_value=True),
                mock.patch("core.settings.auth_enabled", return_value=True),
            ):
                response = self.client.patch(
                    "/api/settings", json={"agent_allowed_roots": [str(root)]}
                )
        finally:
            self.client.cookies.clear()
            auth.revoke_token(token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "recent_auth_required")

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
