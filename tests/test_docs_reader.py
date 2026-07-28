import unittest
from unittest.mock import patch

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
        bl = self.client.get("/api/vault-md/backlinks", params={"name": "alpha"}).json()[
            "backlinks"
        ]
        self.assertTrue(any(b["name"] == "beta" for b in bl))
        r = self.client.post(
            "/api/vault-md/rename", json={"path": "alpha.md", "new_path": "gamma.md"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json().get("links_rewritten", 0), 1)
        self.assertRegex(r.json().get("transaction_id", ""), r"^[0-9a-f]{32}$")
        beta = self.client.get("/api/vault-md/file", params={"path": "beta.md"}).json()
        self.assertIn("[[gamma]]", beta["content"])

    def test_rename_rejects_invalid_document_and_folder_destinations_as_client_errors(self):
        from services import vault_md

        self._new("document", "safe")
        folder = vault_md.vault_dir() / "folder"
        folder.mkdir()

        for source in ("document.md", "folder"):
            with self.subTest(source=source):
                response = self.client.post(
                    "/api/vault-md/rename",
                    json={"path": source, "new_path": "../outside"},
                )
                self.assertEqual(response.status_code, 400, response.text)

        self.assertTrue(vault_md._safe("document.md").is_file())
        self.assertTrue(vault_md._safe("folder").is_dir())

    def test_pending_rename_can_resume_after_a_restart_point(self):
        from services import document_safety, vault_md

        self._new("before", "# before")
        self._new("reference", "see [[before]]")
        manifest = document_safety.prepare_rename("before.md", "after.md")
        vault_md._safe("before.md").rename(vault_md._safe("after.md"))

        pending = self.client.get("/api/vault-md/rename/pending").json()["transactions"]
        self.assertIn(manifest["id"], {item["id"] for item in pending})
        recovered = self.client.post(
            "/api/vault-md/rename/recover",
            json={"id": manifest["id"], "action": "resume"},
        )
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["transaction"]["state"], "complete")
        reference = self.client.get("/api/vault-md/file", params={"path": "reference.md"}).json()
        self.assertIn("[[after]]", reference["content"])

    def test_delete(self):
        self._new("trash", "x")
        deleted = self.client.delete("/api/vault-md/file", params={"path": "trash.md"}).json()
        self.assertTrue(deleted["trashed"])
        self.assertFalse(
            self.client.get("/api/vault-md/file", params={"path": "trash.md"}).json()["exists"]
        )
        items = self.client.get("/api/vault-md/trash").json()
        self.assertEqual([item["path"] for item in items], ["trash.md"])
        restored = self.client.post("/api/vault-md/trash/restore", json={"id": items[0]["id"]})
        self.assertEqual(restored.status_code, 200)
        self.assertTrue(
            self.client.get("/api/vault-md/file", params={"path": "trash.md"}).json()["exists"]
        )

    def test_restore_never_replaces_a_newer_file(self):
        self._new("same", "old")
        deleted = self.client.delete("/api/vault-md/file", params={"path": "same.md"}).json()
        self._new("same", "new")
        response = self.client.post("/api/vault-md/trash/restore", json={"id": deleted["trash_id"]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "restore_conflict")
        current = self.client.get("/api/vault-md/file", params={"path": "same.md"}).json()
        self.assertEqual(current["content"], "new")

    def test_search_and_tags(self):
        self._new("searchme", "uniquetoken here #proj")
        hits = self.client.get("/api/vault-md/grep", params={"q": "uniquetoken"}).json()["results"]
        self.assertTrue(any(h["name"] == "searchme" for h in hits))
        tags = self.client.get("/api/vault-md/tags").json()["tags"]
        self.assertTrue(any(t["tag"] == "proj" for t in tags))

    def test_folder_and_ask(self):
        self.assertEqual(
            self.client.post("/api/vault-md/folder", json={"path": "myfolder"}).status_code, 200
        )
        r = self.client.get("/api/vault-md/ask", params={"q": "anything"})
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json()["sources"], list)

    def test_watcher_signature_detects_changes(self):
        from routes.vault_md import _sig_diff, _vault_sig
        from services import vault_md

        self._new("watched", "v1")
        sig1 = _vault_sig()
        self.assertIn("watched.md", sig1)
        vault_md.write("watched.md", "v2")  # same-size external edit in the same second
        changed, removed = _sig_diff(sig1, _vault_sig())
        self.assertIn("watched.md", changed)
        sig2 = _vault_sig()
        vault_md.delete("watched.md")
        changed2, removed2 = _sig_diff(sig2, _vault_sig())
        self.assertIn("watched.md", removed2)

    def test_removed_editor_routes_are_gone(self):
        self.assertIn(
            self.client.put("/api/vault-md/file", json={"path": "x", "content": "y"}).status_code,
            (404, 405),
        )
        self.assertIn(self.client.get("/api/vault-md/graph").status_code, (404, 405))
        self.assertIn(
            self.client.post(
                "/api/vault-md/ai-edit", json={"path": "x", "instruction": "y"}
            ).status_code,
            (404, 405),
        )
        self.assertIn(
            self.client.get("/api/vault-md/revisions", params={"path": "x"}).status_code, (404, 405)
        )


class DocsStreamOrderingTest(unittest.IsolatedAsyncioTestCase):
    async def test_change_event_is_emitted_after_reindex(self):
        from routes.vault_md import stream

        indexed: list[str] = []

        async def no_sleep(_seconds):
            return None

        with (
            patch("asyncio.sleep", new=no_sleep),
            patch("routes.vault_md._vault_sig", side_effect=[{}, {"fresh.md": "1:1"}]),
            patch(
                "routes.vault_md._observed_event",
                return_value={"path": "fresh.md", "kind": "changed"},
            ),
            patch("routes.vault_md._sync_changed", side_effect=indexed.append),
        ):
            response = await stream()
            iterator = response.body_iterator
            self.assertIn("hello", await anext(iterator))
            event = await anext(iterator)
            self.assertIn('"changed": ["fresh.md"]', event)
            self.assertEqual(indexed, ["fresh.md"])
            await iterator.aclose()
