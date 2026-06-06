import os
import tempfile
import unittest

from services import agent_tools as at


class ToolGatingTests(unittest.TestCase):
    def _names(self, settings):
        return {t["function"]["name"] for t in at.build_tool_defs(settings)}

    def test_base_excludes_optional(self):
        names = self._names({})
        self.assertIn("shell", names)
        self.assertNotIn("screenshot", names)        # computer use off
        self.assertIn("spawn_agent", names)          # subagents default on

    def test_computer_use_toggle(self):
        self.assertIn("screenshot", self._names({"agent_computer_use": True}))

    def test_subagents_off(self):
        self.assertNotIn("spawn_agent", self._names({"agent_subagents": False}))

    def test_plan_mode_hides_mutating(self):
        names = self._names({"agent_permission_mode": "plan"})
        self.assertNotIn("write_file", names)
        self.assertNotIn("shell", names)
        self.assertIn("read_file", names)            # read-only stays

    def test_mutating_set_membership(self):
        for w in ("shell", "write_file", "edit_file", "apply_patch", "git_commit"):
            self.assertIn(w, at.MUTATING_TOOLS)
        for r in ("read_file", "grep_files", "git_status", "code_symbols"):
            self.assertNotIn(r, at.MUTATING_TOOLS)


class PreviewChangeTests(unittest.TestCase):
    def test_write_file_diff(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with open(p, "w") as f:
                f.write("old line\n")
            diff = at.preview_change("write_file", {"path": p, "content": "new line\n"})
            self.assertIn("-old line", diff)
            self.assertIn("+new line", diff)

    def test_edit_file_diff(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with open(p, "w") as f:
                f.write("hello world\n")
            diff = at.preview_change("edit_file", {"path": p, "old": "world", "new": "there"})
            self.assertIn("-hello world", diff)
            self.assertIn("+hello there", diff)

    def test_apply_patch_returns_patch(self):
        patch = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
        self.assertEqual(at.preview_change("apply_patch", {"patch": patch}), patch.strip())

    def test_non_diff_tool_empty(self):
        self.assertEqual(at.preview_change("shell", {"command": "ls"}), "")


class WorkspaceFilesTests(unittest.TestCase):
    def test_lists_and_filters(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "alpha.py"), "w").close()
            open(os.path.join(d, "beta.txt"), "w").close()
            os.makedirs(os.path.join(d, "node_modules"))
            open(os.path.join(d, "node_modules", "junk.js"), "w").close()
            allf = at.workspace_files(d)
            self.assertIn("alpha.py", allf)
            self.assertNotIn("node_modules/junk.js", allf)   # skip dir
            only = at.workspace_files(d, "alpha")
            self.assertEqual(only, ["alpha.py"])


if __name__ == "__main__":
    unittest.main()
