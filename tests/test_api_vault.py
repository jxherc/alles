import tempfile
from pathlib import Path
from unittest import mock

import core.settings as cs
import routes.vault as vroute
from tests._client import ApiTest


class VaultApiTest(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(cs, "_SETTINGS_FILE", Path(self._tmp.name) / "settings.json")
        self._p.start()
        vroute._unlock_tokens.clear()

    def tearDown(self):
        vroute._unlock_tokens.clear()
        self._p.stop()
        self._tmp.cleanup()
        super().tearDown()

    def _unlock(self, pw="hunter2"):
        tok = self.client.post("/api/vault/unlock", json={"password": pw}).json()["token"]
        return {"X-Vault-Token": tok}

    def test_generate_and_strength_no_unlock(self):
        g = self.client.get("/api/vault/generate", params={"length": 24}).json()
        self.assertEqual(len(g["password"]), 24)
        self.assertIn("strength", g)
        s = self.client.post("/api/vault/strength", json={"password": "abc"}).json()
        self.assertIn("score", s if isinstance(s, dict) else {})  # estimate_strength returns a dict

    def test_locked_until_unlocked(self):
        self.assertEqual(self.client.get("/api/vault").status_code, 403)
        self.assertEqual(
            self.client.post("/api/vault", json={"name": "x", "value": "y"}).status_code, 403
        )

    def test_full_flow_unlock_create_reveal_lock(self):
        # first unlock sets the master verifier and hands back this session's token
        tok = self.client.post("/api/vault/unlock", json={"password": "hunter2"}).json()
        self.assertIn("token", tok)
        h = {"X-Vault-Token": tok["token"]}

        # create an encrypted entry
        r = self.client.post(
            "/api/vault",
            json={"name": "github", "value": "ghp_secret", "username": "me"},
            headers=h,
        )
        self.assertEqual(r.status_code, 200)
        eid = r.json()["id"]

        # list shows metadata (not the secret)
        lst = self.client.get("/api/vault", headers=h).json()
        self.assertEqual(lst[0]["name"], "github")
        self.assertNotIn("value", lst[0])

        # reveal decrypts back to the original
        rv = self.client.get(f"/api/vault/{eid}/reveal", headers=h).json()
        self.assertEqual(rv["value"], "ghp_secret")

        # lock → access denied again
        self.assertEqual(self.client.post("/api/vault/lock", headers=h).json(), {"ok": True})
        self.assertEqual(self.client.get(f"/api/vault/{eid}/reveal", headers=h).status_code, 403)

    def test_unlock_token_is_required_not_just_any_unlock(self):
        # a live unlock must NOT authorize a request that doesn't present the
        # matching token — otherwise one unlock opens the vault to every caller
        tok = self.client.post("/api/vault/unlock", json={"password": "hunter2"}).json()["token"]
        self.assertEqual(self.client.get("/api/vault").status_code, 403)  # no token header
        self.assertEqual(
            self.client.get("/api/vault", headers={"X-Vault-Token": "bogus"}).status_code, 403
        )
        self.assertEqual(
            self.client.get("/api/vault", headers={"X-Vault-Token": tok}).status_code, 200
        )

    def test_wrong_master_rejected(self):
        self.client.post("/api/vault/unlock", json={"password": "right"})
        self.client.post("/api/vault/lock")
        self.assertEqual(
            self.client.post("/api/vault/unlock", json={"password": "wrong"}).status_code, 401
        )

    def test_patch_entry_name_and_username(self):
        h = self._unlock()
        eid = self.client.post(
            "/api/vault", json={"name": "old", "value": "secret", "username": "alice"}, headers=h
        ).json()["id"]
        r = self.client.patch(
            f"/api/vault/{eid}", json={"name": "new", "username": "bob"}, headers=h
        )
        self.assertEqual(r.status_code, 200)
        # reveal should still decrypt the original value
        rv = self.client.get(f"/api/vault/{eid}/reveal", headers=h).json()
        self.assertEqual(rv["value"], "secret")
        # metadata in list should reflect patch
        lst = self.client.get("/api/vault", headers=h).json()
        self.assertEqual(lst[0]["name"], "new")
        self.assertEqual(lst[0]["username"], "bob")

    def test_patch_entry_value(self):
        h = self._unlock()
        eid = self.client.post(
            "/api/vault", json={"name": "mykey", "value": "v1"}, headers=h
        ).json()["id"]
        self.client.patch(f"/api/vault/{eid}", json={"value": "v2"}, headers=h)
        rv = self.client.get(f"/api/vault/{eid}/reveal", headers=h).json()
        self.assertEqual(rv["value"], "v2")

    def test_delete_entry(self):
        h = self._unlock()
        eid = self.client.post(
            "/api/vault", json={"name": "to-del", "value": "x"}, headers=h
        ).json()["id"]
        self.assertEqual(self.client.delete(f"/api/vault/{eid}", headers=h).json(), {"ok": True})
        self.assertEqual(self.client.get("/api/vault", headers=h).json(), [])

    def test_reveal_missing_404(self):
        h = self._unlock()
        self.assertEqual(self.client.get("/api/vault/nope/reveal", headers=h).status_code, 404)

    def test_entry_endpoints_scope_to_unlocked_vault(self):
        # regression (F15, security): unlocking vault A must not let you reveal/delete/
        # attach-to/share an entry that lives in vault B. before the fix these per-entry
        # endpoints only checked the password, not e.vault_id, so they crossed vaults.
        ha = self._unlock("masterA")  # default vault, token A
        vid_b = self.client.post(
            "/api/vault/vaults", json={"name": "work", "password": "masterB"}, headers=ha
        ).json()["id"]
        hb = {
            "X-Vault-Token": self.client.post(
                "/api/vault/unlock", json={"password": "masterB", "vault_id": vid_b}
            ).json()["token"]
        }
        # secret created inside vault B
        eid = self.client.post(
            "/api/vault", json={"name": "vaultB-secret", "value": "topsecret"}, headers=hb
        ).json()["id"]

        # vault A's token must NOT reach vault B's entry
        self.assertEqual(self.client.get(f"/api/vault/{eid}/reveal", headers=ha).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/vault/{eid}", headers=ha).status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/vault/{eid}/attachments", headers=ha).status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/api/vault/{eid}/share", headers=ha).status_code, 404
        )
        # the entry is untouched: vault B can still read it
        self.assertEqual(
            self.client.get(f"/api/vault/{eid}/reveal", headers=hb).json()["value"], "topsecret"
        )

    def test_generate_length_param(self):
        g12 = self.client.get("/api/vault/generate", params={"length": 12}).json()
        g32 = self.client.get("/api/vault/generate", params={"length": 32}).json()
        self.assertEqual(len(g12["password"]), 12)
        self.assertEqual(len(g32["password"]), 32)

    def test_strength_empty_password(self):
        s = self.client.post("/api/vault/strength", json={"password": ""}).json()
        self.assertEqual(s["score"], 0)
        self.assertIn("warning", s)

    def test_strength_strong_password(self):
        s = self.client.post(
            "/api/vault/strength", json={"password": "X7$kQpR!mLzN2@vW9#"}
        ).json()
        self.assertGreaterEqual(s["score"], 3)
