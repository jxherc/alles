"""Independent TOTP checks with disposable local credentials and no providers.

These checks complement the production-generator-based enrollment tests. They
do not certify QR scanning, third-party authenticators, or cryptographic security.
"""

import base64
import hashlib
import hmac
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

# Disable dotenv before the isolated harness imports application settings. This
# is necessary even when this module is run directly with ordinary unittest.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
from tests._client import ApiTest

# isort: split
# The harness must establish temporary data before application modules load.
import core.settings
import routes.vault
from services.pwtools import totp_now, totp_verify


def independent_code(key: bytes, timestamp: int, period: int = 30, digits: int = 6):
    counter = timestamp // period
    digest = hmac.digest(key, counter.to_bytes(8, "big"), "sha1")
    offset = digest[-1] & 15
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{value % (10**digits):0{digits}d}"


class TotpDavinciCounterTests(unittest.TestCase):
    def test_independent_step_large_counter_normalization_and_skew(self):
        key = hashlib.sha256(b"alles independent totp test fixture").digest()[:20]
        encoded = base64.b32encode(key).decode().rstrip("=")
        variants = {
            "uppercase": encoded,
            "lowercase": encoded.lower(),
            "spaced": " ".join(encoded[i : i + 4] for i in range(0, len(encoded), 4)),
        }
        for timestamp in (
            29,
            30,
            2_147_483_647,
            2_147_483_648,
            20_000_000_000,
            (2**32 - 1) * 30,
            2**32 * 30,
            (2**32 + 1) * 60,
        ):
            for period in (30, 60):
                for digits in (6, 8):
                    for label, secret in variants.items():
                        with self.subTest(
                            timestamp=timestamp,
                            period=period,
                            digits=digits,
                            normalization=label,
                        ):
                            self.assertEqual(
                                totp_now(secret, period=period, digits=digits, t=timestamp),
                                independent_code(key, timestamp, period, digits),
                            )
        now = 1_700_000_000
        for offset in (-2, -1, 0, 1, 2):
            with self.subTest(skew_steps=offset):
                code = independent_code(key, now + offset * 30)
                self.assertEqual(totp_verify(encoded, code, t=now), abs(offset) <= 1)


class TotpDavinciEnrollmentTests(ApiTest):
    NOW = 1_700_000_000
    PASSWORD = "synthetic-totp-master-only"

    def setUp(self):
        super().setUp()
        # ApiTest normally uses tearDown; registering it immediately also closes
        # its client/engine if a later assertion in this subclass's setup fails.
        self.addCleanup(super().tearDown)
        self.temp_data = tempfile.TemporaryDirectory(prefix="alles-totp-davinci-")
        self.addCleanup(self.temp_data.cleanup)
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "ALLES_DATA": self.temp_data.name,
                    "PYTHON_DOTENV_DISABLED": "1",
                },
            )
        )
        # Register before patching: LIFO cleanup restores the old path, then
        # clears any cached settings loaded from this test's now-unused path.
        self.addCleanup(core.settings._clear_settings_cache)
        self.enterContext(
            mock.patch.object(
                core.settings,
                "_SETTINGS_FILE",
                Path(self.temp_data.name) / "settings.json",
            )
        )
        core.settings._clear_settings_cache()
        self.enterContext(mock.patch.object(routes.vault, "_unlock_tokens", {}))
        self.enterContext(mock.patch.object(time, "time", return_value=self.NOW))
        response = self.client.post("/api/vault/unlock", json={"password": self.PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.headers = {"X-Vault-Token": response.json()["token"]}

    def tearDown(self):
        # All resources, including the base harness, are registered cleanups.
        pass

    def test_independent_enrollment_expiry_and_settings_cache_reload(self):
        setup = self.client.post("/api/vault/2fa/totp/setup", headers=self.headers)
        self.assertEqual(setup.status_code, 200)
        payload = setup.json()
        secret = payload["secret"]
        key = base64.b32decode(secret + "=" * (-len(secret) % 8))
        uri = urlsplit(payload["uri"])
        self.assertEqual(uri.scheme, "otpauth")
        self.assertEqual(uri.netloc, "totp")
        self.assertEqual(parse_qs(uri.query)["secret"], [secret])
        status = self.client.get("/api/vault/2fa", headers=self.headers)
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["totp"])

        allowed = {independent_code(key, self.NOW + step * 30) for step in (-1, 0, 1)}
        expired = next(
            code
            for step in range(2, 32)
            if (code := independent_code(key, self.NOW - step * 30)) not in allowed
        )
        refused = self.client.post(
            "/api/vault/2fa/totp", headers=self.headers, json={"secret": secret, "code": expired}
        )
        self.assertEqual(refused.status_code, 400)
        self.assertNotIn("default", core.settings.load_settings().get("vault_2fa_totp", {}))
        enabled = self.client.post(
            "/api/vault/2fa/totp",
            headers=self.headers,
            json={"secret": secret, "code": independent_code(key, self.NOW)},
        )
        self.assertEqual(enabled.status_code, 200)
        core.settings._clear_settings_cache()
        self.assertEqual(core.settings.load_settings()["vault_2fa_totp"]["default"], secret)

        challenge = self.client.post("/api/vault/unlock", json={"password": self.PASSWORD})
        self.assertEqual(challenge.status_code, 200)
        self.assertTrue(challenge.json()["requires_2fa"])
        self.assertNotIn("token", challenge.json())
        refused_unlock = self.client.post(
            "/api/vault/unlock/2fa/totp", json={"password": self.PASSWORD, "code": expired}
        )
        self.assertEqual(refused_unlock.status_code, 401)
        accepted = self.client.post(
            "/api/vault/unlock/2fa/totp",
            json={"password": self.PASSWORD, "code": independent_code(key, self.NOW)},
        )
        self.assertEqual(accepted.status_code, 200)
        new_headers = {"X-Vault-Token": accepted.json()["token"]}
        status = self.client.get("/api/vault/2fa", headers=new_headers)
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["totp"])


if __name__ == "__main__":
    unittest.main()
