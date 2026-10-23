"""aide agent tools over the markdown vault: read/write/append/search/backlinks.
exercised through services.agent_tools.execute() against an isolated vault + db."""

import asyncio
from unittest.mock import patch

import services.agent_tools as at
from services import document_safety, textindex, vault_md
from tests._client import VaultApiTest


class AgentVaultToolsTests(VaultApiTest):
    def ex(self, name, args=None):
        return asyncio.run(at.execute(name, args or {}))

    # ── write / read ───────────────────────────────────────────────────────────
    def test_write_then_read_by_name(self):
        self.ex("note_write", {"path": "Ideas", "content": "ship the vault tools"})
        r = self.ex("note_read", {"name": "Ideas"})
        self.assertIn("ship the vault tools", r["output"])

    def test_tasks_conversation_can_write_and_read_research_in_docs(self):
        written = self.ex(
            "docs_write",
            {
                "path": "Research/local-search.md",
                "content": "# local search\n\nSearXNG is the selected source.",
            },
        )
        self.assertFalse(written.get("error"), written)
        self.assertIn("Research/local-search.md", written["output"])

        read = self.ex("docs_read", {"path": "Research/local-search.md"})
        self.assertFalse(read.get("error"), read)
        self.assertIn("SearXNG is the selected source", read["output"])
        self.assertTrue((vault_md.vault_dir() / "Research/local-search.md").is_file())

    def test_read_by_path_in_subfolder(self):
        self.ex("note_write", {"path": "Projects/Roadmap", "content": "q3 plan"})
        r = self.ex("note_read", {"name": "Projects/Roadmap.md"})
        self.assertIn("q3 plan", r["output"])

    def test_read_missing_errors(self):
        r = self.ex("note_read", {"name": "nope-not-here"})
        self.assertTrue(r.get("error"))

    def test_read_returns_the_exact_document_version_for_a_reviewed_write(self):
        saved = vault_md.write("versioned.md", "source\r\n")
        read = self.ex("docs_read", {"path": "versioned.md"})
        self.assertEqual(read.get("hash"), saved["hash"])
        self.assertEqual(read.get("path"), "versioned.md")
        self.assertIn(saved["hash"], read["output"])
        self.assertEqual(
            read["source"], {"kind": "document", "path": "versioned.md", "hash": saved["hash"]}
        )

    def test_search_returns_actual_paths_without_claiming_full_document_reads(self):
        vault_md.write("Research/one.md", "synthetic search phrase")
        found = self.ex("docs_search", {"query": "synthetic search phrase"})
        self.assertEqual(
            found["source"],
            {
                "kind": "search",
                "query": "synthetic search phrase",
                "results": [{"kind": "document", "path": "Research/one.md", "label": "one"}],
            },
        )

    def test_existing_document_requires_the_reviewed_version_for_both_write_tools(self):
        for tool in ("docs_write", "note_write"):
            with self.subTest(tool=tool):
                path = f"{tool}.md"
                original = vault_md.write(path, "owner source")
                result = self.ex(tool, {"path": path, "content": "unchecked replacement"})
                self.assertTrue(result.get("error"), result)
                self.assertEqual(vault_md.read(path)["hash"], original["hash"])

    def test_stale_write_keeps_both_versions_and_does_not_report_success(self):
        opened = vault_md.write("stale.md", "reviewed source")
        vault_md.write("stale.md", "newer owner source")
        result = self.ex(
            "docs_write",
            {"path": "stale.md", "content": "generated candidate", "expected_hash": opened["hash"]},
        )
        self.assertTrue(result.get("error"), result)
        self.assertEqual(vault_md.read("stale.md")["content"], "newer owner source")
        conflict = self.client.get(f"/api/vault-md/safety/conflicts/{result['conflict_id']}")
        self.assertEqual(conflict.status_code, 200, conflict.text)
        self.assertEqual(conflict.json()["local"], "generated candidate")
        self.assertEqual(conflict.json()["external"], "newer owner source")

    def test_reviewed_write_has_a_revision_that_restores_exact_original_bytes(self):
        opened = vault_md.write("restore.md", "owner source\r\n")
        result = self.ex(
            "docs_write",
            {
                "path": "restore.md",
                "content": "accepted revision\n",
                "expected_hash": opened["hash"],
            },
        )
        self.assertFalse(result.get("error"), result)
        revisions = document_safety.list_revisions("restore.md")
        self.assertEqual(len(revisions), 1)
        restored = document_safety.restore_revision(
            "restore.md", revisions[0]["id"], vault_md.read("restore.md")["hash"]
        )
        self.assertEqual(restored["hash"], opened["hash"])
        self.assertEqual((vault_md.vault_dir() / "restore.md").read_bytes(), b"owner source\r\n")

    def test_append_does_not_overwrite_a_write_that_arrives_after_its_read(self):
        vault_md.write("append-race.md", "opened source")
        original_read = vault_md.read

        def concurrent_read(path):
            value = original_read(path)
            vault_md.write(path, "concurrent owner source")
            return value

        with patch.object(vault_md, "read", side_effect=concurrent_read):
            result = self.ex("note_append", {"path": "append-race.md", "content": "addition"})
        self.assertTrue(result.get("error"), result)
        self.assertEqual(vault_md.read("append-race.md")["content"], "concurrent owner source")

    def test_invalid_encoding_is_not_reported_as_an_empty_readable_note(self):
        (vault_md.vault_dir() / "binary.md").write_bytes(b"owner bytes\xff\xfe")
        result = self.ex("docs_read", {"path": "binary.md"})
        self.assertTrue(result.get("error"), result)
        self.assertIn("UTF-8", result["output"])

    def test_document_approval_previews_exact_changes_without_writing(self):
        opened = vault_md.write("preview.md", "old line\n")
        for tool in ("docs_write", "note_write"):
            diff = at.preview_change(
                tool,
                {"path": "preview.md", "content": "new line\n", "expected_hash": opened["hash"]},
            )
            self.assertIn("-old line", diff)
            self.assertIn("+new line", diff)
            self.assertEqual(vault_md.read("preview.md")["hash"], opened["hash"])

    def test_docs_read_and_write_preview_do_not_substitute_a_matching_basename(self):
        vault_md.write("nested/idea.md", "private nested source\n")
        read = self.ex("docs_read", {"path": "idea"})
        self.assertTrue(read.get("error"), read)
        self.assertNotIn("private nested source", read["output"])
        preview = at.preview_change("docs_write", {"path": "idea", "content": "new root source\n"})
        self.assertNotIn("private nested source", preview)
        self.assertIn("+new root source", preview)
        legacy = self.ex("note_read", {"name": "idea"})
        self.assertIn("private nested source", legacy["output"])

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
        self.assertIn("docs_write", names)
        self.assertIn("docs_read", names)
        self.assertIn("docs_search", names)
        self.assertIn("note_append", names)
        self.assertIn("note_backlinks", names)
        self.assertIn("docs_write", at.MUTATING_TOOLS)
        self.assertIn("note_append", at.MUTATING_TOOLS)
        self.assertNotIn("note_backlinks", at.MUTATING_TOOLS)  # read-only

    def test_plan_mode_hides_append_keeps_backlinks(self):
        plan = {
            t["function"]["name"] for t in at.build_tool_defs({"agent_permission_mode": "plan"})
        }
        self.assertNotIn("note_append", plan)  # mutating → hidden
        self.assertIn("note_backlinks", plan)  # read → stays

    # ── safety: traversal paths return a clean error, not an uncaught crash ──────
    def test_traversal_path_returns_error(self):
        cases = [
            ("note_read", {"name": "../../escape"}),
            ("note_write", {"path": "../../escape", "content": "x"}),
            ("note_append", {"path": "../../escape", "content": "x"}),
        ]
        for tool, args in cases:
            r = self.ex(tool, args)
            self.assertTrue(r.get("error"), f"{tool} should error on a traversal path")
        # nothing escaped the vault
        self.assertFalse((vault_md.vault_dir().parent / "escape.md").exists())
