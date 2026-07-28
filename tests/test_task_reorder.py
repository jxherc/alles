from core.database import Task
from tests._client import ApiTest


class TaskReorderTests(ApiTest):
    def _task(self, title, stage="backlog", sort_order=0, done=False):
        session = self.db()
        task = Task(
            title=title,
            stage=stage,
            sort_order=sort_order,
            done=done,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id
        session.close()
        return task_id

    def test_reorders_and_moves_active_tasks_atomically(self):
        first = self._task("first")
        second = self._task("second", stage="next")

        response = self.client.post(
            "/api/tasks/reorder",
            json={
                "items": [
                    {"id": second, "stage": "doing", "sort_order": 0},
                    {"id": first, "stage": "doing", "sort_order": 1},
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(item["id"], item["stage"], item["sort_order"]) for item in response.json()["items"]],
            [(second, "doing", 0), (first, "doing", 1)],
        )
        session = self.db()
        self.assertEqual(
            (session.get(Task, second).stage, session.get(Task, second).sort_order), ("doing", 0)
        )
        self.assertEqual(
            (session.get(Task, first).stage, session.get(Task, first).sort_order), ("doing", 1)
        )
        session.close()

    def test_rejects_missing_task_without_changing_any_row(self):
        task_id = self._task("kept", stage="next", sort_order=4)

        response = self.client.post(
            "/api/tasks/reorder",
            json={
                "items": [
                    {"id": task_id, "stage": "doing", "sort_order": 0},
                    {"id": "missing", "stage": "waiting", "sort_order": 1},
                ]
            },
        )

        self.assertEqual(response.status_code, 404)
        session = self.db()
        saved = session.get(Task, task_id)
        self.assertEqual((saved.stage, saved.sort_order), ("next", 4))
        session.close()

    def test_rejects_duplicate_ids_and_done_stage(self):
        task_id = self._task("one")
        duplicate = self.client.post(
            "/api/tasks/reorder",
            json={
                "items": [
                    {"id": task_id, "stage": "next", "sort_order": 0},
                    {"id": task_id, "stage": "doing", "sort_order": 1},
                ]
            },
        )
        done = self.client.post(
            "/api/tasks/reorder",
            json={"items": [{"id": task_id, "stage": "done", "sort_order": 0}]},
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(done.status_code, 400)

    def test_legacy_reorder_rejects_oversized_id_list_before_conversion(self):
        response = self.client.post(
            "/api/tasks/reorder",
            json={"ids": [f"task-{index}" for index in range(2001)]},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "too many tasks")

    def test_rejects_completed_task(self):
        task_id = self._task("finished", stage="done", done=True)
        response = self.client.post(
            "/api/tasks/reorder",
            json={"items": [{"id": task_id, "stage": "backlog", "sort_order": 0}]},
        )
        self.assertEqual(response.status_code, 409)

    def test_partial_reorder_requires_the_complete_active_board(self):
        moved = self._task("moved", stage="backlog", sort_order=0)
        occupied = self._task("occupied", stage="doing", sort_order=0)

        response = self.client.post(
            "/api/tasks/reorder",
            json={"items": [{"id": moved, "stage": "doing", "sort_order": 0}]},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(
            response.json()["detail"], "reorder requires the complete active-task board"
        )
        session = self.db()
        self.assertEqual(
            (session.get(Task, moved).stage, session.get(Task, moved).sort_order), ("backlog", 0)
        )
        self.assertEqual(
            (session.get(Task, occupied).stage, session.get(Task, occupied).sort_order),
            ("doing", 0),
        )
        session.close()
