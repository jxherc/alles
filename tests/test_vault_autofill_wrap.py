"""The Passwords UI owns paired browser access without exposing vault tokens."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "vault.js").read_text(encoding="utf-8")


class AutofillWrap(unittest.TestCase):
    def test_connected_browser_controls_are_visible_in_manage_vault(self):
        self.assertIn('id="vault-browser-access"', JS)
        self.assertIn('id="mv-browser-download"', JS)
        self.assertIn("data-browser-pair", JS)
        self.assertIn("data-browser-unlock", JS)
        self.assertIn("data-browser-lock", JS)
        self.assertIn("data-browser-revoke", JS)
        self.assertIn("exact origin", JS)

    def test_unsafe_vault_token_flow_stays_gone(self):
        self.assertNotIn("paste an unlock token", JS)
        self.assertNotIn("browser autofill is off", JS)


if __name__ == "__main__":
    unittest.main()
