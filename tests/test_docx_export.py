import unittest


class DocxExportTests(unittest.TestCase):
    def test_produces_valid_docx(self):
        try:
            from services.docx_export import md_to_docx
        except Exception:
            self.skipTest("python-docx not installed")
        md = "# Title\n\nsome **bold** and *italic* and `code`.\n\n- one\n- two\n\n```\ncode block\n```\n\nsee [[other note]]"
        data = md_to_docx(md, "My Note")
        # a .docx is a zip — starts with the PK signature
        self.assertTrue(data[:2] == b"PK")
        self.assertGreater(len(data), 1000)


if __name__ == "__main__":
    unittest.main()
