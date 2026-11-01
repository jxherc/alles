"""the /api/signin contract the frontend is built against.

this file checks every field and type the screens may read, so a backend change that
quietly drops or renames a field fails here before it reaches the frontend.
"""

import base64
import json
import os
import re
from unittest import mock
from urllib.parse import parse_qs

import httpx

from core.settings import data_dir, save_settings
from services import signin
from tests._client import ApiTest

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FLOWS = {"device", "redirect", "paste_code"}
STATES = {"waiting", "done", "expired", "denied", "cancelled", "error"}
ACCOUNT_STATES = {"ok", "needs_sign_in", "error"}
NOT_READY_CODES = {"no_client_id", "no_client", "needs_https"}


def _jwt(claims: dict) -> str:
    def part(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}."


def _assert_simple_text(test, value):
    test.assertIsInstance(value, str)
    test.assertTrue(value)
    test.assertEqual(value, value.strip())


class SigninContractTest(ApiTest):
    def setUp(self):
        super().setUp()
        signin._attempts.clear()
        signin._by_use.clear()
        signin._tasks.clear()
        save_settings(
            {
                "signin_github_client_id": "github-client",
                "signin_microsoft_client_id": "microsoft-client",
                "mail_oauth_client_id": "google-client",
                "mail_oauth_client_secret": "google-secret",
                "mail_oauth_redirect_base": "https://alles.example",
            }
        )
        for name in ("signin-accounts.json", "caldav.json"):
            (data_dir() / name).unlink(missing_ok=True)
            (data_dir() / f".{name}-{os.getpid()}").unlink(missing_ok=True)
        spawn = mock.patch.object(signin, "_spawn", lambda attempt: None)
        spawn.start()
        self.addCleanup(spawn.stop)

    def tearDown(self):
        save_settings(
            {
                "signin_github_client_id": "",
                "signin_microsoft_client_id": "",
                "mail_oauth_client_id": "",
                "mail_oauth_client_secret": "",
                "mail_oauth_redirect_base": "",
            }
        )
        signin._attempts.clear()
        signin._by_use.clear()
        signin._tasks.clear()
        super().tearDown()

    def fake_async(self, handler):
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            return real(*args, transport=httpx.MockTransport(handler), **kwargs)

        patch = mock.patch("services.signin_providers.httpx.AsyncClient", side_effect=factory)
        patch.start()
        self.addCleanup(patch.stop)

    def device_handler(self):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/login/device/code":
                return httpx.Response(
                    200,
                    json={
                        "device_code": "dev-1",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://github.com/login/device",
                        "expires_in": 900,
                        "interval": 0,
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        return handle

    def test_providers_contract(self):
        response = self.client.get("/api/signin/providers")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"providers"})
        self.assertIsInstance(body["providers"], list)
        self.assertTrue(body["providers"])
        for provider in body["providers"]:
            self.assertEqual(
                set(provider),
                {"id", "name", "flow", "ready", "not_ready", "uses"},
            )
            self.assertIsInstance(provider["id"], str)
            self.assertIsInstance(provider["name"], str)
            self.assertIn(provider["flow"], FLOWS)
            self.assertIsInstance(provider["ready"], bool)
            if provider["ready"]:
                self.assertIsNone(provider["not_ready"])
            else:
                self.assertEqual(set(provider["not_ready"]), {"code", "text"})
                self.assertIn(provider["not_ready"]["code"], NOT_READY_CODES)
                _assert_simple_text(self, provider["not_ready"]["text"])
            self.assertIsInstance(provider["uses"], list)
            for use in provider["uses"]:
                self.assertEqual(set(use), {"id", "name"})
                self.assertIn(use["id"], {"github", "mail", "calendar", "models"})
                self.assertIsInstance(use["name"], str)

    def test_device_start_and_attempt_contract(self):
        self.fake_async(self.device_handler())
        response = self.client.post(
            "/api/signin/start", json={"provider": "github", "use": "github"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        started = response.json()
        self.assertEqual(
            set(started),
            {
                "attempt",
                "provider",
                "use",
                "flow",
                "user_code",
                "verify_url",
                "verify_url_complete",
                "expires_at",
                "poll_every",
            },
        )
        self.assertIsInstance(started["attempt"], str)
        self.assertEqual((started["provider"], started["use"]), ("github", "github"))
        self.assertEqual(started["flow"], "device")
        self.assertIsInstance(started["user_code"], str)
        self.assertIsInstance(started["verify_url"], str)
        self.assertIn(started["verify_url_complete"], (None, str))
        self.assertRegex(started["expires_at"], DATE)
        self.assertIsInstance(started["poll_every"], int)

        attempt = self.client.get(f"/api/signin/attempts/{started['attempt']}")
        self.assertEqual(attempt.status_code, 200, attempt.text)
        body = attempt.json()
        self.assertEqual(set(body), {"attempt", "provider", "use", "state", "error", "account"})
        self.assertEqual(body["attempt"], started["attempt"])
        self.assertEqual((body["provider"], body["use"]), ("github", "github"))
        self.assertIn(body["state"], STATES)
        self.assertEqual(body["state"], "waiting")
        self.assertIsNone(body["error"])
        self.assertIsNone(body["account"])

    def test_cancel_contract(self):
        self.fake_async(self.device_handler())
        started = self.client.post(
            "/api/signin/start", json={"provider": "github", "use": "github"}
        ).json()
        response = self.client.post(f"/api/signin/attempts/{started['attempt']}/cancel")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"attempt", "state"})
        self.assertEqual(body, {"attempt": started["attempt"], "state": "cancelled"})
        self.assertEqual(
            self.client.get(f"/api/signin/attempts/{started['attempt']}").json()["state"],
            "cancelled",
        )

    def test_unknown_attempt_is_a_404_with_detail_and_code(self):
        response = self.client.get("/api/signin/attempts/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(set(response.json()), {"detail", "code"})
        _assert_simple_text(self, response.json()["detail"])
        self.assertIsInstance(response.json()["code"], str)

    def test_not_ready_is_a_409_with_detail_and_code(self):
        save_settings({"signin_github_client_id": ""})
        response = self.client.post(
            "/api/signin/start", json={"provider": "github", "use": "github"}
        )
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(set(body), {"detail", "code"})
        self.assertEqual(body["code"], "not_ready")
        _assert_simple_text(self, body["detail"])

    def test_provider_error_is_a_502_with_the_provider_message(self):
        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"message": "device flow is disabled"})

        self.fake_async(handle)
        response = self.client.post(
            "/api/signin/start", json={"provider": "github", "use": "github"}
        )
        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(set(body), {"detail", "code"})
        self.assertEqual(body["code"], "provider_error")
        self.assertIn("device flow is disabled", body["detail"])

    def test_redirect_start_contract(self):
        response = self.client.post("/api/signin/start", json={"provider": "google", "use": "mail"})
        self.assertEqual(response.status_code, 200, response.text)
        started = response.json()
        self.assertEqual(set(started), {"attempt", "provider", "use", "flow", "url"})
        self.assertEqual(
            (started["provider"], started["use"], started["flow"]), ("google", "mail", "redirect")
        )
        self.assertTrue(started["url"].startswith("https://accounts.google.com/"))
        from urllib.parse import unquote

        self.assertIn("api/signin/callback/google", unquote(started["url"]))

    def test_paste_code_start_contract(self):
        response = self.client.post(
            "/api/signin/start", json={"provider": "anthropic", "use": "models"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        started = response.json()
        self.assertEqual(set(started), {"attempt", "provider", "use", "flow", "url"})
        self.assertEqual(
            (started["provider"], started["use"], started["flow"]),
            ("anthropic", "models", "paste_code"),
        )
        self.assertTrue(started["url"].startswith("https://claude.ai/oauth/authorize"))

    def test_accounts_and_account_contract(self):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/oauth/token":
                body = json.loads(request.content)
                if body.get("grant_type") == "refresh_token":
                    return httpx.Response(
                        200,
                        json={
                            "access_token": "sk-ant-oat-2",
                            "refresh_token": "anthropic-refresh-2",
                            "expires_in": 3600,
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "access_token": "sk-ant-oat-1",
                        "refresh_token": "anthropic-refresh-1",
                        "expires_in": 3600,
                        "id_token": _jwt({"email": "owner@claude.test"}),
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        self.fake_async(handle)
        started = self.client.post(
            "/api/signin/start", json={"provider": "anthropic", "use": "models"}
        ).json()
        state = signin._attempts[started["attempt"]]["state_token"]
        finished = self.client.post(
            f"/api/signin/attempts/{started['attempt']}/code",
            json={"code": f"the-code#{state}"},
        )
        self.assertEqual(finished.status_code, 200, finished.text)
        self.assertEqual(finished.json()["state"], "done")

        attempt = self.client.get(f"/api/signin/attempts/{started['attempt']}").json()
        self.assertEqual(attempt["state"], "done")
        self.assertTrue(attempt["account"])

        response = self.client.get("/api/signin/accounts")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"accounts"})
        self.assertIsInstance(body["accounts"], list)
        item = body["accounts"][0]
        self.assertEqual(
            set(item),
            {
                "id",
                "provider",
                "use",
                "login",
                "email",
                "scopes",
                "state",
                "error",
                "signed_in_at",
                "refreshed_at",
                "expires_at",
            },
        )
        self.assertIsInstance(item["id"], str)
        self.assertEqual((item["provider"], item["use"]), ("anthropic", "models"))
        self.assertIsInstance(item["login"], str)
        self.assertTrue(item["email"] is None or isinstance(item["email"], str))
        self.assertIsInstance(item["scopes"], list)
        self.assertTrue(all(isinstance(scope, str) for scope in item["scopes"]))
        self.assertIn(item["state"], ACCOUNT_STATES)
        self.assertIsNone(item["error"])
        self.assertRegex(item["signed_in_at"], DATE)
        self.assertTrue(item["refreshed_at"] is None or isinstance(item["refreshed_at"], str))
        self.assertRegex(item["expires_at"], DATE)

        checked = self.client.post(f"/api/signin/accounts/{item['id']}/check")
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertEqual(set(checked.json()), set(item))
        self.assertEqual(checked.json()["state"], "ok")

        signed_out = self.client.delete(f"/api/signin/accounts/{item['id']}")
        self.assertEqual(signed_out.status_code, 200, signed_out.text)
        self.assertEqual(set(signed_out.json()), {"id", "signed_out", "revoked"})
        self.assertEqual(signed_out.json()["id"], item["id"])
        self.assertIs(signed_out.json()["signed_out"], True)
        self.assertIsInstance(signed_out.json()["revoked"], bool)
        self.assertEqual(self.client.get("/api/signin/accounts").json(), {"accounts": []})

    def test_redirect_callback_finishes_and_sends_the_browser_back(self):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/token":
                form = parse_qs(request.content.decode())
                self.assertEqual(form["code"], ["google-code"])
                return httpx.Response(
                    200,
                    json={
                        "access_token": "google-access",
                        "refresh_token": "google-refresh",
                        "expires_in": 3600,
                        "scope": "https://mail.google.com/ openid email",
                        "id_token": _jwt({"email": "owner@gmail.test"}),
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        self.fake_async(handle)
        started = self.client.post(
            "/api/signin/start", json={"provider": "google", "use": "mail"}
        ).json()
        state = signin._attempts[started["attempt"]]["state_token"]
        callback = self.client.get(
            f"/api/signin/callback/google?code=google-code&state={state}",
            follow_redirects=False,
        )
        self.assertEqual(callback.status_code, 303)
        self.assertEqual(
            callback.headers["location"],
            f"http://testserver/?signin={started['attempt']}",
        )
        attempt = self.client.get(f"/api/signin/attempts/{started['attempt']}").json()
        self.assertEqual(attempt["state"], "done")
        self.assertEqual(attempt["account"]["provider"], "google")

    def test_recent_owner_is_required_to_start_and_sign_out(self):
        with mock.patch("core.settings.auth_enabled", return_value=True):
            started = self.client.post(
                "/api/signin/start", json={"provider": "anthropic", "use": "models"}
            )
            self.assertEqual(started.status_code, 403)
            self.assertEqual(started.json()["code"], "recent_auth_required")
            self.assertEqual(set(started.json()), {"detail", "code"})
