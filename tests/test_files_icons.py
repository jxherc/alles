"""ui-5b — files app uses the central icon set, not emoji/Unicode glyphs.
Source-level contract for the shipped Files workbench; rendered coverage is in pw_phase7_files_real.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = (ROOT / "static" / "js" / "filesphase7.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "kokuen.css").read_text(encoding="utf-8")
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
            self.assertNotIn(g, FILES, f"{g!r} still in filesphase7.js — swap it for window.icon")

    def test_uses_central_icon_helper(self):
        self.assertIn("if (window.icon) return window.icon(name)", FILES)
        self.assertIn("function locationIcon(kind)", FILES)
        self.assertIn("return icon('folder')", FILES)

    def test_storage_and_file_types_use_named_icons(self):
        for name in ("cloud", "database", "folder", "image", "file"):
            self.assertIn(f"icon('{name}')", FILES)

    def test_all_referenced_icons_exist_in_catalog(self):
        import re

        names = set(re.findall(r"icon\('([a-z-]+)'\)", FILES))
        self.assertTrue(names)
        for name in names:
            self.assertIn(f"  {name}:", ICONS.replace("'", ""), name)

    def test_css_sizes_location_icons(self):
        self.assertRegex(CSS, r"\.files-location-button svg\s*\{[^}]*width")


if __name__ == "__main__":
    unittest.main()
