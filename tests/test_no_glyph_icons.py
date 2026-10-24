"""icons are svg from the shared set, never emoji or unicode symbol glyphs (owner rule 2026-10-23).

text that is genuinely text keeps its characters: arrows inside a sentence ("settings → models"),
keyboard notation (⌘, ↑/↓ in shortcut hints), calculator math keys, and the journal's mood faces,
which are emoji content. everything else that draws a mark in the interface uses icon()/_si().
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLYPHS = re.compile("[\U0001f300-\U0001faff☀-➿⌀-⏿■-◿✓✕↻↺⇄⇆⇅↳⟰-⟿⊕‹›⤺•]")
# file -> substrings on a line where the glyph is text, not an icon
ALLOWED = {
    "journal.js": ["MOODS"],  # mood faces are emoji content
    "andromeda_tools.js": [
        "['⌫', 'back']",
        "'⌫': 'delete'",
        "label === '⌫'",
    ],  # calculator key label
    "aidegoals.js": ["press ⌘C"],  # keyboard notation
    "kokuen.js": [
        "ICON_GLYPHS",
        "'✕': 'close'",
        "glyph === '×' || glyph === '✕'",
        "'‹': 'chevron-left'",
        "'›': 'chevron-right'",
        "{ '‹': 'previous', '›': 'next' }",
    ],  # glyph -> svg map
    # ‹ › pager buttons, replaced by kokuen's chevron svg at render
    "datepick.js": ['class="dp-step"', 'class="dp-nav"'],
    "specialist_groups.js": ["'specialist-view-scroll'"],
    "calendar.js": ['class="cal-mini-nav"'],
    "aideworkspace.js": ["back.textContent = '‹'"],
    "index.html": ['id="cal-prev"', 'id="cal-next"', 'id="money-prev"', 'id="money-next"'],
    # a breadcrumb separator and a markdown bullet parser: text, not marks
    "andromeda.js": [".join(' › ')", "/^[-*•]\\s+(.*)$/"],
    "skills.js": ['data-kokuen-icon="close">✕'],  # replaced by its svg at render
    "vault.js": ['class="modal-close"'],  # ✕ close, replaced by its svg at render
    "connections.js": ['class="perm-rule-del"'],  # ✕ remove, replaced by its svg at render
    "habits.js": ["HABIT_COLORS", "_si('none')"],
    "icons.js": ["//"],
}


def _lines():
    files = sorted((ROOT / "static" / "js").rglob("*.js")) + [ROOT / "static" / "index.html"]
    for path in files:
        if "vendor" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = (
                re.sub(r"//.*$", "", line)
                if path.suffix == ".js"
                else re.sub(r"<!--.*?-->", "", line)
            )
            if code.strip().startswith(("*", "/*")):
                continue
            yield path, number, code


class NoGlyphIcons(unittest.TestCase):
    def test_marks_in_the_interface_are_svg(self):
        found = []
        for path, number, code in _lines():
            if not GLYPHS.search(code):
                continue
            if any(marker in code for marker in ALLOWED.get(path.name, [])):
                continue
            found.append(f"{path.relative_to(ROOT)}:{number}: {code.strip()[:90]}")
        self.assertEqual(found, [], "use icon()/_si() for these marks:\n" + "\n".join(found))

    def test_every_file_that_draws_an_icon_defines_its_helper(self):
        # a near-miss name check ("const _signin…") once skipped one; the page then threw
        # "_si is not defined"
        missing = []
        for path in sorted((ROOT / "static" / "js").rglob("*.js")):
            text = path.read_text(encoding="utf-8")
            if "_si(" in text and not re.search(r"^(const _si = |function _si\()", text, re.M):
                missing.append(str(path.relative_to(ROOT)))
        self.assertEqual(missing, [])
