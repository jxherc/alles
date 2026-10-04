"""Retry a confirmed unanswered turn without duplicating context or newer history."""

import asyncio
import json
from unittest import mock

from core.database import Message, ModelEndpoint, Session
from routes import chat
from services import incognito
from tests._client import ApiTest


class ChatRetryTests(ApiTest):
    def setUp(self):
        super().setUp()
        incognito.clear_for_tests()
        self.addCleanup(incognito.clear_for_tests)
        self.settings = {
            "memory_policy": "off",
            "memory_auto_inject": False,
            "auto_compact": False,
            "agent_context_files": False,
            "agent_permission_mode": "approve",
        }
        patch = mock.patch.object(chat, "load_settings", lambda: dict(self.settings))
        patch.start()
        self.addCleanup(patch.stop)
        with self.db() as db:
            ep = ModelEndpoint(
                name="fixture", base_url="http://127.0.0.1:1", cached_models='["fixture"]'
            )
            db.add(ep)
            db.commit()
            self.endpoint = ep.id
        self.captured = []
        self.failure = True

        async def provider(messages, *args, **kwargs):
            self.captured.append(messages)
            if self.failure:
                yield {"error": "HTTP 503: synthetic unavailable model"}
            else:
                yield {"delta": "synthetic reply"}
                yield {"done": True, "usage": {}}

        patch = mock.patch("services.chat_turn.stream_chat", provider)
        patch.start()
        self.addCleanup(patch.stop)

    def session(self, private=False):
        response = self.client.post(
            "/api/sessions",
            json={
                "name": "retry fixture",
                "model": "fixture",
                "endpoint_id": self.endpoint,
                "incognito": private,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def send(self, sid, **extra):
        return self.client.post(
            "/api/chat",
            json={
                "session_id": sid,
                "message": "original question",
                "simple": True,
                **extra,
            },
        )

    def failed(self, sid):
        response = self.send(sid)
        self.assertEqual(response.status_code, 200, response.text)
        chunks = [
            json.loads(line[5:])
            for line in response.text.splitlines()
            if line.startswith("data:") and "[DONE]" not in line
        ]
        saved = next(c["saved_user"]["id"] for c in chunks if "saved_user" in c)
        self.assertIn("data: [DONE]", response.text)
        return saved

    def history(self, sid):
        return self.client.get(f"/api/sessions/{sid}/history").json()["messages"]

    def test_retry_keeps_one_prompt_in_provider_context_and_saved_history(self):
        for private in (False, True):
            with self.subTest(private=private):
                self.failure = True
                sid = self.session(private)
                pending = self.failed(sid)
                # Repeated failed retries retain the same saved turn identity.
                response = self.send(sid, retry_message_id=pending)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn(pending, response.text)
                self.failure = False
                response = self.send(sid, retry_message_id=pending)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('"saved_message"', response.text)
                users = [m for m in self.captured[-1] if m["role"] == "user"]
                self.assertEqual(users, [{"role": "user", "content": "original question"}])
                history = self.history(sid)
                self.assertEqual([m["role"] for m in history], ["user", "assistant"])
                self.assertEqual(history[0]["id"], pending)
                self.assertEqual(history[1]["content"], "synthetic reply")
                if private:
                    with self.db() as db:
                        self.assertIsNone(db.get(Session, sid))
                        self.assertEqual(db.query(Message).filter_by(session_id=sid).count(), 0)
                self.assertEqual(self.send(sid, retry_message_id=pending).status_code, 409)

    def test_stale_foreign_changed_and_running_retries_never_call_provider(self):
        sid = self.session()
        pending = self.failed(sid)
        other = self.session()
        for request in [
            {"retry_message_id": "missing"},
            {"retry_message_id": pending, "message": "changed"},
            {"retry_message_id": pending, "session_id": other},
        ]:
            before = len(self.captured)
            self.assertEqual(self.send(sid, **request).status_code, 409)
            self.assertEqual(len(self.captured), before)
        chat._streams[sid] = asyncio.Event()
        try:
            self.assertEqual(self.send(sid, retry_message_id=pending).status_code, 409)
        finally:
            chat._streams.pop(sid)
        with self.db() as db:
            db.add(Message(session_id=sid, role="user", content="newer question"))
            db.commit()
        before = len(self.captured)
        self.assertEqual(self.send(sid, retry_message_id=pending).status_code, 409)
        self.assertEqual(len(self.captured), before)
        self.assertEqual(self.history(sid)[-1]["content"], "newer question")

    def test_rechecks_history_after_awaited_context_assembly(self):
        sid = self.session()
        pending = self.failed(sid)
        self.settings.update(memory_policy="ask", memory_auto_inject=True)

        def memories(*args, **kwargs):
            with self.db() as db:
                db.add(Message(session_id=sid, role="user", content="arrived during context"))
                db.commit()
            return "", []

        before = len(self.captured)
        with mock.patch.object(chat, "inject_memories", memories):
            response = self.send(sid, retry_message_id=pending)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(self.captured), before)
        self.assertNotIn(sid, chat._streams)

    def test_retry_rechecks_document_hash_before_any_provider_call(self):
        sid = self.session()
        pending = self.failed(sid)
        before = len(self.captured)
        with mock.patch.object(
            chat,
            "_vault_document_context",
            side_effect=chat.ApiError(409, "document_changed", "source changed"),
        ):
            response = self.send(
                sid,
                retry_message_id=pending,
                context_scope={"kind": "vault_document", "path": "note.md", "expected_hash": "old"},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.captured), before)
        self.assertEqual(len(self.history(sid)), 1)
