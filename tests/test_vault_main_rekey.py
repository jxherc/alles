"""ui-8b — main vault (master password) vs per-vault passwords, + change-vault-password re-key.
The main vault is the default; others have their own password. Changing a vault's password re-encrypts
its entries (and attachments) under the new key, atomically."""

import asyncio
import io
import os
import tempfile
from pathlib import Path
from unittest import mock

from fastapi import HTTPException, UploadFile

import core.settings
from routes import vault as vault_routes
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
        self._mk("Work", "work-password-1")
        w = next(v for v in self._vaults() if v["name"] == "Work")
        self.assertFalse(w["main"])

    def test_created_vault_uses_own_password_not_master(self):
        self._mk("Work", "work-password-1")
        wid = self._id_of("Work")
        self.assertEqual(self._unlock("work-password-1", wid).status_code, 200)
        self.assertEqual(self._unlock("master-password-1", wid).status_code, 401)

    # ── change-password re-key ──
    def _entry(self, headers, name="gmail", pw="hunter2"):
        return self.client.post(
            "/api/vault",
            json={"name": name, "username": "me", "fields": {"password": pw, "username": "me"}},
            headers=headers,
        ).json()["id"]

    def test_change_password_rekeys_entries(self):
        self._mk("Work", "work-password-1")
        wid = self._id_of("Work")
        wh = {"X-Vault-Token": self._unlock("work-password-1", wid).json()["token"]}
        eid = self._entry(wh)
        r = self.client.post(
            "/api/vault/vaults/password", json={"new_password": "work-password-2"}, headers=wh
        )
        self.assertEqual(r.status_code, 200)
        # old password no longer unlocks; new one does
        self.assertEqual(self._unlock("work-password-1", wid).status_code, 401)
        ntok = self._unlock("work-password-2", wid).json()["token"]
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
            "/api/vault/vaults/password", json={"new_password": "master-password-2"}, headers=self.h
        )
        self.assertEqual(r.status_code, 200)
        ntok = self._unlock("master-password-2").json()["token"]
        dl = self.client.get(f"/api/vault/attachments/{aid}", headers={"X-Vault-Token": ntok})
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.content, blob)

    def test_settings_mirror_failure_does_not_undo_committed_rekey(self):
        eid = self._entry(self.h)
        blob = b"keep the committed password generation"
        up = self.client.post(
            f"/api/vault/{eid}/attachments",
            files={"file": ("s.bin", io.BytesIO(blob), "application/octet-stream")},
            headers=self.h,
        )
        self.assertEqual(up.status_code, 200)
        aid = up.json()["id"]

        with mock.patch.object(
            vault_routes,
            "save_settings",
            side_effect=RuntimeError("settings write died"),
        ):
            changed = self.client.post(
                "/api/vault/vaults/password",
                json={"new_password": "master-password-2"},
                headers=self.h,
            )

        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self._unlock("master-password-1").status_code, 401)
        new_headers = {"X-Vault-Token": self._unlock("master-password-2").json()["token"]}
        revealed = self.client.get(f"/api/vault/{eid}/reveal", headers=new_headers)
        self.assertEqual(revealed.status_code, 200)
        downloaded = self.client.get(f"/api/vault/attachments/{aid}", headers=new_headers)
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, blob)

    def test_rekey_revokes_every_old_token_for_the_vault(self):
        second = self._unlock("master-password-1").json()["token"]
        changed = self.client.post(
            "/api/vault/vaults/password",
            json={"new_password": "master-password-2"},
            headers=self.h,
        )
        self.assertEqual(changed.status_code, 200)

        self.assertEqual(self.client.get("/api/vault", headers=self.h).status_code, 403)
        self.assertEqual(
            self.client.get("/api/vault", headers={"X-Vault-Token": second}).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                "/api/vault",
                headers={"X-Vault-Token": changed.json()["token"]},
            ).status_code,
            200,
        )

    def test_inflight_old_password_cannot_write_after_rekey(self):
        eid = self._entry(self.h)
        changed = self.client.post(
            "/api/vault/vaults/password",
            json={"new_password": "master-password-2"},
            headers=self.h,
        )
        self.assertEqual(changed.status_code, 200)

        db = self.db()
        try:
            stale = ("master-password-1", "default")
            blocked_calls = (
                lambda: vault_routes.create_entry(
                    vault_routes.CreateEntry(name="late entry", value="old-key-data"),
                    db=db,
                    ctx=stale,
                ),
                lambda: vault_routes.patch_entry(
                    eid,
                    vault_routes.PatchEntry(value="old-key-data"),
                    db=db,
                    ctx=stale,
                ),
                lambda: asyncio.run(
                    vault_routes.add_attachment(
                        eid,
                        UploadFile(file=io.BytesIO(b"old-key-data"), filename="late.bin"),
                        db=db,
                        ctx=stale,
                    )
                ),
                lambda: vault_routes.webauthn_register(
                    vault_routes.WaRegister(
                        label="late device",
                        credential_id="late-credential",
                        public_key="late-public-key",
                    ),
                    db=db,
                    ctx=stale,
                ),
            )
            for call in blocked_calls:
                with self.subTest(call=call), self.assertRaises(HTTPException) as err:
                    call()
                self.assertEqual(err.exception.status_code, 403)

            fake_passkey = {
                "rp_id": "example.test",
                "username": "late-user",
                "credential_id": "late-passkey",
                "public_key": "late-public-key",
                "private_key_pem": "late-private-key",
            }
            with (
                mock.patch("services.passkey.create_passkey", return_value=fake_passkey),
                self.assertRaises(HTTPException) as err,
            ):
                vault_routes.passkey_new(
                    vault_routes.PasskeyNew(rp_id="example.test"),
                    db=db,
                    ctx=stale,
                )
            self.assertEqual(err.exception.status_code, 403)
        finally:
            db.close()

        new_headers = {"X-Vault-Token": changed.json()["token"]}
        revealed = self.client.get(f"/api/vault/{eid}/reveal", headers=new_headers)
        self.assertEqual(revealed.json()["fields"]["password"], "hunter2")
        self.assertEqual(
            self.client.get(f"/api/vault/{eid}/attachments", headers=new_headers).json(),
            [],
        )
        self.assertEqual(len(self.client.get("/api/vault", headers=new_headers).json()), 1)

    def test_change_password_restores_attachment_if_commit_fails(self):
        self._mk("Work", "work-password-1")
        wid = self._id_of("Work")
        wh = {"X-Vault-Token": self._unlock("work-password-1", wid).json()["token"]}
        eid = self._entry(wh)
        blob = b"keep me readable"
        up = self.client.post(
            f"/api/vault/{eid}/attachments",
            files={"file": ("s.bin", io.BytesIO(blob), "application/octet-stream")},
            headers=wh,
        )
        aid = up.json()["id"]
        path = Path(self._tmp) / "vault_attachments" / f"{aid}.enc"
        old_cipher = path.read_bytes()

        db = self.db()
        try:
            with mock.patch.object(db, "commit", side_effect=RuntimeError("commit died")):
                with self.assertRaises(HTTPException) as err:
                    vault_routes.change_vault_password(
                        vault_routes.ChangePw(new_password="work-password-2"),
                        db=db,
                        ctx=("work-password-1", wid),
                    )
            self.assertEqual(err.exception.status_code, 500)
        finally:
            db.close()

        self.assertEqual(path.read_bytes(), old_cipher)
        self.assertEqual(self._unlock("work-password-1", wid).status_code, 200)
        self.assertEqual(self._unlock("work-password-2", wid).status_code, 401)
        dl = self.client.get(f"/api/vault/attachments/{aid}", headers=wh)
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.content, blob)

    def test_change_default_password_changes_master(self):
        self.client.post(
            "/api/vault/vaults/password", json={"new_password": "master-password-2"}, headers=self.h
        )
        self.assertEqual(self._unlock("master-password-1").status_code, 401)
        self.assertEqual(self._unlock("master-password-2").status_code, 200)

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
        self._mk("Work", "work-password-1")
        wid = self._id_of("Work")
        work_token = self._unlock("work-password-1", wid).json()["token"]
        response = self.client.patch(
            f"/api/vault/vaults/{wid}",
            json={"name": "Job"},
            headers={"X-Vault-Token": work_token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Job", [v["name"] for v in self._vaults()])
