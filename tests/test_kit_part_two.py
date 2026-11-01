"""kit part 2 (decisions 0052, 0053): one entry row, one date field, the busy edge, no chip walls."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def css(name):
    return re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)


ALL_CSS = "".join(css(n) for n in ("style.css", "kokuen.css", "revamp.css", "aidecoding.css"))
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


class EntryRowTests(unittest.TestCase):
    def test_every_add_row_is_the_entry_row(self):
        for marker in (
            'id="task-add-input"',
            'id="contact-name"',
            'id="day-name"',
            'id="sub-name"',
            'id="reminder-text"',
        ):
            at = HTML.index(marker)
            row = HTML.rfind("<div class=", 0, at)
            opening = HTML[row : HTML.index(">", row)]
            self.assertIn("k-entry-row", opening, marker)
            self.assertNotIn("gap:", opening, marker)

    def test_the_row_pads_4px_and_the_button_takes_the_concentric_radius(self):
        rule = re.search(r"\.k-entry-row\s*\{([^}]*)\}", ALL_CSS).group(1)
        self.assertIn("padding: var(--k-space-1)", rule)
        button = re.search(r"\.k-entry-row > \.btn\s*\{([^}]*)\}", ALL_CSS).group(1)
        self.assertIn("border-radius: var(--k-radius-control)", button)
        self.assertIn("min-height: 44px", button)
        self.assertNotRegex(ALL_CSS, r"padding:\s*6px 6px 6px")


class BusyEdgeTests(unittest.TestCase):
    def test_no_busy_line_is_laid_over_a_rounded_box(self):
        for gone in ("aide-sweep", "acw-sweep", "whats-new-draw", ".composer-box::after"):
            self.assertNotIn(gone, ALL_CSS, gone)
        self.assertNotIn("acw-entry::after", ALL_CSS)

    def test_the_busy_edge_follows_the_box_and_rests_under_reduced_motion(self):
        kokuen = css("kokuen.css")
        self.assertIn("@property --k-busy-turn", kokuen)
        edge = re.search(r"\.k-busy\[data-busy=\"true\"\]\)::before\s*\{([^}]*)\}", kokuen).group(1)
        for part in ("inset: 0", "border-radius: inherit", "border: 1px solid transparent", "pointer-events: none"):
            self.assertIn(part, edge)
        self.assertNotRegex(edge, r"blur|box-shadow")
        self.assertRegex(
            kokuen,
            r"prefers-reduced-motion: reduce\)\s*\{\s*:is\(body\.aide-working[^{]*\{\s*animation: none",
        )

    def test_the_steps_strip_has_no_line_under_it(self):
        strip = re.search(
            r"#messages \.agent-steps > :is\(summary, \.custom-summary\)\s*\{([^}]*)\}", ALL_CSS
        ).group(1)
        self.assertIn("box-shadow: none", strip)
        self.assertNotRegex(ALL_CSS, r"agent-step\.destructive\s*\{[^}]*(border-left|inset 2px)")


class ChoiceTests(unittest.TestCase):
    def test_former_chip_walls_are_dropdowns(self):
        models = (STATIC / "js/models.js").read_text(encoding="utf-8")
        self.assertNotIn("mm-preset-btn", models)
        self.assertIn("populateDropdown(pick, PRESETS", models)
        settings = (STATIC / "js/settings.js").read_text(encoding="utf-8")
        self.assertNotIn('class="rule-preset"', settings)
        server = (STATIC / "js/server_workbench.js").read_text(encoding="utf-8")
        self.assertIn("options.length > 3", server)
        self.assertIn("{ list: true }", server)


if __name__ == "__main__":
    unittest.main()
