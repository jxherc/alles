from core.database import Task
from tests._client import ApiTest


class TaskTreeTests(ApiTest):
    def setUp(self):
        super().setUp()
        d = self.db()
        self.parent = Task(title="Launch site", done=False)
        d.add(self.parent)
        d.flush()
        d.add_all(
            [
                Task(title="write copy", parent_id=self.parent.id, done=True),
                Task(title="design hero", parent_id=self.parent.id, done=False),
                Task(title="Standalone", done=False),  # top-level, no subtasks
                Task(title="Done parent", done=True),  # excluded from tree
            ]
        )
        d.commit()
        self.pid = self.parent.id
        d.close()

    def _tree(self):
        return self.client.get("/api/tasks/tree").json()

    def test_returns_top_level_only(self):
        titles = [t["title"] for t in self._tree()]
        self.assertEqual(sorted(titles), ["Launch site", "Standalone"])

    def test_subtasks_nested(self):
        node = next(t for t in self._tree() if t["title"] == "Launch site")
        self.assertEqual(
            sorted(s["title"] for s in node["subtasks"]), ["design hero", "write copy"]
        )

    def test_progress_counts(self):
        node = next(t for t in self._tree() if t["title"] == "Launch site")
        self.assertEqual(node["progress"], {"done": 1, "total": 2})

    def test_no_subtasks_zero_progress(self):
        node = next(t for t in self._tree() if t["title"] == "Standalone")
        self.assertEqual(node["progress"], {"done": 0, "total": 0})
        self.assertEqual(node["subtasks"], [])

    def test_excludes_done_parent(self):
        self.assertNotIn("Done parent", [t["title"] for t in self._tree()])

    def test_active_subtask_not_top_level(self):
        # "design hero" is active but a subtask — must not appear as a top-level node
        self.assertNotIn("design hero", [t["title"] for t in self._tree()])

    def test_done_subtask_counted(self):
        node = next(t for t in self._tree() if t["title"] == "Launch site")
        done = [s for s in node["subtasks"] if s["done"]]
        self.assertEqual([s["title"] for s in done], ["write copy"])

    def test_node_shape(self):
        node = self._tree()[0]
        self.assertIn("subtasks", node)
        self.assertIn("progress", node)
        self.assertIn("id", node)
