import os
import tempfile
import time
from pathlib import Path
from unittest import mock

import services.files_store as fstore
from tests._client import ApiTest


class FilesSmartTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fp = mock.patch.object(fstore, "files_dir", lambda: self.root)
        self.fp.start()
        self._mk("readme.txt", "hello")
        self._mk("projects/app.js", "console.log(1)")
        self._mk("projects/big.log", "x" * 20000)
        self._mk("photos/a.png", "png")
        self._mk("photos/b.jpg", "jpg")
        self._mk("notes/ideas.md", "# notes")

    def tearDown(self):
        self.fp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _mk(self, rel, content):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def _smart(self, kind, **params):
        return self.client.get(f"/api/files/smart/{kind}", params=params).json()

    def test_images_kind(self):
        names = {i["name"] for i in self._smart("images")["items"]}
        self.assertEqual(names, {"a.png", "b.jpg"})

    def test_images_excludes_non_images(self):
        names = {i["name"] for i in self._smart("images")["items"]}
        self.assertNotIn("readme.txt", names)

    def test_documents_kind(self):
        names = {i["name"] for i in self._smart("documents")["items"]}
        self.assertIn("readme.txt", names)
        self.assertIn("ideas.md", names)
        self.assertNotIn("a.png", names)

    def test_large_sorted_desc(self):
        items = self._smart("large")["items"]
        sizes = [i["size"] for i in items]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(items[0]["name"], "big.log")

    def test_recent_sorted_by_mtime_desc(self):
        # touch one file to be newest
        newest = self.root / "notes/ideas.md"
        os.utime(newest, (time.time() + 100, time.time() + 100))
        items = self._smart("recent")["items"]
        self.assertEqual(items[0]["name"], "ideas.md")

    def test_recent_window_excludes_old(self):
        old = self.root / "readme.txt"
        old_ts = time.time() - 60 * 86400  # 60 days ago
        os.utime(old, (old_ts, old_ts))
        names = {i["name"] for i in self._smart("recent", days=30)["items"]}
        self.assertNotIn("readme.txt", names)

    def test_unknown_kind_400(self):
        r = self.client.get("/api/files/smart/bogus")
        self.assertEqual(r.status_code, 400)

    def test_items_have_path(self):
        items = self._smart("images")["items"]
        self.assertTrue(all("/" in i["path"] or i["path"] for i in items))
        self.assertTrue(any(i["path"] == "photos/a.png" for i in items))

    def test_limit_respected(self):
        items = self._smart("documents", limit=1)["items"]
        self.assertLessEqual(len(items), 1)

    def test_skips_dotfiles(self):
        self._mk(".secret/hidden.png", "x")
        names = {i["name"] for i in self._smart("images")["items"]}
        self.assertNotIn("hidden.png", names)

    def test_kind_echoed(self):
        self.assertEqual(self._smart("recent")["kind"], "recent")
