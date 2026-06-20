import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from services.crypto import make_verifier
from tests._client import ApiTest


class VaultMultiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles9c1-")
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

    def _mk_vault(self, name, pw, headers=None):
        return self.client.post(
            "/api/vault/vaults", json={"name": name, "password": pw}, headers=headers or self.h
        )

    def _id_of(self, name):
        return next(v["id"] for v in self._vaults() if v["name"] == name)

    # ── multiple vaults ──────────────────────────────────────────────────────
    def test_default_vault_exists(self):
        ids = [v["id"] for v in self._vaults()]
        self.assertIn("default", ids)

    def test_create_vault(self):
        r = self._mk_vault("Work", "wpw")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Work", [v["name"] for v in self._vaults()])

    def test_vaults_list_shape(self):
        v = self._vaults()[0]
        for k in ("id", "name", "travel_safe", "entries"):
            self.assertIn(k, v)

    def test_entries_scoped_to_vault(self):
        # an entry created under default lands in default, not a fresh vault
        self.client.post(
            "/api/vault", json={"name": "GH", "fields": {"password": "x"}}, headers=self.h
        )
        self._mk_vault("Work", "wpw")
        wtok = self.client.post(
            "/api/vault/unlock", json={"password": "wpw", "vault_id": self._id_of("Work")}
        ).json()["token"]
        work_entries = self.client.get("/api/vault", headers={"X-Vault-Token": wtok}).json()
        self.assertEqual(work_entries, [])
        default_entries = self.client.get("/api/vault", headers=self.h).json()
        self.assertEqual(len(default_entries), 1)

    def test_cross_vault_isolation(self):
        self._mk_vault("Work", "wpw")
        wtok = self.client.post(
            "/api/vault/unlock", json={"password": "wpw", "vault_id": self._id_of("Work")}
        ).json()["token"]
        self.client.post(
            "/api/vault",
            json={"name": "Secret", "fields": {"password": "p"}},
            headers={"X-Vault-Token": wtok},
        )
        # default token can't see Work's entry
        names = [e["name"] for e in self.client.get("/api/vault", headers=self.h).json()]
        self.assertNotIn("Secret", names)

    def test_unlock_specific_vault(self):
        self._mk_vault("Work", "wpw")
        r = self.client.post(
            "/api/vault/unlock", json={"password": "wpw", "vault_id": self._id_of("Work")}
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("token"))

    def test_rename_and_flag_vault(self):
        self._mk_vault("Work", "wpw")
        vid = self._id_of("Work")
        self.client.patch(
            f"/api/vault/vaults/{vid}", json={"name": "Job", "travel_safe": True}, headers=self.h
        )
        v = next(v for v in self._vaults() if v["id"] == vid)
        self.assertEqual(v["name"], "Job")
        self.assertTrue(v["travel_safe"])

    def test_delete_vault(self):
        self._mk_vault("Tmp", "t")
        vid = self._id_of("Tmp")
        self.assertEqual(
            self.client.delete(f"/api/vault/vaults/{vid}", headers=self.h).status_code, 200
        )
        self.assertNotIn("Tmp", [v["name"] for v in self._vaults()])

    def test_cannot_delete_default(self):
        self.assertEqual(
            self.client.delete("/api/vault/vaults/default", headers=self.h).status_code, 400
        )

    # ── travel mode ──────────────────────────────────────────────────────────
    def test_travel_mode_lists_only_safe(self):
        self._mk_vault("Work", "wpw")  # new vaults are not travel-safe by default
        self.client.put("/api/vault/travel-mode", json={"on": True}, headers=self.h)
        names = [v["name"] for v in self._vaults()]
        self.assertNotIn("Work", names)
        self.assertIn("default", [v["id"] for v in self._vaults()])  # default is travel-safe

    def test_travel_mode_blocks_unsafe_unlock(self):
        self._mk_vault("Work", "wpw")
        vid = self._id_of("Work")
        self.client.put("/api/vault/travel-mode", json={"on": True}, headers=self.h)
        r = self.client.post("/api/vault/unlock", json={"password": "wpw", "vault_id": vid})
        self.assertEqual(r.status_code, 403)

    def test_legacy_verifier_migrates(self):
        # simulate an upgraded install: no Vault rows yet, only a legacy global verifier
        from core.database import Vault
        from core.settings import save_settings

        d = self.db()
        d.query(Vault).delete()
        d.commit()
        d.close()
        save_settings({"vault_verifier": make_verifier("oldpw")})
        ok = self.client.post("/api/vault/unlock", json={"password": "oldpw"})
        self.assertEqual(ok.status_code, 200)
        bad = self.client.post("/api/vault/unlock", json={"password": "nope"})
        self.assertEqual(bad.status_code, 401)
