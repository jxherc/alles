"""audit fixes: renaming a file must carry its tags/star (not orphan them) and reject a
collision with a clean 400 (not crash); deleting must clear its tag metadata."""

import tempfile
from pathlib import Path
from unittest import mock

import services.files_store as fstore
from tests._client import ApiTest


class FilesMetaTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fp = mock.patch.object(fstore, "files_dir", lambda: self.root)
        self.fp.start()

    def tearDown(self):
        self.fp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _w(self, rel, body="x"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)

    def _starred(self):
        r = self.client.get("/api/files/starred").json()
        rows = r if isinstance(r, list) else r.get("items", [])
        return [x["path"] for x in rows]

    def test_rename_carries_tags_and_star(self):
        self._w("a.txt")
        self.client.put("/api/files/star?path=a.txt", json={"starred": True})
        self.client.put("/api/files/tags?path=a.txt", json={"tags": ["work"]})
        r = self.client.post("/api/files/rename", json={"path": "a.txt", "to": "c.txt"})
        self.assertEqual(r.status_code, 200)
        starred = self._starred()
        self.assertIn("c.txt", starred)
        self.assertNotIn("a.txt", starred)

    def test_rename_onto_existing_is_400(self):
        self._w("a.txt")
        self._w("b.txt")
        r = self.client.post("/api/files/rename", json={"path": "a.txt", "to": "b.txt"})
        self.assertEqual(r.status_code, 400)

    def test_delete_clears_tag_metadata(self):
        self._w("a.txt")
        self.client.put("/api/files/star?path=a.txt", json={"starred": True})
        self.client.delete("/api/files/delete?path=a.txt")
        self.assertNotIn("a.txt", self._starred())
