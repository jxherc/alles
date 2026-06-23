"""stage 3a - unified capability/action registry. tests first (RED)."""

import asyncio
import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import capabilities as cap


class RegistryTests(unittest.TestCase):
    def setUp(self):
        cap.clear()

    def test_register_and_get(self):
        c = cap.Capability(name="foo", kind="tool", scope="read")
        cap.register(c)
        self.assertIs(cap.get("foo", "tool"), c)

    def test_get_unknown(self):
        self.assertIsNone(cap.get("nope", "tool"))

    def test_kind_disambiguates_same_name(self):
        cap.register(cap.Capability(name="x", kind="tool", scope="read"))
        cap.register(cap.Capability(name="x", kind="action", scope="state"))
        self.assertEqual(cap.get("x", "tool").kind, "tool")
        self.assertEqual(cap.get("x", "action").kind, "action")

    def test_duplicate_overwrites(self):
        cap.register(cap.Capability(name="x", kind="tool", scope="read"))
        cap.register(cap.Capability(name="x", kind="tool", scope="write"))
        self.assertEqual(cap.get("x", "tool").scope, "write")
        self.assertEqual(len(cap.all(kind="tool")), 1)

    def test_all_filters(self):
        cap.register(cap.Capability(name="a", kind="tool", scope="read", tags=("tool", "read")))
        cap.register(cap.Capability(name="b", kind="tool", scope="write", tags=("tool", "write")))
        cap.register(
            cap.Capability(name="c", kind="action", scope="state", tags=("action", "state"))
        )
        self.assertEqual(len(cap.all()), 3)
        self.assertEqual(len(cap.all(kind="tool")), 2)
        self.assertEqual({x.name for x in cap.all(scope="read")}, {"a"})
        self.assertEqual({x.name for x in cap.all(tag="write")}, {"b"})


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        cap.clear()
        cap.bootstrap()

    def test_tools_registered_with_scope(self):
        from services import agent_tools

        shell = cap.get("shell", "tool")
        self.assertIsNotNone(shell)
        self.assertEqual(shell.scope, agent_tools.TOOL_PERMISSION["shell"])

    def test_every_permissioned_tool_is_registered(self):
        from services import agent_tools

        names = {c.name for c in cap.all(kind="tool")}
        missing = [t for t in agent_tools.TOOL_PERMISSION if t not in names]
        self.assertEqual(missing, [])

    def test_actions_registered(self):
        from services import automations

        names = {c.name for c in cap.all(kind="action")}
        for a in automations.ACTIONS:
            self.assertIn(a, names)

    def test_tool_carries_schema(self):
        shell = cap.get("shell", "tool")
        self.assertIn("command", (shell.schema or {}).get("properties", {}))

    def test_bootstrap_idempotent(self):
        n1 = len(cap.all())
        cap.bootstrap()
        self.assertEqual(len(cap.all()), n1)

    def test_tags_include_kind_and_scope(self):
        shell = cap.get("shell", "tool")
        self.assertIn("tool", shell.tags)
        self.assertIn(shell.scope, shell.tags)


class InvokeTests(unittest.TestCase):
    def setUp(self):
        cap.clear()
        cap.bootstrap()

    def test_invoke_delegates_to_execute(self):
        from services import agent_tools

        seen = {}

        async def fake_exec(name, args):
            seen["name"], seen["args"] = name, args
            return {"ok": True}

        orig = agent_tools.execute
        agent_tools.execute = fake_exec
        try:
            out = asyncio.run(cap.invoke("recall", {"query": "hi"}))
        finally:
            agent_tools.execute = orig
        self.assertEqual(seen["name"], "recall")
        self.assertEqual(seen["args"], {"query": "hi"})
        self.assertEqual(out, {"ok": True})

    def test_invoke_unknown_tool_raises(self):
        with self.assertRaises(KeyError):
            asyncio.run(cap.invoke("nonexistent_tool_xyz", {}))


if __name__ == "__main__":
    unittest.main()
