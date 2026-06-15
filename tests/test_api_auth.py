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
        self._env = os.environ.pop("AUTH_PASSWORD", None)   # deterministic: no seeded env password

    def tearDown(self):
        if self._env is not None:
            os.environ["AUTH_PASSWORD"] = self._env
        self._p.stop()
        self._tmp.cleanup()
        super().tearDown()

    def test_set_initial_password(self):
        r = self.client.post("/api/auth/change-password", json={"new_password": "secret1"})
        self.assertEqual(r.status_code, 200)

    def test_change_requires_correct_current(self):
        self.client.post("/api/auth/change-password", json={"new_password": "first1"})
        self.assertEqual(self.client.post("/api/auth/change-password",
                         json={"old_password": "wrong", "new_password": "second1"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/change-password",
                         json={"old_password": "first1", "new_password": "second1"}).status_code, 200)

    def test_short_password_rejected(self):
        self.assertEqual(self.client.post("/api/auth/change-password", json={"new_password": "ab"}).status_code, 400)

    def test_change_password_throttles_brute_force(self):
        from core import auth
        auth._login_fails.clear()
        self.client.post("/api/auth/change-password", json={"new_password": "first1"})
        # wrong current password, hammered: must eventually rate-limit (429) so the
        # endpoint isn't an unmetered oracle for the master password
        statuses = [self.client.post("/api/auth/change-password",
                    json={"old_password": "nope", "new_password": "second1"}).status_code
                    for _ in range(auth._LOGIN_MAX_FAILS + 1)]
        self.assertIn(429, statuses)
        auth._login_fails.clear()

    def test_username_round_trips_through_me(self):
        self.assertEqual(self.client.get("/api/auth/me").json().get("username"), "")
        self.client.patch("/api/settings", json={"username": "jxh"})
        self.assertEqual(self.client.get("/api/auth/me").json().get("username"), "jxh")
