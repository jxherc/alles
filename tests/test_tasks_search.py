from core.database import Task
from tests._client import ApiTest


class TaskSearchTests(ApiTest):
    def setUp(self):
        super().setUp()
        d = self.db()
        d.add_all(
            [
                Task(title="Buy groceries", notes="milk and eggs", tags="home", done=False),
                Task(
                    title="Email the accountant",
                    notes="about Q3 taxes",
                    tags="work,finance",
                    done=False,
                ),
                Task(title="Plan vacation", notes="", tags="home,travel", done=False),
                Task(title="Old groceries run", notes="", tags="", done=True),
            ]
        )
        d.commit()
        d.close()

    def _q(self, q):
        return [t["title"] for t in self.client.get("/api/tasks/search", params={"q": q}).json()]

    def test_match_in_title(self):
        self.assertEqual(self._q("vacation"), ["Plan vacation"])

    def test_match_in_notes(self):
        self.assertEqual(self._q("taxes"), ["Email the accountant"])

    def test_match_in_tags(self):
        self.assertEqual(sorted(self._q("home")), ["Buy groceries", "Plan vacation"])

    def test_case_insensitive(self):
        self.assertEqual(self._q("GROCERIES"), ["Buy groceries"])

    def test_partial_substring(self):
        self.assertIn("Email the accountant", self._q("account"))

    def test_no_match(self):
        self.assertEqual(self._q("zzzzz"), [])

    def test_empty_query_returns_empty(self):
        self.assertEqual(self._q(""), [])

    def test_excludes_done_by_default(self):
        # "groceries" matches an active task and a done one — only the active shows
        self.assertEqual(self._q("groceries"), ["Buy groceries"])

    def test_multiple_matches(self):
        self.assertEqual(
            len(self.client.get("/api/tasks/search", params={"q": "e"}).json()) >= 2, True
        )
