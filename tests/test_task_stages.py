from core.database import Task
from tests._client import ApiTest


class TaskStageApiTest(ApiTest):
    def test_new_task_defaults_to_backlog_without_changing_done_contract(self):
        task = self.client.post("/api/tasks", json={"title": "one"}).json()
        self.assertEqual(task["stage"], "backlog")
        self.assertFalse(task["done"])

    def test_doing_and_waiting_remain_active(self):
        task = self.client.post("/api/tasks", json={"title": "work", "stage": "doing"}).json()
        self.assertEqual(task["stage"], "doing")
        self.assertFalse(task["done"])
        waiting = self.client.patch(f"/api/tasks/{task['id']}", json={"stage": "waiting"}).json()
        self.assertEqual(waiting["stage"], "waiting")
        self.assertFalse(waiting["done"])

    def test_stage_done_and_legacy_done_stay_in_sync(self):
        task = self.client.post("/api/tasks", json={"title": "finish"}).json()
        done = self.client.patch(f"/api/tasks/{task['id']}", json={"stage": "done"}).json()
        self.assertTrue(done["done"])
        self.assertEqual(done["stage"], "done")

        reopened = self.client.patch(f"/api/tasks/{task['id']}", json={"done": False}).json()
        self.assertFalse(reopened["done"])
        self.assertEqual(reopened["stage"], "backlog")

        legacy_done = self.client.patch(f"/api/tasks/{task['id']}", json={"done": True}).json()
        self.assertTrue(legacy_done["done"])
        self.assertEqual(legacy_done["stage"], "done")

    def test_invalid_stage_fails_without_changing_task(self):
        task = self.client.post("/api/tasks", json={"title": "safe"}).json()
        response = self.client.patch(f"/api/tasks/{task['id']}", json={"stage": "whatever"})
        self.assertEqual(response.status_code, 400)
        db = self.db()
        saved = db.get(Task, task["id"])
        self.assertEqual(saved.stage, "backlog")
        self.assertFalse(saved.done)
        db.close()

    def test_recurring_completion_spawns_a_backlog_task(self):
        task = self.client.post(
            "/api/tasks",
            json={
                "title": "repeat",
                "repeat": "daily",
                "due_date": "2026-07-12",
                "stage": "doing",
            },
        ).json()
        completed = self.client.patch(f"/api/tasks/{task['id']}", json={"stage": "done"}).json()
        self.assertEqual(completed["stage"], "done")
        self.assertEqual(completed["spawned"]["stage"], "backlog")
        self.assertFalse(completed["spawned"]["done"])
