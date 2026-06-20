"""ui-8b (frontend contract) — manage panel: main badge, inline rename, change-password.
Backend re-key/main-flag logic is covered by tests/test_vault_main_rekey.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "vault.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class VaultMainUi(unittest.TestCase):
    def test_main_badge_rendered(self):
        self.assertIn("mv-badge", JS)
        self.assertIn("v.main ? 'main' : 'own password'", JS)

    def test_help_text_explains_model(self):
        self.assertIn("mv-help", JS)
        self.assertIn("opens with your master password", JS)

    def test_inline_rename(self):
        self.assertIn("function _inlineRename", JS)
        self.assertIn("data-rename", JS)
        self.assertIn("JSON.stringify({ name })", JS)

    def test_change_password_flow(self):
        self.assertIn("function _changeVaultPw", JS)
        self.assertIn("function _promptNewPw", JS)
        self.assertIn("/api/vault/vaults/password", JS)
        # the current vault's button reads change-master vs change-password
        self.assertIn("change master password", JS)
        self.assertIn("data-chpw", JS)

    def test_token_rebinds_after_change(self):
        self.assertRegex(JS, r"_token = \(await r\.json\(\)\)\.token")

    def test_css_for_badge_and_rename(self):
        self.assertRegex(CSS, r".mv-badge.mv-main")
        self.assertRegex(CSS, r"\.mv-rename-input")


if __name__ == "__main__":
    unittest.main()
