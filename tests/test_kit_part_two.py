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


def _svg_body(s):
    s = re.sub(r"<(\w+)([^<>]*?)>\s*</\1>", r"<\1\2/>", s)
    return re.sub(r"\s+", " ", re.sub(r"\s*/>", "/>", s)).replace("> <", "><").strip()


ICONS_JS = (STATIC / "js/icons.js").read_text(encoding="utf-8")
ICON_BODIES = {_svg_body(v): k for k, v in re.findall(r"^\s+'?([\w-]+)'?: '(.*?)',$", ICONS_JS, re.M)}
# hand drawn copies of a shared icon: the feather and andromeda gears, the 6.5 glass, the feather x
ICON_COPIES = {
    "gear": r"M19\.4 15a1\.7|M19 12a7 7 0 0 0-\.08",
    "search": r'^<circle cx="11" cy="11" r="[\d.]+"/><(path d="m16 16 4 4"|line [^>]*x2="1\d(\.\d+)?"[^>]*)/>$',
    "close": r'^(<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>|<path d="m7 7 10 10M17 7 7 17"/>)$',
    "chevron-down": r'^<polyline points="6 9 12 15 18 9"/>$',
    "plus": r'^<path d="M12 5v14M5 12h14"/>$',
    "more": r'^(<circle cx="(5|12|19)" cy="12" r="1\.\d"/>){3}$',
}


class IconTests(unittest.TestCase):
    """28.11: one drawing per icon. an inline svg that redraws an icons.js name uses the shared one."""

    def test_no_inline_svg_duplicates_an_icons_js_name(self):
        for page in ("index.html", "kit.html"):
            text = (STATIC / page).read_text(encoding="utf-8")
            for m in re.finditer(r"<svg\b[^>]*>(.*?)</svg>", text, re.S):
                body = _svg_body(m.group(1))
                if not body:
                    continue
                name = ICON_BODIES.get(body) or next((k for k, r in ICON_COPIES.items() if re.search(r, body)), None)
                line = text[: m.start()].count("\n") + 1
                self.assertIsNone(name, f"{page}:{line} draws its own {name}; use data-kokuen-icon or <svg data-ic>")

    def test_every_settings_gear_is_the_shared_one(self):
        self.assertEqual(len(re.findall(r'data-kokuen-icon="gear"', HTML)), 7)
        self.assertNotIn("M19.4 15a1.7", HTML)
        app = (STATIC / "js/app.js").read_text(encoding="utf-8")
        self.assertIn("slot.replaceWith(iconEl(slot.dataset.ic", app)


def js(name):
    return (STATIC / "js" / name).read_text(encoding="utf-8")


class RailTests(unittest.TestCase):
    """28.05 (decision 0054): every app's sidebar resizes with the one handle."""

    def test_every_sidebar_uses_the_shared_handle(self):
        app = js("app.js")
        for sel in ("#aide-sidebar", "#docs-nav-panel", ".s-navigation", ".files-phase7-location-panel",
                    "#mail-sidebar", "#cal-sidebar", "#photos-sidebar"):
            self.assertIn(sel, app)
        self.assertIn("makeResizableRail({ rail,", app)
        self.assertIn("makeResizableRail({", js("aidecoding.js"))
        self.assertNotIn("handle.addEventListener('pointermove'", js("aidecoding.js"))

    def test_the_handle_is_a_full_separator(self):
        mod = js("rail_resize.js")
        for part in ("'separator'", "aria-valuetext", "aria-valuenow", "ArrowLeft", "Home", "dblclick",
                     "localStorage.setItem", "pointerdown"):
            self.assertIn(part, mod)
        self.assertIn('"static/js/rail_resize.js"', (ROOT / "features/control-census-overrides.json").read_text())
        kokuen = css("kokuen.css")
        self.assertRegex(kokuen, r"@media \(max-width: 620px\) \{ \.k-rail-resize \{ display: none; \} \}")
        self.assertIn("var(--k-rail-w, 244px)", css("revamp.css"))


class NativeTooltipTests(unittest.TestCase):
    """27.35, 27.51: no native title tooltip on a control."""

    def test_the_shared_runtime_drops_titles_from_controls(self):
        kokuen = js("kokuen.js")
        self.assertIn("function dropNativeTooltip(element)", kokuen)
        self.assertIn("'data-kokuen-icon', 'title']", kokuen)

    def test_the_reported_controls_have_no_title(self):
        mail = js("mail.js")
        self.assertIsNone(re.search(r'<button class="mail-(?:act|flag)[^>]*\btitle=', mail))
        self.assertNotIn("trigger.title", js("response_actions.js"))
        self.assertNotIn("bb.title", js("sessions.js"))
        chat = js("chat.js")
        for spot in ("sb.title", "rb.title", "stop.title", 'msg-branch-btn" title='):
            self.assertNotIn(spot, chat)


class NoticeTests(unittest.TestCase):
    """27.54: confirmations clear themselves, errors stay with a close button."""

    def test_errors_use_the_kept_notice(self):
        notice = js("notice.js")
        self.assertIn("export function errorNotice(host, text)", notice)
        for name in ("answer_task.js", "answer_note.js"):
            self.assertIn("errorNotice(host, plainError(", js(name))


class FollowUpAndPhotoTests(unittest.TestCase):
    def test_andromeda_hands_the_answer_to_aide(self):
        self.assertNotIn("andromeda-follow-input", HTML)
        self.assertIn('id="andromeda-continue-aide"', HTML)
        self.assertIn("el('andromeda-continue-aide')?.addEventListener('click', event => void explainResults(", js("andromeda.js"))

    def test_photo_size_has_four_remembered_steps(self):
        photos = js("photos.js")
        self.assertIn("const PHOTO_SIZES = [0.7, 1, 1.45, 2];", photos)
        self.assertIn("* PHOTO_SIZES[_size]", photos)
        self.assertIn("localStorage.setItem(SIZE_KEY", photos)
        self.assertIn('id="photos-zoom-in"', HTML)


if __name__ == "__main__":
    unittest.main()
