import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import vault_md
from tests._client import ApiTest


class FrontmatterParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_parse_none(self):
        props, body = vault_md.parse_frontmatter("# hello\n\nno fm")
        self.assertEqual(props, {})
        self.assertEqual(body, "# hello\n\nno fm")

    def test_parse_basic_scalars(self):
        props, body = vault_md.parse_frontmatter("---\nstatus: active\npriority: high\n---\n# A\n")
        self.assertEqual(props["status"], "active")
        self.assertEqual(props["priority"], "high")
        self.assertEqual(body, "# A\n")

    def test_parse_inline_list(self):
        props, _ = vault_md.parse_frontmatter("---\ntags: [work, q3]\n---\nx")
        self.assertEqual(props["tags"], ["work", "q3"])

    def test_parse_block_list(self):
        props, _ = vault_md.parse_frontmatter("---\ntags:\n  - work\n  - q3\n---\nx")
        self.assertEqual(props["tags"], ["work", "q3"])

    def test_parse_ignores_unterminated(self):
        props, body = vault_md.parse_frontmatter("---\nstatus: active\n# no close")
        self.assertEqual(props, {})
        self.assertTrue(body.startswith("---"))

    def test_set_adds_block(self):
        out = vault_md.set_frontmatter("# A\n", {"status": "active"})
        self.assertTrue(out.startswith("---\n"))
        self.assertIn("status: active", out)
        self.assertIn("# A", out)

    def test_set_replaces_existing(self):
        out = vault_md.set_frontmatter("---\nstatus: old\n---\n# A\n", {"status": "new"})
        self.assertIn("status: new", out)
        self.assertNotIn("old", out)
        self.assertEqual(out.count("---"), 2)  # exactly one fenced block

    def test_set_empty_strips_block(self):
        out = vault_md.set_frontmatter("---\nstatus: x\n---\n# A\n", {})
        self.assertNotIn("---", out)
        self.assertIn("# A", out)

    def test_set_list_roundtrip(self):
        out = vault_md.set_frontmatter("body", {"tags": ["a", "b"]})
        props, body = vault_md.parse_frontmatter(out)
        self.assertEqual(props["tags"], ["a", "b"])
        self.assertEqual(body, "body")

    def test_roundtrip_preserves_body(self):
        body = "# Title\n\npara with [[link]] and #tag\n"
        out = vault_md.set_frontmatter(body, {"k": "v"})
        _, b2 = vault_md.parse_frontmatter(out)
        self.assertEqual(b2, body)


class PropertiesApiTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.vp = mock.patch.object(vault_md, "vault_dir", lambda: Path(self.tmp.name))
        self.vp.start()

    def tearDown(self):
        self.vp.stop()
        self.tmp.cleanup()
        super().tearDown()

    def test_get_properties_empty(self):
        vault_md.create("note", "# note\n\nbody")
        r = self.client.get("/api/vault-md/properties", params={"path": "note"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["properties"], {})

    def test_get_properties_parsed(self):
        vault_md.write("note.md", "---\nstatus: active\ntags: [a, b]\n---\nbody")
        d = self.client.get("/api/vault-md/properties", params={"path": "note"}).json()
        self.assertEqual(d["properties"]["status"], "active")
        self.assertEqual(d["properties"]["tags"], ["a", "b"])

    def test_put_sets_properties(self):
        vault_md.write("note.md", "# note\n\nbody")
        r = self.client.put(
            "/api/vault-md/properties",
            json={"path": "note", "properties": {"status": "done", "tags": ["x"]}},
        )
        self.assertEqual(r.status_code, 200)
        content = vault_md.read("note.md")["content"]
        self.assertIn("status: done", content)
        self.assertIn("body", content)

    def test_put_preserves_body_and_roundtrips(self):
        vault_md.write("n.md", "---\nold: 1\n---\nhello body")
        self.client.put("/api/vault-md/properties", json={"path": "n", "properties": {"new": "2"}})
        got = self.client.get("/api/vault-md/properties", params={"path": "n"}).json()
        self.assertEqual(got["properties"], {"new": "2"})
        self.assertIn("hello body", vault_md.read("n.md")["content"])


if __name__ == "__main__":
    unittest.main()
