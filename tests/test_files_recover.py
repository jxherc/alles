import tempfile
from pathlib import Path
from unittest import mock

from services import files_store as fstore
from tests._client import ApiTest


class FilesRecoverTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fp = mock.patch.object(fstore, "files_dir", lambda: self.root)
        self.fp.start()
        (self.root / "a.txt").write_text("hello")  # 5 bytes
        (self.root / "b.txt").write_text("world!!")  # 7 bytes
        (self.root / "sub").mkdir()
        (self.root / "sub" / "c.txt").write_text("xyz")  # 3 bytes

    def tearDown(self):
        self.fp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _star(self, path, starred=True):
        return self.client.put(f"/api/files/star?path={path}", json={"starred": starred})

    def test_star_sets_flag(self):
        d = self._star("a.txt").json()
        self.assertTrue(d["starred"])

    def test_star_unsets(self):
        self._star("a.txt")
        d = self._star("a.txt", starred=False).json()
        self.assertFalse(d["starred"])

    def test_listing_carries_starred(self):
        self._star("a.txt")
        items = self.client.get("/api/files/list").json()["items"]
        a = next(i for i in items if i["path"] == "a.txt")
        self.assertTrue(a["starred"])

    def test_starred_lists_only_starred(self):
        self._star("a.txt")
        d = self.client.get("/api/files/starred").json()
        self.assertEqual([i["path"] for i in d["items"]], ["a.txt"])

    def test_star_persists(self):
        self._star("b.txt")
        items = self.client.get("/api/files/list").json()["items"]
        b = next(i for i in items if i["path"] == "b.txt")
        self.assertTrue(b["starred"])

    def test_unstarred_not_listed(self):
        self._star("a.txt")
        self._star("a.txt", starred=False)
        self.assertEqual(self.client.get("/api/files/starred").json()["items"], [])

    def test_quota_used_sums_files(self):
        d = self.client.get("/api/files/quota").json()
        self.assertEqual(d["used"], 15)  # 5 + 7 + 3

    def test_quota_has_disk_totals(self):
        d = self.client.get("/api/files/quota").json()
        self.assertGreater(d["total"], 0)
        self.assertGreaterEqual(d["free"], 0)

    def test_star_empty_path_400(self):
        r = self.client.put("/api/files/star?path=", json={"starred": True})
        self.assertEqual(r.status_code, 400)
