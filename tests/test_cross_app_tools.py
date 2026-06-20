import unittest

from routes import search
from services import agent_tools as at


class CrossAppToolTests(unittest.TestCase):
    def _names(self, settings):
        return {t["function"]["name"] for t in at.build_tool_defs(settings)}

    def test_app_tools_registered(self):
        n = self._names({})
        for t in (
            "calendar_list",
            "calendar_create",
            "task_add",
            "task_list",
            "note_write",
            "note_search",
            "contact_add",
            "mail_list",
            "mail_send",
            "calendar_delete",
            "task_done",
            "contact_list",
            "note_read",
            "note_list",
        ):
            self.assertIn(t, n)

    def test_plan_mode_hides_app_mutations(self):
        plan = self._names({"agent_permission_mode": "plan"})
        for mut in (
            "calendar_create",
            "calendar_delete",
            "task_add",
            "task_done",
            "note_write",
            "contact_add",
            "mail_send",
        ):
            self.assertNotIn(mut, plan)
        for read in ("calendar_list", "task_list", "note_search", "mail_list", "contact_list"):
            self.assertIn(read, plan)  # reads stay available in plan mode

    def test_app_mutations_in_mutating_set(self):
        for mut in (
            "calendar_create",
            "calendar_delete",
            "task_add",
            "task_done",
            "note_write",
            "contact_add",
            "mail_send",
        ):
            self.assertIn(mut, at.MUTATING_TOOLS)

    def test_full_auto_has_more_tools_than_plan(self):
        full = self._names({"agent_permission_mode": "full_auto"})
        plan = self._names({"agent_permission_mode": "plan"})
        self.assertGreater(len(full), len(plan))

    def test_shell_in_mutating_set(self):
        self.assertIn("shell", at.MUTATING_TOOLS)
        self.assertIn("write_file", at.MUTATING_TOOLS)

    def test_decide_permission_full_auto_allows_mutations(self):
        p = at.decide_permission("write_file", {"path": "/tmp/x.txt"}, "full_auto", [])
        self.assertEqual(p, "allow")

    def test_decide_permission_plan_denies_mutations(self):
        p = at.decide_permission("write_file", {"path": "/tmp/x.txt"}, "plan", [])
        self.assertEqual(p, "deny")

    def test_decide_permission_approve_asks(self):
        p = at.decide_permission("shell", {"command": "ls"}, "approve", [])
        self.assertEqual(p, "ask")

    def test_decide_permission_rule_override_wins(self):
        # user rule that always allows shell
        rules = [{"tool": "shell", "action": "allow"}]
        p = at.decide_permission("shell", {"command": "ls"}, "approve", rules)
        self.assertEqual(p, "allow")


class SearchHelperTests(unittest.TestCase):
    def test_snip_centers_match(self):
        t = ("word " * 30) + "NEEDLE here " + ("word " * 30)
        s = search._snip(t, "needle")
        self.assertIn("NEEDLE", s)
        self.assertLessEqual(len(s), 121)
        self.assertNotIn("\n", s)

    def test_snip_no_match_takes_head(self):
        self.assertTrue(search._snip("abc def ghi", "zzz").startswith("abc"))

    def test_snip_strips_newlines(self):
        # multiline text — snip should collapse newlines
        t = "hello\nNEEDLE\nworld"
        s = search._snip(t, "needle")
        self.assertNotIn("\n", s)

    def test_snip_at_start(self):
        # match at very beginning — no room to go left
        s = search._snip("NEEDLE rest of text", "needle")
        self.assertTrue(s.startswith("NEEDLE"))


if __name__ == "__main__":
    unittest.main()
