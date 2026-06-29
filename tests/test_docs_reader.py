from tests._client import VaultApiTest


class DocsReaderTest(VaultApiTest):
    def _new(self, path, content=""):
        return self.client.post("/api/vault-md/file", json={"path": path, "content": content})

    def test_create_read_tree(self):
        r = self._new("hello", "# Hi\n\nbody text")
        self.assertEqual(r.status_code, 200)
        path = r.json()["path"]
        self.assertTrue(path.endswith("hello.md"))
        doc = self.client.get("/api/vault-md/file", params={"path": path}).json()
        self.assertIn("body text", doc["content"])
        names = [i["name"] for i in self.client.get("/api/vault-md/tree").json()["items"]]
        self.assertIn("hello", names)

    def test_rename_rewrites_backlinks(self):
        self._new("alpha", "a")
        self._new("beta", "see [[alpha]]")
        bl = self.client.get("/api/vault-md/backlinks", params={"name": "alpha"}).json()["backlinks"]
        self.assertTrue(any(b["name"] == "beta" for b in bl))
        r = self.client.post("/api/vault-md/rename", json={"path": "alpha.md", "new_path": "gamma.md"})
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json().get("links_rewritten", 0), 1)
        beta = self.client.get("/api/vault-md/file", params={"path": "beta.md"}).json()
        self.assertIn("[[gamma]]", beta["content"])

    def test_delete(self):
        self._new("trash", "x")
        self.client.delete("/api/vault-md/file", params={"path": "trash.md"})
        self.assertFalse(self.client.get("/api/vault-md/file", params={"path": "trash.md"}).json()["exists"])

    def test_search_and_tags(self):
        self._new("searchme", "uniquetoken here #proj")
        hits = self.client.get("/api/vault-md/grep", params={"q": "uniquetoken"}).json()["results"]
        self.assertTrue(any(h["name"] == "searchme" for h in hits))
        tags = self.client.get("/api/vault-md/tags").json()["tags"]
        self.assertTrue(any(t["tag"] == "proj" for t in tags))

    def test_folder_and_ask(self):
        self.assertEqual(self.client.post("/api/vault-md/folder", json={"path": "myfolder"}).status_code, 200)
        r = self.client.get("/api/vault-md/ask", params={"q": "anything"})
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json()["sources"], list)

    def test_removed_editor_routes_are_gone(self):
        self.assertIn(self.client.put("/api/vault-md/file", json={"path": "x", "content": "y"}).status_code, (404, 405))
        self.assertIn(self.client.get("/api/vault-md/graph").status_code, (404, 405))
        self.assertIn(self.client.post("/api/vault-md/ai-edit", json={"path": "x", "instruction": "y"}).status_code, (404, 405))
        self.assertIn(self.client.get("/api/vault-md/revisions", params={"path": "x"}).status_code, (404, 405))
