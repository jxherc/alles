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


class _WaitStop:
    def __init__(self):
        self.event = asyncio.Event()

    def is_set(self):
        return self.event.is_set()

    async def wait(self):
        await self.event.wait()


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
                    # This helper exercises the runtime without a database-backed
                    # chat session. Keep the delegated-action scope unbound too.
                    session_id="",
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


class KeepStreamedOutputTests(unittest.TestCase):
    def test_interrupted_stream_keeps_partial(self):
        # result never arrived (stopped) -> fall back to the streamed buffer
        r = ar._keep_streamed_output({"output": "", "error": False}, "partial shell output")
        self.assertEqual(r["output"], "partial shell output")

    def test_real_result_wins(self):
        # a result that carries output is authoritative — don't clobber it with the buffer
        r = ar._keep_streamed_output({"output": "final", "error": False}, "streamed tail")
        self.assertEqual(r["output"], "final")

    def test_no_output_either_way(self):
        r = ar._keep_streamed_output({"output": "", "error": False}, "")
        self.assertEqual(r["output"], "")


class AgentSystemNoteSecurityTests(unittest.TestCase):
    def test_full_access_does_not_promise_shell_secret_confinement(self):
        note = ar.agent_system_note(
            {
                "agent_context_files": False,
                "agent_subagents": False,
                "agent_permission_mode": "full_access",
            }
        )

        self.assertIn("an unsandboxed shell has the same host access as Alles", note)
        self.assertIn("never read credential stores unless the owner explicitly asked", note)

    def test_detached_auto_reports_that_approval_actions_are_unavailable(self):
        note = ar.agent_system_note(
            {
                "agent_context_files": False,
                "agent_subagents": False,
                "agent_permission_mode": "full_auto",
                "agent_detached": True,
            }
        )

        self.assertIn("DETACHED AUTO MODE", note)
        self.assertIn("require owner approval are unavailable", note)

    def test_detached_auto_rejects_approval_action_without_waiting(self):
        shell_call = {
            "call_id": "c1",
            "name": "shell",
            "args": {"command": "pwd"},
        }
        with mock.patch.object(ar, "_await_permission") as await_permission:
            _, _, chunks = _drive(
                [
                    [{"tool_call": shell_call}, {"done": True, "usage": {}}],
                    [{"done": True, "usage": {}}],
                ],
                {
                    "agent_permission_mode": "full_auto",
                    "agent_detached": True,
                },
            )

        await_permission.assert_not_called()
        self.assertFalse(any("tool_permission" in chunk for chunk in chunks))
        outputs = [chunk["tool_result"]["output"] for chunk in chunks if "tool_result" in chunk]
        self.assertTrue(any("approval unavailable in detached run" in output for output in outputs))


class SelectableQuestionRuntimeTests(unittest.TestCase):
    def test_question_pauses_then_returns_structured_answer_to_model(self):
        call = {
            "call_id": "q1",
            "name": "ask_user",
            "args": {
                "questions": [
                    {
                        "id": "scope",
                        "prompt": "Which surface?",
                        "choices": [
                            {"id": "files", "label": "Files"},
                            {"id": "aide", "label": "Aide"},
                        ],
                    }
                ]
            },
        }
        fake, state = _make_fake(
            [[{"tool_call": call}, {"done": True}], [{"delta": "continuing"}, {"done": True}]]
        )
        endpoint = SimpleNamespace(base_url="http://x/", api_key="k")

        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(agent_state, "DATA_DIR", Path(directory)),
                mock.patch.object(ar, "stream_chat", fake),
            ):

                async def go():
                    chunks = []
                    async for chunk in ar.run_agent(
                        [{"role": "user", "content": "ask me"}],
                        endpoint,
                        "m",
                        _WaitStop(),
                        {"agent_context_files": False},
                        [],
                        [],
                        [],
                        session_id="session-1",
                    ):
                        chunks.append(chunk)
                        if chunk.get("user_question"):
                            request_id = chunk["user_question"]["id"]
                            self.assertTrue(
                                ar.resolve_user_question(
                                    request_id,
                                    {
                                        "answers": {
                                            "scope": {"selected": ["files"], "free_text": ""}
                                        }
                                    },
                                )
                            )
                    return chunks

                chunks = asyncio.run(go())

        self.assertEqual(state["n"], 2)
        resolved = next(chunk["user_question_resolved"] for chunk in chunks if chunk.get("user_question_resolved"))
        self.assertEqual(resolved["answer"]["answers"]["scope"]["selected"], ["files"])
        result = next(chunk["tool_result"] for chunk in chunks if chunk.get("tool_result"))
        self.assertFalse(result["error"])
        self.assertIn('"files"', result["output"])
        self.assertTrue(any(chunk.get("delta") == "continuing" for chunk in chunks))


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
        tc = {"call_id": "c1", "name": "list_files", "args": {"path": ".", "depth": 1}}
        status, _, _ = _drive([[{"tool_call": tc}, {"done": True}], [{"error": "HTTP 400: bad"}]])
        self.assertEqual(status, "stopped")  # work landed → interrupted, not a clean failure

    def test_immediate_unrecoverable_with_no_work_is_error(self):
        status, calls, _ = _drive([[{"error": "HTTP 400: bad"}]])  # non-retryable, nothing done
        self.assertEqual(status, "error")
        self.assertEqual(calls, 1)  # no pointless retry on a 4xx

    def test_transient_error_after_thinking_still_retries(self):
        # reasoning models stream thinking BEFORE any answer/tool-call; a transient blip
        # during the thinking phase must still retry — thinking is throwaway, not real output
        status, calls, _ = _drive(
            [
                [{"thinking": "let me reason "}, {"error": ""}],  # blip mid-thought
                [{"done": True, "usage": {}}],  # retry succeeds
            ]
        )
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
    def test_subagent_turn_cap_limits_effort_turns(self):
        self.assertEqual(ar._agent_max_turns({"agent_effort": "max", "_agent_turn_cap": 10}), 10)
        self.assertEqual(ar._agent_max_turns({"agent_effort": "high", "_agent_turn_cap": 4}), 4)

    def test_deep_work_and_custom_turn_bounds(self):
        self.assertEqual(ar._agent_max_turns({"agent_effort": "deep_work"}), 48)
        self.assertEqual(
            ar._agent_max_turns(
                {"agent_effort": "custom", "agent_custom_effort": {"max_turns": 999}}
            ),
            64,
        )
        self.assertEqual(
            ar._agent_max_turns(
                {"agent_effort": "custom", "agent_custom_effort": {"max_turns": 0}}
            ),
            1,
        )

    def test_local_profiles_map_to_supported_provider_efforts(self):
        self.assertEqual(ar.provider_effort({"agent_effort": "deep_work"}), "high")
        self.assertEqual(
            ar.provider_effort(
                {
                    "agent_effort": "custom",
                    "agent_custom_effort": {"verification": "quick"},
                }
            ),
            "low",
        )
        self.assertEqual(
            ar.provider_effort(
                {
                    "agent_effort": "custom",
                    "agent_custom_effort": {"verification": "thorough"},
                }
            ),
            "high",
        )

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

    def test_custom_profile_controls_verification_and_delegation_copy(self):
        note = ar.agent_system_note(
            {
                "agent_effort": "custom",
                "agent_custom_effort": {
                    "max_turns": 32,
                    "verification": "thorough",
                    "delegation": "off",
                    "workflows": "auto",
                },
                "agent_subagents": False,
            }
        )
        self.assertIn("VERIFICATION: thorough", note)
        self.assertIn("Delegation is disabled", note)


if __name__ == "__main__":
    unittest.main()
