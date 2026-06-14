from datetime import datetime, timedelta

from tests._client import ApiTest


class RemindersApiTest(ApiTest):
    def test_create_list_delete(self):
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        r = self.client.post("/api/reminders", json={"text": "call mom", "trigger_at": future}).json()
        self.assertEqual(r["text"], "call mom")
        self.assertFalse(r["fired"])
        self.assertEqual([x["id"] for x in self.client.get("/api/reminders").json()], [r["id"]])
        self.assertEqual(self.client.delete(f"/api/reminders/{r['id']}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/reminders").json(), [])

    def test_bad_trigger_at_400(self):
        self.assertEqual(self.client.post("/api/reminders", json={"text": "x", "trigger_at": "not-a-date"}).status_code, 400)

    def test_due_marks_fired_and_drops_from_list(self):
        past = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
        self.client.post("/api/reminders", json={"text": "overdue", "trigger_at": past})
        due = self.client.get("/api/reminders/due").json()
        self.assertEqual([x["text"] for x in due], ["overdue"])
        # marked fired → no longer in the active list, and not due again
        self.assertEqual(self.client.get("/api/reminders").json(), [])
        self.assertEqual(self.client.get("/api/reminders/due").json(), [])

    def test_delete_missing_404(self):
        self.assertEqual(self.client.delete("/api/reminders/nope").status_code, 404)
