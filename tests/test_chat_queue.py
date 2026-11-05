"""Messages sent while aide replies wait in the task and are answered by the next turn."""

import json
import unittest
from unittest import mock

from core.database import Message, ModelEndpoint, QueuedMessage
from routes import chat
from tests._client import ApiTest


class ChatQueueTests(ApiTest):
    def setUp(self):
        super().setUp()
        # the live engine turns this on for every connection; the test engine does not
        with self.eng.connect() as conn:
            conn.exec_driver_sql("pragma foreign_keys=on")
        settings = {
            "memory_policy": "off",
            "memory_auto_inject": False,
            "auto_compact": False,
            "agent_context_files": False,
            "agent_permission_mode": "approve",
        }
        patch = mock.patch.object(chat, "load_settings", lambda: dict(settings))
        patch.start()
        self.addCleanup(patch.stop)
        with self.db() as db:
            ep = ModelEndpoint(
                name="fixture", base_url="http://127.0.0.1:1", cached_models='["fixture"]'
            )
            db.add(ep)
            db.commit()
            self.endpoint = ep.id
        self.seen = []

        async def provider(messages, *args, **kwargs):
            self.seen.append(messages[-1]["content"])
            yield {"delta": "synthetic reply"}
            yield {"done": True, "usage": {}}

        patch = mock.patch("services.chat_turn.stream_chat", provider)
        patch.start()
        self.addCleanup(patch.stop)
        self.sid = self.session()

    def session(self, private=False):
        response = self.client.post(
            "/api/sessions",
            json={
                "name": "queue fixture",
                "model": "fixture",
                "endpoint_id": self.endpoint,
                "incognito": private,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def queue(self, text, sid=None):
        return self.client.post(
            "/api/chat/queue", json={"session_id": sid or self.sid, "message": text}
        )

    def waiting(self):
        return self.client.get(f"/api/chat/queue/{self.sid}").json()["queued"]

    def test_waiting_messages_keep_their_order_and_show_in_history(self):
        for text in ("one", "two", "three"):
            self.assertEqual(self.queue(text).status_code, 200)
        self.assertEqual([m["message"] for m in self.waiting()], ["one", "two", "three"])
        history = self.client.get(f"/api/sessions/{self.sid}/history").json()
        self.assertEqual([m["message"] for m in history["queued"]], ["one", "two", "three"])
        self.assertEqual(history["messages"], [])

    def test_a_waiting_message_can_be_removed_before_it_is_answered(self):
        first = self.queue("keep").json()["id"]
        second = self.queue("drop").json()["id"]
        response = self.client.delete(f"/api/chat/queue/{self.sid}/{second}")
        self.assertEqual(response.json(), {"removed": True})
        self.assertEqual([m["id"] for m in self.waiting()], [first])
        again = self.client.delete(f"/api/chat/queue/{self.sid}/{second}")
        self.assertEqual(again.json(), {"removed": False})

    def test_the_next_turn_answers_them_together_and_they_stop_waiting(self):
        ids = [self.queue(text).json()["id"] for text in ("one", "two")]
        response = self.client.post(
            "/api/chat",
            json={
                "session_id": self.sid,
                "message": "one\n\ntwo",
                "simple": True,
                "queued_ids": ids,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("synthetic reply", response.text)
        self.assertEqual(self.waiting(), [])
        self.assertTrue(self.seen[-1].endswith("one\n\ntwo"))
        with self.db() as db:
            rows = db.query(Message).filter(Message.session_id == self.sid).all()
        self.assertEqual([m.role for m in rows], ["user", "assistant"])
        self.assertEqual(rows[0].content, "one\n\ntwo")

    def test_messages_taken_elsewhere_are_not_sent_a_second_time(self):
        ids = [self.queue("once").json()["id"]]
        body = {"session_id": self.sid, "message": "once", "simple": True, "queued_ids": ids}
        self.assertEqual(self.client.post("/api/chat", json=body).status_code, 200)
        again = self.client.post("/api/chat", json=body)
        self.assertEqual(again.status_code, 409, again.text)
        self.assertEqual(again.json()["code"], "queue_changed")
        with self.db() as db:
            users = db.query(Message).filter_by(session_id=self.sid, role="user").count()
        self.assertEqual(users, 1)

    def test_a_refused_turn_leaves_them_waiting(self):
        ids = [self.queue("stay").json()["id"]]
        body = {"session_id": self.sid, "message": "stay", "simple": True, "queued_ids": ids}
        event = mock.Mock()
        with mock.patch.dict(chat._streams, {self.sid: event}):
            refused = self.client.post("/api/chat", json=body)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual([m["id"] for m in self.waiting()], ids)

    def test_a_running_turn_is_reported_so_the_page_can_wait_for_it(self):
        with mock.patch.dict(chat._streams, {self.sid: mock.Mock()}):
            state = self.client.get(f"/api/chat/queue/{self.sid}").json()
        self.assertTrue(state["answering"])
        self.assertFalse(self.client.get(f"/api/chat/queue/{self.sid}").json()["answering"])

    def test_private_tasks_never_write_the_queue_to_the_database(self):
        private = self.session(private=True)
        self.assertEqual(self.queue("secret", private).status_code, 400)
        with self.db() as db:
            self.assertEqual(db.query(QueuedMessage).count(), 0)
        history = self.client.get(f"/api/sessions/{private}/history").json()
        self.assertEqual(history["queued"], [])

    def test_empty_and_too_many_are_refused(self):
        self.assertEqual(self.queue("   ").status_code, 400)
        for n in range(chat._QUEUE_LIMIT):
            self.assertEqual(self.queue(f"m{n}").status_code, 200)
        full = self.queue("one more")
        self.assertEqual(full.status_code, 409)
        self.assertEqual(json.loads(full.text)["code"], "queue_full")

    def test_deleting_the_task_deletes_what_waited_in_it(self):
        self.queue("gone with it")
        self.assertEqual(self.client.delete(f"/api/sessions/{self.sid}").status_code, 200)
        with self.db() as db:
            self.assertEqual(db.query(QueuedMessage).count(), 0)


if __name__ == "__main__":
    unittest.main()
