import unittest
import tempfile
from pathlib import Path
from unittest import mock

from services import files_store as fs


class FileSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "notes.txt").write_text("hello world\nfind the needle here please", "utf-8")
        (self.base / "report.md").write_text("quarterly numbers only", "utf-8")
        (self.base / "sub").mkdir()
        (self.base / "sub" / "needle_named.txt").write_text("nothing relevant", "utf-8")
        (self.base / ".hidden.txt").write_text("needle inside a dotfile", "utf-8")
        self.patch = mock.patch.object(fs, "files_dir", lambda: self.base)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_content_and_name_hits(self):
        r = fs.search("needle")
        paths = {x["path"] for x in r["results"]}
        self.assertIn("notes.txt", paths)              # content hit
        self.assertIn("sub/needle_named.txt", paths)   # filename hit
        notes = next(x for x in r["results"] if x["path"] == "notes.txt")
        self.assertIn("needle", notes["snippet"].lower())
        self.assertEqual(notes["match"], "content")

    def test_skips_dotfiles(self):
        self.assertNotIn(".hidden.txt", {x["path"] for x in fs.search("needle")["results"]})

    def test_no_match(self):
        self.assertEqual(fs.search("zzzznotfound")["results"], [])

    def test_empty_query(self):
        self.assertEqual(fs.search("")["results"], [])


if __name__ == "__main__":
    unittest.main()
