import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cs
from tests._client import ApiTest


class AuthApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(cs, "_SETTINGS_FILE", Path(self._tmp.name) / "settings.json")
        self._p.start()
        cs._clear_settings_cache()
        self._env = os.environ.pop("AUTH_PASSWORD", None)  # deterministic: no seeded env password

    def tearDown(self):
        if self._env is not None:
            os.environ["AUTH_PASSWORD"] = self._env
        cs._clear_settings_cache()
        self._p.stop()
        self._tmp.cleanup()
        super().tearDown()

    def test_set_initial_password(self):
        r = self.client.post("/api/auth/change-password", json={"new_password": "secret1"})
        self.assertEqual(r.status_code, 200)

    def test_change_requires_correct_current(self):
        self.client.post("/api/auth/change-password", json={"new_password": "first1"})
        self.assertEqual(
            self.client.post(
                "/api/auth/change-password",
                json={"old_password": "wrong", "new_password": "second1"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/auth/change-password",
                json={"old_password": "first1", "new_password": "second1"},
            ).status_code,
            200,
        )

    def test_short_password_rejected(self):
        self.assertEqual(
            self.client.post("/api/auth/change-password", json={"new_password": "ab"}).status_code,
            400,
        )

    def test_change_password_throttles_brute_force(self):
        from core import auth

        auth._login_fails.clear()
        self.client.post("/api/auth/change-password", json={"new_password": "first1"})
        # wrong current password, hammered: must eventually rate-limit (429) so the
        # endpoint isn't an unmetered oracle for the master password
        statuses = [
            self.client.post(
                "/api/auth/change-password",
                json={"old_password": "nope", "new_password": "second1"},
            ).status_code
            for _ in range(auth._LOGIN_MAX_FAILS + 1)
        ]
        self.assertIn(429, statuses)
        auth._login_fails.clear()

    def test_username_round_trips_through_me(self):
        self.assertEqual(self.client.get("/api/auth/me").json().get("username"), "")
        self.client.patch("/api/settings", json={"username": "jxh"})
        self.assertEqual(self.client.get("/api/auth/me").json().get("username"), "jxh")

    def test_auth_enabled_env_wins_else_settings(self):
        saved = os.environ.pop("AUTH_ENABLED", None)
        try:
            cs.save_settings({"auth_enabled": True})
            self.assertTrue(cs.auth_enabled())  # env unset → settings decides
            cs.save_settings({"auth_enabled": False})
            self.assertFalse(cs.auth_enabled())
            os.environ["AUTH_ENABLED"] = "true"  # explicit env wins over settings
            self.assertTrue(cs.auth_enabled())
            os.environ["AUTH_ENABLED"] = "false"
            cs.save_settings({"auth_enabled": True})
            self.assertFalse(cs.auth_enabled())
        finally:
            os.environ.pop("AUTH_ENABLED", None)
            if saved is not None:
                os.environ["AUTH_ENABLED"] = saved

    def test_auth_enabled_settings_read_is_cached(self):
        saved = os.environ.pop("AUTH_ENABLED", None)
        try:
            cs._clear_settings_cache()
            cs._SETTINGS_FILE.write_text('{"auth_enabled": true}', "utf-8")
            calls = []
            path_cls = type(cs._SETTINGS_FILE)
            orig = path_cls.read_text

            def tracked(self, *args, **kwargs):
                if self == cs._SETTINGS_FILE:
                    calls.append(str(self))
                return orig(self, *args, **kwargs)

            with mock.patch.object(path_cls, "read_text", tracked):
                self.assertTrue(cs.auth_enabled())
                self.assertTrue(cs.auth_enabled())
            self.assertEqual(len(calls), 1)
        finally:
            os.environ.pop("AUTH_ENABLED", None)
            if saved is not None:
                os.environ["AUTH_ENABLED"] = saved
            cs._clear_settings_cache()

    def test_auth_config_enable_needs_password_then_works(self):
        # nothing set yet → can't enable
        self.assertEqual(
            self.client.post("/api/auth/config", json={"enabled": True}).status_code, 400
        )
        # supply a password inline → enables
        r = self.client.post("/api/auth/config", json={"enabled": True, "password": "secret1"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["enabled"])

    def test_auth_config_disable_requires_current_password(self):
        from core import auth as cauth

        cauth._login_fails.clear()
        self.client.post("/api/auth/config", json={"enabled": True, "password": "secret1"})
        self.assertEqual(
            self.client.post(
                "/api/auth/config", json={"enabled": False, "password": "nope"}
            ).status_code,
            401,
        )
        r = self.client.post("/api/auth/config", json={"enabled": False, "password": "secret1"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])
        cauth._login_fails.clear()

    def test_reauth_refreshes_an_expired_recent_owner_window(self):
        from core import auth as cauth

        cauth._login_fails.clear()
        cauth._tokens.clear()
        cauth._recent_auth.clear()
        self.client.post("/api/auth/config", json={"enabled": True, "password": "secret1"})
        self.assertEqual(
            self.client.post("/api/auth/login", json={"password": "secret1"}).status_code,
            200,
        )
        session = self.client.cookies.get("aide_session")
        cauth._recent_auth[session] = cauth.time.time() - cauth.RECENT_AUTH_SECONDS - 1
        os.environ["AUTH_ENABLED"] = "true"
        try:
            blocked = self.client.post("/api/tokens", json={"name": "blocked"})
            self.assertEqual(blocked.status_code, 403)
            self.assertEqual(
                self.client.post("/api/auth/reauth", json={"password": "wrong"}).status_code,
                401,
            )
            refreshed = self.client.post("/api/auth/reauth", json={"password": "secret1"})
            self.assertEqual(refreshed.status_code, 200)
            self.assertEqual(refreshed.json()["expires_in"], cauth.RECENT_AUTH_SECONDS)
            self.assertEqual(
                self.client.post("/api/tokens", json={"name": "allowed"}).status_code,
                200,
            )
        finally:
            os.environ["AUTH_ENABLED"] = "false"
            cauth._login_fails.clear()

    def test_reauth_requires_a_live_session(self):
        self.assertEqual(
            self.client.post("/api/auth/reauth", json={"password": "secret1"}).status_code,
            401,
        )

    def test_admin_bearer_does_not_replace_owner_reauth(self):
        self.client.post("/api/auth/config", json={"enabled": True, "password": "secret1"})
        raw = self.client.post(
            "/api/tokens", json={"name": "admin", "scopes": ["admin"]}
        ).json()["token"]
        os.environ["AUTH_ENABLED"] = "true"
        try:
            response = self.client.post(
                "/api/tokens",
                headers={"Authorization": f"Bearer {raw}"},
                json={"name": "another", "scopes": ["read"]},
            )
            self.assertEqual(response.status_code, 403)
        finally:
            os.environ["AUTH_ENABLED"] = "false"
