"""ui-7d — journal toolbar (search / export / lock) shares one height + baseline.
Computed-style check in docs/evidence/ui-7d/verify.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class JournalToolbarAlign(unittest.TestCase):
    def test_controls_share_a_height(self):
        # one rule sizes both the search input and the toolbar buttons
        self.assertRegex(
            CSS, r"\.jrnl-toolbar \.jrnl-search,\s*\.jrnl-toolbar \.btn\s*\{[^}]*height:\s*30px"
        )
        self.assertRegex(
            CSS,
            r"\.jrnl-toolbar \.jrnl-search,\s*\.jrnl-toolbar \.btn\s*\{[^}]*font-size:\s*0\.74rem",
        )

    def test_search_margin_zeroed(self):
        # the leaked .jrnl-tags margin-top is cancelled so tops line up
        self.assertRegex(CSS, r"\.jrnl-toolbar \.jrnl-search\s*\{[^}]*margin:\s*0")

    def test_buttons_center_their_content(self):
        self.assertRegex(CSS, r"\.jrnl-toolbar \.btn\s*\{[^}]*align-items:\s*center")


if __name__ == "__main__":
    unittest.main()
