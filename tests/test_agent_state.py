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
        ast._clear_disk_active_cache()

    def tearDown(self):
        ast._active.clear()
        ast._clear_disk_active_cache()
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
        r = ast.start_run("s", "m", 10)  # status running, saved to disk
        ast._active.clear()  # simulate a process restart (memory lost, disk kept)
        n = ast.reconcile_interrupted()
        self.assertEqual(n, 1)
        self.assertEqual(ast.get_run(r["id"])["status"], "interrupted")
        # a finished run is left alone
        r2 = ast.start_run("s2", "m", 10)
        ast.finish_run(r2["id"], "done")
        ast._active.clear()
        self.assertEqual(ast.reconcile_interrupted(), 0)

    def test_list_incomplete(self):
        a = ast.start_run("s", "m", 10)
        b = ast.start_run("s", "m", 10)
        ast.finish_run(b["id"], "done")
        ast._active.clear()
        ast.reconcile_interrupted()
        incomplete = [x["id"] for x in ast.list_incomplete()]
        self.assertIn(a["id"], incomplete)
        self.assertNotIn(b["id"], incomplete)

    def test_update_run_patches_fields(self):
        r = ast.start_run("s", "m", 10)
        ast.update_run(r["id"], turn=3, text="hello")
        got = ast.get_run(r["id"])
        self.assertEqual(got["turn"], 3)
        self.assertEqual(got["text"], "hello")

    def test_get_run_nonexistent_returns_none(self):
        self.assertIsNone(ast.get_run("does-not-exist"))

    def test_add_checkpoint_stored(self):
        r = ast.start_run("s", "m", 10)
        ast.add_checkpoint(r["id"], {"path": "/tmp/foo.py", "original": "x = 1"})
        got = ast.get_run(r["id"])
        self.assertEqual(len(got["checkpoints"]), 1)
        self.assertEqual(got["checkpoints"][0]["path"], "/tmp/foo.py")

    def test_find_active_run_by_session(self):
        r = ast.start_run("sess-abc", "m", 10)
        found = ast.find_active_run("sess-abc")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], r["id"])

    def test_find_active_run_unknown_session_none(self):
        self.assertIsNone(ast.find_active_run("no-such-session"))

    def test_find_active_run_disk_fallback_is_cached(self):
        r = ast.start_run("sess-disk", "m", 10)
        ast._active.clear()
        with mock.patch.object(ast, "list_runs", wraps=ast.list_runs) as lr:
            self.assertEqual(ast.find_active_run("sess-disk")["id"], r["id"])
            self.assertEqual(ast.find_active_run("sess-disk")["id"], r["id"])
        self.assertEqual(lr.call_count, 1)

    def test_find_active_run_cache_clears_on_save(self):
        r = ast.start_run("sess-disk", "m", 10)
        ast._active.clear()
        self.assertEqual(ast.find_active_run("sess-disk")["id"], r["id"])
        ast.finish_run(r["id"], "done")
        self.assertIsNone(ast.find_active_run("sess-disk"))

    def test_run_sources_extracts_files_and_searches(self):
        r = ast.start_run("s", "m", 10)
        ast.record_event(
            r["id"],
            "tool_result",
            {"error": False, "name": "read_file", "args": {"path": "/tmp/a.py"}},
        )
        ast.record_event(
            r["id"],
            "tool_result",
            {"error": False, "name": "web_search", "args": {"query": "python asyncio"}},
        )
        ast.record_event(
            r["id"],
            "tool_result",
            {"error": False, "name": "write_file", "args": {"path": "/tmp/b.py"}},
        )
        src = ast.run_sources(r["id"])
        self.assertIn("/tmp/a.py", src["files"])
        self.assertIn("/tmp/b.py", src["files"])
        self.assertIn("python asyncio", src["searches"])

    def test_finish_run_removes_from_active(self):
        r = ast.start_run("s", "m", 10)
        self.assertIn(r["id"], ast._active)
        ast.finish_run(r["id"], "done")
        self.assertNotIn(r["id"], ast._active)


if __name__ == "__main__":
    unittest.main()


class IncognitoRunStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(ast, "DATA_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        ast._active.clear()
        ast._clear_disk_active_cache()
        self.addCleanup(ast._active.clear)
        self.addCleanup(ast._clear_disk_active_cache)
        from services import incognito

        self.private_sessions = incognito
        incognito.clear_for_tests()
        self.addCleanup(incognito.clear_for_tests)
        self.session = incognito.create_session()

    def test_private_lifecycle_is_queryable_but_never_writes_run_content(self):
        run = ast.start_run(self.session.id, "fixture", 4, incognito=True)
        ast.update_run(run["id"], intent="private synthetic prompt", text="partial reply")
        ast.record_event(run["id"], "tool_start", {"name": "fixture", "args": "private"})
        ast.add_checkpoint(run["id"], {"original": "private synthetic content"})
        self.assertEqual(ast.find_active_run(self.session.id)["id"], run["id"])
        self.assertIn(run["id"], [row["id"] for row in ast.list_runs()])
        ast.finish_run(run["id"], "cancelled")
        self.assertEqual(ast.get_run(run["id"])["text"], "partial reply")
        self.assertIsNone(ast.find_active_run(self.session.id))
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])

    def test_exit_purges_running_and_finished_private_runs(self):
        running = ast.start_run(self.session.id, "fixture", 4, incognito=True)
        finished = ast.start_run(self.session.id, "fixture", 4, incognito=True)
        ast.finish_run(finished["id"])
        self.assertTrue(self.private_sessions.delete_session(self.session.id))
        for run in [running, finished]:
            self.assertIsNone(ast.get_run(run["id"]))
            self.assertNotIn(run["id"], ast._active)
            self.assertNotIn(run["id"], ast._private)
            ast.update_run(run["id"], text="late provider reply")
            ast.finish_run(run["id"], "cancelled")
        self.assertEqual(ast.list_runs(), [])
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])

    def test_expiry_purges_private_runs_without_public_poll_extending_ttl(self):
        from datetime import UTC, datetime, timedelta

        run = ast.start_run(self.session.id, "fixture", 4, incognito=True)
        expires = self.session.expires_at
        ast.list_runs()
        ast.get_run(run["id"])
        self.assertEqual(self.session.expires_at, expires)
        self.session.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        self.assertIsNone(ast.find_active_run(self.session.id))
        self.assertIsNone(ast.get_run(run["id"]))
        self.assertEqual(ast.list_runs(), [])
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])

    def test_late_private_start_after_exit_creates_no_orphan(self):
        self.private_sessions.delete_session(self.session.id)
        run = ast.start_run(self.session.id, "fixture", 4, incognito=True)
        self.assertIsNone(ast.get_run(run["id"]))
        self.assertNotIn(run["id"], ast._active)
        self.assertEqual(ast.list_runs(), [])
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])

    def test_private_finish_and_delete_preserve_public_run(self):
        public = ast.start_run("ordinary-session", "fixture", 4)
        private = ast.start_run(self.session.id, "fixture", 4, incognito=True)
        ast.finish_run(private["id"])
        self.private_sessions.delete_session(self.session.id)
        self.assertEqual(ast.find_active_run("ordinary-session")["id"], public["id"])
        self.assertEqual([row["id"] for row in ast.list_runs()], [public["id"]])
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.json"))), 1)
