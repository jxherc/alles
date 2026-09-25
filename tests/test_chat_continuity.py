"""Conversation and run finalization across SSE closure and task cancellation."""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.database import Message, Session
from routes import chat
from services import agent_runtime, agent_state, incognito
from tests._client import ApiTest


class ChatContinuityTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.runs = tempfile.TemporaryDirectory()
        self.addCleanup(self.runs.cleanup)
        patch = mock.patch.object(agent_state, "DATA_DIR", Path(self.runs.name))
        patch.start()
        self.addCleanup(patch.stop)
        incognito.clear_for_tests()
        self.addCleanup(incognito.clear_for_tests)
        with self.db() as db:
            session = Session(name="continuity fixture")
            db.add(session)
            db.commit()
            self.sid = session.id

    def stream(self, *, private=False, mode="agent", **settings):
        return chat._sse(
            chat._stream_and_save(
                self.sid,
                "keep this prompt",
                [{"role": "user", "content": "keep this prompt"}],
                SimpleNamespace(base_url="http://fixture.invalid", api_key=""),
                "fixture",
                asyncio.Event(),
                self.db,
                incognito=private,
                mode=mode,
                settings={"agent_context_files": False, **settings},
            )
        )

    def history(self):
        with self.db() as db:
            rows = (
                db.query(Message).filter_by(session_id=self.sid).order_by(Message.timestamp).all()
            )
            count = db.get(Session, self.sid).message_count
            self.assertEqual(count, len(rows))
            return [(row.role, row.content) for row in rows]

    def assert_terminal(self, status, text="partial reply"):
        runs = agent_state.list_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], status)
        self.assertEqual(runs[0]["text"], text)
        self.assertTrue(runs[0]["finished_at"])
        self.assertIsNone(agent_state.find_active_run(self.sid))

    def test_close_between_chunks_preserves_turn_and_closes_provider(self):
        for mode in ("chat", "agent"):
            with self.subTest(mode=mode):
                closed = []

                async def provider(*args, **kwargs):
                    try:
                        yield {"delta": "partial reply"}
                        await asyncio.Event().wait()
                    finally:
                        closed.append(True)

                async def run():
                    stream = self.stream(mode=mode)
                    async for chunk in stream:
                        if b'"delta"' in chunk:
                            break
                    await stream.aclose()
                    await stream.aclose()  # repeated cleanup must not append a second turn

                with (
                    mock.patch.object(chat, "stream_chat", provider),
                    mock.patch.object(agent_runtime, "stream_chat", provider),
                ):
                    asyncio.run(run())
                self.assertEqual(closed, [True])
                self.assertEqual(
                    self.history(),
                    [("user", "keep this prompt"), ("assistant", "partial reply")]
                    * (1 if mode == "chat" else 2),
                )
        self.assert_terminal("cancelled")

    def test_tool_only_interruption_preserves_steps_and_status_metadata(self):
        async def agent(messages, ep, model, stop, settings, accumulated, thinking, steps, **kw):
            thinking.append("checking the fixture")
            steps.append({"name": "read_file", "output": "partial tool output", "error": False})
            yield {"tool_delta": {"call_id": "fixture", "text": "partial tool output"}}
            await asyncio.Event().wait()

        async def run():
            stream = self.stream()
            await anext(stream)
            await stream.aclose()

        with mock.patch.object(chat, "run_agent", agent):
            asyncio.run(run())
        self.assertEqual(self.history(), [("user", "keep this prompt"), ("assistant", "")])
        with self.db() as db:
            reply = db.query(Message).filter_by(session_id=self.sid, role="assistant").one()
            self.assertTrue(reply.meta_dict()["interrupted"])
            self.assertEqual(reply.meta_dict()["thinking"], "checking the fixture")
            self.assertEqual(reply.meta_dict()["tool_steps"][0]["output"], "partial tool output")

    def test_task_cancel_during_provider_wait_preserves_partial(self):
        waiting = None

        async def provider(*args, **kwargs):
            yield {"delta": "partial reply"}
            waiting.set()
            await asyncio.Event().wait()

        async def run():
            nonlocal waiting
            waiting = asyncio.Event()

            async def consume():
                async for _ in self.stream():
                    pass

            task = asyncio.create_task(consume())
            await waiting.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with mock.patch.object(agent_runtime, "stream_chat", provider):
            asyncio.run(run())
        self.assertEqual(
            self.history(), [("user", "keep this prompt"), ("assistant", "partial reply")]
        )
        self.assert_terminal("cancelled")

    def test_stop_before_first_token_preserves_prompt_and_finishes_run(self):
        async def run():
            stream = self.stream()
            first = await anext(stream)
            self.assertIn(b'"agent_run"', first)
            await stream.aclose()

        asyncio.run(run())
        self.assertEqual(self.history(), [("user", "keep this prompt"), ("assistant", "")])
        self.assert_terminal("cancelled", "")

    def test_close_at_provenance_saves_accepted_prompt_without_starting_run(self):
        async def run():
            stream = self.stream(context_provenance={"fixture": True})
            self.assertIn(b'"context_provenance"', await anext(stream))
            await stream.aclose()

        asyncio.run(run())
        self.assertEqual(self.history(), [("user", "keep this prompt"), ("assistant", "")])
        self.assertEqual(agent_state.list_runs(), [])

    def test_completion_and_close_at_done_each_save_exactly_one_turn(self):
        async def provider(*args, **kwargs):
            yield {"delta": "partial reply"}
            yield {"done": True, "usage": {"output_tokens": 2}}

        async def run(close_at_done):
            stream = self.stream()
            async for chunk in stream:
                if close_at_done and b'"done": true' in chunk:
                    break
            await stream.aclose()

        with mock.patch.object(agent_runtime, "stream_chat", provider):
            asyncio.run(run(True))
            self.assert_terminal("done")
            asyncio.run(run(False))
        self.assertEqual(
            self.history(), [("user", "keep this prompt"), ("assistant", "partial reply")] * 2
        )
        self.assertTrue(all(run["status"] == "done" for run in agent_state.list_runs()))

    def test_incognito_cancellation_and_completion_never_write_sqlite(self):
        private = incognito.create_session()
        public_id = self.sid
        self.sid = private.id

        async def provider(*args, **kwargs):
            yield {"delta": "private partial"}
            yield {"done": True, "usage": {}}

        async def run(cancel):
            stream = self.stream(private=True, mode="chat")
            async for chunk in stream:
                if cancel and b'"delta"' in chunk:
                    break
            await stream.aclose()
            await stream.aclose()

        with mock.patch.object(chat, "stream_chat", provider):
            asyncio.run(run(True))
            asyncio.run(run(False))
        self.assertEqual(
            [(row.role, row.content) for row in private.messages],
            [("user", "keep this prompt"), ("assistant", "private partial")] * 2,
        )
        with self.db() as db:
            self.assertEqual(db.query(Message).count(), 0)
            self.assertEqual([s.id for s in db.query(Session).all()], [public_id])
