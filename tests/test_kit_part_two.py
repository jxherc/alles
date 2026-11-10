"""kit part 2 (decisions 0052, 0053): one entry row, one date field, the busy edge, no chip walls."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def css(name):
    return re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)


ALL_CSS = "".join(css(n) for n in ("style.css", "kokuen.css", "revamp.css"))
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
        for part in (
            "inset: 0",
            "border-radius: inherit",
            "border: 1px solid transparent",
            "pointer-events: none",
        ):
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


MENUS = (
    ".ctx-menu", ".aide-central-menu", ".msg-actions-menu", ".aide-sidebar-menu",
    ".aide-project-context-menu", ".aide-schedule-project-menu", ".docs-action-menu",
    ".plan-board-menu", ".perm-menu", ".photos-albmenu", ".jrnl-lockmenu",
    ".mention-menu", ".slash-popup", ".custom-dropdown-panel",
)  # fmt: skip


class MenuTests(unittest.TestCase):
    """u4, 28.19: every hand rolled menu floats with one look."""

    def test_every_menu_takes_the_one_menu_look(self):
        rule = re.search(
            r"html:not\(#_\):not\(#_\) :is\(([^)]*)\)\s*\{([^}]*)\}", css("revamp.css")
        )
        names, body = rule.group(1), rule.group(2)
        for menu in MENUS:
            self.assertIn(menu, names)
        self.assertIn("border-radius: var(--k-radius-surface)", body)
        self.assertIn("box-shadow: var(--k-float)", body)
        self.assertIn("--k-radius-surface: 12px;", css("kokuen.css"))
        self.assertIn("--k-radius-control: 8px;", css("kokuen.css"))

    def test_components_has_no_stale_menu_radius(self):
        doc = (ROOT / "design-system/COMPONENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("4px outer radius", doc)
        self.assertIn("12px surface radius, 8px row radius", doc)

    def test_run_controls_reach_the_real_steps_head(self):
        # the steps head is a div.custom-summary; rules written for <summary> only never matched
        style = css("style.css")
        self.assertNotRegex(style, r"#messages \.agent-steps > summary [:.]")
        self.assertIn(
            "#messages .agent-steps > :is(summary, .custom-summary) :is(.agent-sources-btn", style
        )


class ReaderFocusTests(unittest.TestCase):
    def test_the_docs_reader_draws_no_box_when_it_takes_focus(self):
        # 28.40: the reader is focused when a doc opens; a keyboard open drew a ring round the page
        rule = re.search(r"#wiki-preview:focus-visible\s*\{([^}]*)\}", css("kokuen.css")).group(1)
        self.assertIn("outline: none", rule)


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
        # 28.14: 4 or more options in the language pane, the appearance editor and the app
        # settings popover are the kit dropdown; the pill switch keeps 3 or fewer
        app_settings = (STATIC / "js/appsettings.js").read_text(encoding="utf-8")
        self.assertIn("f.opts.length > 3", app_settings)
        theme = (STATIC / "js/theme.js").read_text(encoding="utf-8")
        self.assertIn("_pick('bgPattern'", theme)
        self.assertIn("_pick('harmony-type'", theme)
        self.assertNotIn("_seg('bgPattern'", theme)
        self.assertIn('data-locale-choice="language"', HTML)
        self.assertNotIn("locale-language-choice", HTML)

    def test_no_group_of_more_than_3_text_choices(self):
        """28.14: 2 or 3 text choices are a pill switch, 4 or more (or a list that can grow) the
        dropdown. a group listed in CHOICE_EXCEPTIONS keeps its look for the reason given; a group in
        CHOICE_TO_CONVERT is a known wall still waiting for its dropdown, so a new one fails here."""
        found = set(_choice_groups())
        listed = set(CHOICE_EXCEPTIONS) | set(CHOICE_TO_CONVERT)
        self.assertEqual(sorted(found - listed), [], "a new text choice wall; use the dropdown")
        self.assertEqual(sorted(listed - found), [], "gone or renamed; drop it from the lists")


# a button that picks one of several values (radio, pressed, checked or a seg option); switches
# and menu rows are not choice groups
_CHOICE = re.compile(r'role="radio"|aria-pressed|aria-checked|class="[^"]*\bseg-opt')
_NOT_CHOICE = re.compile(r'role="(switch|menuitem\w*|tab)"')
_TAG = re.compile(r"<(/?)([a-z][\w-]*)\b([^<>]*?)(/?)>", re.S)
_VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr", "path", "circle", "line",
         "rect", "polyline", "polygon", "use", "ellipse", "span", "strong", "small", "svg"}  # fmt: skip


def _choice_groups():
    """index.html and kit.html: an element with more than 3 choice buttons as children, named by
    its id or first class. js: a .map() that renders choice buttons (its size isn't known
    statically), named by the button's first class or data attribute."""
    for page in ("index.html", "kit.html"):
        stack = []
        for m in _TAG.finditer((STATIC / page).read_text(encoding="utf-8")):
            close, tag, attrs, selfclose = m.groups()
            if tag in _VOID or selfclose:
                continue
            if not close:
                if (
                    tag == "button"
                    and stack
                    and _CHOICE.search(attrs)
                    and not _NOT_CHOICE.search(attrs)
                ):
                    stack[-1][1] += 1
                stack.append([attrs, 0, tag])
                continue
            while stack:
                attrs_, n, tag_ = stack.pop()
                if n > 3:
                    name = re.search(r'\bid="([^"]+)"', attrs_) or re.search(
                        r'class="([\w-]+)', attrs_
                    )
                    yield f"{page}:{name.group(1)}"
                if tag_ == tag:
                    break
    for path in sorted((STATIC / "js").rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(
            r"\.map\(\s*\(?[\w\s,{}\[\]]*\)?\s*=>\s*`[^`]*?<button\b([^>]*)>", text
        ):
            attrs = m.group(1)
            if _CHOICE.search(attrs) and not _NOT_CHOICE.search(attrs):
                name = re.search(r'class="([\w-]+)', attrs) or re.search(r"(data-[\w-]+)=", attrs)
                yield f"{path.relative_to(STATIC).as_posix()}:{name.group(1)}"


CHOICE_EXCEPTIONS = {
    # you pick a color by seeing it; a menu would hide it (u4)
    "js/calendar.js:cal-sw": "color swatches",
    "js/habits.js:habit-sw": "color swatches",
    # a rating is a row of every value (owner's pick, ux laws)
    "js/journal.js:jrnl-mood": "mood rating",
    # toggles that each turn one thing on, not one pick from a list
    "js/calendar.js:cal-dow-b": "weekday toggles, like every calendar's repeat editor",
    "js/calendar.js:cal-rem": "reminder toggles, several at once",
    "index.html:token-scopes": "token powers, several at once, each with a mark",
    "js/habit_loggers.js:dlog-step-check": "a checklist's own steps, each ticked on its own",
    # navigation, not a value: the open view or place, like every calendar and files app
    "index.html:cal-view": "calendar view switch",
    "js/filesphase7.js:files-location-button": "rail rows, the open place is pressed",
    # 2 or 3 fixed options: already the size of a pill switch
    "js/books.js:data-move": "3 shelves",
    "js/books.js:te-seg-opt": "3 shelves",
    "js/settings/providers.js:data-value": "2 sign in kinds",
    "js/setupwizard.js:data-value": "2 or 3 choices per step",
    "js/contacts.js:data-value": "3 sync intervals: manual, hourly, daily",
    "js/vault.js:data-value": "3 field widths",
    # the renderer picks by length: 4 or more options draw the dropdown, so these hold 3 or fewer
    "js/appsettings.js:seg-opt": "app setting choices with 3 options or fewer",
    "js/theme.js:te-seg-opt": "font, density and harmony mode: 3 options or fewer",
}
# known walls still waiting for the dropdown: none left
CHOICE_TO_CONVERT = {}


def _svg_body(s):
    s = re.sub(r"<(\w+)([^<>]*?)>\s*</\1>", r"<\1\2/>", s)
    return re.sub(r"\s+", " ", re.sub(r"\s*/>", "/>", s)).replace("> <", "><").strip()


ICONS_JS = (STATIC / "js/icons.js").read_text(encoding="utf-8")
ICON_BODIES = {
    _svg_body(v): k for k, v in re.findall(r"^\s+'?([\w-]+)'?: '(.*?)',$", ICONS_JS, re.M)
}
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
                name = ICON_BODIES.get(body) or next(
                    (k for k, r in ICON_COPIES.items() if re.search(r, body)), None
                )
                line = text[: m.start()].count("\n") + 1
                self.assertIsNone(
                    name,
                    f"{page}:{line} draws its own {name}; use data-kokuen-icon or <svg data-ic>",
                )

    def test_no_js_template_redraws_an_icons_js_name(self):
        pending = {"js/dropdown.js:chevron-down"}  # dropdown.js is s5b's this wave
        found = set()
        pat = (
            r"<svg\b[^>]*>(.*?)</svg>|(['\"`])(<(?:path|circle|line|polyline|rect)\b[^'\"`]*?/>)\2"
        )
        for path in sorted((STATIC / "js").rglob("*.js")):
            if path.name == "icons.js":
                continue
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(pat, text, re.S):
                body = _svg_body(m.group(1) or m.group(3) or "")
                if not body or "${" in body:
                    continue
                name = ICON_BODIES.get(body) or next(
                    (k for k, r in ICON_COPIES.items() if re.search(r, body)), None
                )
                if name:
                    found.add(f"{path.relative_to(STATIC).as_posix()}:{name}")
        self.assertEqual(sorted(found - pending), [], "use icon() from icons.js")
        self.assertEqual(sorted(pending - found), [], "fixed; drop it from pending")

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
        for sel in (
            "#aide-sidebar",
            "#docs-nav-panel",
            ".s-navigation",
            ".files-phase7-location-panel",
            "#mail-sidebar",
            "#cal-sidebar",
            "#photos-sidebar",
        ):
            self.assertIn(sel, app)
        self.assertIn("makeResizableRail({ rail,", app)

    def test_the_handle_is_a_full_separator(self):
        mod = js("rail_resize.js")
        for part in (
            "'separator'",
            "aria-valuetext",
            "aria-valuenow",
            "ArrowLeft",
            "Home",
            "dblclick",
            "localStorage.setItem",
            "pointerdown",
        ):
            self.assertIn(part, mod)
        self.assertIn(
            '"static/js/rail_resize.js"',
            (ROOT / "features/control-census-overrides.json").read_text(),
        )
        kokuen = css("kokuen.css")
        self.assertRegex(
            kokuen, r"@media \(max-width: 620px\) \{ \.k-rail-resize \{ display: none; \} \}"
        )
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
        self.assertIn(
            "el('andromeda-continue-aide')?.addEventListener('click', event => void explainResults(",
            js("andromeda.js"),
        )

    def test_photo_size_has_four_remembered_steps(self):
        photos = js("photos.js")
        self.assertIn("const PHOTO_SIZES = [0.7, 1, 1.45, 2];", photos)
        # each step is a whole number of pictures across, one fewer than the step before, so no
        # step can land on the layout of its neighbour at any width
        self.assertIn("_stepCols(cw, _size)", photos)
        self.assertIn("Math.min(cols - 1,", photos)
        self.assertIn("localStorage.setItem(SIZE_KEY", photos)
        self.assertIn('id="photos-zoom-in"', HTML)


if __name__ == "__main__":
    unittest.main()
