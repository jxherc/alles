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


def _keypair():
    priv = ec.generate_private_key(ec.SECP256R1())
    der = priv.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv, der


def _assertion(priv, challenge):
    client_data = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": "http://localhost:8000"}
    ).encode()
    auth_data = os.urandom(37)
    sig = priv.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
    return auth_data, client_data, sig


class HwKey2faTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles9d2-")
        self._prev = os.environ.get("ALLES_DATA")
        os.environ["ALLES_DATA"] = self._tmp
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        self.tok = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["token"]
        self.h = {"X-Vault-Token": self.tok}
        self.priv, self.der = _keypair()
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
            "/api/vault/2fa/register",
            json={"label": "YubiKey", "credential_id": self.cred_id, "public_key": _b64(self.der)},
            headers=self.h,
        )

    def _enable(self, on=True):
        return self.client.put("/api/vault/2fa", json={"on": on}, headers=self.h)

    def test_register_2fa_credential(self):
        self.assertEqual(self._register().status_code, 200)
        st = self.client.get("/api/vault/2fa", headers=self.h).json()
        self.assertEqual(len(st["credentials"]), 1)

    def test_enable_2fa_requires_unlock(self):
        self.assertEqual(self.client.put("/api/vault/2fa", json={"on": True}).status_code, 403)

    def test_unlock_returns_challenge_when_2fa(self):
        self._register()
        self._enable()
        r = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()
        self.assertTrue(r.get("requires_2fa"))
        self.assertTrue(r.get("challenge"))

    def test_unlock_withholds_token_when_2fa(self):
        self._register()
        self._enable()
        r = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()
        self.assertNotIn("token", r)

    def test_twofa_unlock_valid(self):
        self._register()
        self._enable()
        ch = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["challenge"]
        ad, cd, sig = _assertion(self.priv, ch)
        r = self.client.post(
            "/api/vault/unlock/2fa",
            json={
                "vault_id": "default",
                "password": "m1",
                "credential_id": self.cred_id,
                "authenticator_data": _b64(ad),
                "client_data_json": _b64(cd),
                "signature": _b64(sig),
            },
        )
        self.assertEqual(r.status_code, 200)
        tok = r.json()["token"]
        self.assertEqual(
            self.client.get("/api/vault", headers={"X-Vault-Token": tok}).status_code, 200
        )

    def test_twofa_wrong_password_401(self):
        self._register()
        self._enable()
        ch = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["challenge"]
        ad, cd, sig = _assertion(self.priv, ch)
        r = self.client.post(
            "/api/vault/unlock/2fa",
            json={
                "vault_id": "default",
                "password": "WRONG",
                "credential_id": self.cred_id,
                "authenticator_data": _b64(ad),
                "client_data_json": _b64(cd),
                "signature": _b64(sig),
            },
        )
        self.assertEqual(r.status_code, 401)

    def test_twofa_bad_assertion_401(self):
        self._register()
        self._enable()
        ch = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["challenge"]
        ad, cd, sig = _assertion(self.priv, ch)
        bad = bytearray(sig)
        bad[-1] ^= 0xFF
        r = self.client.post(
            "/api/vault/unlock/2fa",
            json={
                "vault_id": "default",
                "password": "m1",
                "credential_id": self.cred_id,
                "authenticator_data": _b64(ad),
                "client_data_json": _b64(cd),
                "signature": _b64(bytes(bad)),
            },
        )
        self.assertEqual(r.status_code, 401)

    def test_twofa_unknown_credential_404(self):
        self._register()
        self._enable()
        ch = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()["challenge"]
        ad, cd, sig = _assertion(self.priv, ch)
        r = self.client.post(
            "/api/vault/unlock/2fa",
            json={
                "vault_id": "default",
                "password": "m1",
                "credential_id": _b64(os.urandom(16)),
                "authenticator_data": _b64(ad),
                "client_data_json": _b64(cd),
                "signature": _b64(sig),
            },
        )
        self.assertEqual(r.status_code, 404)

    def test_disable_2fa_restores_plain_unlock(self):
        self._register()
        self._enable()
        self._enable(False)
        r = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()
        self.assertTrue(r.get("token"))

    def test_no_credential_no_lockout(self):
        # enabling 2fa without ever registering a key must not lock the user out
        self._enable()
        r = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()
        self.assertTrue(r.get("token"))
