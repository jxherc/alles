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
    head = INDEX[a : INDEX.index("photos-layout", a)]
    lb = INDEX[INDEX.index('id="photos-lightbox"') :]
    lb = lb[: lb.index("</div>\n</div>") + 6]
    return head + lb


def _photos_fn(name):
    start = PHOTOS.index(f"function {name}")
    nxt = PHOTOS.find("\nfunction ", start + 1)
    exp = PHOTOS.find("\nexport function ", start + 1)
    stops = [x for x in (nxt, exp) if x != -1]
    end = min(stops) if stops else len(PHOTOS)
    return PHOTOS[start:end]


class GalleryIcons(unittest.TestCase):
    def test_no_emoji_in_photos_js(self):
        for g in GONE + ["★"]:
            self.assertNotIn(g, PHOTOS, f"{g!r} still in photos.js")

    def test_no_emoji_in_photos_markup(self):
        import re

        block = _photos_block()
        # the shortcuts legend legitimately shows the literal arrow keys inside <kbd> chips
        block = re.sub(r"<kbd>.*?</kbd>", "", block)
        for g in GONE:
            self.assertNotIn(g, block, f"{g!r} still in gallery markup")

    def test_uses_central_icon_helper(self):
        self.assertIn("window.icon", PHOTOS)
        self.assertRegex(PHOTOS, r"_si\s*=\s*n\s*=>")
        self.assertGreater(PHOTOS.count("_si("), 10)

    def test_header_buttons_carry_inline_icons(self):
        # share renders an <svg class="ic"> in the static markup
        # (generate/trash moved out of the header in phase 1 — gen dropped, trash → sidebar)
        block = _photos_block()
        i = block.index("photos-share-album-btn")
        self.assertIn('svg class="ic"', block[i : i + 400], "share button missing inline icon")

    def test_lightbox_actions_decorated_in_js(self):
        for name in ("edit", "download", "trash", "close", "eye-off"):
            self.assertIn(f"_si('{name}')", PHOTOS)

    def test_lightbox_keyboard_and_nav_icons(self):
        # phase 3: arrow stepping + shortcuts handler, chevron / info icons
        self.assertIn("addEventListener('keydown'", PHOTOS)
        for name in ("info", "chevron-left", "chevron-right", "archive"):
            self.assertIn(f"_si('{name}')", PHOTOS)

    def test_fav_badge_is_an_icon_not_css_glyph(self):
        self.assertIn("photos-fav-badge", PHOTOS)
        self.assertIn("_si('heart-fill')", PHOTOS)
        # the old CSS ♥ pseudo-element is gone
        self.assertNotRegex(CSS, r"\.photos-cell\.fav::after\s*\{[^}]*content:\s*'♥'")
        self.assertRegex(CSS, r"\.photos-fav-badge\s+\.ic")

    def test_sidebar_nav_uses_icon_map(self):
        # the left rail builds each nav item's glyph through the central icon set (_si(ic))
        self.assertIn("photos-nav-item", PHOTOS)
        self.assertIn("_si(ic)", PHOTOS)
        for name in (
            "'image'",
            "'map-pin'",
            "'sparkles'",
            "'folder'",
            "'heart'",
            "'lock'",
            "'trash'",
        ):
            self.assertIn(name, PHOTOS, f"sidebar icon {name} missing")

    def test_video_badge_uses_play_icon(self):
        self.assertIn("_si('play')", PHOTOS)
        self.assertRegex(CSS, r"\.photos-vbadge\s+\.ic")

    def test_trash_uses_shared_video_cell_markup(self):
        block = PHOTOS[
            PHOTOS.index("async function openPhotoTrash") : PHOTOS.index(
                "async function uploadPhotos"
            )
        ]
        self.assertIn("_cellHtml(p, restore)", block)
        self.assertNotIn('<img loading="lazy" src="${p.thumb}" alt="">', block)
        self.assertIn("extra = ''", _photos_fn("_cellHtml"))


if __name__ == "__main__":
    unittest.main()
