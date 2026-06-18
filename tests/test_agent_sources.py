import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import agent_state as ast


class AgentSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(ast, "DATA_DIR", Path(self.tmp.name))
        self._p.start()
        ast._active.clear()

    def tearDown(self):
        ast._active.clear()
        self._p.stop()
        self.tmp.cleanup()

    def test_extracts_provenance(self):
        r = ast.start_run("s", "m", 10)
        rid = r["id"]
        ast.record_event(rid, "tool_start", {"name": "read_file", "args": {"path": "app.py"}})
        ast.record_event(rid, "tool_start", {"name": "write_file", "args": {"path": "out.txt"}})
        ast.record_event(
            rid, "tool_start", {"name": "web_fetch", "args": {"url": "https://example.com"}}
        )
        ast.record_event(rid, "tool_start", {"name": "web_search", "args": {"query": "fizzbuzz"}})
        ast.record_event(
            rid, "tool_start", {"name": "shell", "args": {"command": "python out.txt"}}
        )
        ast.record_event(
            rid, "tool_start", {"name": "memory_search", "args": {"query": "x"}}
        )  # ignored
        src = ast.run_sources(rid)
        self.assertEqual(src["files"], ["app.py", "out.txt"])
        self.assertEqual(src["urls"], ["https://example.com"])
        self.assertEqual(src["searches"], ["fizzbuzz"])
        self.assertEqual(src["commands"], ["python out.txt"])

    def test_missing_run(self):
        self.assertEqual(ast.run_sources("nope"), {})


class RunsSummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(ast, "DATA_DIR", Path(self.tmp.name))
        self._p.start()
        ast._active.clear()

    def tearDown(self):
        ast._active.clear()
        self._p.stop()
        self.tmp.cleanup()

    def test_summary_strips_heavy_fields_and_counts(self):
        from routes.agent import runs as runs_route

        r = ast.start_run("sess1", "claude-opus-4-8", 12)
        rid = r["id"]
        ast.update_run(
            rid,
            tool_steps=[{"name": "shell"}, {"name": "read_file"}],
            todos=[{"text": "do a", "status": "done"}, {"text": "do b", "status": "pending"}],
            checkpoints=[{"path": "x.py"}],
        )
        ast.record_event(rid, "tool_start", {"name": "read_file", "args": {"path": "x.py"}})
        ast.finish_run(rid, "done")

        full = runs_route(summary=False)
        self.assertIn("events", full[0])  # heavy fields present in full mode

        lite = runs_route(summary=True)[0]
        self.assertNotIn("events", lite)  # stripped
        self.assertNotIn("tool_steps", lite)
        self.assertEqual(lite["steps"], 2)
        self.assertEqual(lite["edits"], 1)
        self.assertEqual(lite["todos_total"], 2)
        self.assertEqual(lite["todos_done"], 1)
        self.assertEqual(lite["todo"], "do a")
        self.assertEqual(lite["status"], "done")
        self.assertEqual(lite["model"], "claude-opus-4-8")


if __name__ == "__main__":
    unittest.main()
