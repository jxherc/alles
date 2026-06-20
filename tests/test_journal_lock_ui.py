"""ui-7c — journal 'lock now' frontend fix: the action menu is an anchored dropdown (not buried in
the reflection panel) and the lock chrome uses the central icon set. Backend gating: test_journal_lock."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "journal.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class JournalLockUi(unittest.TestCase):
    def test_lock_menu_is_anchored_popover(self):
        i = JS.index("function pickLockAction")
        body = JS[i : i + 900]
        # appended to body + positioned, not stuffed into the reflection panel
        self.assertIn("document.body.appendChild(menu)", body)
        self.assertIn("getBoundingClientRect", body)
        self.assertNotIn("jrnl-reflection", body)

    def test_lock_menu_dismisses_on_outside_click(self):
        i = JS.index("function pickLockAction")
        body = JS[i : i + 900]
        self.assertIn("mousedown", body)

    def test_lock_now_still_posts_and_refreshes(self):
        # the working lock action is preserved
        self.assertIn("/api/journal/lock'", JS)
        self.assertIn("showLock('unlock')", JS)

    def test_lock_chrome_uses_icons(self):
        self.assertIn("_si('lock')", JS)
        self.assertIn("_si('unlock')", JS)
        self.assertNotIn("🔒", JS)
        self.assertNotIn("🔓", JS)

    def test_menu_css_is_fixed_dropdown(self):
        self.assertRegex(CSS, r"\.jrnl-lockmenu\s*\{[^}]*position:\s*fixed")
        self.assertRegex(CSS, r"\.jrnl-lock-btn\s+\.ic")


if __name__ == "__main__":
    unittest.main()
