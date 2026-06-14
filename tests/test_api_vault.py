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

    def test_generate_and_strength_no_unlock(self):
        g = self.client.get("/api/vault/generate", params={"length": 24}).json()
        self.assertEqual(len(g["password"]), 24)
        self.assertIn("strength", g)
        s = self.client.post("/api/vault/strength", json={"password": "abc"}).json()
        self.assertIn("score", s if isinstance(s, dict) else {})  # estimate_strength returns a dict

    def test_locked_until_unlocked(self):
        self.assertEqual(self.client.get("/api/vault").status_code, 403)
        self.assertEqual(self.client.post("/api/vault", json={"name": "x", "value": "y"}).status_code, 403)

    def test_full_flow_unlock_create_reveal_lock(self):
        # first unlock sets the master verifier
        tok = self.client.post("/api/vault/unlock", json={"password": "hunter2"}).json()
        self.assertIn("token", tok)

        # create an encrypted entry
        r = self.client.post("/api/vault", json={"name": "github", "value": "ghp_secret", "username": "me"})
        self.assertEqual(r.status_code, 200)
        eid = r.json()["id"]

        # list shows metadata (not the secret)
        lst = self.client.get("/api/vault").json()
        self.assertEqual(lst[0]["name"], "github")
        self.assertNotIn("value", lst[0])

        # reveal decrypts back to the original
        rv = self.client.get(f"/api/vault/{eid}/reveal").json()
        self.assertEqual(rv["value"], "ghp_secret")

        # lock → access denied again
        self.assertEqual(self.client.post("/api/vault/lock").json(), {"ok": True})
        self.assertEqual(self.client.get(f"/api/vault/{eid}/reveal").status_code, 403)

    def test_wrong_master_rejected(self):
        self.client.post("/api/vault/unlock", json={"password": "right"})
        self.client.post("/api/vault/lock")
        self.assertEqual(self.client.post("/api/vault/unlock", json={"password": "wrong"}).status_code, 401)
