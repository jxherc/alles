import unittest

from services import agent_tools as at
from routes import search


class CrossAppToolTests(unittest.TestCase):
    def _names(self, settings):
        return {t["function"]["name"] for t in at.build_tool_defs(settings)}

    def test_app_tools_registered(self):
        n = self._names({})
        for t in ("calendar_list", "calendar_create", "task_add", "task_list",
                  "note_write", "note_search", "contact_add", "mail_list", "mail_send",
                  "calendar_delete", "task_done", "contact_list", "note_read", "note_list"):
            self.assertIn(t, n)

    def test_plan_mode_hides_app_mutations(self):
        plan = self._names({"agent_permission_mode": "plan"})
        for mut in ("calendar_create", "calendar_delete", "task_add", "task_done",
                    "note_write", "contact_add", "mail_send"):
            self.assertNotIn(mut, plan)
        for read in ("calendar_list", "task_list", "note_search", "mail_list", "contact_list"):
            self.assertIn(read, plan)   # reads stay available in plan mode

    def test_app_mutations_in_mutating_set(self):
        for mut in ("calendar_create", "calendar_delete", "task_add", "task_done",
                    "note_write", "contact_add", "mail_send"):
            self.assertIn(mut, at.MUTATING_TOOLS)


class SearchHelperTests(unittest.TestCase):
    def test_snip_centers_match(self):
        t = ("word " * 30) + "NEEDLE here " + ("word " * 30)
        s = search._snip(t, "needle")
        self.assertIn("NEEDLE", s)
        self.assertLessEqual(len(s), 121)
        self.assertNotIn("\n", s)

    def test_snip_no_match_takes_head(self):
        self.assertTrue(search._snip("abc def ghi", "zzz").startswith("abc"))


if __name__ == "__main__":
    unittest.main()
