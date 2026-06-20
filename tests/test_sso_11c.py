"""11c-1 — cross-subdomain SSO + auth scope, driven over HTTP against the real app.

The unit tests (test_auth.py) already cover the handoff dict mechanics; this covers the wire:
login sets the session, /me reflects it, the handoff code round-trips into a fresh cookie and
is single-use, and the middleware actually gates /api/ (except /api/auth/*) when the lock is on.
AUTH_ENABLED is read at call time, so each test flips the env var and isolates settings.
"""

import os
import tempfile
from pathlib import Path
from unittest import mock

import core.auth as ca
import core.settings as cs
from tests._client import ApiTest


class SsoTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(cs, "_SETTINGS_FILE", Path(self._tmp.name) / "settings.json")
        self._p.start()
        self._env = os.environ.pop("AUTH_PASSWORD", None)
        self._auth_env = os.environ.pop("AUTH_ENABLED", None)
        # clean module-global stores so tests don't bleed into each other
        ca._tokens.clear()
        ca._handoff.clear()
        ca._login_fails.clear()

    def tearDown(self):
        os.environ.pop("AUTH_ENABLED", None)
        if self._auth_env is not None:
            os.environ["AUTH_ENABLED"] = self._auth_env
        if self._env is not None:
            os.environ["AUTH_PASSWORD"] = self._env
        self._p.stop()
        self._tmp.cleanup()
        super().tearDown()

    def _enable(self, pw="hunter2"):
        self.client.post("/api/auth/change-password", json={"new_password": pw})
        os.environ["AUTH_ENABLED"] = "true"

    # ── /me shape ──────────────────────────────────────────────────────────────
    def test_me_disabled_shape(self):
        r = self.client.get("/api/auth/me").json()
        self.assertEqual(r["enabled"], False)
        self.assertEqual(r["authenticated"], True)
        self.assertIn("base_domain", r)

    def test_me_enabled_unauthed(self):
        self._enable()
        r = self.client.get("/api/auth/me").json()
        self.assertEqual(r["enabled"], True)
        self.assertEqual(r["authenticated"], False)

    def test_login_then_me_authed(self):
        self._enable("sesame123")
        lr = self.client.post("/api/auth/login", json={"password": "sesame123"})
        self.assertEqual(lr.status_code, 200)
        # the session cookie now rides on self.client
        r = self.client.get("/api/auth/me").json()
        self.assertEqual(r["authenticated"], True)

    def test_login_wrong_password(self):
        self._enable("rightpw")
        r = self.client.post("/api/auth/login", json={"password": "wrongpw"})
        self.assertEqual(r.status_code, 401)

    # ── handoff round-trip ───────────────────────────────────────────────────────
    def test_handoff_requires_auth(self):
        self._enable()
        r = self.client.get("/api/auth/handoff")
        self.assertEqual(r.status_code, 401)

    def test_full_handoff_redeem_roundtrip(self):
        self._enable("pw12345")
        self.client.post("/api/auth/login", json={"password": "pw12345"})
        code = self.client.get("/api/auth/handoff").json()["code"]
        self.assertTrue(code)
        # a *fresh* client (a different subdomain, no cookie) redeems the code
        from starlette.testclient import TestClient

        from app import app

        other = TestClient(app)
        rr = other.get(f"/api/auth/redeem?code={code}")
        self.assertEqual(rr.status_code, 200)
        # and now that client is authenticated
        self.assertEqual(other.get("/api/auth/me").json()["authenticated"], True)

    def test_handoff_single_use(self):
        self._enable("pw12345")
        self.client.post("/api/auth/login", json={"password": "pw12345"})
        code = self.client.get("/api/auth/handoff").json()["code"]
        self.assertEqual(self.client.get(f"/api/auth/redeem?code={code}").status_code, 200)
        # second redeem of the same code is rejected
        self.assertEqual(self.client.get(f"/api/auth/redeem?code={code}").status_code, 401)

    def test_redeem_bad_code(self):
        self._enable()
        self.assertEqual(self.client.get("/api/auth/redeem?code=nope").status_code, 401)

    def test_redeem_expired_code(self):
        self._enable("pw12345")
        self.client.post("/api/auth/login", json={"password": "pw12345"})
        # inject an already-expired entry pointing at a valid token
        tok = next(iter(ca._tokens))
        ca._handoff["stale"] = (0.0, tok)
        self.assertEqual(self.client.get("/api/auth/redeem?code=stale").status_code, 401)

    # ── middleware gating ──────────────────────────────────────────────────────
    def test_middleware_gates_api(self):
        self._enable()
        # no cookie + lock on → a normal /api route is blocked
        self.assertEqual(self.client.get("/api/projects").status_code, 401)

    def test_auth_routes_exempt(self):
        self._enable()
        # /api/auth/* is reachable without a session (so you can log in)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_api_open_when_disabled(self):
        # lock off → /api routes are open
        self.assertEqual(self.client.get("/api/projects").status_code, 200)

    # ── session lifecycle + cookie scope ─────────────────────────────────────────
    def test_logout_revokes(self):
        self._enable("pw12345")
        self.client.post("/api/auth/login", json={"password": "pw12345"})
        self.assertEqual(self.client.get("/api/auth/me").json()["authenticated"], True)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/auth/me").json()["authenticated"], False)

    def test_cookie_host_only_on_localhost(self):
        # base_domain is localhost in tests → the session cookie must be host-only
        # (no Domain=), since Domain=localhost wouldn't be sent to *.localhost anyway
        self._enable("pw12345")
        r = self.client.post("/api/auth/login", json={"password": "pw12345"})
        setc = r.headers.get("set-cookie", "")
        self.assertIn("aide_session=", setc)
        self.assertNotIn("domain=", setc.lower())
        self.assertIn("httponly", setc.lower())
