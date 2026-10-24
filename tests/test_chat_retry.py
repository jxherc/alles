"""Retry a confirmed unanswered turn without duplicating context or newer history."""

import asyncio
import json
import time
import unittest
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

    def test_failed_response_keeps_exact_retry_options_until_success(self):
        for private in (False, True):
            with self.subTest(private=private):
                self.failure = True
                sid = self.session(private)
                pending = self.failed(sid)
                saved = self.history(sid)[0]
                recovery = saved["meta"]["response_recovery"]
                self.assertEqual(recovery["status"], "failed")
                self.assertTrue(recovery["request"]["simple"])
                self.assertNotIn("message", recovery["request"])
                self.assertNotIn("session_id", recovery["request"])
                self.assertNotIn("HTTP 503", json.dumps(saved["meta"]))
                # A persisted retry cannot silently replace the original scope or controls.
                before = len(self.captured)
                changed = self.send(sid, retry_message_id=pending, mode="agent")
                self.assertEqual(changed.status_code, 409)
                self.assertEqual(len(self.captured), before)
                self.failure = False
                response = self.send(sid, retry_message_id=pending)
                self.assertEqual(response.status_code, 200)
                history = self.history(sid)
                self.assertEqual([m["role"] for m in history], ["user", "assistant"])
                self.assertNotIn("response_recovery", history[0]["meta"])

    def test_partial_clean_eof_keeps_incomplete_history_without_replay(self):
        for private in (False, True):
            for complete in (False, True):
                with self.subTest(private=private, complete=complete):
                    sid = self.session(private)

                    async def provider(*args, **kwargs):
                        yield {"delta": "owned partial answer 草稿"}
                        if complete:
                            yield {"done": True, "usage": {}}

                    with mock.patch("services.chat_turn.stream_chat", provider):
                        response = self.send(sid)
                    self.assertEqual(response.status_code, 200, response.text)
                    history = self.history(sid)
                    self.assertEqual([m["role"] for m in history], ["user", "assistant"])
                    saved = history[-1]
                    self.assertEqual(saved["content"], "owned partial answer 草稿")
                    if complete:
                        self.assertNotIn("response_recovery", saved["meta"])
                        self.assertNotIn('"error"', response.text)
                    else:
                        recovery = saved["meta"].get("response_recovery", {})
                        self.assertEqual(recovery.get("status"), "incomplete")
                        self.assertNotIn("request", recovery)
                        self.assertIn('"error"', response.text)
                    before = len(self.captured)
                    self.assertEqual(
                        self.send(sid, retry_message_id=history[0]["id"]).status_code, 409
                    )
                    self.assertEqual(len(self.captured), before)
                    if private:
                        with self.db() as db:
                            self.assertIsNone(db.get(Session, sid))
                            self.assertEqual(db.query(Message).filter_by(session_id=sid).count(), 0)

    def test_partial_empty_and_tool_outcomes_do_not_offer_replay(self):
        for kind in ("partial", "empty", "tool"):
            for private in (False, True):
                with self.subTest(kind=kind, private=private):
                    sid = self.session(private)

                    async def provider(messages, *args, **kwargs):
                        if kind == "partial":
                            yield {"delta": "partial synthetic answer"}
                        if kind == "tool":
                            yield {
                                "tool_start": {
                                    "call_id": "synthetic",
                                    "name": "synthetic_tool",
                                    "args": {},
                                }
                            }
                        if kind == "empty":
                            yield {"done": True, "usage": {}}
                        else:
                            yield {"error": "synthetic provider failure"}

                    target = (
                        "services.chat_turn.run_agent"
                        if kind == "tool"
                        else "services.chat_turn.stream_chat"
                    )
                    with mock.patch(target, provider):
                        response = self.send(
                            sid, mode="agent" if kind == "tool" else "chat", simple=kind != "tool"
                        )
                    self.assertEqual(response.status_code, 200)
                    history = self.history(sid)
                    recovery = history[-1]["meta"]["response_recovery"]
                    self.assertEqual(
                        recovery["status"], "incomplete" if kind == "empty" else "failed"
                    )
                    self.assertNotIn("request", recovery)
                    pending = history[0]["id"]
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
        scope = {"kind": "vault_document", "path": "note.md", "expected_hash": "old"}
        with mock.patch.object(chat, "_vault_document_context", return_value=("", None)):
            self.assertEqual(self.send(sid, context_scope=scope).status_code, 200)
        pending = self.history(sid)[0]["id"]
        before = len(self.captured)
        with mock.patch.object(
            chat,
            "_vault_document_context",
            side_effect=chat.ApiError(409, "document_changed", "source changed"),
        ) as read_scope:
            response = self.send(
                sid,
                retry_message_id=pending,
                context_scope=scope,
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "document_changed")
        read_scope.assert_called_once()
        self.assertEqual(len(self.captured), before)
        self.assertEqual(len(self.history(sid)), 1)

    def test_private_consumed_files_and_legacy_unanswered_turns_cannot_replay(self):
        sid = self.session(True)
        upload = incognito.put_upload("local.txt", "text/plain", b"synthetic private file")
        response = self.send(sid, file_ids=[upload.id])
        self.assertEqual(response.status_code, 200)
        saved = self.history(sid)[0]
        self.assertNotIn("request", saved["meta"]["response_recovery"])
        self.assertIsNone(incognito.get_upload(upload.id))
        before = len(self.captured)
        self.assertEqual(
            self.send(sid, file_ids=[upload.id], retry_message_id=saved["id"]).status_code, 409
        )
        sid = self.session()
        with self.db() as db:
            pending = Message(session_id=sid, role="user", content="original question")
            db.add(pending)
            db.commit()
            pending_id = pending.id
        self.assertEqual(self.send(sid, retry_message_id=pending_id).status_code, 409)
        self.assertEqual(len(self.captured), before)

    def test_closing_after_error_before_finalization_does_not_record_safe_retry(self):
        for private in (False, True):
            with self.subTest(private=private):
                sid = self.session(private)
                with self.db() as db:
                    endpoint = db.get(ModelEndpoint, self.endpoint)

                    async def scenario():
                        stream = chat._stream_and_save(
                            sid,
                            "original question",
                            [],
                            endpoint,
                            "fixture",
                            asyncio.Event(),
                            self.db,
                            incognito=private,
                            mode="chat",
                            settings={"response_retry_request": {"simple": True}},
                        )
                        self.assertIn("error", await anext(stream))
                        await stream.aclose()

                    asyncio.run(scenario())
                recovery = self.history(sid)[-1]["meta"]["response_recovery"]
                self.assertEqual(recovery["status"], "failed")
                self.assertNotIn("request", recovery)

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
                self.settings.update(auto_compact=True, compact_threshold=1, compact_min_chars=0)

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

    def events(self, response):
        return [
            json.loads(line[5:])
            for line in response.text.splitlines()
            if line.startswith("data:") and "[DONE]" not in line
        ]

    def ask_again(self, sid, message_id, *, edit=None, newest=None, **extra):
        # what the tab sends for regenerate (stored words) or edit (new words)
        history = self.history(sid)
        body = {"newest_id": history[-1]["id"] if newest is None else newest}
        if edit is None:
            words = next((m["content"] for m in history if m["id"] == message_id), "")
            body.update(regenerate_message_id=message_id, message=words)
        else:
            body.update(edit_message_id=message_id, message=edit)
        return self.send(sid, **{**body, **extra})

    def test_edit_and_regenerate_answer_the_stored_message_once(self):
        self.failure = False
        for private in (False, True):
            with self.subTest(private=private):
                sid = self.session(private)
                first = self.send(sid)
                self.assertEqual(first.status_code, 200, first.text)
                events = self.events(first)
                # the first event names both rows, before any text: a stopped reply knows them too
                turn = events[0]["turn"]
                asked = next(e["saved_user"]["id"] for e in events if "saved_user" in e)
                answer = next(e["saved_message"]["id"] for e in events if "saved_message" in e)
                self.assertEqual((turn["user_id"], turn["assistant_id"]), (asked, answer))
                self.assertEqual([m["id"] for m in self.history(sid)], [asked, answer])

                # regenerate: same words, the old reply goes, the question is reused
                again = self.ask_again(sid, asked)
                self.assertEqual(again.status_code, 200, again.text)
                turn = self.events(again)[0]["turn"]
                self.assertEqual(turn["user_id"], asked)
                users = [m for m in self.captured[-1] if m["role"] == "user"]
                self.assertEqual(users, [{"role": "user", "content": "original question"}])
                history = self.history(sid)
                self.assertEqual([m["id"] for m in history], [asked, turn["assistant_id"]])
                self.assertNotEqual(history[1]["id"], answer)

                # edit: new words replace the message, everything after it goes
                edited = self.ask_again(sid, asked, edit="edited question")
                self.assertEqual(edited.status_code, 200, edited.text)
                users = [m for m in self.captured[-1] if m["role"] == "user"]
                self.assertEqual(users, [{"role": "user", "content": "edited question"}])
                history = self.history(sid)
                self.assertEqual(
                    [(m["role"], m["content"]) for m in history],
                    [("user", "edited question"), ("assistant", "synthetic reply")],
                )
                self.assertEqual(history[0]["id"], asked)

                # refusals change nothing and never reach the model
                before = len(self.captured)
                cases = [
                    ({"newest": answer}, 409, "history_moved"),  # a reply this tab never saw
                    ({"edit": "x", "newest": ""}, 409, "history_moved"),
                    ({"edit": "   "}, 400, "empty_message"),
                ]
                for extra, status, code in cases:
                    response = self.ask_again(sid, asked, **extra)
                    self.assertEqual(response.status_code, status, (extra, response.text))
                    self.assertEqual(response.json()["code"], code)
                gone = self.ask_again(sid, history[1]["id"], edit="not a question")
                self.assertEqual(gone.status_code, 404, gone.text)
                self.assertEqual(gone.json()["detail"], "this message is gone. reload the task.")
                # no cut while a reply is still running
                chat._streams[sid] = asyncio.Event()
                try:
                    busy = self.ask_again(sid, asked, edit="too soon")
                finally:
                    chat._streams.pop(sid, None)
                self.assertEqual(busy.status_code, 409, busy.text)
                self.assertEqual(len(self.captured), before)
                self.assertEqual(self.history(sid), history)
                if private:
                    with self.db() as db:
                        self.assertIsNone(db.get(Session, sid))
                        self.assertEqual(db.query(Message).filter_by(session_id=sid).count(), 0)

    def test_a_tab_that_missed_later_turns_cannot_cut_them(self):
        self.failure = False
        for private in (False, True):
            with self.subTest(private=private):
                sid = self.session(private)
                # tab b shows the first turn; tab a then sends a second one
                first = self.events(self.send(sid))
                asked, seen = first[0]["turn"]["user_id"], first[0]["turn"]["assistant_id"]
                self.assertEqual(self.send(sid, message="tt4").status_code, 200)
                history = self.history(sid)
                self.assertEqual(len(history), 4)
                before = len(self.captured)
                # b regenerates its last visible reply: refused, tt4 stays
                stale = self.ask_again(sid, asked, newest=seen)
                self.assertEqual(stale.status_code, 409, stale.text)
                self.assertEqual(stale.json()["code"], "history_moved")
                self.assertEqual(
                    stale.json()["detail"], "this task changed in another tab. reload it first."
                )
                self.assertEqual(self.history(sid), history)
                self.assertEqual(len(self.captured), before)
                # once b has seen tt4 the edit goes through and cuts it
                fresh = self.ask_again(sid, asked, edit="first, edited")
                self.assertEqual(fresh.status_code, 200, fresh.text)
                self.assertEqual(
                    [m["content"] for m in self.history(sid)], ["first, edited", "synthetic reply"]
                )

    def test_a_stopped_reply_is_kept_under_the_id_its_stream_named_first(self):
        self.failure = False
        for private in (False, True):
            with self.subTest(private=private):
                sid = self.session(private)
                stops = []

                async def stopped(messages, *args, **kwargs):
                    self.captured.append(messages)
                    yield {"delta": "half an answer"}
                    chat._streams[sid].set()  # the stop button, mid-reply
                    stops.append(sid)
                    yield {"delta": " never shown"}

                turns = []
                with mock.patch("services.chat_turn.stream_chat", stopped):
                    for _ in range(2):
                        turns.append(self.events(self.send(sid, message="slow same"))[0]["turn"])
                self.assertEqual(len(stops), 2)
                history = self.history(sid)
                # same words twice, each pair under the ids its own stream named
                expected = [i for t in turns for i in (t["user_id"], t["assistant_id"])]
                self.assertEqual([m["id"] for m in history], expected)
                self.assertTrue(all(m["meta"].get("interrupted") for m in history[1::2]))
                # editing the first copy cuts after the first copy, wherever the words repeat
                edited = self.ask_again(sid, turns[0]["user_id"], edit="first stopped, edited")
                self.assertEqual(edited.status_code, 200, edited.text)
                self.assertEqual(
                    [(m["id"], m["content"]) for m in self.history(sid)][0],
                    (turns[0]["user_id"], "first stopped, edited"),
                )
                self.assertEqual(len(self.history(sid)), 2)

    def test_nothing_is_cut_when_the_answer_is_refused_after_the_checks(self):
        self.failure = False
        sid = self.session()
        self.assertEqual(self.send(sid).status_code, 200)
        history = self.history(sid)
        before = len(self.captured)
        # context building awaits; a turn that lands meanwhile makes the edit stale
        self.settings.update(memory_policy="ask", memory_auto_inject=True)

        def memories(*args, **kwargs):
            with self.db() as db:
                db.add(Message(session_id=sid, role="user", content="arrived during context"))
                db.commit()
            return "", []

        with mock.patch.object(chat, "inject_memories", memories):
            moved = self.ask_again(sid, history[0]["id"], edit="edited while it moved")
        self.assertEqual(moved.status_code, 409, moved.text)
        self.assertEqual(moved.json()["code"], "history_moved")
        after = self.history(sid)
        self.assertEqual([m["id"] for m in after[:2]], [m["id"] for m in history])
        self.assertEqual(after[0]["content"], "original question")
        self.assertEqual(len(self.captured), before)
        self.assertNotIn(sid, chat._streams)

    def test_an_edit_drops_a_reply_stamped_the_same_moment_as_its_question(self):
        # a coarse clock can stamp a question and its reply identically: the cut goes by row
        # order, so the stale reply still goes
        self.failure = False
        sid = self.session()
        stamp = datetime(2026, 6, 1, 12, 0, 0)
        with self.db() as db:
            question = Message(session_id=sid, role="user", content="q", timestamp=stamp)
            reply = Message(session_id=sid, role="assistant", content="old answer", timestamp=stamp)
            db.add_all([question, reply])
            db.commit()
            asked, old = question.id, reply.id
        response = self.ask_again(sid, asked, edit="q2", newest=old)
        self.assertEqual(response.status_code, 200, response.text)
        history = self.history(sid)
        self.assertEqual([(m["id"], m["content"]) for m in history][0], (asked, "q2"))
        self.assertNotIn(old, [m["id"] for m in history])
        self.assertEqual(len(history), 2)

    def test_regenerate_keeps_the_old_answer_until_a_new_one_has_words(self):
        self.failure = False
        for private in (False, True):
            with self.subTest(private=private):
                sid = self.session(private)
                self.send(sid)
                self.send(sid, message="second question")
                before = self.history(sid)
                asked = before[0]["id"]
                # the endpoint is down: nothing changes, no empty row, nothing to recover
                self.failure = True
                down = self.ask_again(sid, asked)
                self.assertEqual(down.status_code, 200, down.text)
                self.assertIn("synthetic unavailable model", down.text)
                self.assertEqual(self.history(sid), before)
                self.failure = False

                # stopped before any words came: the same
                async def stopped_at_once(messages, *args, **kwargs):
                    self.captured.append(messages)
                    chat._streams[sid].set()
                    yield {"delta": "never shown"}

                with mock.patch("services.chat_turn.stream_chat", stopped_at_once):
                    early = self.ask_again(sid, asked)
                self.assertEqual(early.status_code, 200, early.text)
                self.assertEqual(self.history(sid), before)

                # a real answer replaces the old one and the turns after it, nothing else
                good = self.ask_again(sid, asked)
                self.assertEqual(good.status_code, 200, good.text)
                after = self.history(sid)
                self.assertEqual([m["id"] for m in after][0], asked)
                self.assertEqual(len(after), 2)
                self.assertEqual(after[1]["id"], self.events(good)[0]["turn"]["assistant_id"])

    def test_an_edit_stopped_before_any_words_leaves_no_empty_reply(self):
        self.failure = False
        for private in (False, True):
            with self.subTest(private=private):
                sid = self.session(private)
                self.send(sid)
                asked = self.history(sid)[0]["id"]

                async def stopped_at_once(messages, *args, **kwargs):
                    self.captured.append(messages)
                    chat._streams[sid].set()
                    yield {"delta": "never shown"}

                with mock.patch("services.chat_turn.stream_chat", stopped_at_once):
                    edited = self.ask_again(sid, asked, edit="new words")
                self.assertEqual(edited.status_code, 200, edited.text)
                history = self.history(sid)
                # the edit stands (its words changed the question); no empty interrupted reply
                self.assertEqual(
                    [(m["role"], m["content"]) for m in history], [("user", "new words")]
                )

    def test_regenerate_asks_the_stored_words_whatever_the_tab_sent(self):
        # stored with \r\n; the page draws \n. regenerate must not be refused over that
        self.failure = False
        sid = self.session()
        with self.db() as db:
            question = Message(session_id=sid, role="user", content="line one\r\nline two")
            db.add(question)
            db.commit()
            db.add(Message(session_id=sid, role="assistant", content="old"))
            db.commit()
        history = self.history(sid)
        asked = history[0]["id"]
        again = self.ask_again(sid, asked, message="line one\nline two")
        self.assertEqual(again.status_code, 200, again.text)
        users = [m for m in self.captured[-1] if m["role"] == "user"]
        self.assertEqual(users[-1]["content"], "line one\r\nline two")
        # an edit that only differs by line endings asks the same question: kept as stored
        history = self.history(sid)
        same = self.ask_again(sid, asked, edit="line one\nline two ")
        self.assertEqual(same.status_code, 200, same.text)
        self.assertEqual(self.history(sid)[0]["content"], "line one\r\nline two")

    def test_an_edit_never_cuts_a_row_written_after_the_newest_it_saw(self):
        # a writer in a worker thread could land a row right after the check: the cut stops at
        # the newest row the tab saw
        sid = self.session()
        with self.db() as db:
            rows = [
                Message(session_id=sid, role=role, content=text)
                for role, text in (("user", "q"), ("assistant", "a"), ("user", "late"))
            ]
            for row in rows:
                db.add(row)
                db.commit()
            session = db.get(Session, sid)
            chat._cut_after(session, db, rows[0], "q edited", rows[1].id)
            left = [
                m.content
                for m in db.query(Message).filter_by(session_id=sid).order_by(Message.timestamp)
            ]
        self.assertEqual(left, ["q edited", "late"])

    def test_a_claim_waits_for_a_writer_and_writers_wait_for_a_turn(self):
        sid = "owned-task"
        done = []
        # a turn runs: the write is held for its end, in order
        stop = asyncio.Event()
        self.assertTrue(chat.claim_turn(sid, stop))
        self.assertFalse(
            chat.write_after_turn(sid, lambda: done.append("now"), lambda: done.append("later"))
        )
        self.assertEqual(done, [])
        self.assertFalse(chat.claim_turn(sid, asyncio.Event()))
        chat.release_turn(sid, stop)
        self.assertEqual(done, ["later"])
        self.assertNotIn(sid, chat._streams)
        # a writer mid-write: the claim waits for it instead of checking around it
        seen = []

        def slow_write():
            seen.append(chat.claim_turn(sid, asyncio.Event()))

        self.assertTrue(chat.write_after_turn(sid, slow_write, lambda: None))
        self.assertEqual(seen, [False])
        self.assertNotIn(sid, chat._writing)

    def test_regenerate_swaps_only_for_a_finished_reply_or_one_the_owner_stopped(self):
        self.failure = False

        def provider(*chunks, stop_after=None):
            async def stream(messages, *args, **kwargs):
                self.captured.append(messages)
                for at, chunk in enumerate(chunks):
                    if isinstance(chunk, Exception):
                        raise chunk
                    if at == stop_after:
                        chat._streams[sid].set()  # the owner presses stop
                    yield chunk

            return stream

        for private in (False, True):
            with self.subTest(private=private):
                sid = self.session(private)
                self.send(sid)
                before = self.history(sid)
                asked = before[0]["id"]
                kept = [
                    # blank lines aren't an answer
                    provider({"delta": "\n\n"}, {"done": True, "usage": {}}),
                    # the provider fails after some words: a fragment the owner didn't choose
                    provider({"delta": "half a"}, {"error": "HTTP 502: upstream went away"}),
                    # the connection to the model drops mid-reply
                    provider({"delta": "half a"}, ConnectionError("reset by peer")),
                ]
                for stream in kept:
                    with mock.patch("services.chat_turn.stream_chat", stream):
                        try:
                            response = self.ask_again(sid, asked)
                            outcome = [e for e in self.events(response) if "regenerated" in e]
                            self.assertEqual(outcome, [{"regenerated": {"replaced": False}}])
                        except ConnectionError:
                            pass  # the test client surfaces the broken stream
                    self.assertEqual(self.history(sid), before)
                    self.assertNotIn(sid, chat._streams)
                # the owner stops after words came: those words are the answer now
                stopped = provider(
                    {"delta": "chosen words"}, {"delta": " never sent"}, stop_after=1
                )
                with mock.patch("services.chat_turn.stream_chat", stopped):
                    response = self.ask_again(sid, asked)
                self.assertIn({"regenerated": {"replaced": True}}, self.events(response))
                after = self.history(sid)
                self.assertEqual(len(after), 2)
                self.assertEqual(after[1]["content"], "chosen words")
                # and a finished reply swaps as before
                good = self.ask_again(sid, asked)
                self.assertIn({"regenerated": {"replaced": True}}, self.events(good))
                self.assertEqual(self.history(sid)[1]["content"], "synthetic reply")

    def test_a_failure_after_the_claim_hands_the_turn_back(self):
        self.failure = False
        sid = self.session()
        with mock.patch.object(chat, "_decide_mode", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                self.send(sid)
        # not stuck as "already running"
        self.assertNotIn(sid, chat._streams)
        self.assertEqual(self.send(sid).status_code, 200)

    def test_the_stop_button_names_its_turn(self):
        self.failure = False
        sid = self.session()
        late = []

        async def provider(messages, *args, **kwargs):
            self.captured.append(messages)
            # a stop from a turn that already ended arrives while this one runs
            late.append(self.client.post(f"/api/chat/stop/{sid}", json={"turn_token": "old-turn"}))
            yield {"delta": "still answering"}
            yield {"done": True, "usage": {}}

        with mock.patch("services.chat_turn.stream_chat", provider):
            response = self.send(sid, turn_token="this-turn")
        self.assertEqual(late[0].status_code, 200, late[0].text)
        self.assertEqual(late[0].json(), {"ok": False, "reason": "turn_changed"})
        self.assertEqual(self.history(sid)[-1]["content"], "still answering")
        self.assertNotIn("interrupted", self.history(sid)[-1]["meta"])
        self.assertEqual(response.status_code, 200)

    def test_a_stop_that_comes_while_an_edit_gets_ready_cuts_nothing(self):
        self.failure = False
        sid = self.session()
        self.send(sid)
        self.send(sid, message="second question")
        before = self.history(sid)
        calls = len(self.captured)
        self.settings.update(memory_policy="ask", memory_auto_inject=True)

        def slow_context(*args, **kwargs):
            # the owner presses stop while the edit is still getting ready (not yet claimed)
            stopped = self.client.post(f"/api/chat/stop/{sid}", json={"turn_token": "edit-turn"})
            self.assertEqual(stopped.json(), {"ok": False, "reason": "not_running"})
            return "", []

        with mock.patch.object(chat, "inject_memories", slow_context):
            edited = self.ask_again(sid, before[0]["id"], edit="edited", turn_token="edit-turn")
        self.assertEqual(edited.status_code, 409, edited.text)
        self.assertEqual(edited.json()["code"], "turn_stopped")
        self.assertEqual(self.history(sid), before)
        self.assertEqual(len(self.captured), calls)
        self.assertNotIn(sid, chat._streams)

    def test_a_page_that_went_away_before_the_claim_cuts_nothing(self):
        self.failure = False
        sid = self.session()
        self.send(sid)
        before = self.history(sid)

        async def gone(self_request):
            return True

        with mock.patch("starlette.requests.Request.is_disconnected", gone):
            edited = self.ask_again(sid, before[0]["id"], edit="edited", turn_token="t1")
        self.assertEqual(edited.status_code, 409, edited.text)
        self.assertEqual(self.history(sid), before)
        self.assertNotIn(sid, chat._streams)

    def test_a_stop_ends_a_stalled_model_at_once(self):
        self.failure = False
        sid = self.session()

        async def stalls(messages, *args, **kwargs):
            self.captured.append(messages)
            yield {"delta": "half an answer"}
            # the owner stops while the model has gone quiet: no next chunk is coming soon
            asyncio.get_running_loop().call_later(0.1, chat._streams[sid].set)
            await asyncio.sleep(30)
            yield {"delta": " never"}

        started = time.monotonic()
        with mock.patch("services.chat_turn.stream_chat", stalls):
            response = self.send(sid, turn_token="t1")
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(response.status_code, 200)
        reply = self.history(sid)[-1]
        self.assertEqual(reply["content"], "half an answer")
        self.assertTrue(reply["meta"]["interrupted"])
        self.assertNotIn(sid, chat._streams)

    def test_history_says_which_turn_is_still_running(self):
        sid = self.session()
        self.assertEqual(
            {
                k: v
                for k, v in self.client.get(f"/api/sessions/{sid}/history").json().items()
                if k.startswith("answering")
            },
            {"answering": False, "answering_turn": ""},
        )
        running = asyncio.Event()
        running.turn_token = "page-turn"
        self.assertTrue(chat.claim_turn(sid, running))
        try:
            data = self.client.get(f"/api/sessions/{sid}/history").json()
            self.assertEqual((data["answering"], data["answering_turn"]), (True, "page-turn"))
        finally:
            chat.release_turn(sid, running)

    def test_an_old_page_resending_an_edit_is_turned_away(self):
        # a page from before the update edits through the retired route (which changes nothing)
        # and then sends the edited words as a plain new question
        self.failure = False
        sid = self.session()
        self.send(sid)
        before = self.history(sid)
        retired = self.client.post(
            f"/api/sessions/{sid}/messages/{before[0]['id']}/edit", json={"content": "edited"}
        )
        self.assertEqual(retired.status_code, 410)
        old = self.send(sid, message="edited")
        self.assertEqual(old.status_code, 409, old.text)
        self.assertEqual(old.json()["detail"], "alles was updated. reload this page.")
        self.assertEqual(self.history(sid), before)
        # once: the next plain send (or any send from an updated page) goes through
        self.assertEqual(self.send(sid, message="a real new question").status_code, 200)
        self.assertEqual(len(self.history(sid)), 4)

    def test_an_api_token_client_is_never_taken_for_an_old_page(self):
        # scripts and the cli send no turn token; a page's retired edit doesn't make them stale
        self.failure = False
        sid = self.session()
        self.send(sid)
        before = self.history(sid)
        self.client.post(
            f"/api/sessions/{sid}/messages/{before[0]['id']}/edit", json={"content": "edited"}
        )
        raw = self.client.post("/api/tokens", json={"name": "cli", "scopes": ["models"]})
        self.assertEqual(raw.status_code, 200, raw.text)
        sent = self.client.post(
            "/api/chat",
            json={"session_id": sid, "message": "from a script", "simple": True},
            headers={"authorization": f"Bearer {raw.json()['token']}"},
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(len(self.history(sid)), 4)

    def test_the_retired_cut_route_cuts_nothing(self):
        self.failure = False
        sid = self.session()
        self.send(sid)
        history = self.history(sid)
        response = self.client.post(
            f"/api/sessions/{sid}/messages/{history[0]['id']}/edit",
            json={"content": "x", "newest_id": history[-1]["id"]},
        )
        self.assertEqual(response.status_code, 410, response.text)
        self.assertEqual(self.history(sid), history)


class AgentTurnTests(ApiTest):
    """Agent turns through /api/chat: what tools see, how a stop ends them, a cut-off reply."""

    def setUp(self):
        super().setUp()
        self.settings = {
            "memory_policy": "off",
            "memory_auto_inject": False,
            "auto_compact": False,
            "agent_context_files": False,
        }
        patch = mock.patch.object(chat, "load_settings", lambda: dict(self.settings))
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch("services.agent_runtime.LLM_RETRY_BASE", 0)
        patch.start()
        self.addCleanup(patch.stop)
        with self.db() as db:
            ep = ModelEndpoint(
                name="fixture", base_url="http://127.0.0.1:1", cached_models='["fixture"]'
            )
            db.add(ep)
            db.commit()
            endpoint = ep.id
        import os
        import tempfile

        folder = tempfile.TemporaryDirectory(prefix="alles-agent-turn-")
        self.addCleanup(folder.cleanup)
        self.folder = os.path.realpath(folder.name)
        response = self.client.post(
            "/api/sessions",
            json={
                "name": "agent fixture",
                "model": "fixture",
                "endpoint_id": endpoint,
                "working_dir": self.folder,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.sid = response.json()["id"]

    def turn(self, provider, tool=None):
        with (
            mock.patch("services.agent_runtime.stream_chat", provider),
            mock.patch("services.agent_runtime.stream_execute", tool or self.no_tool),
        ):
            response = self.client.post(
                "/api/chat",
                json={
                    "session_id": self.sid,
                    "message": "do the work",
                    "mode": "agent",
                    "permission_mode": "full_auto",
                    "turn_token": "agent-turn",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line[6:] != "[DONE]"
        ]
        run = next(e["agent_run"]["id"] for e in events if "agent_run" in e)
        return events, run

    async def no_tool(self, name, args):
        raise AssertionError("no tool was meant to run")
        yield

    def reply(self):
        rows = self.client.get(f"/api/sessions/{self.sid}/history").json()["messages"]
        return rows[-1]

    @staticmethod
    def calls_then_answers(calls):
        asked = {"n": 0}

        async def provider(messages, *args, **kwargs):
            asked["n"] += 1
            if asked["n"] <= calls:
                yield {
                    "tool_call": {
                        "call_id": f"call-{asked['n']}",
                        "name": "read_file",
                        "args": {"path": "notes.md"},
                    }
                }
            else:
                yield {"delta": "all done"}
            yield {"done": True, "usage": {}}

        return provider

    def test_every_tool_step_sees_its_own_runs_context(self):
        import contextvars

        from services import agent_tools

        seen = []

        async def tool(name, args):
            ctx = agent_tools.get_agent_ctx()
            seen.append((ctx.get("run_id"), ctx.get("session_id"), agent_tools._settings()))
            # a tool that notes what it read writes into its run's context, nobody else's
            ctx.setdefault("_reads", set()).add("/owned/target")
            yield {"type": "result", "result": {"output": "ok", "error": False}}

        events, run = self.turn(self.calls_then_answers(3), tool)
        self.assertEqual(len(seen), 3, events)
        self.assertEqual({(r, s) for r, s, _ in seen}, {(run, self.sid)})
        settings = [cfg for _, _, cfg in seen]
        self.assertTrue(all(cfg is settings[0] for cfg in settings))
        self.assertEqual(settings[0].get("agent_cwd"), self.folder)
        self.assertEqual(settings[0].get("agent_permission_mode"), "full_auto")
        self.assertEqual(self.reply()["content"], "all done")
        # the shared default is never where a run keeps its things
        self.assertEqual(contextvars.Context().run(agent_tools.get_agent_ctx), {})

    def test_a_stop_ends_a_stalled_model_and_says_the_agent_stopped(self):
        from services import agent_state

        async def stalls(messages, *args, **kwargs):
            yield {"delta": "half an answer"}
            asyncio.get_running_loop().call_later(0.1, chat._streams[self.sid].set)
            await asyncio.sleep(30)
            yield {"delta": " never"}

        started = time.monotonic()
        events, run = self.turn(stalls)
        self.assertLess(time.monotonic() - started, 5)
        reply = self.reply()
        self.assertEqual(reply["content"], "half an answer\n\nAgent stopped.")
        self.assertTrue(reply["meta"]["interrupted"])
        self.assertEqual(agent_state.get_run(run)["status"], "stopped")
        self.assertNotIn(self.sid, chat._streams)

    def test_a_stop_during_a_tool_lets_that_step_finish(self):
        from services import agent_state

        finished = []

        async def tool(name, args):
            chat._streams[self.sid].set()
            await asyncio.sleep(0.2)
            finished.append(name)
            yield {"type": "result", "result": {"output": "written", "error": False}}

        events, run = self.turn(self.calls_then_answers(1), tool)
        self.assertEqual(finished, ["read_file"])
        step = next(e["tool_result"] for e in events if "tool_result" in e)
        self.assertEqual(step["output"], "written")
        self.assertTrue(self.reply()["content"].endswith("Agent stopped."))
        self.assertEqual(agent_state.get_run(run)["status"], "stopped")

    def test_a_reply_cut_off_part_way_is_not_passed_off_as_whole(self):
        async def cut(messages, *args, **kwargs):
            yield {"delta": "half a"}

        events, run = self.turn(cut)
        self.assertIn(
            "the model's reply was cut off before it finished",
            [e.get("error") for e in events],
        )
        reply = self.reply()
        self.assertEqual(reply["content"], "half a")
        self.assertEqual(reply["meta"]["response_recovery"]["status"], "failed")

    def test_a_cut_before_any_words_is_asked_again(self):
        asked = {"n": 0}

        async def flaky(messages, *args, **kwargs):
            asked["n"] += 1
            if asked["n"] > 1:
                yield {"delta": "the whole answer"}
                yield {"done": True, "usage": {}}

        events, run = self.turn(flaky)
        self.assertEqual(asked["n"], 2)
        self.assertFalse([e for e in events if e.get("error")], events)
        self.assertEqual(self.reply()["content"], "the whole answer")


class CompactionTriggerTest(unittest.TestCase):
    def test_a_long_but_small_history_never_waits_on_a_summary(self):
        from routes.chat import needs_compaction

        system = {"role": "system", "content": "x" * 5000}
        short = [system] + [{"role": "user", "content": "hi there"}] * 36
        self.assertFalse(needs_compaction(short, 30, 60_000))  # 36 messages, tiny: no model call
        big = [system] + [{"role": "user", "content": "y" * 3000}] * 36
        self.assertTrue(needs_compaction(big, 30, 60_000))
        self.assertFalse(needs_compaction(big[:20], 30, 60_000))  # few messages: never
