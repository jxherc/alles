"""ui-8a — vault toolbar: settings (gear) moved rightmost, glyphs unified to the central icon set,
switcher reads as a chip. Behavioral check in docs/evidence/ui-8a/verify.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "vault.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _head():
    i = INDEX.index('id="vault-view"')
    return INDEX[i : INDEX.index("vault-locked", i)]


class VaultToolbar(unittest.TestCase):
    def test_settings_is_rightmost(self):
        head = _head()
        # manage (settings) appears after lock in the source order
        self.assertLess(head.index("vault-lock-btn"), head.index("vault-manage-btn"))

    def test_toolbar_emoji_removed(self):
        head = _head()
        for g in ("✈", "⚙", "🛡", "🔓", "＋"):
            self.assertNotIn(g, head)

    def test_buttons_decorated_with_icons(self):
        self.assertIn("dec('vault-manage-btn', 'gear', 'settings')", JS)
        self.assertIn("dec('vault-watchtower-btn', 'shield', 'watchtower')", JS)
        self.assertIn("dec('vault-bio-add-btn', 'fingerprint', 'biometric')", JS)
        # travel button keeps its toggle text but with a plane icon
        self.assertIn("_si('plane')} travel", JS)

    def test_switcher_is_a_chip_with_icon_map(self):
        self.assertIn('class="custom-select vault-switcher"', INDEX)
        self.assertIn("_iconHtml", JS)
        # the ' ✈' label suffix is gone
        self.assertNotIn("' ✈'", JS)
        self.assertRegex(CSS, r"\.vault-switcher\s*\{")

    def test_manage_panel_and_gen_de_iconed(self):
        self.assertNotIn("✈ safe", JS)
        self.assertNotIn("⚙ gen", JS)
        self.assertIn("_si('plane')} safe", JS)
        self.assertIn("_si('refresh')} gen", JS)

    def test_uses_central_icon_helper(self):
        self.assertIn("window.icon", JS)
        self.assertRegex(JS, r"_si\s*=\s*n\s*=>")


if __name__ == "__main__":
    unittest.main()
