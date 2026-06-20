import tempfile
import unittest
from pathlib import Path

from routes.chat import _extract_artifacts, _resolve_mentions


class ArtifactTests(unittest.TestCase):
    def test_full_attrs(self):
        a = _extract_artifacts(
            'x <aide-artifact type="html" title="Page" lang="js">BODY</aide-artifact> y'
        )
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["type"], "html")
        self.assertEqual(a[0]["title"], "Page")
        self.assertEqual(a[0]["lang"], "js")
        self.assertEqual(a[0]["content"], "BODY")

    def test_defaults(self):
        a = _extract_artifacts("<aide-artifact>code</aide-artifact>")[0]
        self.assertEqual(a["type"], "code")
        self.assertEqual(a["title"], "artifact")
        self.assertEqual(a["lang"], "")

    def test_multiple(self):
        self.assertEqual(
            len(
                _extract_artifacts(
                    "<aide-artifact>a</aide-artifact> mid <aide-artifact>b</aide-artifact>"
                )
            ),
            2,
        )

    def test_none(self):
        self.assertEqual(_extract_artifacts("no artifacts here"), [])


class MentionTests(unittest.TestCase):
    def test_inlines_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "notes.txt").write_text("hello content", "utf-8")
            out = _resolve_mentions("see @notes.txt please", d)
            self.assertIn("hello content", out)
            self.assertIn('<file name="notes.txt">', out)

    def test_missing_file_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_resolve_mentions("see @nope.txt", d), "see @nope.txt")

    def test_no_mention(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_resolve_mentions("plain text", d), "plain text")

    def test_duplicate_mention_inlined_once(self):
        # same @file twice → only one <file> block
        with tempfile.TemporaryDirectory() as d:
            Path(d, "dup.txt").write_text("stuff", "utf-8")
            out = _resolve_mentions("@dup.txt and again @dup.txt", d)
            self.assertEqual(out.count('<file name="dup.txt">'), 1)

    def test_trailing_punctuation_stripped(self):
        # @file.txt. or @file.txt, — the trailing punct should be stripped so the file resolves
        with tempfile.TemporaryDirectory() as d:
            Path(d, "note.txt").write_text("data", "utf-8")
            out = _resolve_mentions("check @note.txt, please", d)
            self.assertIn("data", out)

    def test_content_truncated_at_20000(self):
        big = "x" * 30000
        with tempfile.TemporaryDirectory() as d:
            Path(d, "big.txt").write_text(big, "utf-8")
            out = _resolve_mentions("@big.txt", d)
        # only 20000 x's should appear in the file block
        self.assertIn("x" * 20000, out)
        self.assertNotIn("x" * 20001, out)


class ArtifactEdgeCaseTests(unittest.TestCase):
    def test_partial_attrs_only_type(self):
        # title + lang fall back to defaults when absent
        a = _extract_artifacts('<aide-artifact type="svg">stuff</aide-artifact>')[0]
        self.assertEqual(a["type"], "svg")
        self.assertEqual(a["title"], "artifact")
        self.assertEqual(a["lang"], "")

    def test_empty_content(self):
        a = _extract_artifacts('<aide-artifact type="code"></aide-artifact>')[0]
        self.assertEqual(a["content"], "")

    def test_multiline_content_preserved(self):
        body = "line1\nline2\nline3"
        a = _extract_artifacts(f"<aide-artifact>{body}</aide-artifact>")[0]
        self.assertEqual(a["content"], body)


if __name__ == "__main__":
    unittest.main()
