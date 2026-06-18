import unittest
from datetime import datetime

from services import vault_md
from tests._client import ApiTest


class SlashCommandTests(unittest.TestCase):
    def test_registry_has_core_commands(self):
        ids = {c["id"] for c in vault_md.slash_commands()}
        for expected in [
            "h1",
            "h2",
            "h3",
            "bullet",
            "todo",
            "quote",
            "code",
            "table",
            "callout",
            "math",
            "mermaid",
            "divider",
            "wikilink",
            "date",
            "time",
        ]:
            self.assertIn(expected, ids)

    def test_heading_snippet(self):
        cmds = {c["id"]: c for c in vault_md.slash_commands()}
        self.assertEqual(cmds["h2"]["snippet"], "## {}")

    def test_todo_snippet(self):
        cmds = {c["id"]: c for c in vault_md.slash_commands()}
        self.assertEqual(cmds["todo"]["snippet"], "- [ ] {}")

    def test_code_snippet_has_fence(self):
        cmds = {c["id"]: c for c in vault_md.slash_commands()}
        self.assertIn("```", cmds["code"]["snippet"])

    def test_callout_snippet(self):
        cmds = {c["id"]: c for c in vault_md.slash_commands()}
        self.assertTrue(cmds["callout"]["snippet"].startswith("> [!note]"))

    def test_date_time_resolved(self):
        now = datetime(2026, 6, 18, 9, 30)
        cmds = {c["id"]: c for c in vault_md.slash_commands(now=now)}
        self.assertEqual(cmds["date"]["snippet"], "2026-06-18")
        self.assertEqual(cmds["time"]["snippet"], "09:30")

    def test_filter_headings(self):
        out = vault_md.filter_slash_commands("head")
        self.assertEqual(sorted(c["id"] for c in out), ["h1", "h2", "h3"])

    def test_filter_empty_returns_all(self):
        self.assertEqual(len(vault_md.filter_slash_commands("")), len(vault_md.slash_commands()))

    def test_filter_single(self):
        out = vault_md.filter_slash_commands("table")
        self.assertEqual([c["id"] for c in out], ["table"])

    def test_filter_ranks_prefix_first(self):
        out = vault_md.filter_slash_commands("code")
        self.assertTrue(out)
        self.assertEqual(out[0]["id"], "code")


class SlashApiTests(ApiTest):
    def test_api_filtered(self):
        r = self.client.get("/api/vault-md/slash-commands", params={"q": "head"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(c["id"] for c in r.json()["commands"]), ["h1", "h2", "h3"])

    def test_api_all(self):
        r = self.client.get("/api/vault-md/slash-commands")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["commands"]), len(vault_md.slash_commands()))


if __name__ == "__main__":
    unittest.main()
