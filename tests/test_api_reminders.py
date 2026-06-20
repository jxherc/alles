from datetime import datetime, timedelta

from tests._client import ApiTest


class RemindersApiTest(ApiTest):
    def test_create_list_delete(self):
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        r = self.client.post(
            "/api/reminders", json={"text": "call mom", "trigger_at": future}
        ).json()
        self.assertEqual(r["text"], "call mom")
        self.assertFalse(r["fired"])
        self.assertEqual([x["id"] for x in self.client.get("/api/reminders").json()], [r["id"]])
        self.assertEqual(self.client.delete(f"/api/reminders/{r['id']}").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/reminders").json(), [])

    def test_bad_trigger_at_400(self):
        self.assertEqual(
            self.client.post(
                "/api/reminders", json={"text": "x", "trigger_at": "not-a-date"}
            ).status_code,
            400,
        )

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

    def test_future_not_in_due(self):
        future = (datetime.utcnow() + timedelta(hours=2)).isoformat()
        self.client.post("/api/reminders", json={"text": "not yet", "trigger_at": future})
        self.assertEqual(self.client.get("/api/reminders/due").json(), [])

    def test_message_type_not_in_due(self):
        past = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
        self.client.post(
            "/api/reminders", json={"text": "msg", "trigger_at": past, "type": "message"}
        )
        self.assertEqual(self.client.get("/api/reminders/due").json(), [])
        # but it still shows in the active list since not fired
        lst = self.client.get("/api/reminders").json()
        self.assertEqual(len(lst), 1)
        self.assertEqual(lst[0]["type"], "message")

    def test_multiple_ordered_by_trigger_at(self):
        t1 = (datetime.utcnow() + timedelta(hours=3)).isoformat()
        t2 = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        t3 = (datetime.utcnow() + timedelta(hours=2)).isoformat()
        self.client.post("/api/reminders", json={"text": "third", "trigger_at": t1})
        self.client.post("/api/reminders", json={"text": "first", "trigger_at": t2})
        self.client.post("/api/reminders", json={"text": "second", "trigger_at": t3})
        texts = [x["text"] for x in self.client.get("/api/reminders").json()]
        self.assertEqual(texts, ["first", "second", "third"])

    def test_response_has_all_fields(self):
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        r = self.client.post(
            "/api/reminders",
            json={"text": "check fields", "trigger_at": future, "session_id": "abc"},
        ).json()
        for field in ("id", "text", "trigger_at", "type", "session_id", "fired", "created_at"):
            self.assertIn(field, r)
        self.assertEqual(r["type"], "reminder")
        self.assertEqual(r["session_id"], "abc")
        self.assertFalse(r["fired"])

    def test_create_custom_type(self):
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        r = self.client.post(
            "/api/reminders", json={"text": "hey", "trigger_at": future, "type": "message"}
        ).json()
        self.assertEqual(r["type"], "message")

    def test_create_with_session_id(self):
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        r = self.client.post(
            "/api/reminders", json={"text": "hi", "trigger_at": future, "session_id": "sess-xyz"}
        ).json()
        self.assertEqual(r["session_id"], "sess-xyz")

    def test_delete_one_of_two(self):
        future = (datetime.utcnow() + timedelta(days=1)).isoformat()
        a = self.client.post("/api/reminders", json={"text": "keep", "trigger_at": future}).json()
        b = self.client.post("/api/reminders", json={"text": "drop", "trigger_at": future}).json()
        self.client.delete(f"/api/reminders/{b['id']}")
        ids = [x["id"] for x in self.client.get("/api/reminders").json()]
        self.assertIn(a["id"], ids)
        self.assertNotIn(b["id"], ids)
