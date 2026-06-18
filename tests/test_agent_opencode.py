import asyncio
import unittest
from pathlib import Path
from unittest import mock

from services.agent_intents import message_needs_tools
from services import agent_tools as at
from services.agent_runtime import _trim_history, _hist_chars


class IntentTests(unittest.TestCase):
    NEEDS = [
        "add lunch to my calendar friday at 1pm",
        "can you schedule a meeting tomorrow",
        "remind me to call mom",
        "please send an email to bob about the invoice",
        "research the history of the roman aqueducts",
        "fix the bug in the login function",
        "run npm install in the project",
        "open my notes",
    ]
    PLAIN = [
        "what does the grep command do?",
        "how does the calendar feature work?",
        "hello, how are you today",
        "explain what an aqueduct is",
        "i think email is overrated",
    ]

    def test_action_messages_promote(self):
        for t in self.NEEDS:
            self.assertTrue(message_needs_tools(t), t)

    def test_plain_messages_stay(self):
        for t in self.PLAIN:
            self.assertFalse(message_needs_tools(t), t)

    def test_empty(self):
        self.assertFalse(message_needs_tools(""))
        self.assertFalse(message_needs_tools(None))


class PathConfinementTests(unittest.TestCase):
    def test_secret_paths_flagged(self):
        for p in (
            "/home/x/.ssh/id_rsa",
            r"C:\Users\x\.aws\credentials",
            "/srv/app/.env",
            "/etc/ssl/server.pem",
            "/home/x/.netrc",
            "/home/x/id_ed25519",
        ):
            self.assertTrue(at._is_secret_path(p), p)

    def test_normal_paths_ok(self):
        for p in (
            "/home/x/project/main.py",
            r"C:\code\alles\app.py",
            "/tmp/output.txt",
            "notes/todo.md",
        ):
            self.assertFalse(at._is_secret_path(p), p)

    def test_guard_blocks_secret_by_default(self):
        with mock.patch.object(at, "_settings", lambda: {}):
            self.assertIsNotNone(at._guard_path(Path.home() / ".ssh" / "id_rsa"))

    def test_guard_allows_secret_with_override(self):
        with mock.patch.object(at, "_settings", lambda: {"agent_allow_secrets": True}):
            self.assertIsNone(at._guard_path(Path.home() / ".ssh" / "id_rsa"))

    def test_read_file_blocks_secret(self):
        with mock.patch.object(at, "_settings", lambda: {}):
            res = asyncio.run(at._read_file(str(Path.home() / ".ssh" / "id_rsa")))
        self.assertTrue(res["error"])
        self.assertIn("blocked", res["output"])

    def test_workspace_confine_blocks_outside_writes(self):
        with mock.patch.object(at, "_settings", lambda: {"agent_confine_workspace": True}):
            outside = Path.home() / "definitely_outside_workspace_xyz.txt"
            inside = at.ROOT / "scratch_test_file.txt"
            self.assertIsNotNone(at._guard_path(outside, write=True))
            self.assertIsNone(at._guard_path(inside, write=True))


class CompactionTests(unittest.TestCase):
    def _mk(self, n, size):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(n):
            msgs.append(
                {
                    "role": "assistant",
                    "content": f"turn {i}",
                    "tool_calls": [{"call_id": str(i), "name": "x", "args": {}}],
                }
            )
            msgs.append({"role": "tool", "tool_call_id": str(i), "content": "D" * size})
        return msgs

    def test_under_budget_untouched(self):
        m = self._mk(3, 100)
        before = [x["content"] for x in m]
        _trim_history(m, budget=10**9)
        self.assertEqual([x["content"] for x in m], before)

    def test_over_budget_trims_keeps_recent_and_pairing(self):
        m = self._mk(40, 5000)  # ~400k chars, way over budget
        n_before = len(m)
        recent_before = [x["content"] for x in m[-8:]]
        _trim_history(m, budget=120000, keep_recent=8)
        self.assertLessEqual(_hist_chars(m), 120000)  # got under budget
        self.assertEqual(len(m), n_before)  # pairing-safe: nothing removed
        self.assertEqual([x["content"] for x in m[-8:]], recent_before)  # recent turns intact
        self.assertEqual(m[0]["content"], "sys")  # system intact


class ReplayTests(unittest.TestCase):
    def test_find_active_run(self):
        from services import agent_state as st

        run = st.start_run(session_id="sess-xyz-test", model="m", max_turns=3)
        try:
            self.assertEqual(st.find_active_run("sess-xyz-test")["id"], run["id"])
            self.assertIsNone(st.find_active_run("other-session"))
            st.finish_run(run["id"])
            self.assertIsNone(st.find_active_run("sess-xyz-test"))  # done != active
        finally:
            st._path(run["id"]).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
