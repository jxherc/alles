import os
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
        # editing moved to Obsidian; write via the service + reindex (what the old PUT route did)
        from routes.vault_md import _reindex_doc

        out = vault_md.write(path, content)
        _reindex_doc(out.get("path", path), content)
        return out

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

    def test_reindex_read_error_preserves_existing_search_results(self):
        self._save("keep.md", "searchable owner text")
        base = Path(self.tmp.name)
        (base / "new.md").write_text("new document text", "utf-8")
        original_read_text = Path.read_text

        def read_text(path, *args, **kwargs):
            if path.name == "keep.md":
                raise OSError("document temporarily unavailable")
            return original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", read_text):
            response = self.client.post("/api/index/reindex")

        self.assertEqual(response.status_code, 503, response.text)
        hits = self.client.get(
            "/api/index/search", params={"q": "searchable", "kind": "doc"}
        ).json()["hits"]
        self.assertTrue(any(hit["ref"] == "keep.md" for hit in hits))
        self.assertEqual(self.db().query(IndexChunk).filter_by(ref="new.md").count(), 0)

        retried = self.client.post("/api/index/reindex")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertGreater(self.db().query(IndexChunk).filter_by(ref="new.md").count(), 0)

    def test_reindex_folder_scan_error_preserves_existing_search_results(self):
        self._save("folder/keep.md", "searchable folder text")
        blocked = (Path(self.tmp.name) / "folder").resolve()
        original_scandir = os.scandir

        def scandir(path):
            if Path(path).resolve() == blocked:
                raise PermissionError("folder temporarily unavailable")
            return original_scandir(path)

        with mock.patch("os.scandir", side_effect=scandir):
            response = self.client.post("/api/index/reindex")

        self.assertEqual(response.status_code, 503, response.text)
        hits = self.client.get(
            "/api/index/search", params={"q": "searchable", "kind": "doc"}
        ).json()["hits"]
        self.assertTrue(any(hit["ref"] == "folder/keep.md" for hit in hits))

    def test_reindex_does_not_follow_a_document_symlink_outside_the_vault(self):
        base = Path(self.tmp.name)
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "outside.md"
            external.write_text("synthetic private phrase", "utf-8")
            (base / "linked.md").symlink_to(external)

            response = self.client.post("/api/index/reindex")
            self.assertEqual(response.status_code, 200, response.text)
            hits = self.client.get(
                "/api/index/search", params={"q": "synthetic private phrase", "kind": "doc"}
            ).json()["hits"]
            self.assertFalse(any(hit["ref"] == "linked.md" for hit in hits))

    def test_reindex_skips_a_circular_markdown_symlink(self):
        loop = Path(self.tmp.name) / "loop.md"
        loop.symlink_to(loop.name)

        response = self.client.post("/api/index/reindex")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["docs"], 0)

    def test_ask_does_not_seed_a_partial_document_index(self):
        (Path(self.tmp.name) / "unreadable.md").write_text("private test text", "utf-8")
        with mock.patch.object(Path, "read_text", side_effect=OSError("read failed")):
            response = self.client.get("/api/vault-md/ask", params={"q": "private"})

        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(self.db().query(IndexChunk).filter_by(kind="doc").count(), 0)

    def test_api_search_empty_q(self):
        self._save("e.md", "whiskey xray")
        r = self.client.get("/api/index/search", params={"q": ""}).json()
        self.assertEqual(r["hits"], [])

    def test_save_hook_persists_chunks(self):
        self._save("p.md", "yankee zulu persisted")
        self.assertGreaterEqual(self.db().query(IndexChunk).filter_by(ref="p.md").count(), 1)

    def test_create_existing_note_indexes_disk_content(self):
        self.client.post("/api/vault-md/file", json={"path": "clip", "content": "alpha original"})
        r = self.client.post(
            "/api/vault-md/file", json={"path": "clip", "content": "bravo rejected"}
        )

        self.assertTrue(r.json()["existed"])
        self.assertIn("alpha original", vault_md.read("clip.md")["content"])
        old = self.client.get("/api/index/search", params={"q": "alpha", "kind": "doc"}).json()[
            "hits"
        ]
        stale = self.client.get("/api/index/search", params={"q": "bravo", "kind": "doc"}).json()[
            "hits"
        ]
        self.assertTrue(any(h["ref"] == "clip.md" for h in old))
        self.assertFalse(any(h["ref"] == "clip.md" for h in stale))
