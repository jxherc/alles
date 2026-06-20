"""ui-7e — the day-cluster apps (tasks / calendar / days / journal) draw their control glyphs from the
central icon set, not emoji/Unicode. Live render check in docs/evidence/ui-7e/verify.py.
(Journal MOODS stay — that's a deliberate mood picker, not chrome.)"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = (ROOT / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
CAL = (ROOT / "static" / "js" / "calendar.js").read_text(encoding="utf-8")
DAYS = (ROOT / "static" / "js" / "days.js").read_text(encoding="utf-8")
JRNL = (ROOT / "static" / "js" / "journal.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class DayAppsIcons(unittest.TestCase):
    def test_all_have_icon_helper(self):
        for js in (TASKS, CAL, DAYS, JRNL):
            self.assertRegex(js, r"_si\s*=\s*n\s*=>")

    def test_tasks_repeat_icon(self):
        self.assertNotIn("🔁", TASKS)
        self.assertIn("_si('refresh')", TASKS)

    def test_days_glyphs(self):
        for g in ("★", "🎉", "↻"):
            self.assertNotIn(g, DAYS)
        self.assertIn("_si(e.pinned ? 'star-fill' : 'star')", DAYS)
        self.assertIn("_si('party')", DAYS)
        self.assertIn("_si('refresh')", DAYS)

    def test_journal_glyphs(self):
        for g in ("✨", "🔥"):
            self.assertNotIn(g, JRNL)
        self.assertIn("_si('sparkles')", JRNL)
        self.assertIn("_si('fire')", JRNL)

    def test_calendar_glyphs(self):
        for g in ("🔗", "↻", "☑", "☐", "📹"):
            self.assertNotIn(g, CAL)
        self.assertIn("_si('link')", CAL)
        self.assertIn("_si('refresh')", CAL)
        self.assertIn("_si('video')", CAL)
        self.assertIn("_si('check')", CAL)
        # back buttons use chevrons
        self.assertIn("_si('chevron-left')} back", CAL)

    def test_calendar_rsvp_labels_de_iconed(self):
        self.assertNotIn("✓ yes", CAL)
        self.assertNotIn("✗ no", CAL)
        self.assertIn("accepted: 'yes'", CAL)
        self.assertIn("declined: 'no'", CAL)

    def test_css_sizes_the_new_icons(self):
        self.assertRegex(CSS, r"\.task-repeat \.ic")
        self.assertRegex(CSS, r"\.day-pin \.ic")
        self.assertRegex(CSS, r"\.cal-chip-recur \.ic")
        self.assertRegex(CSS, r"\.cal-task-chk \.ic")


if __name__ == "__main__":
    unittest.main()
