"""s9 vault security: one test per claim in the life vault's "alles vault threat model".

wrapped random vault key (Argon2id), the password never held, the v1 upgrade on unlock (made
from fixtures in the base code's own format), unlock throttling, passkey PRF wraps, the
activity log, and the password-protected export.
"""

import base64
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest import mock

import core.settings
from core.database import Vault, VaultAttachment, VaultEntry, WebAuthnCredential
from routes import vault as vault_routes
from services import crypto, vault_audit, vault_export, vault_keys
from tests._client import ApiTest
from tests.test_vault_webauthn import _assertion, _b64, _make_keypair

PW = "master-password-1"


class CryptoV2Tests(ApiTest):
    def test_kdf_is_argon2id_at_rfc9106_strength(self):
        key = crypto.new_vault_key(PW)
        _v, kdf, memory, passes, lanes, _salt, _blob = key.verifier.split(".")
        self.assertEqual(kdf, "argon2id")
        self.assertGreaterEqual(int(memory), 64 * 1024)
        self.assertGreaterEqual(int(passes), 3)
        self.assertGreaterEqual(int(lanes), 4)

    def test_wrong_password_opens_nothing_and_key_never_prints(self):
        key = crypto.new_vault_key(PW)
        self.assertIsNone(crypto.open_vault_key("master-password-2", key.verifier))
        self.assertEqual(crypto.open_vault_key(PW, key.verifier).key, key.key)
        self.assertNotIn(key.key.hex(), repr(key))
        self.assertNotIn(PW, key.verifier)

    def test_v2_blobs_need_the_key_and_v1_still_reads_with_the_password(self):
        key = crypto.new_vault_key(PW)
        blob = crypto.encrypt(key, "secret")
        self.assertTrue(blob.startswith(crypto.ENTRY_PREFIX))
        with self.assertRaises(ValueError):
            crypto.decrypt(PW, blob)
        self.assertEqual(crypto.decrypt(PW, crypto.encrypt(PW, "old")), "old")
        other = crypto.new_vault_key(PW)
        with self.assertRaises(Exception):
            crypto.decrypt(other, blob)

    def test_rewrap_keeps_the_key(self):
        key = crypto.new_vault_key(PW)
        moved = crypto.rewrap("master-password-2", key)
        self.assertEqual(moved.key, key.key)
        self.assertNotEqual(moved.verifier, key.verifier)
        self.assertIsNone(crypto.open_vault_key(PW, moved.verifier))


class VaultKeyApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles-s9-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = Path(self._tmp) / "settings.json"
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", self._sf)
        self.sp.start()
        core.settings._clear_settings_cache()
        vault_routes._unlock_tokens.clear()
        vault_keys.reset_throttle()

    def tearDown(self):
        self.sp.stop()
        core.settings._clear_settings_cache()
        vault_routes._unlock_tokens.clear()
        vault_keys.reset_throttle()
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        try:
            super().tearDown()
        finally:
            shutil.rmtree(self._tmp, ignore_errors=True)

    def _unlock(self, pw=PW):
        return self.client.post("/api/vault/unlock", json={"password": pw})

    def _h(self, pw=PW):
        r = self._unlock(pw)
        self.assertEqual(r.status_code, 200, r.text)
        return {"X-Vault-Token": r.json()["token"]}

    def _attach_dir(self):
        return Path(self._tmp) / "vault_attachments"

    # ── base-code fixture: exactly what the code before s9 wrote ──
    def _legacy_vault(self, with_passkey=False):
        attach = self._attach_dir()
        attach.mkdir(parents=True, exist_ok=True)
        db = self.db()
        db.add(Vault(id="default", name="Personal", verifier=crypto.make_verifier(PW)))
        rows = [
            VaultEntry(
                vault_id="default",
                name="gmail",
                username="me",
                type="password",
                value_encrypted=crypto.encrypt(PW, json.dumps({"password": "hunter2"})),
            ),
            VaultEntry(
                vault_id="default",
                name="bank card",
                type="card",
                value_encrypted=crypto.encrypt(PW, json.dumps({"number": "4111111111111111"})),
            ),
            VaultEntry(
                vault_id="default",
                name="ancient",
                type="password",
                value_encrypted=crypto.encrypt(PW, "bare old value"),
            ),
        ]
        db.add_all(rows)
        db.flush()
        att = VaultAttachment(entry_id=rows[0].id, filename="note.bin", size=5)
        db.add(att)
        db.flush()
        (attach / f"{att.id}.enc").write_bytes(crypto.encrypt_bytes(PW, b"\x00file"))
        if with_passkey:
            priv, der = _make_keypair()
            cred_id = _b64(os.urandom(16))
            db.add(
                WebAuthnCredential(
                    vault_id="default", label="mac", credential_id=cred_id, public_key=_b64(der)
                )
            )
            db.get(Vault, "default").biometric_blob = crypto.encrypt(vault_routes._server_key(), PW)
            self.priv, self.cred_id = priv, cred_id
        db.commit()
        ids = [r.id for r in rows]
        aid = att.id
        db.close()
        core.settings.save_settings({"vault_verifier": "legacy-mirror"})
        return ids, aid

    def _reveal(self, h, eid):
        return self.client.get(f"/api/vault/{eid}/reveal", headers=h)

    # ── claims ──
    def test_new_vault_stores_wrapped_key_and_v2_blobs(self):
        h = self._h()
        eid = self.client.post(
            "/api/vault", json={"name": "x", "fields": {"password": "p"}}, headers=h
        ).json()["id"]
        db = self.db()
        self.assertTrue(crypto.is_v2(db.get(Vault, "default").verifier))
        self.assertTrue(db.get(VaultEntry, eid).value_encrypted.startswith("v2:"))
        db.close()
        up = self.client.post(
            f"/api/vault/{eid}/attachments", files={"file": ("a.bin", b"data")}, headers=h
        )
        self.assertEqual(up.status_code, 200, up.text)
        raw = (self._attach_dir() / f"{up.json()['id']}.enc").read_bytes()
        self.assertTrue(raw.startswith(crypto.BYTES_MAGIC))

    def test_server_memory_holds_the_key_never_the_password(self):
        self._h()
        for _exp, held, _vid in vault_routes._unlock_tokens.values():
            self.assertIsInstance(held, crypto.VaultKey)
            self.assertNotEqual(held, PW)
        settings_text = self._sf.read_text()
        self.assertNotIn(PW, settings_text)

    def test_base_code_vault_upgrades_on_unlock_and_loses_nothing(self):
        ids, aid = self._legacy_vault()
        h = self._h()
        self.assertEqual(self._reveal(h, ids[0]).json()["fields"]["password"], "hunter2")
        self.assertEqual(self._reveal(h, ids[1]).json()["fields"]["number"], "4111111111111111")
        self.assertEqual(self._reveal(h, ids[2]).json()["fields"]["password"], "bare old value")
        dl = self.client.get(f"/api/vault/attachments/{aid}", headers=h)
        self.assertEqual(dl.content, b"\x00file")
        db = self.db()
        v = db.get(Vault, "default")
        self.assertTrue(crypto.is_v2(v.verifier))
        self.assertEqual(db.query(VaultEntry).count(), 3)
        self.assertTrue(all(e.value_encrypted.startswith("v2:") for e in db.query(VaultEntry)))
        db.close()
        self.assertTrue(
            (self._attach_dir() / f"{aid}.enc").read_bytes().startswith(crypto.BYTES_MAGIC)
        )
        self.assertEqual(list(self._attach_dir().glob("*.v2tmp")), [])
        self.assertEqual(core.settings.load_settings()["vault_verifier"], v.verifier)
        # and the old password still works, the next unlock is a plain v2 unlock
        self.assertEqual(self._unlock().status_code, 200)
        self.assertEqual(self._unlock("wrong-password-9").status_code, 401)

    def test_failed_upgrade_changes_nothing(self):
        ids, aid = self._legacy_vault()
        path = self._attach_dir() / f"{aid}.enc"
        before = path.read_bytes()
        db = self.db()
        with (
            mock.patch.object(db, "commit", side_effect=RuntimeError("disk full")),
            self.assertRaises(RuntimeError),
        ):
            vault_keys.upgrade_vault(
                db, db.get(Vault, "default"), PW, self._attach_dir(), vault_routes._server_key
            )
        db.close()
        db = self.db()
        self.assertFalse(crypto.is_v2(db.get(Vault, "default").verifier))
        self.assertFalse(db.get(VaultEntry, ids[0]).value_encrypted.startswith("v2:"))
        db.close()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self._attach_dir().glob("*.v2tmp")), [])
        h = self._h()
        self.assertEqual(self._reveal(h, ids[0]).json()["fields"]["password"], "hunter2")

    def test_crash_between_commit_and_file_swap_resumes_next_unlock(self):
        _ids, aid = self._legacy_vault()
        db = self.db()
        with mock.patch.object(vault_keys.os, "replace"):
            vault_keys.upgrade_vault(
                db, db.get(Vault, "default"), PW, self._attach_dir(), vault_routes._server_key
            )
        db.close()
        path = self._attach_dir() / f"{aid}.enc"
        self.assertFalse(path.read_bytes().startswith(crypto.BYTES_MAGIC))
        h = self._h()
        self.assertTrue(path.read_bytes().startswith(crypto.BYTES_MAGIC))
        self.assertEqual(
            self.client.get(f"/api/vault/attachments/{aid}", headers=h).content, b"\x00file"
        )

    def test_wrong_passwords_are_throttled(self):
        self._h()
        for _ in range(vault_keys.FREE_TRIES - 1):
            self.assertEqual(self._unlock("wrong-password-9").status_code, 401)
        self.assertEqual(self._unlock("wrong-password-9").status_code, 401)  # the 5th starts a wait
        blocked = self._unlock(PW)
        self.assertEqual(blocked.status_code, 429)
        self.assertGreaterEqual(int(blocked.headers["Retry-After"]), 1)
        later = time.monotonic() + vault_keys.MAX_WAIT + 1
        with mock.patch.object(vault_keys.time, "monotonic", return_value=later):
            self.assertEqual(self._unlock(PW).status_code, 200)
        self.assertEqual(vault_keys.wait_left("default", self._verifier()), 0)

    def _verifier(self):
        db = self.db()
        try:
            return db.get(Vault, "default").verifier
        finally:
            db.close()

    def _passkey_unlock(self, prf=""):
        ch = self.client.get("/api/vault/webauthn/challenge").json()
        self._count = getattr(self, "_count", 0) + 1  # sign counts must go up
        ad, cd, sig = _assertion(self.priv, ch["challenge"], counter=self._count)
        return self.client.post(
            "/api/vault/webauthn/unlock",
            json={
                "vault_id": "default",
                "credential_id": self.cred_id,
                "authenticator_data": _b64(ad),
                "client_data_json": _b64(cd),
                "signature": _b64(sig),
                "prf": prf,
            },
            headers={"Origin": "http://localhost:8000"},
        )

    def test_passkey_with_prf_needs_its_own_secret(self):
        h = self._h()
        self.priv, der = _make_keypair()
        self.cred_id = _b64(os.urandom(16))
        prf = os.urandom(32)
        r = self.client.post(
            "/api/vault/webauthn/register",
            json={
                "credential_id": self.cred_id,
                "public_key": _b64(der),
                "prf": base64.urlsafe_b64encode(prf).decode(),
            },
            headers=h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["prf"])
        ch = self.client.get("/api/vault/webauthn/challenge").json()
        self.assertTrue(ch["prf_salt"])
        self.assertEqual(self._passkey_unlock().status_code, 400)
        self.assertEqual(
            self._passkey_unlock(base64.urlsafe_b64encode(os.urandom(32)).decode()).status_code,
            401,
        )
        ok = self._passkey_unlock(base64.urlsafe_b64encode(prf).decode())
        self.assertEqual(ok.status_code, 200, ok.text)
        held = vault_routes._unlock_tokens[ok.json()["token"]][1]
        self.assertEqual(held.key, vault_routes._unlock_tokens[h["X-Vault-Token"]][1].key)
        # the data folder alone (db + settings with the server key) can't open a prf wrap
        db = self.db()
        blob = db.get(Vault, "default").biometric_blob
        db.close()
        self.assertIsNone(vault_keys.open_wrap(blob, self.cred_id, None, vault_routes._server_key))

    def test_base_code_passkey_unlock_upgrades_and_drops_the_password_copy(self):
        ids, _aid = self._legacy_vault(with_passkey=True)
        r = self._passkey_unlock()
        self.assertEqual(r.status_code, 200, r.text)
        h = {"X-Vault-Token": r.json()["token"]}
        self.assertEqual(self._reveal(h, ids[0]).json()["fields"]["password"], "hunter2")
        db = self.db()
        blob = db.get(Vault, "default").biometric_blob
        db.close()
        self.assertEqual(json.loads(blob)["wraps"][self.cred_id]["kind"], "device")
        self.assertNotIn(PW, blob)
        self.assertEqual(self._passkey_unlock().status_code, 200)

    def test_activity_log_records_without_secrets(self):
        h = self._h()
        self._unlock("wrong-password-9")
        eid = self.client.post(
            "/api/vault", json={"name": "gmail", "fields": {"password": "hunter2"}}, headers=h
        ).json()["id"]
        self._reveal(h, eid)
        self.client.post("/api/vault/lock", headers=h)
        h = self._h()
        rows = self.client.get("/api/vault/audit", headers=h).json()
        actions = [r["action"] for r in rows]
        for action in ("created", "unlock_failed", "revealed", "locked", "unlocked"):
            self.assertIn(action, actions)
        revealed = next(r for r in rows if r["action"] == "revealed")
        self.assertEqual(revealed["entry_name"], "gmail")
        text = (Path(self._tmp) / "vault-audit.jsonl").read_text()
        self.assertNotIn("hunter2", text)
        self.assertNotIn(PW, text)
        self.assertEqual(self.client.get("/api/vault/audit").status_code, 403)

    def test_audit_log_stays_bounded(self):
        with mock.patch.object(vault_audit, "KEEP", 10):
            for i in range(200):
                vault_audit.record("default", "locked", n=i)
        lines = (Path(self._tmp) / "vault-audit.jsonl").read_text().splitlines()
        self.assertLessEqual(len(lines), 10 + 200)
        self.assertLess(len(lines), 200)

    def test_export_is_sealed_and_imports_back(self):
        h = self._h()
        self.client.post(
            "/api/vault", json={"name": "gmail", "fields": {"password": "hunter2"}}, headers=h
        )
        body = {"vault_password": "nope-nope-1", "export_password": "export-pass-1"}
        self.assertEqual(
            self.client.post("/api/vault/export", json=body, headers=h).status_code, 401
        )
        body["vault_password"] = PW
        r = self.client.post("/api/vault/export", json=body, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertNotIn("hunter2", r.text)
        self.assertNotIn("gmail", r.text)
        self.assertEqual(json.loads(r.text)["kdf"]["name"], "argon2id")
        payload = vault_export.open_sealed("export-pass-1", r.text)
        self.assertEqual(payload["entries"][0]["fields"]["password"], "hunter2")
        with self.assertRaises(vault_export.ExportError):
            vault_export.open_sealed("export-pass-2", r.text)
        bad = self.client.post(
            "/api/vault/import",
            json={"export_password": "export-pass-2", "file": r.text},
            headers=h,
        )
        self.assertEqual(bad.status_code, 400)
        good = self.client.post(
            "/api/vault/import",
            json={"export_password": "export-pass-1", "file": r.text},
            headers=h,
        )
        self.assertEqual(good.json(), {"imported": 1})
        names = [e["name"] for e in self.client.get("/api/vault", headers=h).json()]
        self.assertEqual(names.count("gmail"), 2)

    def test_export_file_cant_ask_for_a_huge_kdf(self):
        sealed = json.loads(vault_export.seal("export-pass-1", {"entries": []}))
        sealed["kdf"]["memory_kib"] = 64 * 1024 * 1024
        with self.assertRaises(vault_export.ExportError):
            vault_export.open_sealed("export-pass-1", json.dumps(sealed))
