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


class FilesRowsAndHeader(unittest.TestCase):
    """27.27: the files list read as buggy on an ipad."""

    REVAMP = (ROOT / "static" / "revamp.css").read_text(encoding="utf-8")

    def test_folders_show_no_size(self):
        # a folder isn't 0 B; the list and the details leave the size out
        self.assertIn("item.type === 'dir' ? '' : esc(formatSize(item.size))", FILES)
        self.assertIn("${item.type === 'dir' ? '' : `<dt>${t('files.meta_size')}", FILES)

    def test_picked_row_is_the_one_fill(self):
        self.assertIn("${selected ? ' is-selected' : ''}", FILES)
        self.assertIn("row?.classList.toggle('is-selected', selected)", FILES)
        self.assertIn(":is(:hover, :focus-within, .is-current, .is-selected)", CSS)
        # the select box drew its own 44px tile inside the row's hover, and it stuck after a tap
        self.assertNotRegex(CSS, r"#files-view \.files-check:hover,")

    def test_header_follows_the_column_not_the_screen(self):
        # the details panel and a resized sidebar narrow the column at any screen width
        self.assertIn("container: files-browser / inline-size", self.REVAMP)
        self.assertIn("@container files-browser (max-width: 779px)", self.REVAMP)


if __name__ == "__main__":
    unittest.main()
