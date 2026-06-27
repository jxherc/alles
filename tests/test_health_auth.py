"""/health?deep=1 leaks internal readiness details (the data-dir path, installed deps, provider
state). it's a public route (not under /api/), so when auth is ON those details must NOT go to an
anonymous caller."""

from unittest import mock

import app as appmod
from tests._client import ApiTest


class HealthAuthTest(ApiTest):
    def test_basic_health_is_public(self):
        self.assertEqual(self.client.get("/health").json(), {"ok": True})

    def test_deep_health_shown_in_local_mode(self):
        # ApiTest runs with AUTH_ENABLED=false → local single-user, the readiness detail is fine
        r = self.client.get("/health?deep=1")
        self.assertIn("checks", r.json())

    def test_deep_health_hidden_from_anon_when_auth_on(self):
        with mock.patch.object(appmod, "auth_enabled", lambda: True):
            body = self.client.get("/health?deep=1").json()
        self.assertEqual(body, {"ok": True})       # liveness only
        self.assertNotIn("checks", body)            # no data-dir path / dep list leaked
