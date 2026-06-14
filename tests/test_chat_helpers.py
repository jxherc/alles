import tempfile
import unittest
from pathlib import Path

from routes.chat import _extract_artifacts, _resolve_mentions


class ArtifactTests(unittest.TestCase):
    def test_full_attrs(self):
        a = _extract_artifacts('x <aide-artifact type="html" title="Page" lang="js">BODY</aide-artifact> y')
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
        self.assertEqual(len(_extract_artifacts(
            "<aide-artifact>a</aide-artifact> mid <aide-artifact>b</aide-artifact>")), 2)

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


if __name__ == "__main__":
    unittest.main()
