"""ui-3c — the docs live-preview engine. The rendering itself is CM6-in-browser
(exercised by docs/evidence/ui-3c/verify.py against a live server); here we guard the
shipped bundle + CSS so the feature surface can't silently regress out of the build."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = (ROOT / "static" / "vendor" / "cm6.bundle.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class InlineMarks3c1(unittest.TestCase):
    def test_highlight_extension_built_in(self):
        # ==text== gets a real lezer node, not a fragile regex
        self.assertIn("Highlight", BUNDLE)
        self.assertIn("HighlightMark", BUNDLE)

    def test_highlight_styled(self):
        self.assertIn("cm-mark", BUNDLE)
        self.assertRegex(CSS, r"\.cm-mark\s*\{")

    def test_link_rendered_as_anchor_class(self):
        self.assertIn("cm-link", BUNDLE)
        self.assertRegex(CSS, r"\.cm-link\b")


class BlockWidgets3c2(unittest.TestCase):
    def test_image_widget_and_raw_route(self):
        self.assertIn("cm-img", BUNDLE)
        self.assertIn("/api/vault-md/raw?path=", BUNDLE)

    def test_table_widget(self):
        self.assertIn("cm-table", BUNDLE)
        self.assertRegex(CSS, r"\.cm-table\b")

    def test_callout_widget(self):
        self.assertIn("cm-callout", BUNDLE)
        self.assertIn("cm-callout-head", BUNDLE)
        self.assertRegex(CSS, r"\.cm-callout\b")

    def test_hr_and_quote(self):
        self.assertIn("cm-hr", BUNDLE)
        self.assertIn("cm-quote", BUNDLE)


class Lists3c3(unittest.TestCase):
    def test_bullet_widget(self):
        self.assertIn("cm-bullet", BUNDLE)
        self.assertRegex(CSS, r"\.cm-bullet\b")

    def test_checkbox_widget(self):
        self.assertIn("cm-task-checkbox", BUNDLE)
        self.assertRegex(CSS, r"\.cm-task-checkbox\b")


class CodeViews3g(unittest.TestCase):
    def test_fenced_code_block_styled(self):
        self.assertIn("cm-codeblock", BUNDLE)
        self.assertRegex(CSS, r"\.cm-codeblock\s*\{[^}]*background:\s*var\(--panel\)")

    def test_inline_code_pill(self):
        # discord-style: a subtle background behind inline code
        self.assertRegex(CSS, r"\.cm-code\s*\{[^}]*background:")


class EngineShape(unittest.TestCase):
    def test_still_one_export(self):
        # the editor entry point survives the rebuild
        self.assertIn("createDocEditor", BUNDLE)

    def test_image_ext_gate_present(self):
        # ![[file]] embeds only render when they look like an image
        self.assertIn("webp", BUNDLE)

    def test_spellcheck_enabled(self):
        # ui-3j — native typo underline on the wysiwyg surface
        self.assertIn("contentAttributes", BUNDLE)
        self.assertIn("spellcheck", BUNDLE)


if __name__ == "__main__":
    unittest.main()
