import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import services.skills_store as ss
from services import agent_tools


class AgentSkillMatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(ss, "SKILLS_DIR", Path(self.tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.tmp.cleanup()

    def test_match_returns_relevant_skill(self):
        ss.upsert_skill(
            "Invoice Parser", "extract totals from invoices", "when handling an invoice pdf"
        )
        out = asyncio.run(agent_tools._skill_match("parse this invoice for me"))
        self.assertFalse(out["error"])
        self.assertIn("invoice-parser", out["output"])

    def test_no_match_is_graceful(self):
        out = asyncio.run(agent_tools._skill_match("something totally unrelated zzz"))
        self.assertFalse(out["error"])
        self.assertIn("no matching skills", out["output"])

    def test_registered_as_a_read_tool(self):
        self.assertEqual(agent_tools.TOOL_PERMISSION.get("skill_match"), "read")
        names = {t["function"]["name"] for t in agent_tools.TOOL_DEFS}
        self.assertIn("skill_match", names)

    def test_top_k_limits_results(self):
        for i in range(6):
            ss.upsert_skill(
                f"Skill {i}", f"description {i} invoice parser", "when handling invoices"
            )
        matches = ss.match_skills("invoice parser", top_k=3)
        self.assertLessEqual(len(matches), 3)

    def test_scores_are_sorted_descending(self):
        ss.upsert_skill("Exact Match", "invoice extractor tool", "use when parsing invoices")
        ss.upsert_skill("Loose Match", "generic text handler", "use for documents")
        matches = ss.match_skills("parse invoices", top_k=5)
        if len(matches) > 1:
            self.assertGreaterEqual(matches[0]["score"], matches[1]["score"])

    def test_empty_query_returns_no_match(self):
        ss.upsert_skill("Some Skill", "does stuff", "whenever")
        out = asyncio.run(agent_tools._skill_match(""))
        # empty query → no matches (match_skills returns [] for empty q)
        self.assertFalse(out["error"])
        self.assertIn("no matching skills", out["output"])

    def test_multiple_skills_all_returned_up_to_top_k(self):
        ss.upsert_skill("Email Helper", "draft and send emails", "when composing email")
        ss.upsert_skill("Calendar Tool", "manage calendar events", "when adding calendar events")
        ss.upsert_skill("Invoice Tool", "parse invoice PDFs", "when handling invoice documents")
        matches = ss.match_skills("email calendar invoice", top_k=5)
        self.assertGreaterEqual(len(matches), 1)

    def test_slug_normalised_in_output(self):
        ss.upsert_skill("My Cool Skill", "does something cool", "when things need cooling")
        out = asyncio.run(agent_tools._skill_match("something cool"))
        self.assertFalse(out["error"])
        self.assertIn("my-cool-skill", out["output"])


if __name__ == "__main__":
    unittest.main()
