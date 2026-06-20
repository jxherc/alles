import tempfile
from pathlib import Path
from unittest import mock

import core.settings
from tests._client import ApiTest

# RFC 6238 test vector: base32 of "12345678901234567890", SHA1, T=59 → 94287082 (6-digit: 287082)
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class TotpWatchtowerTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._sf.close()
        self.sp = mock.patch.object(core.settings, "_SETTINGS_FILE", Path(self._sf.name))
        self.sp.start()
        self.tok = self.client.post("/api/vault/unlock", json={"password": "master-1"}).json()[
            "token"
        ]
        self.h = {"X-Vault-Token": self.tok}

    def tearDown(self):
        self.sp.stop()
        Path(self._sf.name).unlink(missing_ok=True)
        super().tearDown()

    def _entry(self, name, fields, type="password"):
        return self.client.post(
            "/api/vault", json={"name": name, "fields": fields, "type": type}, headers=self.h
        ).json()["id"]

    # ── TOTP unit ──
    def test_totp_rfc_vector(self):
        from services.pwtools import totp_now

        self.assertEqual(totp_now(RFC_SECRET, period=30, digits=6, t=59), "287082")

    def test_totp_same_window_stable(self):
        from services.pwtools import totp_now

        # 990–1019 is one 30s window; both must produce the same code
        self.assertEqual(totp_now(RFC_SECRET, t=995), totp_now(RFC_SECRET, t=1019))

    def test_totp_remaining_range(self):
        from services.pwtools import totp_remaining

        rem = totp_remaining(period=30, t=1000)
        self.assertTrue(1 <= rem <= 30)

    def test_totp_endpoint_returns_code(self):
        eid = self._entry("GitHub", {"password": "x", "totp": RFC_SECRET})
        d = self.client.get(f"/api/vault/{eid}/totp", headers=self.h).json()
        self.assertEqual(len(d["code"]), 6)
        self.assertIn("seconds", d)

    def test_totp_endpoint_no_secret_404(self):
        eid = self._entry("NoTotp", {"password": "x"})
        self.assertEqual(self.client.get(f"/api/vault/{eid}/totp", headers=self.h).status_code, 404)

    # ── Watchtower unit ──
    def test_is_weak(self):
        from services.pwtools import is_weak

        self.assertTrue(is_weak("123"))
        self.assertFalse(is_weak("a9$Kf2!qZ7mWp0L#"))

    def test_find_reused(self):
        from services.pwtools import find_reused

        groups = find_reused(
            [
                {"id": "1", "password": "samePass1!"},
                {"id": "2", "password": "samePass1!"},
                {"id": "3", "password": "unique-other-9"},
            ]
        )
        self.assertTrue(any(set(g) == {"1", "2"} for g in groups))

    def test_breach_count_parses(self):
        from services.pwtools import breach_count

        # 'password' SHA1 = 5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8; suffix after first 5 chars:
        suffix = "1E4C9B93F3F0682250B6CF8331B7EE68FD8"

        def fake_fetch(prefix):
            return f"{suffix}:37359\r\nABCDEF0123456789ABCDEF0123456789ABC:5"

        self.assertEqual(breach_count("password", fake_fetch), 37359)

    # ── Watchtower endpoint ──
    def test_watchtower_weak(self):
        self._entry("Weak", {"password": "123"})
        d = self.client.get("/api/vault/watchtower", headers=self.h).json()
        self.assertTrue(any(w["name"] == "Weak" for w in d["weak"]))

    def test_watchtower_reused(self):
        self._entry("A", {"password": "Repeated-Pw-1!"})
        self._entry("B", {"password": "Repeated-Pw-1!"})
        d = self.client.get("/api/vault/watchtower", headers=self.h).json()
        self.assertTrue(d["reused"])
        self.assertTrue(any(len(g["names"]) >= 2 for g in d["reused"]))

    def test_watchtower_breached(self):
        self._entry("Pwned", {"password": "password"})
        with mock.patch(
            "routes.vault._hibp_fetch",
            return_value="1E4C9B93F3F0682250B6CF8331B7EE68FD8:99",
        ):
            d = self.client.get("/api/vault/watchtower", headers=self.h).json()
        self.assertTrue(any(x["name"] == "Pwned" for x in d["breached"]))

    def test_watchtower_requires_unlock_403(self):
        self.assertEqual(self.client.get("/api/vault/watchtower").status_code, 403)
