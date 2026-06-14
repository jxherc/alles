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
        ss.upsert_skill("Invoice Parser", "extract totals from invoices", "when handling an invoice pdf")
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


if __name__ == "__main__":
    unittest.main()
