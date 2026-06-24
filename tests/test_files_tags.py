import tempfile
from pathlib import Path
from unittest import mock

import services.files_store as fstore
from tests._client import ApiTest


class FilesTagTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fp = mock.patch.object(fstore, "files_dir", lambda: self.root)
        self.fp.start()
        for rel in ("a.txt", "b.txt", "sub/c.txt"):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")

    def tearDown(self):
        self.fp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _put(self, path, tags=None, color=None):
        body = {}
        if tags is not None:
            body["tags"] = tags
        if color is not None:
            body["color"] = color
        return self.client.put(f"/api/files/tags?path={path}", json=body)

    def _get(self, path):
        return self.client.get(f"/api/files/tags?path={path}").json()

    def test_put_then_get(self):
        self._put("a.txt", tags=["work", "urgent"], color="red")
        g = self._get("a.txt")
        self.assertEqual(set(g["tags"]), {"work", "urgent"})
        self.assertEqual(g["color"], "red")

    def test_get_unset_is_empty(self):
        g = self._get("b.txt")
        self.assertEqual(g["tags"], [])
        self.assertEqual(g["color"], "")

    def test_update_overwrites(self):
        self._put("a.txt", tags=["one"])
        self._put("a.txt", tags=["two", "three"])
        self.assertEqual(set(self._get("a.txt")["tags"]), {"two", "three"})

    def test_tags_normalized_lowercased_trimmed(self):
        self._put("a.txt", tags=["  Work ", "WORK", "home"])
        # dedup case-insensitively, trimmed
        self.assertEqual(sorted(self._get("a.txt")["tags"]), ["home", "work"])

    def test_clearing_tags(self):
        self._put("a.txt", tags=["x"])
        self._put("a.txt", tags=[])
        self.assertEqual(self._get("a.txt")["tags"], [])

    def test_by_tag_lists_paths(self):
        self._put("a.txt", tags=["proj"])
        self._put("sub/c.txt", tags=["proj"])
        self._put("b.txt", tags=["other"])
        paths = {i["path"] for i in self.client.get("/api/files/by-tag?tag=proj").json()["items"]}
        self.assertEqual(paths, {"a.txt", "sub/c.txt"})

    def test_by_tag_case_insensitive(self):
        self._put("a.txt", tags=["Proj"])
        paths = {i["path"] for i in self.client.get("/api/files/by-tag?tag=PROJ").json()["items"]}
        self.assertIn("a.txt", paths)

    def test_all_tags_known(self):
        self._put("a.txt", tags=["alpha"], color="blue")
        self._put("b.txt", tags=["beta"])
        d = self.client.get("/api/files/tags/all").json()
        self.assertIn("alpha", d["tags"])
        self.assertIn("beta", d["tags"])

    def test_listing_carries_tags(self):
        self._put("a.txt", tags=["flagged"], color="red")
        items = self.client.get("/api/files/list?path=").json()["items"]
        a = [i for i in items if i["name"] == "a.txt"][0]
        self.assertIn("flagged", a["tags"])
        self.assertEqual(a["color"], "red")

    def test_listing_untagged_empty(self):
        items = self.client.get("/api/files/list?path=").json()["items"]
        b = [i for i in items if i["name"] == "b.txt"][0]
        self.assertEqual(b["tags"], [])

    def test_color_only_no_tags(self):
        self._put("b.txt", color="green")
        g = self._get("b.txt")
        self.assertEqual(g["color"], "green")
        self.assertEqual(g["tags"], [])

    def test_by_tag_lists_matching_files(self):
        self._put("a.txt", tags=["work", "urgent"])
        self._put("sub/c.txt", tags=["work"])
        self._put("b.txt", tags=["home"])
        d = self.client.get("/api/files/by-tag", params={"tag": "work"}).json()
        paths = sorted(i["path"] for i in d["items"])
        self.assertEqual(paths, ["a.txt", "sub/c.txt"])

    def test_by_tag_empty(self):
        self._put("a.txt", tags=["work"])
        self.assertEqual(self.client.get("/api/files/by-tag", params={"tag": "nope"}).json()["items"], [])
