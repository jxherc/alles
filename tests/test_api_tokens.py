import os

from core.api_tokens import KNOWN_SCOPES, required_scope
from core.database import ApiToken
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
        unknown = self.client.post("/api/tokens", json={"name": "bad", "scopes": ["root"]})
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
        self.assertEqual(required_scope("POST", "/api/vault/unlock"), "secrets")
        # docs live at /api/vault-md; a docs token must not need the password vault's scope
        self.assertEqual(required_scope("GET", "/api/vault-md/tree"), "read")
        self.assertEqual(required_scope("POST", "/api/vault-md/safety/save"), "write")
        self.assertEqual(required_scope("GET", "/api/vault-location"), "read")
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
            files_write = self.client.post(
                "/api/files/operations",
                headers=headers,
                json={"action": "delete", "source_path": "must-not-run.txt"},
            )
            self.assertEqual(files_write.status_code, 403)
            self.assertEqual(files_write.json()["code"], "token_scope_denied")
            denied = self.client.get("/api/settings", headers=headers)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.json()["code"], "token_scope_denied")
        finally:
            os.environ["AUTH_ENABLED"] = "false"

    def test_write_and_admin_tokens_enforce_their_scopes(self):
        writer = self.client.post(
            "/api/tokens", json={"name": "writer", "scopes": ["write"]}
        ).json()["token"]
        admin = self.client.post("/api/tokens", json={"name": "admin", "scopes": ["admin"]}).json()[
            "token"
        ]
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

    def test_route_admin_check_still_applies_after_middleware_read_check(self):
        reader = self.client.post("/api/tokens", json={"name": "reader"}).json()["token"]
        admin = self.client.post("/api/tokens", json={"name": "admin", "scopes": ["admin"]}).json()[
            "token"
        ]
        os.environ["AUTH_ENABLED"] = "true"
        try:
            denied = self.client.get("/api/news", headers={"Authorization": f"Bearer {reader}"})
            self.assertEqual(denied.status_code, 401, denied.text)
            allowed = self.client.get("/api/news", headers={"Authorization": f"Bearer {admin}"})
            self.assertEqual(allowed.status_code, 200, allowed.text)
        finally:
            os.environ["AUTH_ENABLED"] = "false"

    def test_actual_finance_status_uses_the_global_read_scope(self):
        models = self.client.post(
            "/api/tokens", json={"name": "models only", "scopes": ["models"]}
        ).json()["token"]
        reader = self.client.post(
            "/api/tokens", json={"name": "finance reader", "scopes": ["read"]}
        ).json()["token"]
        os.environ["AUTH_ENABLED"] = "true"
        try:
            denied = self.client.get(
                "/api/finance/actual", headers={"Authorization": f"Bearer {models}"}
            )
            self.assertEqual(denied.status_code, 403, denied.text)
            self.assertEqual(denied.json()["code"], "token_scope_denied")
            allowed = self.client.get(
                "/api/finance/actual", headers={"Authorization": f"Bearer {reader}"}
            )
            self.assertEqual(allowed.status_code, 200, allowed.text)
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

    def test_a_token_removes_itself_whatever_its_scopes(self):
        keep = self.client.post("/api/tokens", json={"name": "another device"}).json()
        for scopes in (["read", "write", "models"], ["secrets"], ["models"], ["admin"]):
            made = self.client.post(
                "/api/tokens", json={"name": "alles app on iphone", "scopes": scopes}
            ).json()
            headers = {"Authorization": f"Bearer {made['token']}"}
            os.environ["AUTH_ENABLED"] = "true"
            try:
                gone = self.client.delete("/api/tokens/current", headers=headers)
                self.assertEqual(gone.status_code, 200, f"{scopes}: {gone.text}")
                self.assertEqual(gone.json(), {"ok": True})
                # it stopped working, for this and for everything else
                again = self.client.delete("/api/tokens/current", headers=headers)
                self.assertEqual(again.status_code, 401)
                self.assertEqual(again.json()["code"], "invalid_token")
            finally:
                os.environ["AUTH_ENABLED"] = "false"
        self.assertEqual([t["id"] for t in self.client.get("/api/tokens").json()], [keep["id"]])

    def test_only_the_token_in_the_request_counts_as_current(self):
        self.client.post("/api/tokens", json={"name": "phone"})
        # the owner's own session carries no token, so there is nothing of its own to remove
        self.assertEqual(self.client.delete("/api/tokens/current").status_code, 404)
        other_kind = self.client.delete(
            "/api/tokens/current", headers={"Authorization": "Bearer not-an-alles-token"}
        )
        self.assertEqual(other_kind.status_code, 404)
        unknown = self.client.delete(
            "/api/tokens/current", headers={"Authorization": "Bearer alles_never_made"}
        )
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(unknown.json()["code"], "invalid_token")
        self.assertEqual(len(self.client.get("/api/tokens").json()), 1)

    def test_a_token_cannot_remove_another_one(self):
        phone = self.client.post(
            "/api/tokens", json={"name": "phone", "scopes": ["read", "write", "models"]}
        ).json()
        admin = self.client.post("/api/tokens", json={"name": "admin", "scopes": ["admin"]}).json()
        os.environ["AUTH_ENABLED"] = "true"
        try:
            scoped = self.client.delete(
                f"/api/tokens/{admin['id']}", headers={"Authorization": f"Bearer {phone['token']}"}
            )
            self.assertEqual(scoped.status_code, 403)
            self.assertEqual(scoped.json()["code"], "token_scope_denied")
            # not even an admin token: removing by id takes the owner's password
            by_admin = self.client.delete(
                f"/api/tokens/{phone['id']}", headers={"Authorization": f"Bearer {admin['token']}"}
            )
            self.assertEqual(by_admin.status_code, 403)
            self.assertEqual(by_admin.json()["code"], "recent_auth_required")
        finally:
            os.environ["AUTH_ENABLED"] = "false"
        self.assertEqual(len(self.client.get("/api/tokens").json()), 2)

    def test_only_removing_itself_is_open_to_every_scope(self):
        self.assertEqual(required_scope("DELETE", "/api/tokens/current"), "")
        self.assertEqual(required_scope("delete", "/api/tokens/current"), "")
        self.assertEqual(required_scope("GET", "/api/tokens/current"), "admin")
        self.assertEqual(required_scope("POST", "/api/tokens/current"), "admin")
        self.assertEqual(required_scope("DELETE", "/api/tokens/current/more"), "admin")
        self.assertEqual(required_scope("DELETE", "/api/tokens/some-id"), "admin")
        self.assertEqual(required_scope("DELETE", "/api/tokens"), "admin")

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
