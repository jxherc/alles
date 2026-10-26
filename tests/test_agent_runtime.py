import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import agent_runtime as ar
from services import agent_state
from tests._client import ApiTest


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

        self.assertIn("The shell's writes are sandboxed but its reads are not", note)
        self.assertIn("never read credential stores unless the owner explicitly asked", note)

    def test_the_note_says_what_holds_the_shell_in(self):
        base = {"agent_context_files": False, "agent_subagents": False}
        cases = (
            ("sandbox-exec", "full_auto", "Shell runs in a write sandbox"),
            ("bwrap", "approve", "put temp files under $TMPDIR"),
            ("", "approve", "shown to the owner as unconfined"),
            ("", "full_auto", "shell commands don't run in this mode"),
        )
        for kind, mode, words in cases:
            with self.subTest(kind=kind, mode=mode):
                with mock.patch.object(ar, "shell_confinement", lambda settings=None: kind):
                    note = ar.agent_system_note({**base, "agent_permission_mode": mode})
                self.assertIn(words, note)

    def test_the_note_says_when_the_sandbox_has_no_network(self):
        base = {"agent_context_files": False, "agent_subagents": False}
        for offline in (True, False):
            with (
                self.subTest(offline=offline),
                mock.patch.object(ar, "shell_confinement", lambda settings=None: "bwrap"),
                mock.patch.object(ar, "sandbox_network", lambda: ((6769,), offline)),
            ):
                note = ar.agent_system_note(base)
            self.assertEqual(
                "no network in the sandbox while alles has no password" in note, offline
            )

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
        resolved = next(
            chunk["user_question_resolved"]
            for chunk in chunks
            if chunk.get("user_question_resolved")
        )
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


