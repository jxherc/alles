import base64
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest


def _b64(b):
    return base64.b64encode(b).decode()


def _client_assertion(challenge):
    """build the authenticatorData + clientDataJSON a relying party would hand us to sign."""
    import hashlib  # noqa: F401 (kept for parity with webauthn test helper)

    client_data = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": "https://example.com"}
    ).encode()
    auth_data = os.urandom(37)
    return auth_data, client_data


class PasskeyUnitTests(ApiTest):
    def test_generate_keypair(self):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        from services import passkey

        pk = passkey.create_passkey("example.com", "alice")
        self.assertTrue(pk["credential_id"])
        self.assertTrue(pk["public_key"])
        # the private key is a real PKCS8 EC key
        load_pem_private_key(pk["private_key_pem"].encode(), password=None)

    def test_sign_roundtrips_with_verify(self):
        from services import passkey, webauthn

        pk = passkey.create_passkey("example.com", "alice")
        ch = webauthn.new_challenge()
        ad, cd = _client_assertion(ch)
        sig = passkey.sign(pk["private_key_pem"], _b64(ad), _b64(cd))
        self.assertTrue(webauthn.verify_assertion(pk["public_key"], _b64(ad), _b64(cd), sig, ch))

    def test_two_passkeys_distinct_keys(self):
        from services import passkey

        a = passkey.create_passkey("a.com", "x")
        b = passkey.create_passkey("a.com", "x")
        self.assertNotEqual(a["credential_id"], b["credential_id"])
        self.assertNotEqual(a["public_key"], b["public_key"])


class PasskeyApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles9d1-")
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

    def _new(self, rp="github.com", user="octocat"):
        return self.client.post(
            "/api/vault/passkey/new", json={"rp_id": rp, "username": user}, headers=self.h
        )

    def test_create_returns_public_credential(self):
        d = self._new().json()
        self.assertTrue(d["id"])
        self.assertTrue(d["credential_id"])
        self.assertTrue(d["public_key"])
        self.assertNotIn("private_key", d)
        self.assertNotIn("private_key_pem", d)

    def test_private_key_encrypted_in_entry(self):
        eid = self._new().json()["id"]
        from core.database import VaultEntry

        d = self.db()
        blob = d.get(VaultEntry, eid).value_encrypted
        d.close()
        self.assertNotIn("PRIVATE KEY", blob)  # the PEM is never stored in the clear

    def test_list_passkeys(self):
        self._new("github.com", "octocat")
        lst = self.client.get("/api/vault/passkeys", headers=self.h).json()
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["rp_id"], "github.com")
        self.assertEqual(lst[0]["username"], "octocat")

    def test_passkey_entry_has_rpid(self):
        eid = self._new().json()["id"]
        rev = self.client.get(f"/api/vault/{eid}/reveal", headers=self.h).json()
        self.assertEqual(rev["fields"]["rp_id"], "github.com")

    def test_create_requires_unlock(self):
        r = self.client.post("/api/vault/passkey/new", json={"rp_id": "x.com", "username": "u"})
        self.assertEqual(r.status_code, 403)

    def test_sign_endpoint_roundtrips(self):
        from services import webauthn

        d = self._new().json()
        ch = webauthn.new_challenge()
        ad, cd = _client_assertion(ch)
        r = self.client.post(
            f"/api/vault/{d['id']}/passkey/sign",
            json={"authenticator_data": _b64(ad), "client_data_json": _b64(cd)},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        sig = r.json()["signature"]
        self.assertTrue(webauthn.verify_assertion(d["public_key"], _b64(ad), _b64(cd), sig, ch))

    def test_sign_unknown_404(self):
        ad, cd = _client_assertion("abc")
        r = self.client.post(
            "/api/vault/nope/passkey/sign",
            json={"authenticator_data": _b64(ad), "client_data_json": _b64(cd)},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 404)

    def test_sign_requires_unlock(self):
        eid = self._new().json()["id"]
        ad, cd = _client_assertion("abc")
        r = self.client.post(
            f"/api/vault/{eid}/passkey/sign",
            json={"authenticator_data": _b64(ad), "client_data_json": _b64(cd)},
        )
        self.assertEqual(r.status_code, 403)
