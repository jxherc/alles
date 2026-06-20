import tempfile
import unittest
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
        self.assertIn("notes.txt", paths)  # content hit
        self.assertIn("sub/needle_named.txt", paths)  # filename hit
        notes = next(x for x in r["results"] if x["path"] == "notes.txt")
        self.assertIn("needle", notes["snippet"].lower())
        self.assertEqual(notes["match"], "content")

    def test_skips_dotfiles(self):
        self.assertNotIn(".hidden.txt", {x["path"] for x in fs.search("needle")["results"]})

    def test_no_match(self):
        self.assertEqual(fs.search("zzzznotfound")["results"], [])

    def test_empty_query(self):
        self.assertEqual(fs.search("")["results"], [])

    def test_both_match_type_when_name_and_content(self):
        # "needle_named.txt" has "needle" in the name but not in content
        # create a file where both name and content match
        (self.base / "needle_content.txt").write_text("needle is here too", "utf-8")
        r = fs.search("needle")
        both = next((x for x in r["results"] if x["path"] == "needle_content.txt"), None)
        self.assertIsNotNone(both)
        self.assertEqual(both["match"], "both")

    def test_name_hit_no_content_search_for_non_text_ext(self):
        # binary file with matching name — content won't be searched (not a text ext)
        (self.base / "needle.bin").write_bytes(b"\x00\x01\x02 needle in bytes \x03")
        r = fs.search("needle")
        paths = {x["path"] for x in r["results"]}
        self.assertIn("needle.bin", paths)
        bin_entry = next(x for x in r["results"] if x["path"] == "needle.bin")
        self.assertEqual(bin_entry["match"], "name")

    def test_case_insensitive_content(self):
        (self.base / "caps.txt").write_text("NEEDLE in caps", "utf-8")
        r = fs.search("needle")
        paths = {x["path"] for x in r["results"]}
        self.assertIn("caps.txt", paths)

    def test_query_preserved_in_result(self):
        r = fs.search("quarterly")
        self.assertEqual(r["query"], "quarterly")

    def test_subdir_skipped_when_dotdir(self):
        # files inside a dot-directory should be skipped
        dotdir = self.base / ".git"
        dotdir.mkdir()
        (dotdir / "secret.txt").write_text("needle secret", "utf-8")
        paths = {x["path"] for x in fs.search("needle")["results"]}
        self.assertFalse(any(".git" in p for p in paths))

    def test_limit_respected(self):
        # create 5 matching files, limit=2 → at most 2 results
        for i in range(5):
            (self.base / f"match_{i}.txt").write_text("target", "utf-8")
        r = fs.search("target", limit=2)
        self.assertLessEqual(len(r["results"]), 2)


if __name__ == "__main__":
    unittest.main()
