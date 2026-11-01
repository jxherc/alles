import asyncio
import base64
import json
import os
import time
from unittest import mock
from urllib.parse import parse_qs

import httpx

from core.settings import data_dir, save_settings
from services import caldav_sync, signin
from tests._client import ApiTest


def _jwt(claims: dict) -> str:
    def part(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}."


class SigninFlowTest(ApiTest):
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
                "mail_oauth_redirect_base": "",
            }
        )
        for name in ("signin-accounts.json", "caldav.json"):
            path = data_dir() / name
            path.unlink(missing_ok=True)
            (data_dir() / f".{name}-{os.getpid()}").unlink(missing_ok=True)

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

    def fake_sync(self, handler):
        real = httpx.Client

        def factory(*args, **kwargs):
            return real(*args, transport=httpx.MockTransport(handler), **kwargs)

        patch = mock.patch("services.signin_providers.httpx.Client", side_effect=factory)
        patch.start()
        self.addCleanup(patch.stop)

    def run_device(self, provider, use):
        async def go():
            started = await signin.start(provider, use, origin="http://localhost:8321")
            task = signin._tasks.get(started["attempt"])
            if task is not None:
                await task
            return started

        return asyncio.run(go())

    def github_handler(self, polls=None, *, refresh=None):
        polls = list(polls or [{"access_token": "gh-access", "scope": "repo,read:user"}])
        calls = {"polls": 0, "refresh": 0, "user": 0}

        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/login/device/code":
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
            if path == "/login/oauth/access_token":
                form = parse_qs(request.content.decode())
                if form.get("grant_type") == ["refresh_token"]:
                    calls["refresh"] += 1
                    answer = refresh or {
                        "access_token": "gh-refreshed",
                        "refresh_token": "gh-refresh-2",
                        "expires_in": 3600,
                        "scope": "repo",
                    }
                    if isinstance(answer, httpx.Response):
                        return answer
                    return httpx.Response(200, json=answer)
                calls["polls"] += 1
                answer = polls.pop(0) if polls else {"error": "authorization_pending"}
                return httpx.Response(200 if "access_token" in answer else 400, json=answer)
            if path == "/user":
                calls["user"] += 1
                return httpx.Response(200, json={"login": "jxherc", "email": "jx@example.test"})
            return httpx.Response(404, json={"message": "not found"})

        return handle, calls

    def microsoft_handler(self, polls=None):
        polls = list(
            polls
            or [
                {
                    "access_token": "ms-access",
                    "refresh_token": "ms-refresh",
                    "expires_in": 3600,
                    "scope": "IMAP.AccessAsUser.All SMTP.Send",
                    "id_token": _jwt({"preferred_username": "me@outlook.com"}),
                }
            ]
        )
        calls = {"polls": 0, "refresh": 0}

        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/common/oauth2/v2.0/devicecode":
                return httpx.Response(
                    200,
                    json={
                        "device_code": "ms-dev",
                        "user_code": "WXYZ-1234",
                        "verification_uri": "https://microsoft.com/devicelogin",
                        "expires_in": 900,
                        "interval": 0,
                    },
                )
            if path == "/common/oauth2/v2.0/token":
                form = parse_qs(request.content.decode())
                if form.get("grant_type") == ["refresh_token"]:
                    calls["refresh"] += 1
                    return httpx.Response(
                        200,
                        json={
                            "access_token": "ms-access-2",
                            "refresh_token": "ms-refresh-2",
                            "expires_in": 3600,
                        },
                    )
                calls["polls"] += 1
                answer = polls.pop(0) if polls else {"error": "authorization_pending"}
                return httpx.Response(200 if "access_token" in answer else 400, json=answer)
            return httpx.Response(404, json={"message": "not found"})

        return handle, calls

    def test_github_device_happy_path_stores_the_connection_token(self):
        handler, calls = self.github_handler()
        self.fake_async(handler)
        started = self.run_device("github", "github")

        self.assertEqual(started["flow"], "device")
        self.assertEqual(started["user_code"], "ABCD-EFGH")
        self.assertEqual(started["poll_every"], 0)
        attempt = signin.get_attempt(started["attempt"])
        self.assertEqual(attempt["state"], "done", attempt)
        self.assertEqual(attempt["account"]["login"], "jxherc")
        self.assertEqual(attempt["account"]["scopes"], ["repo", "read:user"])
        self.assertEqual(calls["polls"], 1)

        from core.database import Connection, SessionLocal

        db = SessionLocal()
        try:
            row = db.query(Connection).filter(Connection.service == "github").one()
            self.assertEqual(row.token, "gh-access")
            self.assertEqual(json.loads(row.meta)["signin"]["login"], "jxherc")
        finally:
            db.close()
        from services.connections import get_token

        self.assertEqual(get_token("github"), "gh-access")

    def test_microsoft_device_happy_path_stores_an_outlook_mail_account(self):
        handler, calls = self.microsoft_handler()
        self.fake_async(handler)
        started = self.run_device("microsoft", "mail")

        self.assertEqual(started["flow"], "device")
        attempt = signin.get_attempt(started["attempt"])
        self.assertEqual(attempt["state"], "done", attempt)
        self.assertEqual(attempt["account"]["provider"], "microsoft")
        self.assertEqual(attempt["account"]["email"], "me@outlook.com")
        self.assertEqual(calls["polls"], 1)

        from core.database import MailAccount, SessionLocal

        db = SessionLocal()
        try:
            account = db.query(MailAccount).filter(MailAccount.email == "me@outlook.com").one()
            self.assertEqual(account.auth_type, "oauth")
            self.assertEqual(account.oauth_provider, "microsoft")
            self.assertEqual((account.imap_host, account.imap_port), ("outlook.office365.com", 993))
            self.assertEqual((account.smtp_host, account.smtp_port), ("smtp.office365.com", 587))
            self.assertEqual(account.oauth_access_token, "ms-access")
            self.assertEqual(account.oauth_refresh_token, "ms-refresh")
        finally:
            db.close()

    def test_authorization_pending_is_retried_until_the_owner_approves(self):
        handler, calls = self.github_handler(
            [{"error": "authorization_pending"}, {"access_token": "gh-access", "scope": "repo"}]
        )
        self.fake_async(handler)
        started = self.run_device("github", "github")
        self.assertEqual(calls["polls"], 2)
        self.assertEqual(signin.get_attempt(started["attempt"])["state"], "done")

    def test_slow_down_adds_five_seconds_to_the_poll_interval(self):
        handler, calls = self.github_handler(
            [{"error": "slow_down"}, {"access_token": "gh-access", "scope": "repo"}]
        )
        self.fake_async(handler)
        started = self.run_device("github", "github")
        self.assertEqual(calls["polls"], 2)
        self.assertEqual(signin.get_attempt(started["attempt"])["state"], "done")
        self.assertEqual(signin._attempts[started["attempt"]]["interval"], 5)

    def test_expired_token_ends_the_attempt_as_expired(self):
        handler, _calls = self.github_handler([{"error": "expired_token"}])
        self.fake_async(handler)
        started = self.run_device("github", "github")
        attempt = signin.get_attempt(started["attempt"])
        self.assertEqual(attempt["state"], "expired")
        self.assertIsNone(attempt["error"])

    def test_access_denied_ends_the_attempt_as_denied(self):
        handler, _calls = self.github_handler([{"error": "access_denied"}])
        self.fake_async(handler)
        started = self.run_device("github", "github")
        attempt = signin.get_attempt(started["attempt"])
        self.assertEqual(attempt["state"], "denied")
        self.assertEqual(set(attempt["error"]), {"code", "text"})
        self.assertEqual(attempt["error"]["code"], "denied")
        self.assertTrue(attempt["error"]["text"])

    def google_handler(self, *, email="me@gmail.test", refresh_token="google-refresh"):
        calls = {"exchange": 0, "refresh": 0, "revoke": 0}

        def handle(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/token":
                form = parse_qs(request.content.decode())
                if form.get("grant_type") == ["refresh_token"]:
                    calls["refresh"] += 1
                    return httpx.Response(
                        200,
                        json={
                            "access_token": "google-access-2",
                            "expires_in": 3600,
                            "scope": "https://mail.google.com/",
                        },
                    )
                calls["exchange"] += 1
                return httpx.Response(
                    200,
                    json={
                        "access_token": "google-access",
                        "refresh_token": refresh_token,
                        "expires_in": 3600,
                        "scope": "https://mail.google.com/ openid email",
                        "id_token": _jwt({"email": email}),
                    },
                )
            if path == "/revoke":
                calls["revoke"] += 1
                return httpx.Response(200)
            return httpx.Response(404, json={"message": "not found"})

        return handle, calls

    def start_google(self, use, origin="https://alles.example"):
        async def go():
            return await signin.start("google", use, origin=origin)

        return asyncio.run(go())

    def finish_google(self, attempt_id, code="google-code"):
        state = signin._attempts[attempt_id]["state_token"]

        async def go():
            return await signin.finish_redirect("google", code=code, state=state, error="")

        return asyncio.run(go())

    def test_google_mail_redirect_happy_path(self):
        handler, calls = self.google_handler()
        self.fake_async(handler)
        started = self.start_google("mail")
        self.assertEqual(started["flow"], "redirect")
        self.assertIn("accounts.google.com", started["url"])
        finished = self.finish_google(started["attempt"])
        self.assertEqual(finished["attempt"], started["attempt"])
        attempt = signin.get_attempt(started["attempt"])
        self.assertEqual(attempt["state"], "done", attempt)
        self.assertEqual(attempt["account"]["email"], "me@gmail.test")
        self.assertEqual(calls["exchange"], 1)

        from core.database import MailAccount, SessionLocal

        db = SessionLocal()
        try:
            account = db.query(MailAccount).filter(MailAccount.email == "me@gmail.test").one()
            self.assertEqual(account.oauth_provider, "google")
            self.assertEqual((account.imap_host, account.imap_port), ("imap.gmail.com", 993))
        finally:
            db.close()

    def test_google_calendar_redirect_stores_a_bearer_caldav_config(self):
        handler, _calls = self.google_handler()
        self.fake_async(handler)
        started = self.start_google("calendar")
        self.finish_google(started["attempt"])

        cfg = caldav_sync.load_cfg()
        self.assertEqual(cfg["auth"], "oauth")
        self.assertEqual(cfg["provider"], "google")
        self.assertTrue(cfg["url"].startswith("https://apidata.googleusercontent.com/caldav/v2/"))
        tokens = caldav_sync.oauth_tokens(cfg)
        self.assertEqual(tokens["access_token"], "google-access")
        self.assertEqual(tokens["refresh_token"], "google-refresh")
        self.assertTrue(caldav_sync.status()["connected"])

        calendar = signin.list_accounts()["accounts"][0]
        self.assertEqual((calendar["provider"], calendar["use"]), ("google", "calendar"))

    def test_google_models_redirect_wraps_gemini(self):
        handler, _calls = self.google_handler()
        self.fake_async(handler)
        started = self.start_google("models")
        self.finish_google(started["attempt"])

        from core.database import ModelEndpoint, SessionLocal

        db = SessionLocal()
        try:
            endpoint = db.query(ModelEndpoint).filter(ModelEndpoint.auth_type == "oauth").one()
            self.assertEqual(endpoint.provider_id, "gemini")
            self.assertEqual(endpoint.api_key, "google-access")
            self.assertEqual(endpoint.oauth_refresh_token, "google-refresh")
            self.assertEqual(endpoint.oauth_client_id, "google-client")
            self.assertEqual(endpoint.oauth_client_secret, "google-secret")
        finally:
            db.close()

    def test_google_revoke_happens_on_sign_out(self):
        handler, calls = self.google_handler()
        self.fake_async(handler)
        started = self.start_google("mail")
        self.finish_google(started["attempt"])
        account_id = signin.get_attempt(started["attempt"])["account"]["id"]

        async def go():
            return await signin.sign_out(account_id)

        result = asyncio.run(go())
        self.assertEqual(result, {"id": account_id, "signed_out": True, "revoked": True})
        self.assertEqual(calls["revoke"], 1)

    def test_refresh_keeps_the_account_ok_and_saves_the_new_token(self):
        handler, calls = self.github_handler(
            [{"access_token": "gh-access", "refresh_token": "gh-refresh", "expires_in": 3600}]
        )
        self.fake_async(handler)
        started = self.run_device("github", "github")
        account_id = signin.get_attempt(started["attempt"])["account"]["id"]
        signin._attempts[started["attempt"]]["account"]["expires_at"] = "2020-01-01T00:00:00Z"

        async def go():
            return await signin.refresh_account(account_id)

        item = asyncio.run(go())
        self.assertEqual(calls["refresh"], 1)
        self.assertEqual(item["state"], "ok")
        self.assertIsNotNone(item["refreshed_at"])

        from core.database import Connection, SessionLocal

        db = SessionLocal()
        try:
            row = db.get(Connection, account_id)
            self.assertEqual(row.token, "gh-refreshed")
            self.assertEqual(json.loads(row.meta)["signin"]["refresh_token"], "gh-refresh-2")
        finally:
            db.close()

    def test_a_refresh_that_fails_for_good_marks_only_that_account(self):
        handler, _calls = self.github_handler(
            [{"access_token": "gh-access", "refresh_token": "gh-refresh", "expires_in": 3600}],
            refresh=httpx.Response(400, json={"error": "bad_refresh_token"}),
        )
        self.fake_async(handler)
        started = self.run_device("github", "github")
        account_id = signin.get_attempt(started["attempt"])["account"]["id"]
        signin._attempts[started["attempt"]]["account"]["expires_at"] = "2020-01-01T00:00:00Z"

        async def go():
            return await signin.refresh_account(account_id)

        item = asyncio.run(go())
        self.assertEqual(item["state"], "needs_sign_in")
        self.assertEqual(item["error"]["code"], "needs_sign_in")

    def test_a_transient_refresh_failure_keeps_the_account_ok(self):
        handler, _calls = self.github_handler(
            [{"access_token": "gh-access", "refresh_token": "gh-refresh", "expires_in": 3600}],
            refresh=httpx.Response(503, json={"message": "try later"}),
        )
        self.fake_async(handler)
        started = self.run_device("github", "github")
        account_id = signin.get_attempt(started["attempt"])["account"]["id"]

        async def go():
            return await signin.refresh_account(account_id)

        item = asyncio.run(go())
        self.assertEqual(item["state"], "ok")

    def test_a_redirect_attempt_expires_when_the_owner_never_returns(self):
        started = self.start_google("mail")
        signin._attempts[started["attempt"]]["deadline"] = 0
        attempt = signin.get_attempt(started["attempt"])
        self.assertEqual(attempt["state"], "expired")

    def test_legacy_gmail_and_gemini_sign_ins_are_listed(self):
        from core.database import MailAccount, ModelEndpoint, SessionLocal

        db = SessionLocal()
        try:
            db.add(
                MailAccount(
                    email="old@gmail.test",
                    username="old@gmail.test",
                    auth_type="oauth",
                    oauth_provider="google",
                    oauth_access_token="old-access",
                    oauth_refresh_token="old-refresh",
                    oauth_expires_at=time.time() + 3600,
                )
            )
            db.add(
                ModelEndpoint(
                    name="Gemini",
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                    provider_id="gemini",
                    auth_type="oauth",
                    auth_status="connected",
                    api_key="old-gemini",
                    oauth_refresh_token="old-gemini-refresh",
                    oauth_scopes=json.dumps(["https://www.googleapis.com/auth/cloud-platform"]),
                    oauth_expires_at=time.time() + 3600,
                )
            )
            db.commit()
        finally:
            db.close()

        accounts = signin.list_accounts()["accounts"]
        uses = {(item["provider"], item["use"]) for item in accounts}
        self.assertIn(("google", "mail"), uses)
        self.assertIn(("gemini", "models"), uses)
        mail = next(item for item in accounts if item["use"] == "mail")
        self.assertEqual(mail["login"], "old@gmail.test")
        self.assertIsNotNone(mail["signed_in_at"])

    def test_microsoft_refresh_rotates_the_saved_refresh_token(self):
        handler, calls = self.microsoft_handler()
        self.fake_async(handler)
        started = self.run_device("microsoft", "mail")
        account_id = signin.get_attempt(started["attempt"])["account"]["id"]

        async def go():
            return await signin.refresh_account(account_id)

        item = asyncio.run(go())
        self.assertEqual(item["state"], "ok")
        self.assertEqual(calls["refresh"], 1)

        from core.database import MailAccount, SessionLocal

        db = SessionLocal()
        try:
            account = db.get(MailAccount, account_id)
            self.assertEqual(account.oauth_access_token, "ms-access-2")
            self.assertEqual(account.oauth_refresh_token, "ms-refresh-2")
        finally:
            db.close()

    def test_sign_out_deletes_the_github_token_and_says_it_cannot_revoke(self):
        handler, _calls = self.github_handler()
        self.fake_async(handler)
        started = self.run_device("github", "github")
        account_id = signin.get_attempt(started["attempt"])["account"]["id"]

        async def go():
            return await signin.sign_out(account_id)

        result = asyncio.run(go())
        self.assertEqual(result, {"id": account_id, "signed_out": True, "revoked": False})
        from core.database import Connection, SessionLocal

        db = SessionLocal()
        try:
            self.assertIsNone(db.get(Connection, account_id))
        finally:
            db.close()

    def test_anthropic_paste_code_happy_path(self):
        calls = {"exchange": 0}

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/oauth/token":
                calls["exchange"] += 1
                body = json.loads(request.content)
                self.assertEqual(body["grant_type"], "authorization_code")
                return httpx.Response(
                    200,
                    json={
                        "access_token": "sk-ant-oat-access",
                        "refresh_token": "anthropic-refresh",
                        "expires_in": 3600,
                        "id_token": _jwt({"email": "owner@claude.test"}),
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        self.fake_async(handle)

        async def go():
            started = await signin.start("anthropic", "models", origin="http://localhost:8321")
            self.assertEqual(started["flow"], "paste_code")
            self.assertIn("claude.ai/oauth/authorize", started["url"])
            state = signin._attempts[started["attempt"]]["state_token"]
            return await signin.finish_code(started["attempt"], f"anthropic-code#{state}")

        attempt = asyncio.run(go())
        self.assertEqual(attempt["state"], "done", attempt)
        self.assertEqual(attempt["account"]["provider"], "anthropic")
        self.assertEqual(calls["exchange"], 1)

        from core.database import ModelEndpoint, SessionLocal

        db = SessionLocal()
        try:
            endpoint = db.query(ModelEndpoint).filter_by(provider_id="anthropic").one()
            self.assertEqual(endpoint.base_url, "https://api.anthropic.com")
            self.assertEqual(endpoint.api_key, "sk-ant-oat-access")
            self.assertEqual(endpoint.oauth_refresh_token, "anthropic-refresh")
        finally:
            db.close()

    def test_openai_paste_code_happy_path(self):
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/oauth/token":
                return httpx.Response(
                    200,
                    json={
                        "access_token": "openai-access",
                        "refresh_token": "openai-refresh",
                        "expires_in": 3600,
                        "id_token": _jwt({"email": "owner@chatgpt.test"}),
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        self.fake_async(handle)

        async def go():
            started = await signin.start("openai", "models", origin="http://localhost:8321")
            self.assertEqual(started["flow"], "paste_code")
            self.assertIn("auth.openai.com/oauth/authorize", started["url"])
            state = signin._attempts[started["attempt"]]["state_token"]
            return await signin.finish_code(started["attempt"], f"openai-code#{state}")

        attempt = asyncio.run(go())
        self.assertEqual(attempt["state"], "done", attempt)
        self.assertEqual(attempt["account"]["provider"], "openai")

        from core.database import ModelEndpoint, SessionLocal

        db = SessionLocal()
        try:
            endpoint = db.query(ModelEndpoint).filter_by(provider_id="openai").one()
            self.assertEqual(endpoint.base_url, "https://chatgpt.com/backend-api/codex")
            self.assertEqual(endpoint.oauth_refresh_token, "openai-refresh")
        finally:
            db.close()

    def test_an_empty_client_id_is_not_ready_with_a_plain_reason(self):
        save_settings({"signin_github_client_id": ""})

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "should not be called"})

        self.fake_async(handle)
        providers = self.client.get("/api/signin/providers").json()["providers"]
        github = next(item for item in providers if item["id"] == "github")
        self.assertFalse(github["ready"])
        self.assertEqual(github["not_ready"]["code"], "no_client_id")
        self.assertTrue(github["not_ready"]["text"])

        started = self.client.post(
            "/api/signin/start", json={"provider": "github", "use": "github"}
        )
        self.assertEqual(started.status_code, 409, started.text)
        self.assertEqual(started.json()["code"], "not_ready")

    def test_client_ids_can_be_set_through_the_settings_api(self):
        response = self.client.patch(
            "/api/settings", json={"signin_github_client_id": "from-settings"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        providers = self.client.get("/api/signin/providers").json()["providers"]
        github = next(item for item in providers if item["id"] == "github")
        self.assertTrue(github["ready"])

    def test_starting_again_cancels_the_old_attempt(self):
        calls = {"starts": 0}

        def handle(request: httpx.Request) -> httpx.Response:
            calls["starts"] += 1
            return httpx.Response(
                200,
                json={
                    "device_code": f"dev-{calls['starts']}",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900,
                    "interval": 30,
                },
            )

        self.fake_async(handle)

        async def go():
            first = await signin.start("github", "github", origin="http://localhost:8321")
            second = await signin.start("github", "github", origin="http://localhost:8321")
            return first, second

        first, second = asyncio.run(go())
        self.assertEqual(signin.get_attempt(first["attempt"])["state"], "cancelled")
        self.assertEqual(signin.get_attempt(second["attempt"])["state"], "waiting")
        for task in list(signin._tasks.values()):
            task.cancel()

    def test_the_synchronous_microsoft_refresh_rotates_and_persists(self):
        handler, calls = self.microsoft_handler()
        self.fake_sync(handler)
        acct = {
            "id": "acct-1",
            "oauth_provider": "microsoft",
            "oauth_access_token": "",
            "oauth_refresh_token": "ms-refresh",
            "oauth_expires_at": 0,
        }
        token = signin.ensure_microsoft_mail_token(acct)
        self.assertEqual(token, "ms-access-2")
        self.assertEqual(acct["oauth_refresh_token"], "ms-refresh-2")
        self.assertEqual(calls["refresh"], 1)
