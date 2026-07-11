import os

from core.database import ApiToken
from routes.api_tokens import KNOWN_SCOPES, required_scope
from tests._client import ApiTest


class TokensApiTest(ApiTest):
    def test_create_shows_raw_once_then_never(self):
        t = self.client.post("/api/tokens", json={"name": "cli"}).json()
        self.assertTrue(t["token"].startswith("alles_"))  # raw shown only on creation
        self.assertEqual(len(t["prefix"]), 12)

        listed = self.client.get("/api/tokens").json()
        self.assertEqual(len(listed), 1)
        self.assertNotIn("token", listed[0])  # never returned again
        self.assertEqual(listed[0]["prefix"], t["prefix"])
        self.assertEqual(t["scopes"], ["read"])
        self.assertEqual(listed[0]["scopes"], ["read"])

    def test_create_accepts_known_scopes_in_stable_order(self):
        token = self.client.post(
            "/api/tokens", json={"name": "automation", "scopes": ["write", "read"]}
        ).json()
        self.assertEqual(token["scopes"], ["read", "write"])

    def test_create_rejects_empty_or_unknown_scopes(self):
        empty = self.client.post("/api/tokens", json={"name": "empty", "scopes": []})
        unknown = self.client.post(
            "/api/tokens", json={"name": "bad", "scopes": ["root"]}
        )
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(empty.json()["code"], "invalid_token_scopes")
        self.assertEqual(unknown.json()["code"], "invalid_token_scopes")

    def test_required_scope_routes_sensitive_surfaces(self):
        self.assertEqual(required_scope("GET", "/api/tasks"), "read")
        self.assertEqual(required_scope("POST", "/api/tasks"), "write")
        self.assertEqual(required_scope("POST", "/v1/chat/completions"), "models")
        self.assertEqual(required_scope("POST", "/api/agent/run"), "agent")
        self.assertEqual(required_scope("GET", "/api/vault"), "secrets")
        self.assertEqual(required_scope("GET", "/api/connections"), "connections")
        self.assertEqual(required_scope("GET", "/api/settings"), "admin")
        self.assertEqual(
            set(KNOWN_SCOPES),
            {"read", "write", "models", "agent", "secrets", "connections", "admin"},
        )

    def test_read_token_works_with_auth_on_but_cannot_write_or_admin(self):
        raw = self.client.post("/api/tokens", json={"name": "reader"}).json()["token"]
        headers = {"Authorization": f"Bearer {raw}"}
        os.environ["AUTH_ENABLED"] = "true"
        try:
            self.assertEqual(self.client.get("/api/tasks", headers=headers).status_code, 200)
            self.assertEqual(
                self.client.post("/api/tasks", headers=headers, json={"title": "no"}).status_code,
                403,
            )
            denied = self.client.get("/api/settings", headers=headers)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.json()["code"], "token_scope_denied")
        finally:
            os.environ["AUTH_ENABLED"] = "false"

    def test_write_and_admin_tokens_enforce_their_scopes(self):
        writer = self.client.post(
            "/api/tokens", json={"name": "writer", "scopes": ["write"]}
        ).json()["token"]
        admin = self.client.post(
            "/api/tokens", json={"name": "admin", "scopes": ["admin"]}
        ).json()["token"]
        os.environ["AUTH_ENABLED"] = "true"
        try:
            created = self.client.post(
                "/api/tasks",
                headers={"Authorization": f"Bearer {writer}"},
                json={"title": "scoped task"},
            )
            self.assertEqual(created.status_code, 200)
            self.assertEqual(
                self.client.get(
                    "/api/settings", headers={"Authorization": f"Bearer {admin}"}
                ).status_code,
                200,
            )
        finally:
            os.environ["AUTH_ENABLED"] = "false"

    def test_revoked_bearer_token_is_rejected(self):
        token = self.client.post("/api/tokens", json={"name": "short lived"}).json()
        self.client.delete(f"/api/tokens/{token['id']}")
        os.environ["AUTH_ENABLED"] = "true"
        try:
            response = self.client.get(
                "/api/tasks", headers={"Authorization": f"Bearer {token['token']}"}
            )
            self.assertEqual(response.status_code, 401)
        finally:
            os.environ["AUTH_ENABLED"] = "false"

    def test_malformed_saved_scopes_fail_closed(self):
        token = self.client.post("/api/tokens", json={"name": "broken"}).json()
        with self.db() as database:
            row = database.get(ApiToken, token["id"])
            row.scopes = "not-json"
            database.commit()
        os.environ["AUTH_ENABLED"] = "true"
        try:
            response = self.client.get(
                "/api/tasks", headers={"Authorization": f"Bearer {token['token']}"}
            )
            self.assertEqual(response.status_code, 403)
        finally:
            os.environ["AUTH_ENABLED"] = "false"

    def test_delete(self):
        tid = self.client.post("/api/tokens", json={"name": "tmp"}).json()["id"]
        self.assertEqual(self.client.delete(f"/api/tokens/{tid}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/tokens").json(), [])

    def test_delete_missing_404(self):
        self.assertEqual(self.client.delete("/api/tokens/nope").status_code, 404)

    def test_multiple_tokens_listed(self):
        self.client.post("/api/tokens", json={"name": "t1"})
        self.client.post("/api/tokens", json={"name": "t2"})
        listed = self.client.get("/api/tokens").json()
        self.assertEqual(len(listed), 2)
        names = {t["name"] for t in listed}
        self.assertEqual(names, {"t1", "t2"})

    def test_prefix_matches_token_start(self):
        t = self.client.post("/api/tokens", json={"name": "pfx"}).json()
        self.assertTrue(t["token"].startswith(t["prefix"]))

    def test_token_has_id_field(self):
        t = self.client.post("/api/tokens", json={"name": "id-check"}).json()
        self.assertIn("id", t)
        self.assertTrue(t["id"])

    def test_listed_tokens_have_no_raw_token(self):
        self.client.post("/api/tokens", json={"name": "a"})
        self.client.post("/api/tokens", json={"name": "b"})
        for t in self.client.get("/api/tokens").json():
            self.assertNotIn("token", t)

    def test_delete_one_leaves_others(self):
        t1 = self.client.post("/api/tokens", json={"name": "keep"}).json()
        t2 = self.client.post("/api/tokens", json={"name": "drop"}).json()
        self.client.delete(f"/api/tokens/{t2['id']}")
        listed = self.client.get("/api/tokens").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], t1["id"])

    def test_created_at_present(self):
        t = self.client.post("/api/tokens", json={"name": "ts"}).json()
        self.assertIn("created_at", t)
        self.assertIsNotNone(t["created_at"])
