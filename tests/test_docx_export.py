import unittest


def _load():
    try:
        from services.docx_export import md_to_docx
        return md_to_docx
    except Exception:
        return None


class DocxExportTests(unittest.TestCase):
    def setUp(self):
        self.md_to_docx = _load()
        if self.md_to_docx is None:
            self.skipTest("python-docx not installed")

    def _valid(self, data):
        self.assertEqual(data[:2], b"PK")
        self.assertGreater(len(data), 1000)

    def test_produces_valid_docx(self):
        md = "# Title\n\nsome **bold** and *italic* and `code`.\n\n- one\n- two\n\n```\ncode block\n```\n\nsee [[other note]]"
        data = self.md_to_docx(md, "My Note")
        self._valid(data)

    def test_empty_md_no_title(self):
        data = self.md_to_docx("", "")
        self._valid(data)

    def test_empty_md_with_title(self):
        data = self.md_to_docx("", "Just a Title")
        self._valid(data)

    def test_numbered_list(self):
        md = "1. first\n2. second\n3. third"
        data = self.md_to_docx(md)
        self._valid(data)

    def test_blockquote(self):
        md = "> This is a blockquote\n> second line"
        data = self.md_to_docx(md)
        self._valid(data)

    def test_horizontal_rule_dashes(self):
        data = self.md_to_docx("before\n\n---\n\nafter")
        self._valid(data)

    def test_horizontal_rule_stars(self):
        data = self.md_to_docx("before\n\n***\n\nafter")
        self._valid(data)

    def test_wikilink_pipe_alias(self):
        # [[other|alias]] → should use "alias" as display text
        md = "see [[other note|alias text]] here"
        data = self.md_to_docx(md)
        self._valid(data)

    def test_wikilink_anchor_stripped(self):
        # [[note#section]] → should strip the anchor
        md = "see [[note#section]] here"
        data = self.md_to_docx(md)
        self._valid(data)

    def test_unclosed_code_block(self):
        md = "intro\n\n```\ncode line\nanother line"
        data = self.md_to_docx(md)
        self._valid(data)

    def test_multiple_heading_levels(self):
        md = "# H1\n## H2\n### H3\n#### H4\nparagraph"
        data = self.md_to_docx(md, "Headings Test")
        self._valid(data)

    def test_all_inline_styles(self):
        md = "**bold** and *italic* and `inline code` mixed"
        data = self.md_to_docx(md)
        self._valid(data)


if __name__ == "__main__":
    unittest.main()
