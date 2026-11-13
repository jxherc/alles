"""A turn asked for with keep_running runs on when its listener leaves, and can be heard again."""

import asyncio
import json
from unittest import mock

from fastapi import Request

from core.api_errors import ApiError
from core.database import ModelEndpoint
from routes import chat
from services import incognito
from tests._client import ApiTest


def _events(raw: bytes | str) -> list[tuple[int | None, dict]]:
    """(place, event) for each event of an sse body; the place is its `id:` line, if it has one."""
    text = raw.decode() if isinstance(raw, bytes) else raw
    out = []
    for block in text.split("\n\n"):
        place, data = None, None
        for line in block.splitlines():
            if line.startswith("id:"):
                place = int(line[3:])
            elif line.startswith("data:") and "[DONE]" not in line:
                data = json.loads(line[5:])
        if data is not None:
            out.append((place, data))
    return out


def _text(events) -> str:
    return "".join(event.get("delta", "") for _, event in events)


class KeptTurnTests(ApiTest):
    def setUp(self):
        super().setUp()
        incognito.clear_for_tests()
        self.addCleanup(incognito.clear_for_tests)
        self.addCleanup(chat._streams.clear)
        self.addCleanup(chat._bg_tasks.clear)
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

    def session(self, private=False):
        response = self.client.post(
            "/api/sessions",
            json={
                "name": "kept fixture",
                "model": "fixture",
                "endpoint_id": self.endpoint,
                "incognito": private,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def history(self, sid):
        return self.client.get(f"/api/sessions/{sid}/history").json()

    def slow_model(self):
        """A model that says half, waits for `go`, then says the rest."""
        state = {"said_half": asyncio.Event(), "go": asyncio.Event()}

        async def provider(messages, *args, **kwargs):
            yield {"delta": "half"}
            state["said_half"].set()
            await state["go"].wait()
            yield {"delta": " and the rest"}
            yield {"done": True, "usage": {}}

        return state, provider

    async def ask(self, sid, db, *, keep, token="t1"):
        """The turn's response, the way the route hands it to the server."""
        return await chat.chat(
            chat.ChatRequest(
                session_id=sid,
                message="a question",
                simple=True,
                turn_token=token,
                keep_running=keep,
            ),
            Request({"type": "http", "headers": []}),
            db,
        )

    async def hear_half(self, response) -> list:
        """Reads the stream up to the model's first words, then drops the connection."""
        heard = []
        stream = response.body_iterator
        async for chunk in stream:
            heard += _events(chunk)
            if _text(heard) == "half":
                break
        await stream.aclose()
        return heard

    def test_a_listener_that_leaves_ends_a_plain_turn_but_not_a_kept_one(self):
        for keep in (False, True):
            with self.subTest(keep=keep):
                sid = self.session()

                async def scenario():
                    state, provider = self.slow_model()
                    with self.db() as db, mock.patch("services.chat_turn.stream_chat", provider):
                        response = await self.ask(sid, db, keep=keep)
                        await self.hear_half(response)
                        running = sid in chat._streams
                        state["go"].set()
                        task = chat._bg_tasks.get(sid)
                        if task:
                            await asyncio.wait_for(task, timeout=3)
                    return running

                still_running = asyncio.run(scenario())
                self.assertEqual(still_running, keep)
                data = self.history(sid)
                self.assertFalse(data["answering"])
                self.assertNotIn(sid, chat._streams)
                self.assertNotIn(sid, chat._bg_tasks)
                reply = data["messages"][-1]
                self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant"])
                if keep:
                    self.assertEqual(reply["content"], "half and the rest")
                    self.assertNotIn("interrupted", reply["meta"])
                    self.assertNotIn("response_recovery", reply["meta"])
                else:
                    # a page that drops its connection still ends its turn
                    self.assertEqual(reply["content"], "half")
                    self.assertTrue(reply["meta"]["interrupted"])

    def test_a_listener_that_comes_back_gets_what_was_written_and_the_rest(self):
        sid = self.session()

        async def scenario():
            state, provider = self.slow_model()
            with self.db() as db, mock.patch("services.chat_turn.stream_chat", provider):
                response = await self.ask(sid, db, keep=True)
                first = await self.hear_half(response)
                # the history says which turn to ask for
                answering = self.history(sid)["answering_turn"]
                again = await chat.rejoin_chat(sid, turn_token=answering)
                rest_only = await chat.rejoin_chat(sid, turn_token="t1", after=first[-1][0] + 1)
                state["go"].set()
                whole = [e async for chunk in again.body_iterator for e in _events(chunk)]
                rest = [e async for chunk in rest_only.body_iterator for e in _events(chunk)]
            return first, answering, whole, rest

        first, answering, whole, rest = asyncio.run(scenario())
        self.assertEqual(answering, "t1")
        # every event has its place, in order, from the first
        self.assertEqual([place for place, _ in whole], list(range(len(whole))))
        self.assertEqual(whole[: len(first)], first)
        self.assertEqual(whole[0][1], {"asked": {"message": "a question"}})
        self.assertIn("turn", whole[1][1])
        self.assertEqual(_text(whole), "half and the rest")
        self.assertTrue(any(event.get("done") for _, event in whole))
        saved = next(event["saved_message"] for _, event in whole if "saved_message" in event)
        # asked from where the first listener stopped: only what it missed
        self.assertEqual(rest, whole[len(first) :])
        self.assertEqual(_text(rest), " and the rest")
        data = self.history(sid)
        self.assertEqual(data["messages"][-1]["id"], saved["id"])
        self.assertEqual(data["messages"][-1]["content"], "half and the rest")
        self.assertEqual(data["messages"][0]["id"], whole[1][1]["turn"]["user_id"])

    def test_a_stop_still_stops_a_kept_turn_nobody_listens_to(self):
        sid = self.session()

        async def scenario():
            state, provider = self.slow_model()
            with self.db() as db, mock.patch("services.chat_turn.stream_chat", provider):
                response = await self.ask(sid, db, keep=True)
                await self.hear_half(response)
                wrong = chat.stop_chat(sid, chat.StopBody(turn_token="another-turn"))
                still = sid in chat._streams
                stopped = chat.stop_chat(sid, chat.StopBody(turn_token="t1"))
                await asyncio.wait_for(chat._bg_tasks[sid], timeout=3)
            return wrong, still, stopped

        wrong, still, stopped = asyncio.run(scenario())
        self.assertEqual(wrong, {"ok": False, "reason": "turn_changed"})
        self.assertTrue(still)
        self.assertEqual(stopped, {"ok": True})
        data = self.history(sid)
        self.assertFalse(data["answering"])
        self.assertEqual(data["messages"][-1]["content"], "half")
        self.assertTrue(data["messages"][-1]["meta"]["interrupted"])
        self.assertNotIn(sid, chat._streams)

    def test_a_shutdown_stops_a_kept_turn_nobody_listens_to(self):
        sid = self.session()

        def reset():
            chat._exiting = False

        self.addCleanup(reset)

        async def scenario():
            state, provider = self.slow_model()
            with self.db() as db, mock.patch("services.chat_turn.stream_chat", provider):
                response = await self.ask(sid, db, keep=True)
                await self.hear_half(response)
                with mock.patch("services.agent_tools.stop_commands"):
                    stopped = chat.stop_open_turns()
                await asyncio.wait_for(chat._bg_tasks[sid], timeout=3)
            return stopped

        self.assertEqual(asyncio.run(scenario()), 1)
        reply = self.history(sid)["messages"][-1]
        self.assertEqual(reply["content"], "half")
        self.assertTrue(reply["meta"]["interrupted"])
        self.assertNotIn(sid, chat._streams)

    def test_a_kept_turn_over_http_carries_places_and_is_saved_complete(self):
        sid = self.session()

        async def provider(messages, *args, **kwargs):
            yield {"delta": "whole"}
            yield {"delta": " answer"}
            yield {"done": True, "usage": {}}

        with mock.patch("services.chat_turn.stream_chat", provider):
            response = self.client.post(
                "/api/chat",
                json={
                    "session_id": sid,
                    "message": "a question",
                    "simple": True,
                    "keep_running": True,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.text.rstrip().endswith("data: [DONE]"))
        events = _events(response.text)
        self.assertEqual([place for place, _ in events], list(range(len(events))))
        self.assertEqual(_text(events), "whole answer")
        data = self.history(sid)
        self.assertEqual([m["content"] for m in data["messages"]], ["a question", "whole answer"])
        self.assertNotIn("interrupted", data["messages"][-1]["meta"])
        self.assertNotIn(sid, chat._streams)
        self.assertNotIn(sid, chat._bg_tasks)

    def test_a_plain_turn_and_a_private_one_are_not_kept(self):
        async def provider(messages, *args, **kwargs):
            yield {"delta": "plain"}
            yield {"done": True, "usage": {}}

        for private, keep in ((False, False), (True, True)):
            with self.subTest(private=private, keep=keep):
                sid = self.session(private)
                with mock.patch("services.chat_turn.stream_chat", provider):
                    response = self.client.post(
                        "/api/chat",
                        json={
                            "session_id": sid,
                            "message": "a question",
                            "simple": True,
                            "keep_running": keep,
                            "incognito": private,
                        },
                    )
                self.assertEqual(response.status_code, 200, response.text)
                events = _events(response.text)
                # the stream a page has always had: no places, the ids first
                self.assertEqual({place for place, _ in events}, {None})
                self.assertIn("turn", events[0][1])
                self.assertFalse(any("asked" in event for _, event in events))

    def test_nothing_to_listen_to_is_a_plain_404(self):
        sid = self.session()
        gone = self.client.get(f"/api/chat/stream/{sid}")
        self.assertEqual(gone.status_code, 404, gone.text)
        self.assertEqual(gone.json()["code"], "turn_not_running")
        # a turn a page started: it runs, but it was never kept
        plain = asyncio.Event()
        plain.turn_token = "page-turn"
        self.assertTrue(chat.claim_turn(sid, plain))
        try:
            unkept = self.client.get(f"/api/chat/stream/{sid}", params={"turn_token": "page-turn"})
            self.assertEqual(unkept.status_code, 404, unkept.text)
            self.assertEqual(unkept.json()["code"], "turn_not_running")
        finally:
            chat.release_turn(sid, plain)

        async def scenario():
            state, provider = self.slow_model()
            with self.db() as db, mock.patch("services.chat_turn.stream_chat", provider):
                response = await self.ask(sid, db, keep=True, token="this-turn")
                await self.hear_half(response)
                try:
                    with self.assertRaises(ApiError) as other:
                        await chat.rejoin_chat(sid, turn_token="the-turn-before")
                finally:
                    state["go"].set()
                    await asyncio.wait_for(chat._bg_tasks[sid], timeout=3)
            return other.exception

        refused = asyncio.run(scenario())
        self.assertEqual((refused.status_code, refused.code), (404, "turn_not_running"))

    def test_a_step_that_needs_the_owner_is_turned_down_while_nobody_listens(self):
        sid = self.session()
        seen = {}

        async def turn(*args, settings=None, **kwargs):
            seen["settings"] = settings
            yield {"delta": "half"}
            await seen["go"].wait()
            yield {"done": True}

        async def scenario():
            seen["go"] = asyncio.Event()
            with self.db() as db, mock.patch.object(chat, "_stream_and_save", turn):
                response = await self.ask(sid, db, keep=True)
                stream = response.body_iterator
                async for chunk in stream:
                    if b'"delta"' in chunk:
                        break
                listening = seen["settings"].get("agent_detached")
                await stream.aclose()
                alone = seen["settings"].get("agent_detached")
                again = (await chat.rejoin_chat(sid)).body_iterator
                await anext(again)
                back = seen["settings"].get("agent_detached")
                seen["go"].set()
                async for _ in again:
                    pass
            return listening, alone, back

        listening, alone, back = asyncio.run(scenario())
        self.assertFalse(listening)
        self.assertTrue(alone, "an approval asked for now would wait on a listener that's gone")
        self.assertFalse(back)

    def test_a_kept_turn_that_breaks_lets_go_and_tells_its_listener(self):
        sid = self.session()

        async def turn(*args, **kwargs):
            yield {"delta": "half"}
            raise RuntimeError("the turn broke")

        async def scenario():
            with (
                self.db() as db,
                mock.patch.object(chat, "_stream_and_save", turn),
                self.assertLogs("alles.chat", level="ERROR"),
            ):
                response = await self.ask(sid, db, keep=True)
                heard = []
                with self.assertRaises(RuntimeError):
                    async for chunk in response.body_iterator:
                        heard += _events(chunk)
            return heard

        heard = asyncio.run(scenario())
        self.assertEqual(_text(heard), "half")
        self.assertNotIn(sid, chat._streams)
        self.assertNotIn(sid, chat._bg_tasks)

    def test_keeping_a_turn_is_not_part_of_what_a_retry_must_match(self):
        sid = self.session()
        failed = {"on": True}

        async def provider(messages, *args, **kwargs):
            if failed["on"]:
                yield {"error": "HTTP 503: synthetic unavailable model"}
            else:
                yield {"delta": "an answer"}
                yield {"done": True, "usage": {}}

        def send(**extra):
            return self.client.post(
                "/api/chat",
                json={"session_id": sid, "message": "a question", "simple": True, **extra},
            )

        with mock.patch("services.chat_turn.stream_chat", provider):
            first = send(keep_running=True)
            pending = next(
                e["saved_user"]["id"] for _, e in _events(first.text) if "saved_user" in e
            )
            stored = self.history(sid)["messages"][0]["meta"]["response_recovery"]["request"]
            self.assertNotIn("keep_running", stored)
            failed["on"] = False
            # the page retries what the phone asked: it never sends the flag
            retried = send(retry_message_id=pending)
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(
            [m["content"] for m in self.history(sid)["messages"]], ["a question", "an answer"]
        )
