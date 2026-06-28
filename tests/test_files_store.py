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

    def test_save_upload_rejects_dot_only_names(self):
        # ".", "..", "..." and "" all reduce to the dir itself; must not write onto it
        for bad in ("", ".", "..", "..."):
            with self.assertRaises(ValueError):
                fs.save_upload("", bad, b"x")

    def test_upload_strips_path_from_name(self):
        fs.save_upload("", "../sneaky.txt", b"x")
        names = [i["name"] for i in fs.listdir("")["items"]]
        self.assertIn("sneaky.txt", names)  # the ../ was stripped

    def test_read_text_reads_only_head_up_to_limit(self):
        # big file: only the head up to `limit` is decoded, but full size is still reported
        fs.save_upload("", "big.txt", b"A" * 5000)
        r = fs.read_text("big.txt", limit=1000)
        self.assertEqual(len(r["content"]), 1000)
        self.assertTrue(r["truncated"])
        self.assertEqual(r["size"], 5000)
        # small file: full content, not truncated
        fs.save_upload("", "small.txt", b"hello")
        r2 = fs.read_text("small.txt", limit=1000)
        self.assertEqual(r2["content"], "hello")
        self.assertFalse(r2["truncated"])

    def test_read_binary_returns_not_text(self):
        fs.save_upload("", "img.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00")
        r = fs.read_text("img.png")
        self.assertFalse(r["is_text"])
        self.assertEqual(r["content"], "")

    def test_rename_moves_across_dirs(self):
        fs.mkdir("src_dir")
        fs.mkdir("dst_dir")
        fs.save_upload("src_dir", "file.txt", b"data")
        fs.rename("src_dir/file.txt", "dst_dir/file.txt")
        self.assertEqual(fs.listdir("src_dir")["items"], [])
        self.assertEqual(fs.listdir("dst_dir")["items"][0]["name"], "file.txt")

    def test_listdir_dirs_float_to_top(self):
        fs.mkdir("zzz_dir")
        fs.save_upload("", "aaa.txt", b"x")
        items = fs.listdir("")["items"]
        types = [i["type"] for i in items]
        # all dirs come before files
        last_dir = max((idx for idx, t in enumerate(types) if t == "dir"), default=-1)
        first_file = min((idx for idx, t in enumerate(types) if t == "file"), default=99)
        self.assertLess(last_dir, first_file)

    def test_search_by_name_and_content(self):
        fs.save_upload("", "match_me.txt", b"something unrelated")
        fs.save_upload("", "other.txt", b"this has the magic word xyzzy in it")
        r = fs.search("match_me")
        names = [e["name"] for e in r["results"]]
        self.assertIn("match_me.txt", names)
        r2 = fs.search("xyzzy")
        names2 = [e["name"] for e in r2["results"]]
        self.assertIn("other.txt", names2)

    def test_search_empty_query_returns_empty(self):
        fs.save_upload("", "file.txt", b"content")
        r = fs.search("")
        self.assertEqual(r["results"], [])

    def test_smart_images_only_images(self):
        fs.save_upload("", "photo.png", b"fakepng")
        fs.save_upload("", "readme.txt", b"text")
        r = fs.smart("images")
        names = [e["name"] for e in r["items"]]
        self.assertIn("photo.png", names)
        self.assertNotIn("readme.txt", names)


if __name__ == "__main__":
    unittest.main()
