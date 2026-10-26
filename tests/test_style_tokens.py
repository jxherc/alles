import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    return m.group(1) if m else ""


def _all_rules(selector):
    return " ".join(re.findall(re.escape(selector) + r"\s*\{([^}]*)\}", CSS))


class StyleTokenTests(unittest.TestCase):
    def test_signal_token_is_real(self):
        self.assertRegex(CSS, r"--signal:\s*#[0-9a-fA-F]{6};")
        self.assertRegex(CSS, r"--warn:\s*var\(--signal\);")
        self.assertNotRegex(CSS, r"var\(--signal\s*,")

    def test_perm_menu_hover_is_not_same_as_menu_bg(self):
        self.assertIn("background: var(--panel)", _rule(".perm-menu"))
        hover = _rule(".perm-menu-item:hover")
        self.assertIn("background:", hover)
        self.assertNotIn("background: var(--panel)", hover)
        self.assertIn("background: var(--bg)", hover)

    def test_legacy_add_endpoint_form_css_is_gone(self):
        self.assertNotIn(".add-ep-form", CSS)
        self.assertIn(".mm-add-form", CSS)
        self.assertIn(".s-ep-form", CSS)

    def test_disclosure_lines_keep_a_44px_target(self):
        # settings' "enter Photon keys yourself" and "remote server and private values" were 18px
        self.assertIn("min-height: 44px", _rule(":is(.mcp-advanced, .photon-keys) > summary"))
        aide = (ROOT / "static" / "aidecentral.css").read_text(encoding="utf-8")
        tucked = re.search(r"\.context-provenance\.is-tucked > summary \{([^}]*)\}", aide)
        self.assertIsNotNone(tucked)
        self.assertIn("min-height: var(--k-control, 44px)", tucked.group(1))

    def test_week_all_day_band_is_buttons_and_scrolls(self):
        # a phone's week grid lost half its height to six all-day rows; events there were 20px divs
        self.assertRegex(CSS, r"\.cal-tg-alldayrow \{ max-height: [^;]+; overflow-y: auto;")
        self.assertIn("min-height: 44px", _all_rules("button.cal-allday-ev"))
        self.assertIn("text-overflow: ellipsis", _rule(".cal-task-title"))
        js = (ROOT / "static" / "js" / "calendar.js").read_text(encoding="utf-8")
        self.assertIn('<button type="button" class="cal-allday-ev', js)
        self.assertNotIn('<div class="cal-allday-ev', js)
        self.assertEqual(js.count('<span class="cal-task-title">'), 2)

    def test_habit_week_gap_gives_way_before_the_days(self):
        # seven 44px days overflowed a 390px phone card with a fixed 0.3rem gap
        self.assertIn("gap: clamp(0px, calc((100% - 7 * 44px) / 6), 0.3rem)", _rule(".habit-week"))

    def test_labels_are_never_uppercased(self):
        # copy is lowercase; "READING", "CALENDAR SETTINGS" and the vault's "NAME/TYPE/CVV" all came
        # from css caps on small labels
        for path in sorted((ROOT / "static").glob("*.css")):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"text-transform:\s*uppercase", path.name)


if __name__ == "__main__":
    unittest.main()
