"""ui-0b / ui-0c — shared toggle + segmented control contracts. These are declarative CSS/markup
contracts, so we assert them against the source (deterministic, no server needed)."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
ACTIVITY = (ROOT / "static" / "js" / "activity.js").read_text(encoding="utf-8")


def _block(selector):
    # return the body of the first `selector { ... }` rule
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return m.group(1) if m else ""


class ToggleSwitchTests(unittest.TestCase):
    def test_switch_track_is_pill(self):
        body = _block(".s-switch")
        m = re.search(r"border-radius:\s*(\d+)px", body)
        self.assertTrue(m, "no border-radius on .s-switch")
        self.assertGreaterEqual(int(m.group(1)), 10, "track radius too small to read as a pill")

    def test_switch_knob_is_round(self):
        self.assertIn("border-radius: 50%", _block(".s-switch::after"))

    def test_switch_on_moves_knob(self):
        self.assertIn("left: 16px", _block(".s-switch.on::after"))

    def test_switch_on_changes_background(self):
        self.assertIn("var(--accent)", _block(".s-switch.on"))


class SegmentedControlTests(unittest.TestCase):
    def test_seg_is_one_bordered_container(self):
        body = _block(".seg")
        self.assertIn("border:", body)
        self.assertIn("overflow: hidden", body)

    def test_seg_opts_are_divided(self):
        self.assertIn("border-left:", _block(".seg-opt"))
        self.assertIn("border-left: none", _block(".seg-opt:first-child"))

    def test_seg_active_state_exists(self):
        self.assertIn("var(--accent)", _block(".seg-opt.active"))

    def test_seg_sm_variant_exists(self):
        self.assertIn(".seg.seg-sm", CSS)

    def test_activity_uses_shared_seg(self):
        self.assertIn('class="seg seg-sm act-seg"', ACTIVITY)
        self.assertIn(".act-seg .seg-opt", ACTIVITY)

    def test_no_divergent_act_range_left(self):
        # the old, visually-inconsistent variant is fully gone
        self.assertNotIn("act-range-opt", CSS)
        self.assertNotIn("act-range-opt", ACTIVITY)


if __name__ == "__main__":
    unittest.main()
