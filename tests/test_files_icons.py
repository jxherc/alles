"""ui-5b — files app uses the central icon set, not emoji/Unicode glyphs.
Source-level contract; behavioral render check lives in docs/evidence/ui-5b/verify.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = (ROOT / "static" / "js" / "files.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
ICONS = (ROOT / "static" / "js" / "icons.js").read_text(encoding="utf-8")

# the emoji/Unicode glyphs that used to live in the files controls
GONE = [
    "🕘",
    "🖼",
    "📦",
    "📈",
    "🧬",
    "🗑",
    "☆",
    "★",
    "⇗",
    "💬",
    "⏱",
    "⊙",
    "✎",
    "✕",
    "↩",
    "☰",
    "▦",
    "✓",
    "○",
    "🎉",
]


class IconUnification(unittest.TestCase):
    def test_no_action_emoji_left(self):
        for g in GONE:
            self.assertNotIn(g, FILES, f"{g!r} still in files.js — swap it for window.icon")

    def test_uses_central_icon_helper(self):
        # the _si wrapper guards window.icon load order and is used everywhere
        self.assertIn("window.icon", FILES)
        self.assertRegex(FILES, r"_si\s*=\s*n\s*=>")
        # used in the smart bar, row actions, comment badge, star toggle
        self.assertGreater(FILES.count("_si("), 14)

    def test_smart_folders_mapped(self):
        # the SMART array carries icon names; activity/dup/star/trash render inline
        for name in ("clock", "image", "file", "archive"):
            self.assertIn(f"icon: '{name}'", FILES, f"smart folder icon {name} missing")
        for name in ("history", "copy", "star", "trash"):
            self.assertIn(f"_si('{name}')", FILES, f"smart action icon {name} missing")

    def test_row_actions_mapped(self):
        for name in ("download", "share", "comment", "tag", "edit"):
            self.assertIn(f"_si('{name}')", FILES)
        # star fills when starred (ternary, not a bare literal call)
        self.assertIn("'star-fill'", FILES)

    def test_star_toggle_renders_icon_not_glyph(self):
        # toggleStar sets innerHTML with an icon, not a textContent star glyph
        self.assertRegex(FILES, r"innerHTML\s*=\s*_si\(on \? 'star-fill' : 'star'\)")

    def test_view_toggle_and_sort_use_icons(self):
        self.assertRegex(FILES, r"_si\('list'\).*_si\('grid'\)")
        self.assertIn("chevron-down", FILES)
        self.assertIn("chevron-up", FILES)

    def test_all_referenced_icons_exist_in_catalog(self):
        import re

        for name in set(re.findall(r"_si\('([a-z-]+)'\)", FILES)):
            self.assertIn(
                f"  {name}:",
                ICONS.replace("'", ""),
                f"icon '{name}' referenced in files.js but not defined in icons.js",
            )

    def test_css_sizes_icons_in_controls(self):
        self.assertRegex(CSS, r"\.file-act \.ic\s*\{[^}]*width")
        self.assertRegex(CSS, r"\.files-smart \.ic\s*\{[^}]*width")
        self.assertRegex(CSS, r"#files-view-toggle \.ic")


if __name__ == "__main__":
    unittest.main()
