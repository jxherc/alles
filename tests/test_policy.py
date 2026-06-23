"""stage 3b - persona-scoped permission policy layer. tests first (RED)."""

import os
import unittest

os.environ["AUTH_ENABLED"] = "false"
from services import policy


class _Persona:
    def __init__(self, blocked_scopes="", blocked_tools=""):
        self.blocked_scopes = blocked_scopes
        self.blocked_tools = blocked_tools


class ScopeTests(unittest.TestCase):
    def test_scope_for_known_tool(self):
        self.assertEqual(policy.scope_for("shell"), "shell")
        self.assertEqual(policy.scope_for("read_file"), "read")
        self.assertEqual(policy.scope_for("write_file"), "write")

    def test_scope_for_unknown(self):
        self.assertEqual(policy.scope_for("totally_made_up"), "")


class PersonaBlockTests(unittest.TestCase):
    def test_blocks_by_scope(self):
        p = _Persona(blocked_scopes="shell")
        self.assertTrue(policy.persona_blocks("shell", p))
        self.assertFalse(policy.persona_blocks("read_file", p))

    def test_blocks_by_tool_name(self):
        p = _Persona(blocked_tools="write_file")
        self.assertTrue(policy.persona_blocks("write_file", p))
        self.assertFalse(policy.persona_blocks("read_file", p))

    def test_multi_scope_csv(self):
        p = _Persona(blocked_scopes="shell, write")
        self.assertTrue(policy.persona_blocks("shell", p))
        self.assertTrue(policy.persona_blocks("write_file", p))
        self.assertFalse(policy.persona_blocks("read_file", p))

    def test_none_persona_never_blocks(self):
        self.assertFalse(policy.persona_blocks("shell", None))


class GateTests(unittest.TestCase):
    def test_disabled_tool_denied(self):
        self.assertEqual(
            policy.gate("shell", {}, mode="full_auto", rules=[], disabled=("shell",)), "deny"
        )

    def test_persona_block_denied(self):
        p = _Persona(blocked_scopes="shell")
        self.assertEqual(
            policy.gate("shell", {"command": "ls"}, mode="full_auto", rules=[], persona=p), "deny"
        )

    def test_defers_to_decide_permission_allow(self):
        # read tool, full_auto, no rules, no persona -> allow
        self.assertEqual(
            policy.gate("read_file", {"path": "x"}, mode="full_auto", rules=[]), "allow"
        )

    def test_plan_mode_mutating_denied_via_decide(self):
        self.assertEqual(policy.gate("write_file", {"path": "x"}, mode="plan", rules=[]), "deny")

    def test_code_reviewer_persona_scenario(self):
        p = _Persona(blocked_scopes="shell,write")
        self.assertEqual(
            policy.gate("shell", {"command": "x"}, mode="full_auto", rules=[], persona=p), "deny"
        )
        self.assertEqual(
            policy.gate("write_file", {"path": "x"}, mode="full_auto", rules=[], persona=p), "deny"
        )
        self.assertEqual(
            policy.gate("read_file", {"path": "x"}, mode="full_auto", rules=[], persona=p), "allow"
        )

    def test_user_rule_still_applies_when_not_blocked(self):
        rules = [{"tool": "read_file", "action": "ask"}]
        self.assertEqual(
            policy.gate("read_file", {"path": "x"}, mode="full_auto", rules=rules), "ask"
        )


if __name__ == "__main__":
    unittest.main()
