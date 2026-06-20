import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.database import AutomationRule, Task
from services import automations
from tests._client import ApiTest


class _Stop:
    def is_set(self):
        return False


class AgentHookTests(ApiTest):
    def _rule(
        self, glob="*", action="create_task", arg="{tool} fired", enabled=True, trigger="agent_tool"
    ):
        d = self.db()
        d.add(
            AutomationRule(
                name="hook",
                trigger=trigger,
                trigger_arg=glob,
                action=action,
                action_arg=arg,
                enabled=enabled,
            )
        )
        d.commit()
        d.close()

    def _tasks(self):
        d = self.db()
        rows = d.query(Task).all()
        out = [t.title for t in rows]
        d.close()
        return out

    def _fire(self, tool, args=None, result=None, run_id="r1"):
        asyncio.run(automations.on_agent_tool(tool, args or {}, result or {"output": "ok"}, run_id))

    def test_glob_exact_match(self):
        self._rule("write_file")
        self._fire("write_file")
        self.assertEqual(len(self._tasks()), 1)

    def test_glob_wildcard(self):
        self._rule("write_*")
        self._fire("write_file")
        self.assertEqual(len(self._tasks()), 1)

    def test_glob_no_match(self):
        self._rule("git_*")
        self._fire("write_file")
        self.assertEqual(self._tasks(), [])

    def test_disabled_rule_skipped(self):
        self._rule("*", enabled=False)
        self._fire("write_file")
        self.assertEqual(self._tasks(), [])

    def test_fires_create_task_with_rendered_title(self):
        self._rule("*", arg="{tool} was used")
        self._fire("edit_file")
        self.assertIn("edit_file was used", self._tasks())

    def test_fires_on_write_only_not_shell(self):
        self._rule("write_*")
        self._fire("shell", {"cmd": "ls"})
        self.assertEqual(self._tasks(), [])

    def test_non_agent_tool_rules_untouched(self):
        self._rule("*", trigger="doc_tag")  # a doc rule should never fire on a tool event
        self._fire("write_file")
        self.assertEqual(self._tasks(), [])

    def test_multiple_rules_fire(self):
        self._rule("write_*", arg="a {tool}")
        self._rule("*", arg="b {tool}")
        self._fire("write_file")
        self.assertEqual(len(self._tasks()), 2)

    def test_hook_safe_when_no_rules(self):
        self._fire("write_file")  # must not raise
        self.assertEqual(self._tasks(), [])

    def test_hook_called_from_runtime(self):
        # an agent run that calls a tool should trigger the matching agent_tool rule
        from services import agent_runtime as ar
        from services import agent_state

        self._rule("task_list", arg="agent ran {tool}")

        async def fake(messages, base_url, api_key, model, **kw):
            i = state["n"]
            state["n"] += 1
            seq = [
                [{"tool_call": {"call_id": "c1", "name": "task_list", "args": {}}}, {"done": True}],
                [{"done": True, "usage": {}}],
            ]
            for ch in seq[i] if i < len(seq) else seq[-1]:
                yield ch

        state = {"n": 0}
        ep = SimpleNamespace(base_url="http://x/", api_key="k")
        with tempfile.TemporaryDirectory() as d:
            with (
                mock.patch.object(agent_state, "DATA_DIR", Path(d)),
                mock.patch.object(ar, "stream_chat", fake),
                mock.patch.object(ar, "LLM_RETRY_BASE", 0),
            ):

                async def go():
                    async for _ in ar.run_agent(
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
                        pass

                asyncio.run(go())
        self.assertIn("agent ran task_list", self._tasks())
