from core.database import Task
from tests._client import ApiTest


class CalendarTasksTests(ApiTest):
    def setUp(self):
        super().setUp()
        d = self.db()
        d.add_all(
            [
                Task(title="pay rent", due_date="2026-06-20", done=False),
                Task(title="call vet", due_date="2026-06-25", done=True),
                Task(title="someday", due_date=None, done=False),
                Task(title="old thing", due_date="2026-05-01", done=False),
            ]
        )
        d.commit()
        d.close()

    def _get(self, **params):
        return self.client.get("/api/calendar/tasks", params=params).json()

    def test_returns_tasks_with_due_in_range(self):
        rows = self._get(start="2026-06-01", end="2026-06-30")
        self.assertEqual(sorted(t["title"] for t in rows), ["call vet", "pay rent"])

    def test_excludes_undated(self):
        rows = self._get(start="2026-01-01", end="2026-12-31")
        self.assertNotIn("someday", [t["title"] for t in rows])

    def test_excludes_out_of_range(self):
        rows = self._get(start="2026-06-01", end="2026-06-30")
        self.assertNotIn("old thing", [t["title"] for t in rows])

    def test_start_boundary_inclusive(self):
        rows = self._get(start="2026-06-20", end="2026-06-20")
        self.assertEqual([t["title"] for t in rows], ["pay rent"])

    def test_end_boundary_inclusive(self):
        rows = self._get(start="2026-06-25", end="2026-06-25")
        self.assertEqual([t["title"] for t in rows], ["call vet"])

    def test_includes_done_flag(self):
        rows = self._get(start="2026-06-01", end="2026-06-30")
        done = {t["title"]: t["done"] for t in rows}
        self.assertTrue(done["call vet"])
        self.assertFalse(done["pay rent"])

    def test_shape(self):
        rows = self._get(start="2026-06-20", end="2026-06-20")
        t = rows[0]
        self.assertEqual(set(t), {"id", "title", "date", "done"})
        self.assertEqual(t["date"], "2026-06-20")

    def test_no_range_returns_all_dated(self):
        rows = self._get()
        self.assertEqual(sorted(t["title"] for t in rows), ["call vet", "old thing", "pay rent"])

    def test_sorted_by_date(self):
        rows = self._get()
        dates = [t["date"] for t in rows]
        self.assertEqual(dates, sorted(dates))
