"""ui-2a/2b/2c — research & docs-ask send on a fresh session, render into their own boxes, and
never sit blank. Source-contract level; behavior is exercised in pw_aide_2.py with mocked network."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = (ROOT / "static" / "js" / "research.js").read_text(encoding="utf-8")
RAG = (ROOT / "static" / "js" / "ragquery.js").read_text(encoding="utf-8")
SESS = (ROOT / "static" / "js" / "sessions.js").read_text(encoding="utf-8")


class SessionCreationTests(unittest.TestCase):
    def test_sessions_exports_ensure(self):
        self.assertIn("export async function ensureSession", SESS)

    def test_research_creates_session(self):
        self.assertIn("await ensureSession()", RESEARCH)
        self.assertNotIn("const sid = getActiveId()", RESEARCH)

    def test_docs_creates_session(self):
        self.assertIn("await ensureSession()", RAG)
        self.assertNotIn("const sid = getActiveId()", RAG)


class PerQueryScopingTests(unittest.TestCase):
    def test_docs_uses_scoped_nodes_not_shared_ids(self):
        # no more shared ids that the 2nd answer would clobber
        self.assertNotIn('id="docs-ans"', RAG)
        self.assertIn("row.querySelector('.rag-ans')", RAG)

    def test_research_uses_scoped_nodes_not_shared_ids(self):
        self.assertNotIn("getElementById('research-steps')", RESEARCH)
        self.assertNotIn("getElementById('research-report')", RESEARCH)
        self.assertIn("resRow.querySelector('.rs-report')", RESEARCH)


class WaitingStateTests(unittest.TestCase):
    def test_research_has_warming_line(self):
        self.assertIn("rs-warming", RESEARCH)
        self.assertIn("searching the web", RESEARCH)

    def test_research_clears_warming_on_first_event(self):
        self.assertIn("clearWarming()", RESEARCH)

    def test_research_handles_empty_result(self):
        self.assertIn("no results", RESEARCH)


if __name__ == "__main__":
    unittest.main()
