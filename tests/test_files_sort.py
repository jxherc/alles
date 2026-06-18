import os
import tempfile
import time
from pathlib import Path
from unittest import mock

import services.files_store as fstore
from tests._client import ApiTest


class FilesSortTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fp = mock.patch.object(fstore, "files_dir", lambda: self.root)
        self.fp.start()
        # files with controlled sizes + mtimes
        (self.root / "zebra.txt").write_text("x" * 10)
        (self.root / "apple.txt").write_text("x" * 500)
        (self.root / "mango.txt").write_text("x" * 50)
        (self.root / "folder").mkdir()
        base = time.time()
        os.utime(self.root / "zebra.txt", (base - 100, base - 100))  # oldest
        os.utime(self.root / "apple.txt", (base - 50, base - 50))
        os.utime(self.root / "mango.txt", (base, base))  # newest

    def tearDown(self):
        self.fp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _names(self, **params):
        d = self.client.get("/api/files/list", params={"path": "", **params}).json()
        return [i["name"] for i in d["items"]]

    def test_default_dirs_first_then_name(self):
        names = self._names()
        self.assertEqual(names[0], "folder")  # dir first
        self.assertEqual(names[1:], ["apple.txt", "mango.txt", "zebra.txt"])

    def test_sort_name_asc(self):
        names = [n for n in self._names(sort="name", order="asc") if n.endswith(".txt")]
        self.assertEqual(names, ["apple.txt", "mango.txt", "zebra.txt"])

    def test_sort_name_desc(self):
        names = [n for n in self._names(sort="name", order="desc") if n.endswith(".txt")]
        self.assertEqual(names, ["zebra.txt", "mango.txt", "apple.txt"])

    def test_sort_size_desc(self):
        names = [n for n in self._names(sort="size", order="desc") if n.endswith(".txt")]
        self.assertEqual(names, ["apple.txt", "mango.txt", "zebra.txt"])  # 500,50,10

    def test_sort_size_asc(self):
        names = [n for n in self._names(sort="size", order="asc") if n.endswith(".txt")]
        self.assertEqual(names, ["zebra.txt", "mango.txt", "apple.txt"])

    def test_sort_mtime_desc(self):
        names = [n for n in self._names(sort="mtime", order="desc") if n.endswith(".txt")]
        self.assertEqual(names, ["mango.txt", "apple.txt", "zebra.txt"])

    def test_sort_mtime_asc(self):
        names = [n for n in self._names(sort="mtime", order="asc") if n.endswith(".txt")]
        self.assertEqual(names, ["zebra.txt", "apple.txt", "mango.txt"])

    def test_dirs_first_preserved_on_size_sort(self):
        # even sorting by size, the folder (a dir) sorts before files
        self.assertEqual(self._names(sort="size", order="desc")[0], "folder")

    def test_unknown_sort_falls_back_to_name(self):
        names = [n for n in self._names(sort="bogus") if n.endswith(".txt")]
        self.assertEqual(names, ["apple.txt", "mango.txt", "zebra.txt"])

    def test_default_order_for_size_is_desc(self):
        # size sort with no order → biggest first is the sensible default
        names = [n for n in self._names(sort="size") if n.endswith(".txt")]
        self.assertEqual(names[0], "apple.txt")
