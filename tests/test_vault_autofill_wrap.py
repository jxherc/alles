"""The Passwords UI explains the retired extension and keeps the safe web fallback."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "vault.js").read_text(encoding="utf-8")


class AutofillWrap(unittest.TestCase):
    def test_retired_notice_is_visible_in_manage_vault(self):
        self.assertIn('id="vault-autofill-info"', JS)
        self.assertIn('aria-label="browser autofill status"', JS)
        self.assertIn('class="mv-autofill-text"', JS)
        self.assertIn("browser autofill is off", JS)
        self.assertIn("remove or reload the old extension", JS)
        self.assertIn("reveal and copy logins here in Passwords", JS)

    def test_unsafe_install_instructions_are_gone(self):
        self.assertNotIn('id="vault-ext-link"', JS)
        self.assertNotIn("developer.chrome.com/docs/extensions", JS)
        self.assertNotIn("paste an unlock token", JS)


if __name__ == "__main__":
    unittest.main()
