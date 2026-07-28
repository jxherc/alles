import time
import unittest
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from core.database import ModelEndpoint
from services import model_auth
from tests._client import ApiTest


class Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload or {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise model_auth.httpx.HTTPStatusError(
                "failed", request=mock.Mock(), response=mock.Mock(status_code=self.status_code)
            )

    def json(self):
        return self.payload


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def post(self, url, data=None):
        self.calls.append((url, data or {}))
        return self.responses.pop(0)


def endpoint(**values):
    defaults = {
        "id": "ep1",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": "",
        "provider_id": "gemini",
        "auth_type": "oauth",
        "auth_status": "connecting",
        "auth_error": "",
        "account_identity": "",
        "oauth_client_id": "client-id",
        "oauth_client_secret": "client-secret",
        "oauth_project_id": "owner-project",
        "oauth_refresh_token": "refresh-token",
        "oauth_expires_at": 0,
        "oauth_scopes": "[]",
        "enabled": True,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


class ModelAuthContractTest(unittest.IsolatedAsyncioTestCase):
    def test_provider_rules_allow_only_published_authentication(self):
        self.assertEqual(
            model_auth.validate_auth("deepseek", "api_key", "https://api.deepseek.com"),
            ("deepseek", "api_key"),
        )
        with self.assertRaisesRegex(ValueError, "does not support"):
            model_auth.validate_auth("deepseek", "oauth", "https://api.deepseek.com")
        with self.assertRaisesRegex(ValueError, "loopback"):
            model_auth.validate_auth("custom", "none", "https://models.example.test")
        self.assertEqual(
            model_auth.validate_auth("ollama", "none", "http://127.0.0.1:11434"),
            ("ollama", "none"),
        )
        self.assertTrue(model_auth.is_loopback_url("http://aide.localhost:6769/callback"))
        self.assertFalse(model_auth.is_loopback_url("http://aide.example.test:6769/callback"))

    def test_public_metadata_contains_guidance_but_no_credentials(self):
        value = model_auth.public_auth(endpoint(api_key="secret", oauth_refresh_token="refresh"))
        self.assertEqual(value["provider_id"], "gemini")
        self.assertEqual(value["auth_type"], "oauth")
        self.assertTrue(value["oauth_refreshable"])
        self.assertIn("quota", value["quota_warning"].lower())
        self.assertNotIn("secret", str(value))
        self.assertNotIn("refresh-token", str(value))

    def test_authorization_url_uses_state_pkce_and_loopback(self):
        url = model_auth.begin_gemini_oauth(
            endpoint(), "http://127.0.0.1:6769/api/models/oauth/gemini/callback"
        )
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["access_type"], ["offline"])
        self.assertEqual(params["client_id"], ["client-id"])
        self.assertNotIn("client_secret", params)
        pending = model_auth.consume_pending(params["state"][0])
        self.assertEqual(pending["endpoint_id"], "ep1")
        self.assertGreater(len(pending["verifier"]), 40)

    async def test_refresh_rotates_access_token_and_registers_project_header(self):
        ep = endpoint(api_key="old", oauth_expires_at=time.time() - 1)
        client = Client(Response({"access_token": "new-token", "expires_in": 1800}))
        changed = await model_auth.refresh_gemini_endpoint(ep, client=client)
        self.assertTrue(changed)
        self.assertEqual(ep.api_key, "new-token")
        self.assertEqual(ep.oauth_refresh_token, "refresh-token")
        self.assertEqual(model_auth.runtime_headers("new-token"), {"x-goog-user-project": "owner-project"})
        self.assertEqual(client.calls[0][1]["grant_type"], "refresh_token")

    async def test_revoke_clears_only_after_provider_confirmation(self):
        ep = endpoint(api_key="access")
        client = Client(Response())
        await model_auth.revoke_gemini_endpoint(ep, client=client)
        model_auth.clear_oauth(ep)
        self.assertEqual(ep.api_key, "")
        self.assertEqual(ep.oauth_refresh_token, "")
        self.assertEqual(ep.auth_status, "revoked")
        self.assertFalse(ep.enabled)


class ModelAuthApiTest(ApiTest):
    def test_regular_endpoint_reports_exact_auth_metadata(self):
        response = self.client.post(
            "/api/models/endpoint",
            json={
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "api_key": "private-key",
                "provider_id": "deepseek",
                "auth_type": "api_key",
                "provider_adapter": "manual",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider_id"], "deepseek")
        self.assertEqual(body["auth_type"], "api_key")
        self.assertEqual(body["auth_status"], "connected")
        self.assertNotIn("private-key", str(body))

    def test_consumer_oauth_cannot_be_added_as_a_pasted_endpoint(self):
        response = self.client.post(
            "/api/models/endpoint",
            json={
                "name": "Claude subscription",
                "base_url": "https://api.anthropic.com",
                "provider_id": "anthropic",
                "auth_type": "oauth",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_model_auth")

    def test_gemini_start_requires_loopback_and_returns_no_secret(self):
        response = self.client.post(
            "/api/models/oauth/gemini/start",
            headers={"host": "127.0.0.1:6769"},
            json={
                "client_id": "owner-client",
                "client_secret": "owner-secret",
                "project_id": "owner-project",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("accounts.google.com", body["authorization_url"])
        self.assertNotIn("owner-secret", str(body))
        self.assertEqual(body["endpoint"]["auth_status"], "connecting")

    def test_gemini_callback_persists_encrypted_tokens_and_enables_endpoint(self):
        start = self.client.post(
            "/api/models/oauth/gemini/start",
            headers={"host": "127.0.0.1:6769"},
            json={
                "client_id": "owner-client",
                "client_secret": "owner-secret",
                "project_id": "owner-project",
            },
        ).json()
        state = parse_qs(urlsplit(start["authorization_url"]).query)["state"][0]
        with (
            mock.patch(
                "services.model_auth.exchange_gemini_code",
                new=mock.AsyncMock(
                    return_value={
                        "access_token": "owner-access-token",
                        "refresh_token": "owner-refresh-token",
                        "expires_in": 3600,
                    }
                ),
            ),
            mock.patch(
                "services.model_catalog.refresh_endpoint",
                new=mock.AsyncMock(return_value={"error_code": ""}),
            ),
        ):
            response = self.client.get(
                "/api/models/oauth/gemini/callback",
                headers={"host": "127.0.0.1:6769"},
                params={"state": state, "code": "provider-code"},
            )
        self.assertEqual(response.status_code, 200)
        listed = self.client.get("/api/models").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["auth_status"], "connected")
        raw = self.eng.raw_connection()
        try:
            row = raw.execute(
                "SELECT api_key, oauth_refresh_token, oauth_client_secret FROM model_endpoints"
            ).fetchone()
        finally:
            raw.close()
        self.assertNotIn("owner-access-token", str(row))
        self.assertNotIn("owner-refresh-token", str(row))
        self.assertNotIn("owner-secret", str(row))


if __name__ == "__main__":
    unittest.main()
