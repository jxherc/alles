import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import agent_state as ast


class AgentStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(ast, "DATA_DIR", Path(self.tmp.name))
        self._p.start()
        ast._active.clear()

    def tearDown(self):
        ast._active.clear()
        self._p.stop()
        self.tmp.cleanup()

    def test_start_persists_and_get(self):
        r = ast.start_run("sess1", "deepseek-v4-pro", max_turns=24)
        self.assertEqual(r["status"], "running")
        self.assertTrue((Path(self.tmp.name) / f"{r['id']}.json").exists())
        self.assertEqual(ast.get_run(r["id"])["session_id"], "sess1")

    def test_events_and_finish(self):
        r = ast.start_run("s", "m", 10)
        ast.record_event(r["id"], "tool_call", {"name": "read_file"})
        ast.finish_run(r["id"], "done")
        got = ast.get_run(r["id"])
        self.assertEqual(got["status"], "done")
        self.assertEqual(got["events"][-1]["type"], "tool_call")
        self.assertIsNotNone(got["finished_at"])

    def test_reconcile_marks_zombie_running_as_interrupted(self):
        r = ast.start_run("s", "m", 10)        # status running, saved to disk
        ast._active.clear()                    # simulate a process restart (memory lost, disk kept)
        n = ast.reconcile_interrupted()
        self.assertEqual(n, 1)
        self.assertEqual(ast.get_run(r["id"])["status"], "interrupted")
        # a finished run is left alone
        r2 = ast.start_run("s2", "m", 10); ast.finish_run(r2["id"], "done"); ast._active.clear()
        self.assertEqual(ast.reconcile_interrupted(), 0)

    def test_list_incomplete(self):
        a = ast.start_run("s", "m", 10)
        b = ast.start_run("s", "m", 10); ast.finish_run(b["id"], "done")
        ast._active.clear()
        ast.reconcile_interrupted()
        incomplete = [x["id"] for x in ast.list_incomplete()]
        self.assertIn(a["id"], incomplete)
        self.assertNotIn(b["id"], incomplete)


if __name__ == "__main__":
    unittest.main()
