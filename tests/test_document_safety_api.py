from pathlib import Path

from services import vault_md
from tests._client import VaultApiTest


class DocumentSafetyApiTests(VaultApiTest):
    def _create(self, path: str, content: str):
        response = self.client.post("/api/vault-md/file", json={"path": path, "content": content})
        self.assertEqual(response.status_code, 200)
        return self.client.get("/api/vault-md/file", params={"path": path}).json()

    def test_draft_safe_save_revision_and_exact_restore(self):
        opened = self._create("safe-api.md", "base source\r\n")
        draft = self.client.put(
            "/api/vault-md/safety/draft",
            json={
                "path": "safe-api.md",
                "content": "local source\r\n",
                "base_hash": opened["hash"],
            },
        )
        self.assertEqual(draft.status_code, 200)
        loaded = self.client.get(
            "/api/vault-md/safety/draft", params={"path": "safe-api.md"}
        ).json()["draft"]
        self.assertEqual(loaded["content"], "local source\r\n")

        saved = self.client.post(
            "/api/vault-md/safety/save",
            json={
                "path": "safe-api.md",
                "content": "local source\r\n",
                "expected_hash": opened["hash"],
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertIsNotNone(saved.json()["revision"])
        self.assertIsNone(
            self.client.get("/api/vault-md/safety/draft", params={"path": "safe-api.md"}).json()[
                "draft"
            ]
        )

        revisions = self.client.get(
            "/api/vault-md/safety/revisions", params={"path": "safe-api.md"}
        ).json()["revisions"]
        self.assertEqual(len(revisions), 1)
        restored = self.client.post(
            "/api/vault-md/safety/revisions/restore",
            json={
                "path": "safe-api.md",
                "revision_id": revisions[0]["id"],
                "expected_hash": saved.json()["hash"],
            },
        )
        self.assertEqual(restored.status_code, 200)
        self.assertEqual((Path(self._vault_tmp) / "safe-api.md").read_bytes(), b"base source\r\n")

    def test_conditional_draft_delete_preserves_a_newer_browser_write(self):
        opened = self._create("conditional-delete.md", "disk")
        first = self.client.put(
            "/api/vault-md/safety/draft",
            json={
                "path": "conditional-delete.md",
                "content": "first",
                "base_hash": opened["hash"],
            },
        ).json()
        second = self.client.put(
            "/api/vault-md/safety/draft",
            json={
                "path": "conditional-delete.md",
                "content": "second",
                "base_hash": opened["hash"],
            },
        ).json()

        stale = self.client.delete(
            "/api/vault-md/safety/draft",
            params={"path": "conditional-delete.md", "expected_hash": first["draft_hash"]},
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        loaded = self.client.get(
            "/api/vault-md/safety/draft", params={"path": "conditional-delete.md"}
        ).json()["draft"]
        self.assertEqual(loaded["content"], "second")

        current = self.client.delete(
            "/api/vault-md/safety/draft",
            params={"path": "conditional-delete.md", "expected_hash": second["draft_hash"]},
        )
        self.assertTrue(current.json()["deleted"])

        absent = self.client.delete(
            "/api/vault-md/safety/draft",
            params={"path": "conditional-delete.md", "expected_hash": second["draft_hash"]},
        )
        self.assertEqual(absent.status_code, 200, absent.text)
        self.assertFalse(absent.json()["deleted"])

    def test_conflict_response_preserves_and_exposes_both_copies(self):
        opened = self._create("conflict-api.md", "base")
        self.client.put(
            "/api/vault-md/safety/draft",
            json={
                "path": "conflict-api.md",
                "content": "local candidate",
                "base_hash": opened["hash"],
            },
        )
        external = vault_md.write("conflict-api.md", "external candidate")

        response = self.client.post(
            "/api/vault-md/safety/save",
            json={
                "path": "conflict-api.md",
                "content": "local candidate",
                "expected_hash": opened["hash"],
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "document_conflict")
        conflict_id = response.json()["conflict"]["id"]
        conflict = self.client.get(f"/api/vault-md/safety/conflicts/{conflict_id}").json()
        self.assertEqual(conflict["local"], "local candidate")
        self.assertEqual(conflict["external"], "external candidate")
        self.assertEqual(conflict["external_hash"], external["hash"])
        self.assertEqual(vault_md.read("conflict-api.md")["content"], "external candidate")

        comparison = self.client.post(
            "/api/vault-md/safety/compare",
            json={
                "path": "conflict-api.md",
                "content": "local candidate",
                "expected_hash": opened["hash"],
            },
        )
        self.assertEqual(comparison.status_code, 200)
        self.assertFalse(comparison.json()["base_matches"])
        self.assertIn("-external candidate", comparison.json()["diff"])
        self.assertIn("+local candidate", comparison.json()["diff"])

    def test_invalid_utf8_stays_read_only_through_safe_api(self):
        path = Path(self._vault_tmp) / "invalid-api.md"
        original = b"owner bytes\xff\xfe"
        path.write_bytes(original)
        opened = self.client.get("/api/vault-md/file", params={"path": "invalid-api.md"}).json()
        self.assertFalse(opened["editable"])

        response = self.client.post(
            "/api/vault-md/safety/save",
            json={
                "path": "invalid-api.md",
                "content": "replacement",
                "expected_hash": opened["hash"],
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "document_encoding_unsupported")
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    import unittest

    unittest.main()
