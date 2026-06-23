import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import agent_runtime as ar
from services import agent_state


class _Stop:
    def is_set(self):
        return False


def _make_fake(behaviors):
    """fake stream_chat that yields a scripted chunk list per successive call."""
    state = {"n": 0}

    async def fake(messages, base_url, api_key, model, **kw):
        i = state["n"]
        state["n"] += 1
        for ch in behaviors[i] if i < len(behaviors) else behaviors[-1]:
            yield ch

    return fake, state


def _drive(behaviors, settings=None):
    fake, state = _make_fake(behaviors)
    ep = SimpleNamespace(base_url="http://x/", api_key="k")
    s = {"agent_context_files": False}
    if settings:
        s.update(settings)
    with tempfile.TemporaryDirectory() as d:
        with (
            mock.patch.object(agent_state, "DATA_DIR", Path(d)),
            mock.patch.object(ar, "stream_chat", fake),
            mock.patch.object(ar, "LLM_RETRY_BASE", 0),
        ):

            async def go():
                chunks = []
                async for ch in ar.run_agent(
                    [{"role": "user", "content": "hi"}],
                    ep,
                    "m",
                    _Stop(),
                    s,
                    [],
                    [],
                    [],
                    session_id="s",
                ):
                    chunks.append(ch)
                return chunks

            chunks = asyncio.run(go())
            rid = next(c["agent_run"]["id"] for c in chunks if "agent_run" in c)
            status = agent_state.get_run(rid)["status"]
    return status, state["n"], chunks


class FillUnansweredToolsTests(unittest.TestCase):
    def test_stub_for_unanswered_call(self):
        # 2 tool_calls, only the first got a result (stop interrupted the batch) -> the
        # second must get a stub tool message so the history stays valid for a resume
        msgs = [{"role": "assistant", "tool_calls": [{"call_id": "c1"}, {"call_id": "c2"}]}]
        ar._fill_unanswered_tools(msgs, [{"call_id": "c1"}, {"call_id": "c2"}], 0, {"c1"})
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_msgs], ["c2"])
        self.assertEqual(tool_msgs[0]["content"], "[interrupted]")

    def test_nothing_added_when_all_answered(self):
        msgs = []
        ar._fill_unanswered_tools(msgs, [{"call_id": "c1"}], 0, {"c1"})
        self.assertEqual(msgs, [])

    def test_synthetic_call_id_matches_loop(self):
        # a call with no call_id uses the same f"tool-{turn}-{ci}" id the run loop assigns
        msgs = []
        ar._fill_unanswered_tools(msgs, [{}, {}], 3, set())
        self.assertEqual([m["tool_call_id"] for m in msgs], ["tool-3-0", "tool-3-1"])


class LlmResilienceTests(unittest.TestCase):
    def test_retryable_classification(self):
        self.assertTrue(ar._retryable(""))  # empty/transient
        self.assertTrue(ar._retryable("can't connect to host"))
        self.assertTrue(ar._retryable("HTTP 503: bad gateway"))
        self.assertTrue(ar._retryable("HTTP 429: rate limited"))
        self.assertFalse(ar._retryable("HTTP 400: bad request"))
        self.assertFalse(ar._retryable("HTTP 401: unauthorized"))

    def test_transient_error_retries_and_recovers(self):
        # 1st call blips (empty error), 2nd succeeds with no tool calls → 'done'
        status, calls, _ = _drive([[{"error": ""}], [{"done": True, "usage": {}}]])
        self.assertEqual(status, "done")
        self.assertEqual(calls, 2)  # it retried instead of aborting

    def test_unrecoverable_after_work_is_stopped_not_error(self):
        tc = {
            "call_id": "c1",
            "name": "todo_update",
            "args": {"items": [{"step": "x", "status": "in_progress"}]},
        }
        status, _, _ = _drive([[{"tool_call": tc}, {"done": True}], [{"error": "HTTP 400: bad"}]])
        self.assertEqual(status, "stopped")  # work landed → interrupted, not a clean failure

    def test_immediate_unrecoverable_with_no_work_is_error(self):
        status, calls, _ = _drive([[{"error": "HTTP 400: bad"}]])  # non-retryable, nothing done
        self.assertEqual(status, "error")
        self.assertEqual(calls, 1)  # no pointless retry on a 4xx

    def test_transient_error_after_thinking_still_retries(self):
        # reasoning models stream thinking BEFORE any answer/tool-call; a transient blip
        # during the thinking phase must still retry — thinking is throwaway, not real output
        status, calls, _ = _drive([
            [{"thinking": "let me reason "}, {"error": ""}],  # blip mid-thought
            [{"done": True, "usage": {}}],                    # retry succeeds
        ])
        self.assertEqual(status, "done")
        self.assertEqual(calls, 2)  # retried despite the earlier thinking chunk


