from tests._client import ApiTest


class TaskDueDateTests(ApiTest):
    def test_only_a_plain_day_or_day_and_time_is_saved(self):
        tid = self.client.post("/api/tasks", json={"title": "pay rent"}).json()["id"]
        for good in ("2026-10-20", "2026-10-20T09:30", "2026-10-20T09:30:00"):
            with self.subTest(good=good):
                r = self.client.patch(f"/api/tasks/{tid}", json={"due_date": good})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["due_date"], good)
        # fromisoformat takes these, but every string compare on due_date misreads them
        for bad in ("20261020", "2026-W43-1", "20261020T0900", "1020-", "2026-13-40"):
            with self.subTest(bad=bad):
                r = self.client.patch(f"/api/tasks/{tid}", json={"due_date": bad})
                self.assertEqual(r.status_code, 400, r.text)
                c = self.client.post("/api/tasks", json={"title": "x", "due_date": bad})
                self.assertEqual(c.status_code, 400, c.text)
