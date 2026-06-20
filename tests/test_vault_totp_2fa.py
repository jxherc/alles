"""ui-8c — authenticator-app (TOTP) as a second unlock factor for a vault, alongside passkeys.
Sets up a TOTP secret, enables 2FA, and gates unlock behind a 6-digit code."""

import os
import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from services.pwtools import totp_now, totp_secret, totp_verify
from tests._client import ApiTest


class TotpHelpers(ApiTest):
    def test_secret_is_base32(self):
        s = totp_secret()
        self.assertGreaterEqual(len(s), 16)
        self.assertTrue(all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in s))

    def test_verify_accepts_current_code(self):
        s = totp_secret()
        self.assertTrue(totp_verify(s, totp_now(s)))

    def test_verify_rejects_wrong_code(self):
        s = totp_secret()
        self.assertFalse(totp_verify(s, "000000" if totp_now(s) != "000000" else "111111"))

    def test_verify_tolerates_one_step_skew(self):
        s = totp_secret()
        prev = totp_now(s, t=0)  # counter 0
        # a code from the previous 30s window is still accepted at t just into the next window
        self.assertTrue(totp_verify(s, prev, t=31))


class TotpUnlock2fa(ApiTest):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="alles8c-")
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

    def _enable_totp(self):
        s = self.client.post("/api/vault/2fa/totp/setup", headers=self.h).json()["secret"]
        r = self.client.post(
            "/api/vault/2fa/totp", json={"secret": s, "code": totp_now(s)}, headers=self.h
        )
        return s, r

    def test_setup_returns_secret_and_uri(self):
        d = self.client.post("/api/vault/2fa/totp/setup", headers=self.h).json()
        self.assertIn("secret", d)
        self.assertTrue(d["uri"].startswith("otpauth://totp/"))

    def test_enable_requires_correct_code(self):
        s = self.client.post("/api/vault/2fa/totp/setup", headers=self.h).json()["secret"]
        bad = self.client.post(
            "/api/vault/2fa/totp", json={"secret": s, "code": "000000"}, headers=self.h
        )
        self.assertEqual(bad.status_code, 400)

    def test_enable_then_status_shows_totp(self):
        _, r = self._enable_totp()
        self.assertEqual(r.status_code, 200)
        st = self.client.get("/api/vault/2fa", headers=self.h).json()
        self.assertTrue(st["totp"])
        self.assertTrue(st["on"])

    def test_unlock_now_demands_2fa_with_totp_method(self):
        self._enable_totp()
        r = self.client.post("/api/vault/unlock", json={"password": "m1"}).json()
        self.assertTrue(r.get("requires_2fa"))
        self.assertIn("totp", r.get("methods", []))
        self.assertNotIn("token", r)

    def test_unlock_2fa_totp_with_code_returns_token(self):
        s, _ = self._enable_totp()
        r = self.client.post(
            "/api/vault/unlock/2fa/totp", json={"password": "m1", "code": totp_now(s)}
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["token"])

    def test_unlock_2fa_totp_wrong_code_rejected(self):
        self._enable_totp()
        r = self.client.post(
            "/api/vault/unlock/2fa/totp", json={"password": "m1", "code": "000000"}
        )
        self.assertEqual(r.status_code, 401)

    def test_unlock_2fa_totp_wrong_password_rejected(self):
        s, _ = self._enable_totp()
        r = self.client.post(
            "/api/vault/unlock/2fa/totp", json={"password": "nope", "code": totp_now(s)}
        )
        self.assertEqual(r.status_code, 401)

    def test_disable_totp(self):
        self._enable_totp()
        self.client.delete("/api/vault/2fa/totp", headers=self.h)
        st = self.client.get("/api/vault/2fa", headers=self.h).json()
        self.assertFalse(st["totp"])


if __name__ == "__main__":
    import unittest

    unittest.main()
