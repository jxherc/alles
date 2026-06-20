"""ui-8b — main vault (master password) vs per-vault passwords, + change-vault-password re-key.
The main vault is the default; others have their own password. Changing a vault's password re-encrypts
its entries (and attachments) under the new key, atomically."""

import io
import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest


class VaultMainRekey(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles8b-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        self.tok = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["token"]
        self.h = {"X-Vault-Token": self.tok}

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    def _vaults(self):
        return self.client.get("/api/vault/vaults", headers=self.h).json()

    def _id_of(self, name):
        return next(v["id"] for v in self._vaults() if v["name"] == name)

    def _unlock(self, pw, vid=None):
        body = {"password": pw}
        if vid:
            body["vault_id"] = vid
        return self.client.post("/api/vault/unlock", json=body)

    def _mk(self, name, pw):
        return self.client.post(
            "/api/vault/vaults", json={"name": name, "password": pw}, headers=self.h
        )

    # ── main flag ──
    def test_default_is_main(self):
        d = next(v for v in self._vaults() if v["id"] == "default")
        self.assertTrue(d["main"])

    def test_created_vault_is_not_main(self):
        self._mk("Work", "wpw")
        w = next(v for v in self._vaults() if v["name"] == "Work")
        self.assertFalse(w["main"])

    def test_created_vault_uses_own_password_not_master(self):
        self._mk("Work", "wpw")
        wid = self._id_of("Work")
        self.assertEqual(self._unlock("wpw", wid).status_code, 200)
        self.assertEqual(self._unlock("m1", wid).status_code, 401)

    # ── change-password re-key ──
    def _entry(self, headers, name="gmail", pw="hunter2"):
        return self.client.post(
            "/api/vault",
            json={"name": name, "username": "me", "fields": {"password": pw, "username": "me"}},
            headers=headers,
        ).json()["id"]

    def test_change_password_rekeys_entries(self):
        self._mk("Work", "wpw")
        wid = self._id_of("Work")
        wh = {"X-Vault-Token": self._unlock("wpw", wid).json()["token"]}
        eid = self._entry(wh)
        r = self.client.post(
            "/api/vault/vaults/password", json={"new_password": "wpw2"}, headers=wh
        )
        self.assertEqual(r.status_code, 200)
        # old password no longer unlocks; new one does
        self.assertEqual(self._unlock("wpw", wid).status_code, 401)
        ntok = self._unlock("wpw2", wid).json()["token"]
        rev = self.client.get(f"/api/vault/{eid}/reveal", headers={"X-Vault-Token": ntok}).json()
        self.assertEqual(rev["fields"]["password"], "hunter2")

    def test_change_password_rekeys_attachments(self):
        eid = self._entry(self.h)
        blob = b"top secret bytes \x00\x01\x02"
        up = self.client.post(
            f"/api/vault/{eid}/attachments",
            files={"file": ("s.bin", io.BytesIO(blob), "application/octet-stream")},
            headers=self.h,
        )
        self.assertEqual(up.status_code, 200)
        aid = up.json()["id"]
        r = self.client.post(
            "/api/vault/vaults/password", json={"new_password": "m2"}, headers=self.h
        )
        self.assertEqual(r.status_code, 200)
        ntok = self._unlock("m2").json()["token"]
        dl = self.client.get(f"/api/vault/attachments/{aid}", headers={"X-Vault-Token": ntok})
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.content, blob)

    def test_change_default_password_changes_master(self):
        self.client.post("/api/vault/vaults/password", json={"new_password": "m2"}, headers=self.h)
        self.assertEqual(self._unlock("m1").status_code, 401)
        self.assertEqual(self._unlock("m2").status_code, 200)

    def test_change_password_empty_rejected(self):
        r = self.client.post(
            "/api/vault/vaults/password", json={"new_password": ""}, headers=self.h
        )
        self.assertEqual(r.status_code, 400)

    def test_change_password_requires_unlock(self):
        # no token → the vault auth gate refuses (403)
        r = self.client.post("/api/vault/vaults/password", json={"new_password": "x"})
        self.assertEqual(r.status_code, 403)

    # ── inline rename ──
    def test_rename_via_patch(self):
        self._mk("Work", "wpw")
        wid = self._id_of("Work")
        self.client.patch(f"/api/vault/vaults/{wid}", json={"name": "Job"}, headers=self.h)
        self.assertIn("Job", [v["name"] for v in self._vaults()])
