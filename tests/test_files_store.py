import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import files_store as fs


class FilesStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(fs, "files_dir", lambda: Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            fs._safe("../../etc/passwd")
        with self.assertRaises(ValueError):
            fs.listdir("../..")

    def test_mkdir_upload_list_rename_delete(self):
        fs.mkdir("docs")
        fs.save_upload("docs", "a.txt", b"hello")
        items = fs.listdir("docs")["items"]
        self.assertEqual([i["name"] for i in items], ["a.txt"])
        self.assertEqual(items[0]["type"], "file")
        fs.rename("docs/a.txt", "docs/b.txt")
        self.assertEqual([i["name"] for i in fs.listdir("docs")["items"]], ["b.txt"])
        fs.delete("docs")
        self.assertEqual(fs.listdir("")["items"], [])

    def test_read_text(self):
        fs.save_upload("", "n.md", b"# hi\ntext")
        r = fs.read_text("n.md")
        self.assertTrue(r["is_text"])
        self.assertIn("# hi", r["content"])

    def test_wont_delete_root(self):
        with self.assertRaises(ValueError):
            fs.delete("")

    def test_upload_strips_path_from_name(self):
        fs.save_upload("", "../sneaky.txt", b"x")
        names = [i["name"] for i in fs.listdir("")["items"]]
        self.assertIn("sneaky.txt", names)   # the ../ was stripped


if __name__ == "__main__":
    unittest.main()
