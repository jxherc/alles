"""aide agent tools over the markdown vault: read/write/append/search/backlinks.
exercised through services.agent_tools.execute() against an isolated vault + db."""

import asyncio

import services.agent_tools as at
from services import textindex, vault_md
from tests._client import VaultApiTest


class AgentVaultToolsTests(VaultApiTest):
    def ex(self, name, args=None):
        return asyncio.run(at.execute(name, args or {}))

    # ── write / read ───────────────────────────────────────────────────────────
    def test_write_then_read_by_name(self):
        self.ex("note_write", {"path": "Ideas", "content": "ship the vault tools"})
        r = self.ex("note_read", {"name": "Ideas"})
        self.assertIn("ship the vault tools", r["output"])

    def test_read_by_path_in_subfolder(self):
        self.ex("note_write", {"path": "Projects/Roadmap", "content": "q3 plan"})
        r = self.ex("note_read", {"name": "Projects/Roadmap.md"})
        self.assertIn("q3 plan", r["output"])

    def test_read_missing_errors(self):
        r = self.ex("note_read", {"name": "nope-not-here"})
        self.assertTrue(r.get("error"))

    # ── append (safe additive write) ────────────────────────────────────────────
    def test_append_creates_when_missing(self):
        r = self.ex("note_append", {"path": "Log", "content": "first line"})
        self.assertFalse(r.get("error"), r)
        self.assertIn("created", r["output"])
        self.assertIn("first line", self.ex("note_read", {"name": "Log"})["output"])

    def test_append_preserves_existing(self):
        self.ex("note_write", {"path": "Log", "content": "first line"})
        self.ex("note_append", {"path": "Log", "content": "second line"})
        out = self.ex("note_read", {"name": "Log"})["output"]
        self.assertIn("first line", out)
        self.assertIn("second line", out)
        self.assertLess(out.index("first line"), out.index("second line"))

    # ── search returns a path to cite ───────────────────────────────────────────
    def test_search_includes_path(self):
        self.ex("note_write", {"path": "Findings", "content": "a unique-marker token"})
        r = self.ex("note_search", {"query": "unique-marker"})
        self.assertIn("Findings", r["output"])
        self.assertIn("Findings.md", r["output"])

    # ── backlinks traversal ─────────────────────────────────────────────────────
    def test_backlinks_finds_linking_note(self):
        self.ex("note_write", {"path": "Target", "content": "the target note"})
        self.ex("note_write", {"path": "Source", "content": "see [[Target]] for more"})
        r = self.ex("note_backlinks", {"name": "Target"})
        self.assertIn("Source", r["output"])

    def test_backlinks_none(self):
        self.ex("note_write", {"path": "Lonely", "content": "no links here"})
        r = self.ex("note_backlinks", {"name": "Lonely"})
        self.assertIn("no notes link", r["output"])

    # ── writes keep the search index fresh ──────────────────────────────────────
    def test_write_reindexes_doc(self):
        self.ex("note_write", {"path": "Indexed", "content": "distinctivephrase here"})
        db = self.db()
        try:
            hits = textindex.search(db, "distinctivephrase", kind="doc", k=5)
        finally:
            db.close()
        refs = {h["ref"] for h in hits}
        self.assertIn("Indexed.md", refs)

    def test_append_reindexes_doc(self):
        self.ex("note_append", {"path": "Appended", "content": "freshtoken appears"})
        db = self.db()
        try:
            hits = textindex.search(db, "freshtoken", kind="doc", k=5)
        finally:
            db.close()
        self.assertIn("Appended.md", {h["ref"] for h in hits})

    # ── registration / wiring ───────────────────────────────────────────────────
    def test_new_tools_registered(self):
        names = {d["function"]["name"] for d in at.APP_TOOL_DEFS}
        self.assertIn("note_append", names)
        self.assertIn("note_backlinks", names)
        self.assertIn("note_append", at.MUTATING_TOOLS)
        self.assertNotIn("note_backlinks", at.MUTATING_TOOLS)  # read-only

    def test_plan_mode_hides_append_keeps_backlinks(self):
        plan = {t["function"]["name"] for t in at.build_tool_defs({"agent_permission_mode": "plan"})}
        self.assertNotIn("note_append", plan)  # mutating → hidden
        self.assertIn("note_backlinks", plan)  # read → stays
