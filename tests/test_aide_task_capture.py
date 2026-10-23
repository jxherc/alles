"""Reviewed Aide replies retain their source through the existing task receipt."""

import hashlib
import uuid

from core.database import Message, Session, Task
from tests._client import ApiTest


class AideTaskCaptureTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.answer = (
            "# send the application\n\nkeep **this** detail and [source](/?doc=owned.md). 🌱"
        )
        with self.db() as db:
            session = Session(name="owned task source")
            db.add(session)
            db.flush()
            message = Message(session_id=session.id, role="assistant", content=self.answer)
            db.add(message)
            db.commit()
            self.session_id, self.message_id = session.id, message.id
        self.source = {
            "kind": "aide",
            "label": "original Aide reply",
            "excerpt": self.answer,
            "fingerprint": hashlib.sha256(self.answer.encode()).hexdigest(),
            "session_id": self.session_id,
            "message_id": self.message_id,
            "private": False,
        }

    def body(self, source=None):
        return {
            "title": "reviewed application",
            "notes": self.answer,
            "source": self.source if source is None else source,
            "request_id": str(uuid.uuid4()),
        }

    def test_acceptance_replay_completion_and_source_deletion_preserve_the_same_task(self):
        body = self.body()
        response = self.client.post("/api/tasks", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved["notes"], self.answer)
        self.assertEqual(saved["source"], self.source)
        retry = self.client.post("/api/tasks", json=body)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["id"], saved["id"])
        done = self.client.patch("/api/tasks/" + saved["id"], json={"done": True})
        self.assertEqual(done.status_code, 200, done.text)
        with self.db() as db:
            db.delete(db.get(Session, self.session_id))
            db.commit()
        replay = self.client.post("/api/tasks", json=body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["done"])
        self.assertEqual(replay.json()["source"], self.source)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 1)
            self.assertEqual(db.get(Task, saved["id"]).notes, self.answer)

    def test_explicit_private_copy_has_no_durable_conversation_or_reply_id(self):
        source = self.source | {"private": True, "session_id": "", "message_id": ""}
        response = self.client.post("/api/tasks", json=self.body(source))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["source"], source)
        self.assertEqual(response.json()["notes"], self.answer)

    def test_private_source_cannot_contain_conversation_or_reply_ids(self):
        for extra in [{"session_id": self.session_id}, {"message_id": self.message_id}]:
            source = self.source | {"private": True, "session_id": "", "message_id": ""} | extra
            response = self.client.post("/api/tasks", json=self.body(source))
            self.assertEqual(response.status_code, 422, response.text)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 0)

    def test_public_source_requires_both_safe_identifiers_and_matching_excerpt(self):
        for change in [
            {"session_id": ""},
            {"message_id": ""},
            {"message_id": "../different"},
            {"session_id": "https://example.invalid"},
            {"excerpt": "changed"},
            {"fingerprint": "0" * 64},
        ]:
            response = self.client.post("/api/tasks", json=self.body(self.source | change))
            self.assertEqual(response.status_code, 422, response.text)
        with self.db() as db:
            self.assertEqual(db.query(Task).count(), 0)

    def test_source_excerpt_is_bounded_but_complete_notes_are_preserved(self):
        raw = "🌱" * 6000 + "\n[kept link](/?doc=after-excerpt.md)\n"
        excerpt = raw[:6000]
        source = self.source | {
            "excerpt": excerpt,
            "fingerprint": hashlib.sha256(excerpt.encode()).hexdigest(),
        }
        body = self.body(source) | {"notes": raw}
        response = self.client.post("/api/tasks", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["notes"], raw)
        self.assertEqual(response.json()["source"]["excerpt"], excerpt)
        changed = self.client.post("/api/tasks", json=body | {"notes": "different"})
        self.assertEqual(changed.status_code, 409, changed.text)


if __name__ == "__main__":
    import unittest

    unittest.main()
