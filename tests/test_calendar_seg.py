"""ui-5c — calendar view switcher is the shared segmented (.seg) control, not the ad-hoc button row.
Behavioral switching lives in docs/evidence/ui-5c/verify.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CAL = (ROOT / "static" / "js" / "calendar.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class CalendarSegSwitcher(unittest.TestCase):
    def test_switcher_is_a_seg(self):
        self.assertRegex(INDEX, r'<div class="seg seg-cal" id="cal-view"')
        # the old bespoke button row is gone
        self.assertNotIn("cal-view-btn", INDEX)
        self.assertNotIn("cal-view-toggle", INDEX)

    def test_five_views_as_seg_opts(self):
        head = INDEX[INDEX.index('id="cal-view"') :]
        block = head[: head.index("</div>")]
        for v in ("month", "week", "day", "agenda", "year"):
            self.assertIn(f'class="seg-opt" data-view="{v}"', block)
        self.assertEqual(block.count("seg-opt"), 5)

    def test_js_targets_seg_opts(self):
        self.assertNotIn("cal-view-btn", CAL)
        # both the click binding and the active-sync use the seg selector
        self.assertEqual(CAL.count("#cal-view .seg-opt"), 2)

    def test_seg_active_class_drives_state(self):
        self.assertIn("classList.toggle('active'", CAL)
        # the shared component highlights .active
        self.assertRegex(CSS, r"\.seg-opt\.active")

    def test_seg_cal_sizing_exists(self):
        self.assertRegex(CSS, r"\.seg\.seg-cal\s+\.seg-opt\s*\{[^}]*padding")


if __name__ == "__main__":
    unittest.main()
