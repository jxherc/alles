"""ui-8f — the autofill "how to load it" link is on its own line, not mid-paragraph."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "vault.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class AutofillWrap(unittest.TestCase):
    def test_text_and_link_are_separate(self):
        self.assertIn('class="mv-autofill-text"', JS)
        self.assertIn('class="mv-autofill-link', JS)

    def test_link_on_its_own_line(self):
        # the paragraph text is block, the link sits beneath it with its own margin
        self.assertRegex(CSS, r"\.mv-autofill-text\s*\{[^}]*display:\s*block")
        self.assertRegex(CSS, r"\.mv-autofill-link\s*\{[^}]*margin-top")


if __name__ == "__main__":
    unittest.main()
