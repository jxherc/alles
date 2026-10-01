import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return m.group(1) if m else ""


class StyleTokenTests(unittest.TestCase):
    def test_signal_token_is_real(self):
        self.assertRegex(CSS, r"--signal:\s*#[0-9a-fA-F]{6};")
        self.assertRegex(CSS, r"--warn:\s*var\(--signal\);")
        self.assertNotRegex(CSS, r"var\(--signal\s*,")

    def test_perm_menu_hover_is_not_same_as_menu_bg(self):
        self.assertIn("background: var(--panel)", _rule(".perm-menu"))
        hover = _rule(".perm-menu-item:hover")
        self.assertIn("background:", hover)
        self.assertNotIn("background: var(--panel)", hover)
        self.assertIn("background: var(--bg)", hover)

    def test_legacy_add_endpoint_form_css_is_gone(self):
        self.assertNotIn(".add-ep-form", CSS)
        self.assertIn(".mm-add-form", CSS)
        self.assertIn(".s-ep-form", CSS)


if __name__ == "__main__":
    unittest.main()
