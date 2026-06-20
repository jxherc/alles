import tempfile
from pathlib import Path
from unittest import mock

from core.database import IndexChunk
from services import textindex, vault_md
from tests._client import ApiTest


class TextIndexApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()
        # force the keyword path so tests are deterministic + fast (no model)
        self._pe = mock.patch.object(textindex, "_embed", lambda texts: None)
        self._pe.start()

    def tearDown(self):
        self._pe.stop()
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _save(self, path, content):
        return self.client.put("/api/vault-md/file", json={"path": path, "content": content})

    def test_save_indexes_doc(self):
        self._save("note.md", "alpha bravo charlie keyword")
        hits = self.client.get("/api/index/search", params={"q": "charlie", "kind": "doc"}).json()[
            "hits"
        ]
        self.assertTrue(any(h["ref"] == "note.md" for h in hits))

    def test_edit_reindexes(self):
        self._save("note.md", "original delta words")
        self._save("note.md", "replaced echo words")
        old = self.client.get("/api/index/search", params={"q": "delta"}).json()["hits"]
        new = self.client.get("/api/index/search", params={"q": "echo"}).json()["hits"]
        self.assertFalse(any(h["ref"] == "note.md" for h in old))
        self.assertTrue(any(h["ref"] == "note.md" for h in new))

    def test_delete_removes_from_index(self):
        self._save("gone.md", "foxtrot golf hotel")
        self.client.delete("/api/vault-md/file", params={"path": "gone.md"})
        hits = self.client.get("/api/index/search", params={"q": "foxtrot"}).json()["hits"]
        self.assertFalse(any(h["ref"] == "gone.md" for h in hits))

    def test_rename_moves_index(self):
        self._save("old.md", "india juliet kilo")
        self.client.post("/api/vault-md/rename", json={"path": "old.md", "new_path": "new.md"})
        hits = self.client.get("/api/index/search", params={"q": "juliet"}).json()["hits"]
        refs = {h["ref"] for h in hits}
        self.assertIn("new.md", refs)
        self.assertNotIn("old.md", refs)

    def test_api_search_returns_hits_shape(self):
        self._save("s.md", "lima mike november")
        hits = self.client.get("/api/index/search", params={"q": "mike"}).json()["hits"]
        self.assertTrue(hits)
        h = hits[0]
        self.assertIn("ref", h)
        self.assertIn("chunk", h)
        self.assertIn("score", h)
        self.assertIn("kind", h)

    def test_api_search_kind_filter(self):
        self._save("d.md", "oscar papa quebec")
        # index a code chunk directly
        d = self.db()
        textindex.index(d, "code", "x.py", "oscar papa quebec")
        only_code = self.client.get(
            "/api/index/search", params={"q": "oscar", "kind": "code"}
        ).json()["hits"]
        self.assertTrue(all(h["kind"] == "code" for h in only_code))

    def test_api_reindex_rebuilds(self):
        # write two docs straight to disk (bypassing the save hook), then reindex
        base = Path(self.tmp.name)
        (base / "a.md").write_text("romeo sierra", "utf-8")
        (base / "b.md").write_text("tango uniform", "utf-8")
        r = self.client.post("/api/index/reindex").json()
        self.assertGreaterEqual(r["docs"], 2)
        hits = self.client.get("/api/index/search", params={"q": "tango"}).json()["hits"]
        self.assertTrue(any(h["ref"] == "b.md" for h in hits))

    def test_api_search_empty_q(self):
        self._save("e.md", "whiskey xray")
        r = self.client.get("/api/index/search", params={"q": ""}).json()
        self.assertEqual(r["hits"], [])

    def test_save_hook_persists_chunks(self):
        self._save("p.md", "yankee zulu persisted")
        self.assertGreaterEqual(self.db().query(IndexChunk).filter_by(ref="p.md").count(), 1)
