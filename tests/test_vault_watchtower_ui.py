"""ui-8d — Watchtower: explained, sectioned layout, and a real toggle (active when open, re-click hides).
Behavioral check in docs/evidence/ui-8d/verify.py; the scan backend is covered by test_vault_totp_watchtower."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "vault.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class WatchtowerUi(unittest.TestCase):
    def test_is_a_real_toggle(self):
        self.assertIn("let _wtOpen", JS)
        self.assertIn("function _closeWatchtower", JS)
        # re-click closes
        self.assertIn("if (_wtOpen) { _closeWatchtower(); return; }", JS)

    def test_button_indicates_active(self):
        self.assertIn("vault-watchtower-btn')?.classList.add('active')", JS)
        self.assertIn("vault-watchtower-btn')?.classList.remove('active')", JS)
        self.assertRegex(CSS, r"#vault-watchtower-btn\.active")

    def test_has_an_explainer(self):
        self.assertIn("wt-intro", JS)
        self.assertIn("scans your saved passwords", JS)

    def test_sections_have_descriptions(self):
        self.assertIn("wt-desc", JS)
        self.assertIn("known data breaches", JS)
        self.assertIn("more than one login", JS)

    def test_lock_resets_state(self):
        # locking clears the open flag so reopening the vault doesn't think it's still showing
        i = JS.index("async function _doLock")
        self.assertIn("_wtOpen = false", JS[i : i + 400])

    def test_layout_css_present(self):
        self.assertRegex(CSS, r"\.wt-section\s*\{[^}]*border")
        self.assertRegex(CSS, r"\.wt-intro\b")


if __name__ == "__main__":
    unittest.main()