class FolderBoundaryTests(ApiTest):
    """Every path a tool names stays in the task's folder, in every mode, before any approval."""

    def setUp(self):
        import os

        super().setUp()
        base = tempfile.TemporaryDirectory(prefix="alles-boundary-")
        self.addCleanup(base.cleanup)
        root = Path(os.path.realpath(base.name))
        self.project = root / "project"
        self.outside = root / "outside"
        (self.project / "sub").mkdir(parents=True)
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("outside words")
        (self.project / "inside.txt").write_text("inside words")
        (self.project / "link").symlink_to(self.outside, target_is_directory=True)
        (self.project / "home").symlink_to(self.project / "sub", target_is_directory=True)
        state = tempfile.TemporaryDirectory(prefix="alles-boundary-runs-")
        self.addCleanup(state.cleanup)
        patch = mock.patch.object(agent_state, "DATA_DIR", Path(state.name))
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(ar, "LLM_RETRY_BASE", 0)
        patch.start()
        self.addCleanup(patch.stop)
        # these are about paths; a machine with no shell sandbox has its own tests below
        patch = mock.patch.object(ar, "shell_confinement", lambda settings=None: "sandbox-exec")
        patch.start()
        self.addCleanup(patch.stop)

    def run_agent(self, model, settings, executor, session_id=""):
        async def go():
            chunks = []
            async for ch in ar.run_agent(
                [{"role": "user", "content": "go"}],
                SimpleNamespace(base_url="http://x/", api_key="k"),
                "m",
                asyncio.Event(),
                {"agent_context_files": False, **settings},
                [],
                [],
                [],
                session_id=session_id,
            ):
                chunks.append(ch)
            return chunks

        with (
            mock.patch.object(ar, "stream_chat", model),
            mock.patch.object(ar, "stream_execute", executor),
        ):
            return asyncio.run(go())

    @staticmethod
    def one_call(name, args):
        asked = {"n": 0}

        async def model(messages, *a, **kw):
            asked["n"] += 1
            if asked["n"] == 1:
                yield {"tool_call": {"call_id": "c1", "name": name, "args": args}}
            else:
                yield {"delta": "done"}
            yield {"done": True, "usage": {}}

        return model

    def owner(self, allow=True, then=None):
        """The owner answering a prompt in the page: a real decision on the stored action."""
        asked = []

        async def permission(request_id, exact_hash, *a, **kw):
            from core.database import DelegatedAction
            from services.delegated_actions import decide_action

            asked.append(request_id)
            with self.db() as db:
                action = db.get(DelegatedAction, request_id)
                if action is not None:
                    decide_action(db, action, allow=allow, exact_hash=exact_hash)
                    db.commit()
            if then:
                then()
            return allow

        return permission, asked

    def outside_calls(self):
        patch = "--- a/../outside/secret.txt\n+++ b/../outside/secret.txt\n@@ -1 +1 @@\n-a\n+b\n"
        return [
            ("write_file", {"path": "../outside/escape.txt", "content": "x"}),
            ("write_file", {"path": str(self.outside / "made.txt"), "content": "x"}),
            ("write_file", {"path": "link/escape.txt", "content": "x"}),
            ("edit_file", {"path": "link/secret.txt", "old": "outside", "new": "x"}),
            ("delete_file", {"path": "../outside/secret.txt"}),
            ("revert_file", {"path": "link/secret.txt"}),
            ("shell", {"command": "pwd", "cwd": "../outside"}),
            ("shell", {"command": "pwd", "cwd": "link"}),
            ("apply_patch", {"patch": patch}),
            ("git_commit", {"message": "x", "paths": ["../outside/secret.txt"]}),
        ]

    def test_reads_and_folder_handoffs_never_leave_the_folder(self):
        calls = [
            ("read_file", {"path": "../outside/secret.txt"}),
            ("read_file", {"path": "link/secret.txt"}),
            ("list_files", {"path": ".."}),
            ("grep_files", {"pattern": "words", "path": str(self.outside)}),
            ("git_status", {"cwd": str(self.outside)}),
            ("opencode_run", {"prompt": "x", "cwd": "link"}),
            ("spawn_agent", {"task": "x", "cwd": "../outside"}),
            ("spawn_agents", {"tasks": [{"task": "x", "cwd": "/"}]}),
        ]
        for mode in ("full_access", "full_auto", "approve", "plan"):
            for name, args in calls:
                with self.subTest(mode=mode, tool=name, args=args):
                    ran = []

                    async def executor(tool, tool_args):
                        ran.append(tool)
                        yield {"type": "result", "result": {"output": "ran", "error": False}}

                    permission, asked = self.owner()
                    with mock.patch.object(ar, "_await_permission", permission):
                        chunks = self.run_agent(
                            self.one_call(name, args),
                            {"agent_permission_mode": mode, "agent_cwd": str(self.project)},
                            executor,
                        )
                    self.assertEqual((ran, asked), ([], []))
                    result = next(c["tool_result"] for c in chunks if "tool_result" in c)
                    self.assertTrue(result["error"])
                    self.assertRegex(result["output"], "isn't inside|only works inside")
                    self.assertTrue(chunks[-1].get("done"))

    def test_nothing_that_approves_by_itself_writes_outside(self):
        for mode in ("full_access", "full_auto", "plan"):
            for name, args in self.outside_calls():
                with self.subTest(mode=mode, tool=name, args=args):
                    ran = []

                    async def executor(tool, tool_args):
                        ran.append(tool)
                        yield {"type": "result", "result": {"output": "ran", "error": False}}

                    permission, asked = self.owner()
                    with mock.patch.object(ar, "_await_permission", permission):
                        chunks = self.run_agent(
                            self.one_call(name, args),
                            {"agent_permission_mode": mode, "agent_cwd": str(self.project)},
                            executor,
                        )
                    self.assertEqual((ran, asked), ([], []))
                    result = next(c["tool_result"] for c in chunks if "tool_result" in c)
                    self.assertTrue(result["error"])
                    if mode == "plan":
                        self.assertIn("plan mode", result["output"])
                    else:
                        self.assertIn("switch to approve mode", result["output"])
                        self.assertIn(str(self.outside), result["output"])
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["secret.txt"])
        self.assertEqual((self.outside / "secret.txt").read_text(), "outside words")

    def test_approve_mode_asks_for_each_outside_write_by_its_resolved_path(self):
        for name, args in self.outside_calls():
            for allow in (False, True):
                with self.subTest(tool=name, args=args, allow=allow):
                    ran = []

                    async def executor(tool, tool_args):
                        ran.append(tool)
                        yield {"type": "result", "result": {"output": "ran", "error": False}}

                    permission, asked = self.owner(allow=allow)
                    with mock.patch.object(ar, "_await_permission", permission):
                        chunks = self.run_agent(
                            self.one_call(name, args),
                            {"agent_permission_mode": "approve", "agent_cwd": str(self.project)},
                            executor,
                        )
                    prompt = next(c["tool_permission"] for c in chunks if "tool_permission" in c)
                    self.assertRegex(
                        prompt["outside"], "^(writes|runs commands) outside this task's folder: "
                    )
                    self.assertIn(str(self.outside), prompt["outside"])
                    self.assertNotIn("..", prompt["outside"])
                    self.assertEqual(len(asked), 1)
                    self.assertEqual(ran, [name] if allow else [])

    def test_an_approved_outside_write_lands_exactly_there_and_nowhere_else(self):
        from services import agent_tools

        settings = {"agent_permission_mode": "approve", "agent_cwd": str(self.project)}
        call = self.one_call("write_file", {"path": "link/approved.txt", "content": "yes"})
        permission, asked = self.owner(allow=False)
        with mock.patch.object(ar, "_await_permission", permission):
            self.run_agent(call, settings, agent_tools.stream_execute)
        self.assertFalse((self.outside / "approved.txt").exists())

        call = self.one_call("write_file", {"path": "link/approved.txt", "content": "yes"})
        permission, asked = self.owner(allow=True)
        with mock.patch.object(ar, "_await_permission", permission):
            chunks = self.run_agent(call, settings, agent_tools.stream_execute)
        result = next(c["tool_result"] for c in chunks if "tool_result" in c)
        self.assertFalse(result["error"], result)
        self.assertEqual((self.outside / "approved.txt").read_text(), "yes")
        # the approval was for that one step: the next outside write asks again
        self.assertEqual(agent_tools.get_agent_ctx().get("_approved_outside"), None)

    def test_a_link_swapped_after_the_approval_is_refused(self):
        from services import agent_tools

        elsewhere = self.project.parent / "elsewhere"
        elsewhere.mkdir()

        def swap():
            (self.project / "link").unlink()
            (self.project / "link").symlink_to(elsewhere, target_is_directory=True)

        permission, asked = self.owner(allow=True, then=swap)
        with mock.patch.object(ar, "_await_permission", permission):
            chunks = self.run_agent(
                self.one_call("write_file", {"path": "link/swapped.txt", "content": "x"}),
                {"agent_permission_mode": "approve", "agent_cwd": str(self.project)},
                agent_tools.stream_execute,
            )
        result = next(c["tool_result"] for c in chunks if "tool_result" in c)
        self.assertTrue(result["error"])
        self.assertIn("approval of that exact path", result["output"])
        self.assertFalse((elsewhere / "swapped.txt").exists())
        self.assertFalse((self.outside / "swapped.txt").exists())

    def test_general_writes_only_with_an_approval_of_that_path(self):
        from services import agent_tools

        target = self.outside / "saved.md"
        general = {"agent_environment": "general", "agent_cwd": ""}
        call = self.one_call("write_file", {"path": str(target), "content": "note"})
        chunks = self.run_agent(
            call, {**general, "agent_permission_mode": "full_auto"}, agent_tools.stream_execute
        )
        self.assertIn(
            "switch to approve mode",
            next(c["tool_result"] for c in chunks if "tool_result" in c)["output"],
        )
        permission, asked = self.owner(allow=True)
        with mock.patch.object(ar, "_await_permission", permission):
            self.run_agent(
                self.one_call("write_file", {"path": str(target), "content": "note"}),
                {**general, "agent_permission_mode": "approve"},
                agent_tools.stream_execute,
            )
        self.assertEqual(target.read_text(), "note")

    def test_extra_roots_are_read_freely_and_written_only_with_approval(self):
        extra = self.project.parent / "extra"
        extra.mkdir()
        (extra / "ref.txt").write_text("reference")
        settings = {
            "agent_permission_mode": "approve",
            "agent_cwd": str(self.project),
            "agent_allowed_roots": [str(extra)],
        }
        for name, args, prompted in (
            ("read_file", {"path": str(extra / "ref.txt")}, False),
            ("write_file", {"path": str(extra / "new.txt"), "content": "x"}, True),
        ):
            with self.subTest(tool=name):
                ran = []

                async def executor(tool, tool_args):
                    ran.append(tool)
                    yield {"type": "result", "result": {"output": "ran", "error": False}}

                permission, asked = self.owner(allow=True)
                with mock.patch.object(ar, "_await_permission", permission):
                    chunks = self.run_agent(self.one_call(name, args), settings, executor)
                self.assertEqual(ran, [name])
                self.assertEqual(bool(asked), prompted)
                self.assertEqual(any("tool_permission" in c for c in chunks), prompted)

    def test_paths_that_stay_inside_still_work(self):
        for name, args in (
            ("read_file", {"path": "sub/../inside.txt"}),
            ("read_file", {"path": "home/../inside.txt"}),
            ("write_file", {"path": "home/new.txt", "content": "x"}),
            ("shell", {"command": "pwd", "cwd": "sub"}),
            ("spawn_agent", {"task": "x", "cwd": "sub"}),
        ):
            with self.subTest(tool=name, args=args):
                ran = []

                async def executor(tool, tool_args):
                    ran.append(tool)
                    yield {"type": "result", "result": {"output": "ran", "error": False}}

                self.run_agent(
                    self.one_call(name, args),
                    {"agent_permission_mode": "full_access", "agent_cwd": str(self.project)},
                    executor,
                )
                self.assertEqual(ran, [name])

    def test_full_auto_writes_land_inside_and_never_outside(self):
        # the real tools, in the mode that approves by itself
        from services import agent_tools

        asked = {"n": 0}

        async def model(messages, *a, **kw):
            asked["n"] += 1
            calls = {
                1: {"path": "../escape_probe.txt", "content": "z"},
                2: {"path": "inside_probe.txt", "content": "z"},
            }
            if asked["n"] in calls:
                yield {
                    "tool_call": {
                        "call_id": f"c{asked['n']}",
                        "name": "write_file",
                        "args": calls[asked["n"]],
                    }
                }
            else:
                yield {"delta": "guard done"}
            yield {"done": True, "usage": {}}

        chunks = self.run_agent(
            model,
            {"agent_permission_mode": "full_auto", "agent_cwd": str(self.project)},
            agent_tools.stream_execute,
        )
        results = [c["tool_result"] for c in chunks if "tool_result" in c]
        self.assertTrue(results[0]["error"], results)
        self.assertFalse(results[1]["error"], results)
        self.assertFalse((self.project.parent / "escape_probe.txt").exists())
        self.assertEqual((self.project / "inside_probe.txt").read_text(), "z")

    def test_a_relative_write_in_general_is_a_tool_error_not_a_crash(self):
        from services import agent_tools

        chunks = self.run_agent(
            self.one_call("write_file", {"path": "notes.txt", "content": "x"}),
            {"agent_permission_mode": "full_auto", "agent_environment": "general"},
            agent_tools.stream_execute,
        )
        result = next(c["tool_result"] for c in chunks if "tool_result" in c)
        self.assertTrue(result["error"])
        self.assertIn("General has no folder", result["output"])
        self.assertTrue(chunks[-1].get("done"))

    @staticmethod
    def parent_and_subs(parent_call, sub_calls):
        """A model that makes the parent call once, and walks each sub-agent through sub_calls."""

        async def model(messages, *a, **kw):
            first = next(m["content"] for m in messages if m.get("role") == "user")
            done = sum(1 for m in messages if m.get("role") == "tool")
            calls = sub_calls if str(first).startswith("SUB") else [parent_call]
            if done < len(calls):
                name, args = calls[done]
                yield {"tool_call": {"call_id": f"c{done}", "name": name, "args": args}}
            else:
                yield {"delta": "sub done" if str(first).startswith("SUB") else "parent done"}
            yield {"done": True, "usage": {}}

        return model

    def session(self):
        from core.database import Session

        with self.db() as db:
            row = Session(name="parent task", working_dir=str(self.project))
            db.add(row)
            db.commit()
            return row.id

    def test_two_sub_agents_doing_the_same_write_at_once_are_two_actions(self):
        from core.database import DelegatedAction
        from services import agent_tools

        sid = self.session()
        write = ("write_file", {"path": "same.txt", "content": "same"})
        spawn = ("spawn_agents", {"tasks": [{"task": "SUB one"}, {"task": "SUB two"}]})

        async def executor(tool, tool_args):
            if tool == "write_file":
                await asyncio.sleep(0.2)  # both writes are in flight together
                yield {"type": "result", "result": {"output": "written", "error": False}}
                return
            async for event in agent_tools.stream_execute(tool, tool_args):
                yield event

        chunks = self.run_agent(
            self.parent_and_subs(spawn, [write]),
            {"agent_permission_mode": "full_access", "agent_cwd": str(self.project)},
            executor,
            session_id=sid,
        )
        report = next(c["tool_result"] for c in chunks if "tool_result" in c)["output"]
        self.assertEqual(report.count("sub done"), 2, report)
        self.assertNotIn("not performed", report)
        with self.db() as db:
            rows = db.query(DelegatedAction).filter_by(action="write_file").all()
            self.assertEqual(len(rows), 2)
            self.assertEqual({r.state for r in rows}, {"completed"})
            self.assertEqual({r.session_id for r in rows}, {sid})
            self.assertEqual(len({r.exact_hash for r in rows}), 2)
            self.assertEqual(len({r.agent_run_id for r in rows}), 2)

    def test_a_sub_agent_never_waits_on_a_prompt_nobody_sees(self):
        from services import agent_tools

        sid = self.session()
        seen, asked = [], []
        spawn = ("spawn_agent", {"task": "SUB write it", "cwd": "sub"})
        steps = [
            ("read_file", {"path": "notes.md"}),
            ("write_file", {"path": "made.txt", "content": "x"}),
            ("ask_user", {"title": "which?", "questions": [{"id": "q", "prompt": "which?"}]}),
        ]

        async def executor(tool, tool_args):
            if tool in ("spawn_agent", "spawn_agents"):
                async for event in agent_tools.stream_execute(tool, tool_args):
                    yield event
                return
            seen.append((tool, agent_tools._settings().get("agent_cwd")))
            yield {"type": "result", "result": {"output": "ran", "error": False}}

        async def permission(request_id, exact_hash, *a, **kw):
            # only the parent's own prompt, which the owner can see; the owner approves it
            from core.database import DelegatedAction
            from services.delegated_actions import decide_action

            asked.append(request_id)
            with self.db() as db:
                action = db.get(DelegatedAction, request_id)
                decide_action(db, action, allow=True, exact_hash=exact_hash)
                db.commit()
            return True

        started = asyncio.get_event_loop_policy().new_event_loop().time()
        with mock.patch.object(ar, "_await_permission", permission):
            chunks = self.run_agent(
                self.parent_and_subs(spawn, steps),
                {"agent_permission_mode": "approve", "agent_cwd": str(self.project)},
                executor,
                session_id=sid,
            )
        took = asyncio.get_event_loop_policy().new_event_loop().time() - started
        self.assertLess(took, 10)
        self.assertEqual(len(asked), 1)
        # it works in the folder it was given, inside its parent's
        self.assertEqual(seen, [("read_file", str(self.project / "sub"))])
        report = next(c["tool_result"] for c in chunks if "tool_result" in c)["output"]
        self.assertIn("sub done", report)
        self.assertFalse((self.project / "sub" / "made.txt").exists())

    def test_a_sub_agent_never_changes_anything_outside_its_folder(self):
        from services import agent_tools

        sid = self.session()
        ran = []
        spawn = ("spawn_agent", {"task": "SUB write outside"})
        steps = [("write_file", {"path": "../outside/sub.txt", "content": "x"})]

        async def executor(tool, tool_args):
            if tool == "spawn_agent":
                async for event in agent_tools.stream_execute(tool, tool_args):
                    yield event
                return
            ran.append(tool)
            yield {"type": "result", "result": {"output": "ran", "error": False}}

        permission, asked = self.owner(allow=True)
        with mock.patch.object(ar, "_await_permission", permission):
            chunks = self.run_agent(
                self.parent_and_subs(spawn, steps),
                {"agent_permission_mode": "approve", "agent_cwd": str(self.project)},
                executor,
                session_id=sid,
            )
        self.assertEqual(len(asked), 1)  # the parent's spawn, nothing for the sub-agent's write
        self.assertEqual(ran, [])
        self.assertIn(
            "sub done", next(c["tool_result"] for c in chunks if "tool_result" in c)["output"]
        )
        self.assertFalse((self.outside / "sub.txt").exists())

    def test_with_no_shell_sandbox_only_the_owners_approval_runs_a_command(self):
        from services import agent_tools, shell_sandbox

        call = ("shell", {"command": "echo approved > approved.txt"})
        nobody_asks = (
            {"agent_permission_mode": "full_auto"},
            {"agent_permission_mode": "full_access"},
            {"agent_permission_mode": "full_auto", "agent_detached": True},
            {"agent_permission_mode": "full_access", "_sub_agent": True},
        )
        with (
            mock.patch.object(ar, "shell_confinement", lambda settings=None: ""),
            mock.patch.object(shell_sandbox, "kind", return_value=""),
        ):
            for settings in nobody_asks:
                with self.subTest(**settings):
                    permission, asked = self.owner(allow=True)
                    with mock.patch.object(ar, "_await_permission", permission):
                        chunks = self.run_agent(
                            self.one_call(*call),
                            {**settings, "agent_cwd": str(self.project)},
                            agent_tools.stream_execute,
                        )
                    result = next(c["tool_result"] for c in chunks if "tool_result" in c)
                    self.assertTrue(result["error"])
                    if settings["agent_permission_mode"] == "full_access" and not settings.get(
                        "_sub_agent"
                    ):
                        self.assertEqual(result["output"], shell_sandbox.missing_hint())
                    self.assertEqual(asked, [])
                    self.assertFalse((self.project / "approved.txt").exists())
            for allow in (False, True):
                with self.subTest(approve=allow):
                    permission, asked = self.owner(allow=allow)
                    with mock.patch.object(ar, "_await_permission", permission):
                        chunks = self.run_agent(
                            self.one_call(*call),
                            {"agent_permission_mode": "approve", "agent_cwd": str(self.project)},
                            agent_tools.stream_execute,
                        )
                    prompt = next(c["tool_permission"] for c in chunks if "tool_permission" in c)
                    self.assertTrue(prompt["unconfined"])
                    self.assertIn("runs without a sandbox", prompt["outside"])
                    self.assertEqual(prompt["args"]["command"], call[1]["command"])
                    self.assertEqual(len(asked), 1)
                    self.assertEqual((self.project / "approved.txt").exists(), allow)

    def test_with_no_sandbox_a_read_tool_that_runs_git_asks_first_and_never_by_itself(self):
        from services import shell_sandbox

        for mode, prompted in (("full_auto", False), ("full_access", False), ("approve", True)):
            with self.subTest(mode=mode):
                ran = []

                async def executor(tool, tool_args):
                    ran.append(tool)
                    yield {"type": "result", "result": {"output": "ran", "error": False}}

                permission, asked = self.owner(allow=True)
                with (
                    mock.patch.object(ar, "shell_confinement", lambda settings=None: ""),
                    mock.patch.object(ar, "_await_permission", permission),
                ):
                    chunks = self.run_agent(
                        self.one_call("git_status", {}),
                        {"agent_permission_mode": mode, "agent_cwd": str(self.project)},
                        executor,
                    )
                prompt = next(
                    (c["tool_permission"] for c in chunks if "tool_permission" in c), None
                )
                self.assertEqual(bool(prompt), prompted)
                self.assertEqual(ran, ["git_status"] if prompted else [])
                if prompted:
                    self.assertTrue(prompt["unconfined"])
                    self.assertIn("runs without a sandbox", prompt["outside"])
                else:
                    result = next(c["tool_result"] for c in chunks if "tool_result" in c)
                    self.assertEqual(result["output"], shell_sandbox.missing_hint())

    def test_full_auto_refuses_a_shell_with_no_sandbox_in_plain_words(self):
        from services import shell_sandbox

        ran = []

        async def executor(tool, tool_args):
            ran.append(tool)
            yield {"type": "result", "result": {"output": "ran", "error": False}}

        with mock.patch.object(ar, "shell_confinement", lambda settings=None: ""):
            chunks = self.run_agent(
                self.one_call("shell", {"command": "ls"}),
                {"agent_permission_mode": "full_auto", "agent_cwd": str(self.project)},
                executor,
            )
        self.assertEqual(ran, [])
        self.assertFalse(any("tool_permission" in c for c in chunks))
        result = next(c["tool_result"] for c in chunks if "tool_result" in c)
        self.assertEqual(result["output"], shell_sandbox.missing_hint())

    def test_a_sandboxed_shell_prompt_is_not_marked_unconfined(self):
        async def executor(tool, tool_args):
            yield {"type": "result", "result": {"output": "ran", "error": False}}

        permission, asked = self.owner(allow=True)
        with mock.patch.object(ar, "_await_permission", permission):
            chunks = self.run_agent(
                self.one_call("shell", {"command": "ls"}),
                {"agent_permission_mode": "approve", "agent_cwd": str(self.project)},
                executor,
            )
        prompt = next(c["tool_permission"] for c in chunks if "tool_permission" in c)
        self.assertNotIn("unconfined", prompt)
        self.assertNotIn("outside", prompt)

    def stalled_sub_agents(self, stop, sid, press):
        """The parent spawns two sub-agents whose model reads stall; `press()` runs once both are
        reading. Returns the parent's chunks, how long it all took, and every run's status."""
        started = []

        async def model(messages, *a, **kw):
            first = next(m["content"] for m in messages if m.get("role") == "user")
            if str(first).startswith("SUB"):
                started.append(first)
                yield {"delta": "working"}
                if len(started) == 2:
                    asyncio.get_running_loop().create_task(press())
                await asyncio.Event().wait()  # the model stalls
            elif not any(m.get("role") == "tool" for m in messages):
                tasks = [{"task": "SUB one"}, {"task": "SUB two"}]
                yield {
                    "tool_call": {"call_id": "c0", "name": "spawn_agents", "args": {"tasks": tasks}}
                }
            else:
                yield {"delta": "parent done"}
            yield {"done": True, "usage": {}}

        async def go():
            chunks = []
            async for ch in ar.run_agent(
                [{"role": "user", "content": "go"}],
                SimpleNamespace(base_url="http://x/", api_key="k"),
                "m",
                stop,
                {
                    "agent_context_files": False,
                    "agent_permission_mode": "full_access",
                    "agent_cwd": str(self.project),
                },
                [],
                [],
                [],
                session_id=sid,
            ):
                chunks.append(ch)
            return chunks

        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        began = loop.time()
        with mock.patch.object(ar, "stream_chat", model):
            chunks = loop.run_until_complete(asyncio.wait_for(go(), 10))
        took = loop.time() - began
        self.assertEqual(len(started), 2)
        statuses = sorted(run["status"] for run in agent_state.list_runs(limit=10))
        return chunks, took, statuses

    def test_the_owners_stop_reaches_every_running_sub_agent(self):
        stop = asyncio.Event()

        async def press():
            stop.set()

        chunks, took, statuses = self.stalled_sub_agents(stop, self.session(), press)
        self.assertLess(took, 5)
        self.assertEqual(statuses, ["stopped", "stopped", "stopped"])
        report = next(c["tool_result"] for c in chunks if "tool_result" in c)["output"]
        self.assertEqual(report.count("Agent stopped."), 2, report)
        self.assertNotIn("parent done", "".join(c.get("delta", "") for c in chunks))

    def test_a_stop_for_this_turn_reaches_sub_agents_and_one_for_another_turn_does_not(self):
        from routes import chat

        sid = self.session()
        stop = asyncio.Event()
        stop.turn_token = "this turn"
        self.assertTrue(chat.claim_turn(sid, stop))
        self.addCleanup(chat._streams.pop, sid, None)
        seen = {}

        async def press():
            seen["other"] = chat.stop_chat(sid, chat.StopBody(turn_token="another turn"))
            await asyncio.sleep(0.15)
            seen["running"] = sorted(run["status"] for run in agent_state.list_runs(limit=10))
            seen["this"] = chat.stop_chat(sid, chat.StopBody(turn_token="this turn"))

        _, took, statuses = self.stalled_sub_agents(stop, sid, press)
        self.assertEqual(seen["other"]["ok"], False)
        self.assertEqual(seen["running"], ["running", "running", "running"])
        self.assertEqual(seen["this"], {"ok": True})
        self.assertLess(took, 5)
        self.assertEqual(statuses, ["stopped", "stopped", "stopped"])


if __name__ == "__main__":
    unittest.main()
