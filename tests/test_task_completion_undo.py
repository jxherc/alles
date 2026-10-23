"""An undo only restores its acknowledged completion; recurrence stays issued."""

from core.database import Task
from tests._client import ApiTest


class TaskCompletionUndoTests(ApiTest):
    def create(self, **fields):
        response = self.client.post(
            "/api/tasks", json={"title": "owned task", "stage": "doing", **fields}
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def change(self, task, done, stage):
        return self.client.patch(
            "/api/tasks/" + task["id"],
            json={
                "done": done,
                "stage": stage,
                "expected": {key: task[key] for key in ("done", "stage", "completed_at")},
            },
        )

    def test_undo_restores_stage_and_keeps_later_content_edits(self):
        for stage in ("backlog", "next", "doing", "waiting"):
            task = self.create(stage=stage)
            self.assertIsNone(task["completed_at"])
            completed = self.change(task, True, "done").json()
            self.assertIsInstance(completed["completed_at"], str)
            self.assertEqual(
                self.client.patch(
                    "/api/tasks/" + task["id"], json={"notes": "new notes", "title": "new title"}
                ).status_code,
                200,
            )
            response = self.change(completed, False, stage)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["stage"], stage)
            self.assertFalse(response.json()["done"])
            self.assertIsNone(response.json()["completed_at"])
            self.assertEqual(response.json()["notes"], "new notes")
            self.assertEqual(response.json()["title"], "new title")

    def test_old_undo_cannot_reverse_another_completion(self):
        original = self.create()
        first = self.change(original, True, "done").json()
        reopened = self.change(first, False, "doing").json()
        second = self.change(reopened, True, "done").json()
        self.assertNotEqual(first["completed_at"], second["completed_at"])
        response = self.change(first, False, "doing")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["fields"], ["completed_at"])
        self.assertEqual(response.json()["detail"]["current"], second)
        self.assertEqual(self.client.get("/api/tasks/done").json(), [second])

    def test_lost_undo_retry_does_not_overwrite_new_stage(self):
        task = self.create()
        completed = self.change(task, True, "done").json()
        self.assertEqual(self.change(completed, False, "doing").status_code, 200)
        self.client.patch("/api/tasks/" + task["id"], json={"stage": "waiting"})
        response = self.change(completed, False, "doing")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["current"]["stage"], "waiting")

    def test_stale_completion_cannot_claim_a_newer_completion(self):
        task = self.create()
        saved = self.change(task, True, "done").json()
        response = self.change(task, True, "done")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["current"], saved)

    def test_recurring_undo_and_recomplete_preserve_one_edited_successor(self):
        task = self.create(repeat="monthly", due_date="2032-01-31")
        completed = self.change(task, True, "done").json()
        successor = completed["spawned"]
        self.client.patch("/api/tasks/" + successor["id"], json={"title": "edited future"})
        reopened = self.change(completed, False, "doing").json()
        result = self.change(reopened, True, "done")
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("spawned", result.json())
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 2)
            self.assertEqual(db.get(Task, successor["id"]).title, "edited future")
            self.assertEqual(db.get(Task, successor["id"]).due_date, "2032-02-29")

    def test_timestamp_is_only_a_readonly_status_expectation(self):
        task = self.create()
        url = "/api/tasks/" + task["id"]
        for body in (
            {"notes": "changed", "expected": {"notes": "", "completed_at": None}},
            {"done": True, "completed_at": "forged", "expected": {"done": False}},
            {"done": True, "expected": {"done": False, "completed_at": 123}},
            {"done": True, "expected": {"completed_at": None}},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.client.patch(url, json=body).status_code, 400)
        self.assertEqual(self.client.get("/api/tasks").json(), [task])

    def test_deleted_task_returns_not_found(self):
        task = self.create()
        completed = self.change(task, True, "done").json()
        self.client.delete("/api/tasks/" + task["id"])
        self.assertEqual(self.change(completed, False, "doing").status_code, 404)

    def test_legacy_stages_compare_using_the_displayed_normalization(self):
        for stage, done in (("", False), ("backlog", True), (None, False)):
            task = self.create()
            with self.db() as db:
                row = db.get(Task, task["id"])
                row.stage, row.done = stage, done
                db.commit()
            shown = next(
                row
                for row in self.client.get("/api/tasks/done" if done else "/api/tasks").json()
                if row["id"] == task["id"]
            )
            response = self.change(shown, not done, "backlog" if done else "done")
            self.assertEqual(response.status_code, 200, response.text)
