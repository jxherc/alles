import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import agent_state
from tests._client import ApiTest


class _Stop:
    def is_set(self):
        return False


class AgentStateTextTests(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp(prefix="bgstate-")
        self.p = mock.patch.object(agent_state, "DATA_DIR", Path(self._d))
        self.p.start()
        agent_state._active.clear()

    def tearDown(self):
        self.p.stop()
        agent_state._active.clear()

    def test_start_run_has_text_field(self):
        r = agent_state.start_run("s1", "m", 6)
        self.assertIn("text", r)
        self.assertEqual(r["text"], "")

    def test_update_run_text_persists(self):
        r = agent_state.start_run("s1", "m", 6)
        agent_state.update_run(r["id"], text="hello world")
        agent_state._active.clear()  # force a disk read
        self.assertEqual(agent_state.get_run(r["id"])["text"], "hello world")

    def test_active_running_then_empty(self):
        r = agent_state.start_run("sess-x", "m", 6)
        self.assertEqual(agent_state.find_active_run("sess-x")["id"], r["id"])
        agent_state.finish_run(r["id"], "done")
        self.assertIsNone(agent_state.find_active_run("sess-x"))

    def test_record_event_patch_persists_and_writes_once(self):
        r = agent_state.start_run("s1", "m", 6)
        steps = [{"name": "shell", "output": "ok"}]
        # the event AND the patched field both persist
        agent_state.record_event(r["id"], "tool_result", {"x": 1}, tool_steps=steps)
        agent_state._active.clear()  # force a disk read
        got = agent_state.get_run(r["id"])
        self.assertEqual(got["tool_steps"], steps)
        self.assertEqual(got["events"][-1]["type"], "tool_result")
        # and it's a single file write (was record_event + update_run = two before)
        with mock.patch.object(agent_state, "_save") as save:
            agent_state.record_event(r["id"], "tool_result", {}, tool_steps=steps)
            self.assertEqual(save.call_count, 1)


class RuntimeTextPersistTests(unittest.TestCase):
    def test_run_persists_text_incrementally(self):
        from services import agent_runtime as ar

        async def fake(messages, base_url, api_key, model, **kw):
            for ch in [{"delta": "hello "}, {"delta": "world"}, {"done": True, "usage": {}}]:
                yield ch

        ep = SimpleNamespace(base_url="http://x/", api_key="k")
        with tempfile.TemporaryDirectory() as d:
            with (
                mock.patch.object(agent_state, "DATA_DIR", Path(d)),
                mock.patch.object(ar, "stream_chat", fake),
                mock.patch.object(ar, "LLM_RETRY_BASE", 0),
            ):
                agent_state._active.clear()

                async def go():
                    rid = None
                    async for ch in ar.run_agent(
                        [{"role": "user", "content": "hi"}],
                        ep,
                        "m",
                        _Stop(),
                        {"agent_context_files": False},
                        [],
                        [],
                        [],
                        session_id="s",
                    ):
                        if "agent_run" in ch:
                            rid = ch["agent_run"]["id"]
                    return rid

                rid = asyncio.run(go())
                agent_state._active.clear()
                self.assertIn("hello world", agent_state.get_run(rid)["text"])


class EventsTailTests(ApiTest):
    def setUp(self):
        super().setUp()
        self._d = tempfile.mkdtemp(prefix="bgtail-")
        self.p = mock.patch.object(agent_state, "DATA_DIR", Path(self._d))
        self.p.start()
        agent_state._active.clear()

    def tearDown(self):
        self.p.stop()
        agent_state._active.clear()
        super().tearDown()

    def _seed(self, n=3, session="s1"):
        r = agent_state.start_run(session, "m", 6)
        for i in range(n):
            agent_state.record_event(r["id"], "turn", {"i": i})
        return r["id"]

    def test_events_since_zero_returns_all(self):
        rid = self._seed(3)
        d = self.client.get(f"/api/agent/runs/{rid}/events", params={"since": 0}).json()
        self.assertEqual(len(d["events"]), 3)
        self.assertEqual(d["next"], 3)

    def test_events_since_n_returns_new(self):
        rid = self._seed(3)
        d = self.client.get(f"/api/agent/runs/{rid}/events", params={"since": 2}).json()
        self.assertEqual(len(d["events"]), 1)
        self.assertEqual(d["next"], 3)

    def test_events_cursor_advances(self):
        rid = self._seed(2)
        first = self.client.get(f"/api/agent/runs/{rid}/events", params={"since": 0}).json()["next"]
        agent_state.record_event(rid, "turn", {"i": 99})
        second = self.client.get(f"/api/agent/runs/{rid}/events", params={"since": first}).json()
        self.assertEqual(len(second["events"]), 1)
        self.assertEqual(second["next"], 3)

    def test_events_includes_status_text_done(self):
        rid = self._seed(1)
        agent_state.update_run(rid, text="partial answer")
        agent_state.finish_run(rid, "done")
        d = self.client.get(f"/api/agent/runs/{rid}/events", params={"since": 0}).json()
        self.assertEqual(d["status"], "done")
        self.assertTrue(d["done"])
        self.assertEqual(d["text"], "partial answer")

    def test_events_unknown_404(self):
        self.assertEqual(self.client.get("/api/agent/runs/nope/events").status_code, 404)

    def test_background_requires_session_404(self):
        r = self.client.post("/api/agent/background", json={"session_id": "ghost", "message": "hi"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
