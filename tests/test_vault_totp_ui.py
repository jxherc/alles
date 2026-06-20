"""ui-8c (frontend contract) — TOTP enrolment in the 2FA panel + the unlock code prompt + explainers.
Backend TOTP logic is covered by tests/test_vault_totp_2fa.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "vault.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class VaultTotpUi(unittest.TestCase):
    def test_panel_has_both_methods(self):
        self.assertIn("passkey / security key", JS)
        self.assertIn("authenticator app (TOTP)", JS)

    def test_setup_posts_to_setup_endpoint(self):
        self.assertIn("function _setupTotp", JS)
        self.assertIn("/api/vault/2fa/totp/setup', { method: 'POST' }", JS)
        self.assertIn("/api/vault/2fa/totp", JS)

    def test_unlock_handles_requires_2fa(self):
        self.assertIn("j.requires_2fa", JS)
        self.assertIn("function _do2fa", JS)
        self.assertIn("/api/vault/unlock/2fa/totp", JS)
        self.assertIn("function _promptCode", JS)

    def test_biometric_vs_passkey_explainer(self):
        self.assertIn("mv-2fa-note", JS)
        self.assertIn("biometric unlock", JS)
        # explains biometric replaces the password vs passkey being a second factor
        self.assertIn("it replaces the password", JS)
        self.assertIn("second factor", JS)

    def test_disable_path(self):
        self.assertIn("mv-totp-del", JS)
        self.assertRegex(JS, r"/api/vault/2fa/totp'?,\s*\{\s*method:\s*'DELETE'")

    def test_css_for_secret_and_note(self):
        self.assertRegex(CSS, r"\.totp-secret\b")
        self.assertRegex(CSS, r"\.mv-2fa-note\b")


if __name__ == "__main__":
    unittest.main()
