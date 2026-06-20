"""ui-6a — gallery header/grid/lightbox rebuild: consistent control sizing, no ad-hoc inline styles,
tidy lightbox layout. Behavioral/computed-style check in docs/evidence/ui-6a/verify.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _photos_head():
    i = INDEX.index('class="page-view-head photos-head"')
    return INDEX[i : INDEX.index("page-view-body", i)]


class GalleryRebuild(unittest.TestCase):
    def test_header_uses_a_scoped_class(self):
        self.assertIn('class="page-view-head photos-head"', INDEX)

    def test_no_per_button_inline_font_size(self):
        # the ad-hoc style="font-size:0.72rem" repeated on every control is gone
        head = _photos_head()
        self.assertNotIn("font-size:0.72rem", head)
        self.assertNotIn('style="font-size', head)

    def test_control_sizing_centralised(self):
        self.assertRegex(CSS, r"\.photos-head \.btn[^{]*\{[^}]*font-size:\s*0\.72rem")
        self.assertRegex(CSS, r"\.photos-head \.photos-trash\s*\{[^}]*margin-left:\s*auto")

    def test_album_and_model_selects_keep_caps(self):
        self.assertRegex(CSS, r"\.photos-album-sel\s*\{[^}]*max-width:\s*180px")
        self.assertRegex(CSS, r"\.photos-model-sel\s*\{[^}]*max-width:\s*170px")

    def test_lightbox_side_widened(self):
        self.assertRegex(CSS, r"\.photos-lightbox-side\s*\{[^}]*width:\s*264px")

    def test_lightbox_actions_are_a_grid(self):
        self.assertRegex(CSS, r"\.photos-lightbox-actions\s*\{[^}]*display:\s*grid")
        self.assertRegex(
            CSS, r"\.photos-lightbox-actions\s*\{[^}]*grid-template-columns:\s*1fr 1fr"
        )

    def test_grid_typography_tightened(self):
        self.assertRegex(CSS, r"\.photos-moment-grid\s*\{[^}]*minmax\(140px")


if __name__ == "__main__":
    unittest.main()
