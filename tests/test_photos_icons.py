"""ui-6b — gallery uses the central icon set, not emoji/Unicode glyphs.
Behavioral render check lives in docs/evidence/ui-6b/verify.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = (ROOT / "static" / "js" / "photos.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

GONE = ["🔗", "✨", "🗑", "♥", "♡", "▶", "🔒", "🗺", "📍", "↩", "←"]


def _photos_block():
    a = INDEX.index('id="photos-view"')
    head = INDEX[a : INDEX.index("page-view-body", a)]
    lb = INDEX[INDEX.index('id="photos-lightbox"') :]
    lb = lb[: lb.index("</div>\n</div>") + 6]
    return head + lb


class GalleryIcons(unittest.TestCase):
    def test_no_emoji_in_photos_js(self):
        for g in GONE + ["★"]:
            self.assertNotIn(g, PHOTOS, f"{g!r} still in photos.js")

    def test_no_emoji_in_photos_markup(self):
        block = _photos_block()
        for g in GONE:
            self.assertNotIn(g, block, f"{g!r} still in gallery markup")

    def test_uses_central_icon_helper(self):
        self.assertIn("window.icon", PHOTOS)
        self.assertRegex(PHOTOS, r"_si\s*=\s*n\s*=>")
        self.assertGreater(PHOTOS.count("_si("), 10)

    def test_header_buttons_carry_inline_icons(self):
        # share / generate / trash render an <svg class="ic"> in the static markup
        block = _photos_block()
        for bid in ("photos-share-album-btn", "photos-gen-btn", "photos-trash-btn"):
            i = block.index(bid)
            self.assertIn('svg class="ic"', block[i : i + 400], f"{bid} missing inline icon")

    def test_lightbox_actions_decorated_in_js(self):
        for name in ("edit", "download", "trash", "close", "eye-off"):
            self.assertIn(f"_si('{name}')", PHOTOS)

    def test_fav_badge_is_an_icon_not_css_glyph(self):
        self.assertIn("photos-fav-badge", PHOTOS)
        self.assertIn("_si('heart-fill')", PHOTOS)
        # the old CSS ♥ pseudo-element is gone
        self.assertNotRegex(CSS, r"\.photos-cell\.fav::after\s*\{[^}]*content:\s*'♥'")
        self.assertRegex(CSS, r"\.photos-fav-badge\s+\.ic")

    def test_album_options_use_icon_map(self):
        self.assertIn("_iconHtml", PHOTOS)
        self.assertIn("__fav__: _si('star')", PHOTOS)
        self.assertIn("__hidden__: _si('lock')", PHOTOS)

    def test_video_badge_uses_play_icon(self):
        self.assertIn("_si('play')", PHOTOS)
        self.assertRegex(CSS, r"\.photos-vbadge\s+\.ic")


if __name__ == "__main__":
    unittest.main()
