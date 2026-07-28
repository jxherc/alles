"""ui-6a — gallery header/grid/lightbox rebuild: consistent control sizing, no ad-hoc inline styles,
tidy lightbox layout. Behavioral/computed-style check in docs/evidence/ui-6a/verify.py."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _photos_head():
    i = INDEX.index('class="page-view-head photos-head"')
    return INDEX[i : INDEX.index("photos-layout", i)]


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
        # search is pushed to the right edge of the slim top bar
        self.assertRegex(CSS, r"\.photos-head \.photos-search\s*\{[^}]*margin-left:\s*auto")

    def test_desktop_title_aligns_with_the_sidebar_content_edge(self):
        self.assertIn(
            "--photos-rail-content-x: calc(var(--photos-rail-pad) + var(--photos-nav-pad))",
            CSS,
        )
        self.assertRegex(
            CSS,
            r"#photos-view \.photos-head\s*\{[^}]*padding-left:\s*var\(--photos-rail-content-x\)",
        )

    def test_sidebar_layout_replaces_dropdowns(self):
        # phase 1: the album/model <select>s are gone, replaced by the immich-style left rail
        self.assertIn('class="photos-layout"', INDEX)
        self.assertIn('class="photos-sidebar"', INDEX)
        self.assertNotIn("photos-album-sel", INDEX)
        self.assertNotIn("photos-model-sel", INDEX)
        self.assertRegex(CSS, r"\.photos-layout\s*\{[^}]*display:\s*flex")
        self.assertRegex(
            CSS,
            r"\.photos-sidebar\s*\{[^}]*width:\s*var\(--photos-rail-w,\s*184px\)",
        )
        # justified mosaic rows
        self.assertRegex(CSS, r"\.photos-row\s*\{[^}]*display:\s*flex")

    def test_active_gallery_controls_use_neutral_kokuen_states(self):
        nav_rule = re.search(r"\.photos-nav-item\.active\s*\{([^}]*)\}", CSS)
        filter_rule = re.search(r"\.photos-filt-seg button\.active\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(nav_rule)
        self.assertIsNotNone(filter_rule)
        for rule in (nav_rule.group(1), filter_rule.group(1)):
            self.assertIn("var(--text)", rule)
            self.assertIn("var(--panel)", rule)
            self.assertNotIn("var(--accent)", rule)

    def test_selection_bar_present(self):
        # phase 2: multi-select action bar + per-cell check-circles
        self.assertIn('id="photos-selbar"', INDEX)
        self.assertIn('id="photos-sel-count"', INDEX)
        for bid in ("photos-sel-fav", "photos-sel-archive", "photos-sel-album", "photos-sel-del"):
            self.assertIn(bid, INDEX)
        self.assertRegex(CSS, r"#photos-view\.selecting \.photos-head\s*\{[^}]*display:\s*none")
        self.assertRegex(CSS, r"\.photos-check\s*\{")

    def test_lightbox_has_slide_in_drawer(self):
        # phase 3: the info/exif panel is a slide-in drawer toggled with the info button / 'i'
        self.assertIn('id="photos-lb-drawer"', INDEX)
        self.assertIn('id="photos-info-btn"', INDEX)
        self.assertRegex(CSS, r"\.photos-lb-drawer\s*\{[^}]*transform:\s*translateX\(100%\)")
        self.assertRegex(
            CSS, r"#photos-lightbox\.drawer-open \.photos-lb-drawer\s*\{[^}]*transform:\s*none"
        )

    def test_lightbox_has_prevnext_and_help(self):
        for el in ("photos-prev-btn", "photos-next-btn", "photos-lb-help", "photos-archive-btn"):
            self.assertIn(f'id="{el}"', INDEX)
        self.assertRegex(CSS, r"\.photos-lb-nav\s*\{")

    def test_scrubber_and_filterbar_present(self):
        # phase 5: date scrubber + filter bar
        for el in (
            "photos-scrubber",
            "photos-scrub-thumb",
            "photos-filterbar",
            "photos-filter-btn",
            "photos-filt-camera",
        ):
            self.assertIn(f'id="{el}"', INDEX)
        self.assertRegex(CSS, r"\.photos-scrubber\s*\{")
        self.assertRegex(CSS, r"\.photos-filterbar\s*\{")

    def test_stack_and_dupes_ui_present(self):
        # phase 6: stack action in the selection bar + stack/dup styling
        self.assertIn('id="photos-sel-stack"', INDEX)
        self.assertRegex(CSS, r"\.photos-stack-badge\s*\{")
        self.assertRegex(CSS, r"\.photos-dup-keep\s*\{")

    def test_grid_typography_tightened(self):
        self.assertRegex(CSS, r"\.photos-moment-grid\s*\{[^}]*minmax\(140px")


if __name__ == "__main__":
    unittest.main()
