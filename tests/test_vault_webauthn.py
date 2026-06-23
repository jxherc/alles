import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

import core.settings
from tests._client import ApiTest


def _b64(b):
    return base64.b64encode(b).decode()


def _make_keypair():
    priv = ec.generate_private_key(ec.SECP256R1())
    der = priv.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv, der


def _assertion(priv, challenge, *, typ="webauthn.get"):
    """build a WebAuthn-shaped assertion the way a browser authenticator would."""
    client_data = json.dumps(
        {"type": typ, "challenge": challenge, "origin": "http://localhost:8000"}
    ).encode()
    auth_data = os.urandom(37)  # rpIdHash(32) + flags(1) + counter(4)
    signed = auth_data + hashlib.sha256(client_data).digest()
    sig = priv.sign(signed, ec.ECDSA(hashes.SHA256()))
    return auth_data, client_data, sig


class WebAuthnUnitTests(ApiTest):
    def test_challenge_random(self):
        from services import webauthn

        a, b = webauthn.new_challenge(), webauthn.new_challenge()
        self.assertTrue(a and b)
        self.assertNotEqual(a, b)

    def test_verify_valid_assertion(self):
        from services import webauthn

        priv, der = _make_keypair()
        ch = webauthn.new_challenge()
        ad, cd, sig = _assertion(priv, ch)
        self.assertTrue(webauthn.verify_assertion(_b64(der), _b64(ad), _b64(cd), _b64(sig), ch))

    def test_verify_bad_signature(self):
        from services import webauthn

        priv, der = _make_keypair()
        ch = webauthn.new_challenge()
        ad, cd, sig = _assertion(priv, ch)
        bad = bytearray(sig)
        bad[-1] ^= 0xFF
        self.assertFalse(
            webauthn.verify_assertion(_b64(der), _b64(ad), _b64(cd), _b64(bytes(bad)), ch)
        )

    def test_verify_wrong_challenge(self):
        from services import webauthn

        priv, der = _make_keypair()
        ad, cd, sig = _assertion(priv, webauthn.new_challenge())
        self.assertFalse(
            webauthn.verify_assertion(_b64(der), _b64(ad), _b64(cd), _b64(sig), "someother")
        )

    def test_verify_wrong_type(self):
        from services import webauthn

        priv, der = _make_keypair()
        ch = webauthn.new_challenge()
        ad, cd, sig = _assertion(priv, ch, typ="webauthn.create")
        self.assertFalse(webauthn.verify_assertion(_b64(der), _b64(ad), _b64(cd), _b64(sig), ch))


class WebAuthnApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles9c2-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        self.tok = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["token"]
        self.h = {"X-Vault-Token": self.tok}
        self.priv, self.der = _make_keypair()
        self.cred_id = _b64(os.urandom(16))

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        if self._prev is None:
            os.environ.pop("ALLES_DATA", None)
        else:
            os.environ["ALLES_DATA"] = self._prev
        super().tearDown()

    def _register(self):
        return self.client.post(
            "/api/vault/webauthn/register",
            json={"label": "MacBook", "credential_id": self.cred_id, "public_key": _b64(self.der)},
            headers=self.h,
        )

    def test_register_requires_unlock(self):
        r = self.client.post(
            "/api/vault/webauthn/register",
            json={"label": "x", "credential_id": self.cred_id, "public_key": _b64(self.der)},
        )
        self.assertEqual(r.status_code, 403)

    def test_register_stores_credential(self):
        self.assertEqual(self._register().status_code, 200)
        creds = self.client.get("/api/vault/webauthn/credentials", headers=self.h).json()
        self.assertEqual(len(creds), 1)
        self.assertEqual(creds[0]["label"], "MacBook")

    def test_list_credentials(self):
        self._register()
        creds = self.client.get("/api/vault/webauthn/credentials", headers=self.h).json()
        for k in ("id", "label", "credential_id"):
            self.assertIn(k, creds[0])

    def test_delete_credential(self):
        self._register()
        cid = self.client.get("/api/vault/webauthn/credentials", headers=self.h).json()[0]["id"]
        self.client.delete(f"/api/vault/webauthn/credentials/{cid}", headers=self.h)
        self.assertEqual(
            self.client.get("/api/vault/webauthn/credentials", headers=self.h).json(), []
        )

    def test_webauthn_unlock_returns_token(self):
        self._register()
        ch = self.client.get("/api/vault/webauthn/challenge").json()["challenge"]
        ad, cd, sig = _assertion(self.priv, ch)
        r = self.client.post(
            "/api/vault/webauthn/unlock",
            json={
                "vault_id": "default",
                "credential_id": self.cred_id,
                "authenticator_data": _b64(ad),
                "client_data_json": _b64(cd),
                "signature": _b64(sig),
            },
        )
        self.assertEqual(r.status_code, 200)
        tok = r.json()["token"]
        # the released token actually opens the vault
        self.assertEqual(
            self.client.get("/api/vault", headers={"X-Vault-Token": tok}).status_code, 200
        )

    def test_webauthn_unlock_bad_assertion_401(self):
        self._register()
        ch = self.client.get("/api/vault/webauthn/challenge").json()["challenge"]
        ad, cd, sig = _assertion(self.priv, ch)
        bad = bytearray(sig)
        bad[-1] ^= 0xFF
        r = self.client.post(
            "/api/vault/webauthn/unlock",
            json={
                "vault_id": "default",
                "credential_id": self.cred_id,
                "authenticator_data": _b64(ad),
                "client_data_json": _b64(cd),
                "signature": _b64(bytes(bad)),
            },
        )
        self.assertEqual(r.status_code, 401)

    def test_biometric_blob_not_plaintext(self):
        self._register()
        from core.database import Vault

        d = self.db()
        blob = d.get(Vault, "default").biometric_blob
        d.close()
        self.assertTrue(blob)
        self.assertNotIn("m1", blob)  # the master pw is never stored in the clear

    def test_biometric_blob_rewrapped_on_password_change(self):
        # changing the master password must re-wrap the biometric blob, else a later
        # biometric unlock releases the OLD password and every decrypt fails (vault bricked)
        self._register()
        r = self.client.post(
            "/api/vault/vaults/password", json={"new_password": "m2"}, headers=self.h
        )
        self.assertEqual(r.status_code, 200)
        from core.database import Vault
        from routes.vault import _server_key
        from services.crypto import decrypt

        d = self.db()
        blob = d.get(Vault, "default").biometric_blob
        d.close()
        self.assertEqual(decrypt(_server_key(), blob), "m2")  # now releases the NEW password