class CapToolContentTests(unittest.TestCase):
    def test_large_output_stays_valid_json(self):
        tc = {"output": "Z" * 50000, "error": False}
        content = ar._cap_tool_content(tc)
        # the old bug: sliced the json string + tacked on `"}` → unparseable
        parsed = json.loads(content)  # must not raise
        self.assertFalse(parsed["error"])
        self.assertIn("truncated for context", parsed["output"])
        self.assertLess(len(content), 20000)
        # head AND tail of the original are preserved
        self.assertTrue(parsed["output"].startswith("Z"))
        self.assertTrue(parsed["output"].rstrip().endswith("Z"))

    def test_small_output_untouched(self):
        tc = {"output": "hello", "error": False}
        self.assertEqual(json.loads(ar._cap_tool_content(tc)), tc)

    def test_hist_chars_counts_image_urls(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hi"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + "A" * 5000},
                    },
                ],
            }
        ]
        self.assertGreaterEqual(ar._hist_chars(msgs), 5000)


class TrimHistoryTests(unittest.TestCase):
    def _convo(self, n, size):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(n):
            msgs.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"call_id": f"c{i}", "name": "shell", "args": {}}],
                }
            )
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "X" * size})
        return msgs

    def test_preserves_structure_and_bounds(self):
        msgs = self._convo(20, 10000)
        before = len(msgs)
        ar._trim_history(msgs, budget=50000, keep_recent=4)
        # never removes messages (assistant<->tool pairing must stay valid)
        self.assertEqual(len(msgs), before)
        total = sum(len(m["content"]) for m in msgs if isinstance(m.get("content"), str))
        self.assertLessEqual(total, 70000)
        # system + most recent tool output untouched
        self.assertEqual(msgs[0]["content"], "sys")
        self.assertEqual(len(msgs[-1]["content"]), 10000)

    def test_under_budget_is_noop(self):
        msgs = self._convo(2, 100)
        snapshot = [m["content"] for m in msgs]
        ar._trim_history(msgs, budget=100000)
        self.assertEqual([m["content"] for m in msgs], snapshot)


class EffortTurnsTests(unittest.TestCase):
    def test_system_note_mentions_effort(self):
        note_low = ar.agent_system_note({"agent_effort": "low"})
        note_high = ar.agent_system_note({"agent_effort": "high"})
        self.assertIn("EFFORT: low", note_low)
        self.assertIn("EFFORT: high", note_high)

    def test_effort_guides_tool_selection(self):
        # claude-code-style: low effort biases to glob/grep, high maps structure first
        self.assertIn("glob/grep", ar.agent_system_note({"agent_effort": "low"}))
        self.assertIn("code_symbols", ar.agent_system_note({"agent_effort": "high"}))

    def test_note_has_file_creation_discipline(self):
        note = ar.agent_system_note({})
        self.assertIn("never create docs/README/boilerplate unless asked", note)


if __name__ == "__main__":
    unittest.main()
