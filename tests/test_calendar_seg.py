"""the calendar's five views are the kokuen dropdown (decision 0075), not a row of buttons.
Behavior lives in tests/pw_calendar_toolbar.py."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CAL = (ROOT / "static" / "js" / "calendar.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class CalendarViewDropdown(unittest.TestCase):
    def test_switcher_is_a_dropdown(self):
        self.assertRegex(INDEX, r'<div class="custom-select cal-view-pick" id="cal-view"')
        self.assertNotIn("seg-cal", INDEX)
        self.assertNotIn("cal-view-btn", INDEX)

    def test_five_views_are_its_options(self):
        tag = INDEX[INDEX.index('id="cal-view"') :]
        tag = tag[: tag.index(">")]
        self.assertIn('data-options="month|month;week|week;day|day;agenda|agenda;year|year"', tag)
        self.assertNotIn("seg-opt", tag)

    def test_js_uses_the_dropdown(self):
        self.assertNotIn("#cal-view .seg-opt", CAL)
        self.assertIn("populateDropdown(pick", CAL)
        self.assertIn("localStorage.setItem('cal-view', _view)", CAL)

    def test_no_dead_segmented_css(self):
        self.assertNotIn("seg-cal", CSS)


if __name__ == "__main__":
    unittest.main()
