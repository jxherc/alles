import tempfile
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


class DocCommentTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self._p.start()
        vault_md.write("notes/a.md", "# A\nthe quick brown fox jumps over the lazy dog")
        vault_md.write("notes/b.md", "# B\nunrelated content")

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()
        super().tearDown()

    def _root(self, anchor="quick brown", body="nice", path="notes/a.md"):
        return self.client.post(
            "/api/vault-md/comments", json={"path": path, "anchor": anchor, "body": body}
        ).json()

    def test_create_thread_root(self):
        d = self._root()
        self.assertTrue(d["id"])
        self.assertIsNone(d["parent_id"])
        self.assertEqual(d["doc"], "notes/a.md")
        self.assertEqual(d["anchor"], "quick brown")

    def test_list_threads_for_doc(self):
        self._root(body="hello")
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/a.md"}).json()
        self.assertEqual(len(d["threads"]), 1)
        self.assertEqual(d["threads"][0]["body"], "hello")
        self.assertEqual(d["threads"][0]["replies"], [])

    def test_reply_attaches_to_thread(self):
        root = self._root()
        self.client.post("/api/vault-md/comments", json={"parent_id": root["id"], "body": "agreed"})
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/a.md"}).json()
        self.assertEqual(len(d["threads"]), 1)
        self.assertEqual(len(d["threads"][0]["replies"]), 1)
        self.assertEqual(d["threads"][0]["replies"][0]["body"], "agreed")

    def test_reply_inherits_doc_and_anchor(self):
        root = self._root(anchor="lazy dog")
        rep = self.client.post(
            "/api/vault-md/comments", json={"parent_id": root["id"], "body": "r"}
        ).json()
        self.assertEqual(rep["doc"], "notes/a.md")
        self.assertEqual(rep["anchor"], "lazy dog")

    def test_resolve_toggles_thread(self):
        root = self._root()
        self.client.post(f"/api/vault-md/comments/{root['id']}/resolve")
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/a.md"}).json()
        self.assertTrue(d["threads"][0]["resolved"])
        self.client.post(f"/api/vault-md/comments/{root['id']}/resolve")
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/a.md"}).json()
        self.assertFalse(d["threads"][0]["resolved"])

    def test_delete_comment(self):
        root = self._root()
        r = self.client.delete(f"/api/vault-md/comments/{root['id']}")
        self.assertEqual(r.status_code, 200)
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/a.md"}).json()
        self.assertEqual(d["threads"], [])

    def test_delete_root_cascades_replies(self):
        root = self._root()
        self.client.post("/api/vault-md/comments", json={"parent_id": root["id"], "body": "r"})
        self.client.delete(f"/api/vault-md/comments/{root['id']}")
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/a.md"}).json()
        self.assertEqual(d["threads"], [])

    def test_orphaned_when_anchor_absent(self):
        self._root(anchor="not present in the note at all")
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/a.md"}).json()
        self.assertTrue(d["threads"][0]["orphaned"])

    def test_not_orphaned_when_anchor_present(self):
        self._root(anchor="brown fox")
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/a.md"}).json()
        self.assertFalse(d["threads"][0]["orphaned"])

    def test_list_scoped_to_doc(self):
        self._root(path="notes/a.md")
        d = self.client.get("/api/vault-md/comments", params={"path": "notes/b.md"}).json()
        self.assertEqual(d["threads"], [])

    def test_reply_unknown_parent_404(self):
        r = self.client.post("/api/vault-md/comments", json={"parent_id": "nope", "body": "x"})
        self.assertEqual(r.status_code, 404)

    def test_create_requires_body(self):
        r = self.client.post(
            "/api/vault-md/comments", json={"path": "notes/a.md", "anchor": "x", "body": ""}
        )
        self.assertEqual(r.status_code, 400)
