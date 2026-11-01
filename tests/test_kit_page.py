"""The kit page and the kit rules that can be read from source (decisions 0049 to 0051)."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SHEET = re.compile(r'<link rel="stylesheet" href="([^"]+)"')
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def css_rules():
    for path in sorted(STATIC.glob("*.css")):
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for match in RULE.finditer(text):
            yield path.name, match.group(1).strip(), match.group(2)


def selector_parts(selector):
    return [part.strip() for part in re.split(r",(?![^(]*\))", selector) if part.strip()]


def block(css, opening):
    start = css.index(opening)
    return css[start : css.index("{", start)]


def text_field_classes():
    # classes that sit on a text input or textarea anywhere in the markup or the js that builds it
    sources = [STATIC / "index.html", *STATIC.joinpath("js").rglob("*.js")]
    tag = re.compile(r"<(input|textarea)\b([^>]*)>", re.S)
    found = set()
    for source in sources:
        for match in tag.finditer(source.read_text(encoding="utf-8", errors="ignore")):
            attrs = match.group(2)
            kind = re.search(r'type="([a-z]+)"', attrs)
            if kind and kind.group(1) not in {
                "text",
                "search",
                "email",
                "url",
                "tel",
                "password",
                "number",
            }:
                continue
            cls = re.search(r'class="([^"$`{}]+)"', attrs)
            if cls:
                found.update(cls.group(1).split())
    return found


class KitPageTests(unittest.TestCase):
    def test_kit_page_links_the_same_stylesheets_as_the_app(self):
        app = SHEET.findall((STATIC / "index.html").read_text(encoding="utf-8"))
        kit = SHEET.findall((STATIC / "kit.html").read_text(encoding="utf-8"))
        self.assertTrue(app)
        self.assertEqual(app, kit, "static/kit.html must load index.html's stylesheets, in order")

    def test_kit_script_loads_the_app_runtime_at_its_stamp(self):
        kit = (STATIC / "kit.html").read_text(encoding="utf-8")
        self.assertIn('<script type="module" src="/static/js/kit.js"></script>', kit)
        self.assertNotRegex(kit, r"<script>(?!</script>)", "the app's csp blocks inline scripts")
        app_stamp = re.search(r"kokuen\.js\?v=(\d+)", (STATIC / "js/app.js").read_text())
        kit_stamp = re.search(r"kokuen\.js\?v=(\d+)", (STATIC / "js/kit.js").read_text())
        self.assertEqual(app_stamp.group(1), kit_stamp.group(1))

    def test_kit_page_shows_every_piece(self):
        kit = (STATIC / "kit.html").read_text(encoding="utf-8")
        for piece in (
            'id="kit-field"',
            'aria-invalid="true"',
            "disabled",
            'class="k-rows',
            'role="tablist"',
            'class="seg"',
            'data-kokuen-choice="switch"',
            'data-kokuen-choice="rating"',
        ):
            with self.subTest(piece=piece):
                self.assertIn(piece, kit)

    def test_tokens_live_in_kokuen_root(self):
        css = (STATIC / "kokuen.css").read_text(encoding="utf-8")
        root = css[css.index(":root") : css.index("}", css.index(":root"))]
        for token in (
            "--k-row-gap: var(--k-space-1)",
            "--k-control-gap: var(--k-space-2)",
            "--k-radius-pill: 999px",
        ):
            with self.subTest(token=token):
                self.assertIn(token, root)

    def test_field_focus_is_the_dim_neutral(self):
        # owner, oct 28 (c.02): dim neutral. nothing may turn it back to the accent
        for name, selector, body in css_rules():
            if "--k-field-focus" in body and ":" in body:
                for decl in body.split(";"):
                    if decl.strip().startswith("--k-field-focus"):
                        with self.subTest(file=name, selector=selector[:80]):
                            value = decl.split(":", 1)[1]
                            self.assertNotIn("accent", value)

    def test_wrapper_focus_is_one_neutral_ring(self):
        # 28.01: andromeda's search kept an accent ring plus a 5px halo after the field pass
        for name, selector, body in css_rules():
            if ":focus-within" not in selector or "box-shadow" not in body:
                continue
            shadow = body.split("box-shadow", 1)[1].split(";", 1)[0]
            with self.subTest(file=name, selector=selector[:90]):
                self.assertNotIn("accent", shadow)
                self.assertNotRegex(shadow, r"0 0 0 [2-9]px")

    def test_no_text_field_has_zero_side_padding(self):
        # a field's focus ring is its own edge, so text at 0px sits on the ring (28.13). a field
        # with zero side padding must be in the one field list (it wins), a wrapper-owned entry
        # (bare inside a box that shows focus) or a long form editor (no box)
        revamp = (STATIC / "revamp.css").read_text(encoding="utf-8")
        kokuen = (STATIC / "kokuen.css").read_text(encoding="utf-8")
        one_field = block(
            revamp, "html:not(#_):not(#_) :is(\n  .settings-input, .settings-textarea"
        )
        wrapper = block(
            kokuen, 'html[data-kokuen-version="5"] :is(\n  .composer-box > .composer-ta'
        )
        allowed = {
            # the date panel's hour, minute and year: digits centered in a 44px box, with their
            # own line under the digits (U5, the date field)
            ":is(input.dp-tv, input.dp-year)",
            # a color swatch is a readonly input with role=button, not text entry
            "input.cp-swatch-input",
            # the sign in screen's own rule (revamp.css #login-screen) gives it the one field look
            ".login-input",
        }
        long_form = (".wiki-source", ".note-editor-title", ".note-editor-body", ".jrnl-text")
        field_classes = text_field_classes()
        offenders = []
        for name, selector, body in css_rules():
            if "padding" not in body:
                continue
            for part in selector_parts(selector):
                subject = re.split(r"\s*[>+~]\s*|\s+", part)[-1]
                is_field = re.search(r"(^|[^-\w])(input|textarea)\b", subject) or any(
                    re.search(r"\." + re.escape(c) + r"(?![-\w])", subject) for c in field_classes
                )
                if not is_field or re.search(r"checkbox|radio|range|color|file|hidden", subject):
                    continue
                for decl in body.split(";"):
                    decl = decl.strip()
                    if not re.match(
                        r"padding(-inline|-left|-right|-inline-start|-inline-end)?\s*:", decl
                    ):
                        continue
                    value = decl.split(":", 1)[1].replace("!important", "").split()
                    inline = (
                        (value[1] if len(value) > 1 else value[0])
                        if decl.startswith("padding:")
                        else value[0]
                    )
                    if not re.fullmatch(r"0(px|rem)?", inline):
                        continue
                    first = re.match(r"[.#]?[\w-]+|:is\([^)]*\)", subject).group(0)
                    if first in ("input", "textarea"):
                        # a bare tag says nothing; name it by its parent, as the lists do
                        parts = re.split(r"\s*[>+~]\s*|\s+", part)
                        first = subject = parts[-2] if len(parts) > 1 else part
                    covered = (
                        part in allowed
                        or any(cls in part for cls in long_form)
                        or subject in one_field
                        or first in one_field
                        or first in wrapper
                    )
                    if not covered:
                        offenders.append(f"{name}: {part} -> {decl}")
        self.assertEqual(
            offenders, [], "text fields with zero side padding:\n" + "\n".join(offenders)
        )


if __name__ == "__main__":
    unittest.main()
