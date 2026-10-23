import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from core.database import BrowserConnection
from services import browser_passwords
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
        self.tok = self.client.post(
            "/api/vault/unlock", json={"password": "master-password-1"}
        ).json()["token"]
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

    def _headers_for(self, vid, password):
        token = self.client.post(
            "/api/vault/unlock", json={"password": password, "vault_id": vid}
        ).json()["token"]
        return {"X-Vault-Token": token}

    def test_patch_entry_rejects_cross_vault(self):
        # patching an entry while a DIFFERENT vault is unlocked re-encrypted it under the wrong
        # key (silent data loss). it must 404 instead, leaving the entry intact.
        eid = self.client.post(
            "/api/vault",
            json={"name": "Email", "fields": {"password": "secret-pw"}},
            headers=self.h,
        ).json()["id"]
        self._mk_vault("Work", "work-password-1")
        wtok = self.client.post(
            "/api/vault/unlock",
            json={"password": "work-password-1", "vault_id": self._id_of("Work")},
        ).json()["token"]
        r = self.client.patch(
            f"/api/vault/{eid}",
            json={"fields": {"password": "hacked"}},
            headers={"X-Vault-Token": wtok},
        )
        self.assertEqual(r.status_code, 404)
        # original still decrypts with its own vault
        rev = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()
        self.assertEqual(rev["value"], "secret-pw")

    # ── multiple vaults ──────────────────────────────────────────────────────
    def test_default_vault_exists(self):
        ids = [v["id"] for v in self._vaults()]
        self.assertIn("default", ids)

    def test_create_vault(self):
        r = self._mk_vault("Work", "work-password-1")
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
        self._mk_vault("Work", "work-password-1")
        wtok = self.client.post(
            "/api/vault/unlock",
            json={"password": "work-password-1", "vault_id": self._id_of("Work")},
        ).json()["token"]
        work_entries = self.client.get("/api/vault", headers={"X-Vault-Token": wtok}).json()
        self.assertEqual(work_entries, [])
        default_entries = self.client.get("/api/vault", headers=self.h).json()
        self.assertEqual(len(default_entries), 1)

    def test_cross_vault_isolation(self):
        self._mk_vault("Work", "work-password-1")
        wtok = self.client.post(
            "/api/vault/unlock",
            json={"password": "work-password-1", "vault_id": self._id_of("Work")},
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
        self._mk_vault("Work", "work-password-1")
        r = self.client.post(
            "/api/vault/unlock",
            json={"password": "work-password-1", "vault_id": self._id_of("Work")},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("token"))

    def test_lock_only_revokes_caller_token(self):
        tok2 = self.client.post("/api/vault/unlock", json={"password": "master-password-1"}).json()[
            "token"
        ]
        self.assertEqual(self.client.post("/api/vault/lock", headers=self.h).status_code, 200)

        self.assertEqual(self.client.get("/api/vault", headers=self.h).status_code, 403)
        self.assertEqual(
            self.client.get("/api/vault", headers={"X-Vault-Token": tok2}).status_code, 200
        )

    def test_rename_and_flag_vault(self):
        self._mk_vault("Work", "work-password-1")
        vid = self._id_of("Work")
        response = self.client.patch(
            f"/api/vault/vaults/{vid}",
            json={"name": "Job", "travel_safe": True},
            headers=self._headers_for(vid, "work-password-1"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        v = next(v for v in self._vaults() if v["id"] == vid)
        self.assertEqual(v["name"], "Job")
        self.assertTrue(v["travel_safe"])

    def test_patch_vault_rejects_a_different_vault_token(self):
        self._mk_vault("Work", "work-password-1")
        work_id = self._id_of("Work")

        response = self.client.patch(
            f"/api/vault/vaults/{work_id}",
            json={"name": "Taken over", "travel_safe": True},
            headers=self.h,
        )

        self.assertEqual(response.status_code, 404, response.text)
        work = next(vault for vault in self._vaults() if vault["id"] == work_id)
        self.assertEqual(work["name"], "Work")
        self.assertFalse(work["travel_safe"])

    def test_delete_vault(self):
        self._mk_vault("Tmp", "temporary-password")
        vid = self._id_of("Tmp")
        self.assertEqual(
            self.client.delete(f"/api/vault/vaults/{vid}", headers=self.h).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/vault/vaults/{vid}", headers=self._headers_for(vid, "temporary-password")
            ).status_code,
            200,
        )
        self.assertNotIn("Tmp", [v["name"] for v in self._vaults()])

    def test_delete_vault_revokes_its_browser_connections_and_sessions(self):
        self._mk_vault("Tmp", "temporary-password")
        vid = self._id_of("Tmp")
        db = self.db()
        connection = BrowserConnection(
            vault_id=vid,
            name="temporary browser",
            secret_hash="hash",
            extension_origin="chrome-extension://" + "a" * 32,
        )
        db.add(connection)
        db.commit()
        connection_id = connection.id
        db.close()

        with mock.patch.object(
            browser_passwords, "lock_vault", wraps=browser_passwords.lock_vault
        ) as lock:
            response = self.client.delete(
                f"/api/vault/vaults/{vid}",
                headers=self._headers_for(vid, "temporary-password"),
            )

        self.assertEqual(response.status_code, 200, response.text)
        lock.assert_called_once_with(vid)
        db = self.db()
        self.assertIsNone(db.get(BrowserConnection, connection_id))
        db.close()

    def test_delete_vault_cleans_2fa_settings(self):
        self._mk_vault("Tmp", "temporary-password")
        vid = self._id_of("Tmp")
        headers = self._headers_for(vid, "temporary-password")
        core.settings.save_settings(
            {
                "vault_require_2fa": {vid: True, "default": True},
                "vault_2fa_totp": {vid: "tmp-secret", "default": "main-secret"},
            }
        )

        self.assertEqual(
            self.client.delete(f"/api/vault/vaults/{vid}", headers=headers).status_code,
            200,
        )

        s = core.settings.load_settings()
        self.assertNotIn(vid, s.get("vault_require_2fa") or {})
        self.assertNotIn(vid, s.get("vault_2fa_totp") or {})
        self.assertTrue((s.get("vault_require_2fa") or {}).get("default"))
        self.assertEqual((s.get("vault_2fa_totp") or {}).get("default"), "main-secret")

    def test_cannot_delete_default(self):
        self.assertEqual(
            self.client.delete("/api/vault/vaults/default", headers=self.h).status_code, 400
        )

    # ── travel mode ──────────────────────────────────────────────────────────
    def test_travel_mode_lists_only_safe(self):
        self._mk_vault("Work", "work-password-1")  # new vaults are not travel-safe by default
        self.client.put("/api/vault/travel-mode", json={"on": True}, headers=self.h)
        names = [v["name"] for v in self._vaults()]
        self.assertNotIn("Work", names)
        self.assertIn("default", [v["id"] for v in self._vaults()])  # default is travel-safe

    def test_travel_mode_blocks_unsafe_unlock(self):
        self._mk_vault("Work", "work-password-1")
        vid = self._id_of("Work")
        self.client.put("/api/vault/travel-mode", json={"on": True}, headers=self.h)
        r = self.client.post(
            "/api/vault/unlock", json={"password": "work-password-1", "vault_id": vid}
        )
        self.assertEqual(r.status_code, 403)

    def test_travel_mode_revokes_and_rechecks_an_existing_unsafe_token(self):
        self._mk_vault("Work", "work-password-1")
        vid = self._id_of("Work")
        work_headers = self._headers_for(vid, "work-password-1")
        self.assertEqual(self.client.get("/api/vault", headers=work_headers).status_code, 200)

        enabled = self.client.put("/api/vault/travel-mode", json={"on": True}, headers=self.h)

        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertEqual(self.client.get("/api/vault", headers=work_headers).status_code, 403)

    def test_default_vault_cannot_be_marked_unsafe(self):
        response = self.client.patch(
            "/api/vault/vaults/default",
            json={"travel_safe": False},
            headers=self.h,
        )

        self.assertEqual(response.status_code, 400, response.text)
        default = next(vault for vault in self._vaults() if vault["id"] == "default")
        self.assertTrue(default["travel_safe"])

    def test_travel_mode_rejects_a_legacy_state_with_no_safe_vault(self):
        from core.database import Vault

        db = self.db()
        db.query(Vault).update({Vault.travel_safe: False})
        db.commit()
        db.close()

        response = self.client.put("/api/vault/travel-mode", json={"on": True}, headers=self.h)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertFalse(self.client.get("/api/vault/travel-mode").json()["on"])

    def test_legacy_verifier_migrates(self):
        # simulate an upgraded install: no Vault rows yet, only a legacy global verifier
        from core.database import Vault
        from core.settings import save_settings

        d = self.db()
        d.query(Vault).delete()
        d.commit()
        d.close()
        save_settings({"vault_verifier": make_verifier("old-password-1")})
        ok = self.client.post("/api/vault/unlock", json={"password": "old-password-1"})
        self.assertEqual(ok.status_code, 200)
        bad = self.client.post("/api/vault/unlock", json={"password": "nope"})
        self.assertEqual(bad.status_code, 401)
