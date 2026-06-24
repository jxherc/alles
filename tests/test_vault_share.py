import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from core.database import VaultShare
from tests._client import ApiTest


class VaultShareTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        self.tok = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["token"]
        self.h = {"X-Vault-Token": self.tok}
        self.eid = self.client.post(
            "/api/vault",
            json={"name": "WiFi", "fields": {"password": "hunter2-wifi-pass"}},
            headers=self.h,
        ).json()["id"]

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        super().tearDown()

    def _mint(self):
        return self.client.post(f"/api/vault/{self.eid}/share", headers=self.h).json()

    def test_mint_returns_token_key(self):
        d = self._mint()
        self.assertTrue(d["token"])
        self.assertTrue(d["key"])
        self.assertIn(f"#{d['key']}", d["url"])

    def test_delete_entry_kills_share_link(self):
        # deleting a secret must revoke its public share link, not leave it live + decryptable
        d = self._mint()
        self.assertEqual(self.client.get(f"/sv/{d['token']}/data").status_code, 200)
        self.client.delete(f"/api/vault/{self.eid}", headers=self.h)
        db = self.db()
        self.assertEqual(db.query(VaultShare).filter(VaultShare.entry_id == self.eid).count(), 0)
        db.close()
        self.assertNotEqual(self.client.get(f"/sv/{d['token']}/data").status_code, 200)

    def test_data_is_ciphertext(self):
        d = self._mint()
        body = self.client.get(f"/sv/{d['token']}/data").json()
        self.assertNotIn("hunter2-wifi-pass", body["blob"])

    def test_decrypt_with_key_roundtrips(self):
        import json as _json

        d = self._mint()
        blob = self.client.get(f"/sv/{d['token']}/data").json()["blob"]
        from services.crypto import envelope_decrypt

        payload = _json.loads(envelope_decrypt(d["key"], blob))
        self.assertEqual(payload["fields"]["password"], "hunter2-wifi-pass")

    def test_data_unknown_404(self):
        self.assertEqual(self.client.get("/sv/nope/data").status_code, 404)

    def test_revoke_then_404(self):
        d = self._mint()
        self.client.delete(f"/api/vault/{self.eid}/share", headers=self.h)
        self.assertEqual(self.client.get(f"/sv/{d['token']}/data").status_code, 404)

    def test_mint_requires_unlock_403(self):
        self.assertEqual(self.client.post(f"/api/vault/{self.eid}/share").status_code, 403)

    def test_key_not_stored_server_side(self):
        d = self._mint()
        db = self.db()
        row = db.query(VaultShare).filter(VaultShare.token == d["token"]).first()
        db.close()
        self.assertNotIn(d["key"], row.blob)
        self.assertNotIn("hunter2-wifi-pass", row.blob)

    def test_viewer_page_served(self):
        d = self._mint()
        r = self.client.get(f"/sv/{d['token']}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])

    def test_mint_idempotent_same_entry(self):
        self._mint()
        self._mint()
        db = self.db()
        n = db.query(VaultShare).filter(VaultShare.entry_id == self.eid).count()
        db.close()
        self.assertEqual(n, 1)
