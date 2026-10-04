"""Retry a confirmed unanswered turn without duplicating context or newer history."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest import mock

from fastapi import Request

from core.api_errors import ApiError
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

    def test_full_history_window_is_identical_on_retry(self):
        self.settings.update(context_limit=3, session_context_inject=False)
        for private in (False, True):
            with self.subTest(private=private):
                sid = self.session(private)
                now = datetime.now(UTC).replace(tzinfo=None)
                records = [
                    dict(role=role, content=text, timestamp=now - timedelta(minutes=5 - i))
                    for i, (role, text) in enumerate(
                        [
                            ("user", "earlier question"),
                            ("assistant", "earlier answer"),
                            ("user", "recent question"),
                            ("assistant", "recent answer"),
                        ]
                    )
                ]
                if private:
                    incognito.get_session(sid).messages.extend(
                        incognito.IncognitoMessage(**row) for row in records
                    )
                else:
                    with self.db() as db:
                        db.add_all(Message(session_id=sid, **row) for row in records)
                        db.commit()
                pending = self.failed(sid)
                original = [m for m in self.captured[-1] if m["role"] != "system"]
                self.assertEqual(len(original), 4)
                response = self.send(sid, retry_message_id=pending)
                self.assertEqual(response.status_code, 200)
                retried = [m for m in self.captured[-1] if m["role"] != "system"]
                self.assertEqual(retried, original)

    def test_waiting_normal_send_does_not_replace_retry_stream(self):
        for private in (False, True):
            with self.subTest(private=private):
                self.settings["auto_compact"] = False
                sid = self.session(private)
                pending = self.failed(sid)
                upload = (
                    incognito.put_upload("local.txt", "text/plain", b"local synthetic attachment")
                    if private
                    else None
                )
                self.settings.update(auto_compact=True, compact_threshold=1)

                async def scenario():
                    waiting, release = asyncio.Event(), asyncio.Event()
                    responses = []

                    async def compact(messages, *args, **kwargs):
                        if messages[-1]["content"].startswith("newer question"):
                            waiting.set()
                            await asyncio.wait_for(release.wait(), timeout=3)
                        return messages

                    request = Request({"type": "http", "headers": []})
                    with (
                        self.db() as ordinary_db,
                        self.db() as retry_db,
                        mock.patch("services.llm.compact_messages", compact),
                    ):
                        task = asyncio.create_task(
                            chat.chat(
                                chat.ChatRequest(
                                    session_id=sid,
                                    message="newer question",
                                    simple=True,
                                    file_ids=[upload.id] if upload else [],
                                ),
                                request,
                                ordinary_db,
                            )
                        )
                        try:
                            await asyncio.wait_for(waiting.wait(), timeout=3)
                            retry_response = await chat.chat(
                                chat.ChatRequest(
                                    session_id=sid,
                                    message="original question",
                                    retry_message_id=pending,
                                    simple=True,
                                ),
                                request,
                                retry_db,
                            )
                            responses.append(retry_response)
                            owner = chat._streams[sid]
                            release.set()
                            outcome = (await asyncio.gather(task, return_exceptions=True))[0]
                            retained = chat._streams.get(sid) is owner
                            if not isinstance(outcome, Exception):
                                responses.append(outcome)
                        finally:
                            release.set()
                            if not task.done():
                                task.cancel()
                                await asyncio.gather(task, return_exceptions=True)
                            for response in responses:
                                async for _ in response.body_iterator:
                                    pass
                            chat._streams.pop(sid, None)
                    self.assertIsInstance(
                        outcome, ApiError, "ordinary send claimed an occupied stream"
                    )
                    self.assertEqual(outcome.status_code, 409)
                    self.assertTrue(retained, "ordinary send replaced the retry stop event")
                    if upload:
                        self.assertIs(incognito.get_upload(upload.id), upload)

                asyncio.run(scenario())

    def test_busy_foreground_and_background_reject_without_touching_owner(self):
        sid = self.session()
        owner = asyncio.Event()
        chat._streams[sid] = owner
        calls = []

        async def stream(*args, **kwargs):
            calls.append(args)
            yield {"done": True}

        try:
            with mock.patch.object(chat, "_stream_and_save", stream):
                for endpoint in ("/api/chat", "/api/agent/background"):
                    response = self.client.post(
                        endpoint,
                        json={
                            "session_id": sid,
                            "message": "not accepted while busy",
                            "simple": True,
                        },
                    )
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(response.json()["code"], "turn_in_progress")
                    self.assertIs(chat._streams.get(sid), owner)
                self.assertEqual(calls, [])
        finally:
            chat._streams.pop(sid, None)
