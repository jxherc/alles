"""docs panels — every side panel uses the one shared toggle so they're mutually exclusive with a
consistent 'active' indicator; the todos popup joins the accordion; ::: columns render in live preview.
Behavioral check: drove every panel button (one-at-a-time active) via Playwright during this change."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "static" / "js" / "vaultmd.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
CM = (ROOT / ".cmbuild" / "cm-entry.js").read_text(encoding="utf-8")


class DocsPanelToggles(unittest.TestCase):
    def test_one_shared_toggle_helper(self):
        self.assertIn("function _togglePanel", JS)

    def test_every_panel_routes_through_it(self):
        for fn in (
            "toggleOutline",
            "toggleHistory",
            "toggleBase",
            "toggleAsk",
            "toggleComments",
            "toggleTaskRoll",
            "toggleProps",
        ):
            i = JS.index(f"function {fn}")
            # each toggle delegates to _togglePanel (props/outline/history/base/ask/comments/taskroll)
            self.assertIn("_togglePanel(", JS[i : i + 200], f"{fn} doesn't use _togglePanel")

    def test_todos_popup_joins_the_accordion(self):
        # opening todos closes other panels + lights its own indicator; closing panels closes the popup
        self.assertIn("_closeOtherPanels('wiki-todos')", JS)
        self.assertIn("btn.classList.add('active')", JS)
        self.assertIn("getElementById('wiki-todos-pop')?.remove()", JS)
        self.assertIn("$('wiki-todos-btn')?.classList.remove('active')", JS)

    def test_consistent_active_indicator(self):
        # one CSS rule lights every panel button the same way
        m = [
            s
            for s in CSS.split("}")
            if "#wiki-todos-btn.active" in s and "#wiki-base-btn.active" in s
        ]
        self.assertTrue(m, "panel buttons don't share one .active rule")
        rule = m[0]
        for b in (
            "outline",
            "props",
            "query",
            "base",
            "history",
            "comments",
            "ask",
            "taskroll",
            "todos",
        ):
            self.assertIn(f"#wiki-{b}-btn.active", rule)


class DocsColumns(unittest.TestCase):
    def test_columns_widget_in_cm_source(self):
        self.assertIn("class ColumnsWidget", CM)
        self.assertIn(":::\\s*columns", CM.replace("\\\\", "\\"))  # the line-scan regex
        self.assertIn("new ColumnsWidget", CM)

    def test_columns_css(self):
        self.assertRegex(CSS, r"\.cm-columns\s*\{[^}]*grid")
        self.assertRegex(CSS, r"\.cm-column\s*\{")


if __name__ == "__main__":
    unittest.main()
