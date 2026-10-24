"""Writers outside the chat stream never land between a running turn's question and its answer."""

import asyncio
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import app
from core.database import (
    AideCall,
    AideCallEvent,
    JarvisRun,
    JarvisWorkflow,
    Message,
    ModelEndpoint,
    Reminder,
    Session,
)
from routes import chat
from services import aide_calls, jarvis_handoff
from services.jarvis_store import create_run
from tests._client import ApiTest


class TurnWriterTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.addCleanup(chat._streams.clear)
        self.addCleanup(chat._after_turn.clear)
        with self.db() as db:
            endpoint = ModelEndpoint(
                name="local",
                base_url="http://127.0.0.1:11434/v1",
                cached_models='["test-model"]',
                enabled=True,
            )
            db.add(endpoint)
            db.flush()
            session = Session(name="busy task", model="test-model", endpoint_id=endpoint.id)
            db.add(session)
            db.commit()
            self.sid, self.endpoint = session.id, endpoint.id

    def busy(self):
        stop = asyncio.Event()
        self.assertTrue(chat.claim_turn(self.sid, stop))
        return stop

    def rows(self):
        with self.db() as db:
            return [
                (m.role, m.content)
                for m in db.query(Message)
                .filter_by(session_id=self.sid)
                .order_by(Message.timestamp)
            ]

    def test_image_chat_and_handoffs_are_turned_away_while_a_turn_runs(self):
        self.busy()
        image = self.client.post(
            "/api/images/chat", json={"session_id": self.sid, "prompt": "a cat", "model": "m"}
        )
        self.assertEqual(image.status_code, 409, image.text)
        self.assertEqual(image.json()["code"], "turn_in_progress")
        handoff = self.client.post(
            "/api/jarvis/handoffs", json={"session_id": self.sid, "request": "do this later"}
        )
        self.assertEqual(handoff.status_code, 409, handoff.text)
        self.assertEqual(handoff.json()["code"], "turn_in_progress")
        with self.db() as db:
            self.assertEqual(db.query(JarvisRun).count(), 0)
        self.assertEqual(self.rows(), [])

    def test_a_live_call_line_waits_for_the_running_turn(self):
        with self.db() as db:
            call = AideCall(session_id=self.sid, state="connected", connected_at=datetime.now(UTC))
            db.add(call)
            db.commit()
            call_id = call.id
        stop = self.busy()
        with self.db() as db:
            call = db.get(AideCall, call_id)
            _, created = aide_calls.append_final_transcript(
                db, call, role="user", text="said during the turn", provider_event_id="e1"
            )
            db.commit()
        self.assertTrue(created)
        # held back: it would sit between the turn's question and its answer
        self.assertEqual(self.rows(), [])
        chat.release_turn(self.sid, stop)
        self.assertEqual(self.rows(), [("user", "said during the turn")])
        # idle: straight in
        with self.db() as db:
            call = db.get(AideCall, call_id)
            aide_calls.append_final_transcript(
                db, call, role="assistant", text="and the reply", provider_event_id="e2"
            )
            db.commit()
        self.assertEqual(self.rows()[-1], ("assistant", "and the reply"))

    def test_a_scheduled_message_waits_for_the_running_turn_without_holding_it_in_memory(self):
        with self.db() as db:
            db.add(
                Reminder(
                    text="give me an update",
                    trigger_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
                    type="message",
                    session_id=self.sid,
                )
            )
            db.commit()

        async def fake_stream(*args, **kwargs):
            yield {"delta": "all done"}

        async def no_push(payload):
            return {"sent": 0, "failed": 0, "uncertain": 0, "pruned": 0, "total": 0}

        asked = []

        async def counted_stream(*args, **kwargs):
            asked.append(1)
            async for chunk in fake_stream():
                yield chunk

        stop = self.busy()
        with (
            mock.patch("services.llm.stream_chat", counted_stream),
            mock.patch("services.push_delivery.broadcast_result", no_push),
        ):
            # a turn runs (it may wait hours on a question): the reminder stays due, unclaimed,
            # with no model call and nothing in memory for a crash to lose
            asyncio.run(app._fire_due_reminders())
            self.assertEqual((self.rows(), asked), ([], []))
            with self.db() as db:
                due = db.query(Reminder).one()
                self.assertEqual((due.fired, due.notified), (False, False))
            chat.release_turn(self.sid, stop)
            # the next tick fires it
            asyncio.run(app._fire_due_reminders())
        self.assertEqual(self.rows(), [("user", "give me an update"), ("assistant", "all done")])
        with self.db() as db:
            self.assertTrue(db.query(Reminder).one().fired)
            self.assertEqual(db.get(Session, self.sid).message_count, 2)

    def test_a_turn_starting_while_the_reminder_was_answered_leaves_it_due(self):
        with self.db() as db:
            db.add(
                Reminder(
                    text="ping",
                    trigger_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1),
                    type="message",
                    session_id=self.sid,
                )
            )
            db.commit()
        held = []

        async def busy_meanwhile(*args, **kwargs):
            held.append(self.busy())
            yield {"delta": "late"}

        async def no_push(payload):
            return {"sent": 0, "failed": 0, "uncertain": 0, "pruned": 0, "total": 0}

        with (
            mock.patch("services.llm.stream_chat", busy_meanwhile),
            mock.patch("services.push_delivery.broadcast_result", no_push),
        ):
            asyncio.run(app._fire_due_reminders())
        # nothing saved and nothing held: it's simply due again
        self.assertEqual(self.rows(), [])
        self.assertEqual(chat._after_turn.get(self.sid), None)
        with self.db() as db:
            due = db.query(Reminder).one()
            self.assertEqual((due.fired, due.notified), (False, False))

    def test_a_handoff_holds_the_task_while_it_runs_and_waits_for_a_running_turn(self):
        with self.db() as db:
            workflow = JarvisWorkflow(
                name="shared turn",
                prompt="record this answer",
                deterministic_action=jarvis_handoff.HANDOFF_ACTION,
                enabled=True,
            )
            db.add(workflow)
            db.flush()
            run = create_run(db, workflow)
            run.session_id = self.sid
            db.commit()
            run_id = run.id
        held = []

        async def agent(messages, _ep, _model, stop, _settings, accumulated, *_args, **_kwargs):
            # the runner holds the task: an edit or a send here is refused meanwhile
            held.append(chat._streams.get(self.sid) is stop)
            accumulated.append("saved answer")
            yield {"delta": "saved answer", "done": True}

        async def scenario():
            turn = self.busy()
            task = asyncio.create_task(jarvis_handoff._execute(run_id))
            await asyncio.sleep(0.4)
            # still waiting for the turn that was running first
            self.assertEqual(held, [])
            with self.db() as db:
                self.assertEqual(db.get(JarvisRun, run_id).state, "queued")
            chat.release_turn(self.sid, turn)
            await asyncio.wait_for(task, 5)

        with (
            mock.patch.object(
                jarvis_handoff, "load_settings", return_value={"memory_policy": "off"}
            ),
            mock.patch("services.chat_turn.run_agent", agent),
        ):
            asyncio.run(scenario())
        self.assertEqual(held, [True])
        self.assertNotIn(self.sid, chat._streams)
        with self.db() as db:
            self.assertEqual(db.get(JarvisRun, run_id).state, "succeeded")
        self.assertEqual(
            self.rows(), [("user", "record this answer"), ("assistant", "saved answer")]
        )

    def test_held_writes_land_in_order_while_the_turn_is_still_claimed(self):
        order = []
        stop = self.busy()
        self.assertFalse(
            chat.write_after_turn(
                self.sid, lambda: order.append("now 1"), lambda: order.append("line 1")
            )
        )

        def second():
            order.append("line 2")
            # a writer arriving while the held ones land queues behind them, it can't jump ahead
            landed = chat.write_after_turn(
                self.sid, lambda: order.append("now 3"), lambda: order.append("line 3")
            )
            order.append(f"landed now: {landed}")

        chat.write_after_turn(self.sid, lambda: None, second)
        chat.release_turn(self.sid, stop)
        self.assertEqual(order, ["line 1", "line 2", "landed now: False", "line 3"])
        self.assertNotIn(self.sid, chat._streams)

    def test_a_held_write_that_fails_is_tried_once_more(self):
        tries = []

        def flaky():
            tries.append(1)
            if len(tries) == 1:
                raise RuntimeError("database is locked")

        stop = self.busy()
        chat.write_after_turn(self.sid, lambda: None, flaky)
        chat.release_turn(self.sid, stop)
        self.assertEqual(len(tries), 2)

    def test_a_kept_call_event_whose_line_was_lost_gets_it_on_retry(self):
        with self.db() as db:
            call = AideCall(session_id=self.sid, state="connected", connected_at=datetime.now(UTC))
            db.add(call)
            db.commit()
            call_id = call.id
        stop = self.busy()
        with self.db() as db:
            call = db.get(AideCall, call_id)
            aide_calls.append_final_transcript(
                db, call, role="user", text="held line", provider_event_id="e1"
            )
            db.commit()
            # a client retry while it's still held adds nothing
            aide_calls.append_final_transcript(
                db, call, role="user", text="held line", provider_event_id="e1"
            )
            db.commit()
        # the process stops mid-turn: the held write is gone, the event is kept
        chat._after_turn.clear()
        aide_calls._held_lines.clear()
        chat._streams.pop(self.sid, None)
        del stop
        self.assertEqual(self.rows(), [])
        # the client's retry with the same provider event puts the line in, once
        for _ in range(2):
            with self.db() as db:
                call = db.get(AideCall, call_id)
                _, created = aide_calls.append_final_transcript(
                    db, call, role="user", text="held line", provider_event_id="e1"
                )
                db.commit()
            self.assertFalse(created)
        self.assertEqual(self.rows(), [("user", "held line")])
        with self.db() as db:
            self.assertEqual(db.get(Session, self.sid).message_count, 1)

    def test_an_image_reads_the_task_again_after_drawing_and_says_its_ids(self):
        async def draw(*args, **kwargs):
            # while the image is drawn another turn lands and the task gets its name
            with self.db() as db:
                db.add_all(
                    [
                        Message(session_id=self.sid, role="user", content="meanwhile"),
                        Message(session_id=self.sid, role="assistant", content="answer"),
                    ]
                )
                task = db.get(Session, self.sid)
                task.message_count = (task.message_count or 0) + 2
                task.name = "renamed meanwhile"
                db.commit()
            return [b"png-bytes"]

        @contextmanager
        def photos(db, images, prompt):
            yield [SimpleNamespace(id="photo-1")]
            db.commit()

        with (
            self.db() as db,
        ):
            db.get(Session, self.sid).name = "new chat"
            db.commit()
        with (
            mock.patch("services.imagegen.generate", draw),
            mock.patch("routes.images.generated_photo_batch", photos),
            mock.patch("services.notes_vault.create", side_effect=OSError),
        ):
            response = self.client.post(
                "/api/images/chat",
                json={
                    "session_id": self.sid,
                    "prompt": "a cat",
                    "model": "m",
                    "endpoint_id": self.endpoint,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        rows = self.rows()
        self.assertEqual([r[1] for r in rows][:3], ["meanwhile", "answer", "a cat"])
        with self.db() as db:
            stored = (
                db.query(Message).filter_by(session_id=self.sid).order_by(Message.timestamp).all()
            )
            task = db.get(Session, self.sid)
            self.assertEqual(task.message_count, 4)
            self.assertEqual(task.name, "renamed meanwhile")
        body = response.json()
        self.assertEqual(
            (body["user_message_id"], body["message_id"]), (stored[2].id, stored[3].id)
        )

    def test_an_image_gives_up_on_a_turn_that_holds_too_long(self):
        held = []

        async def draw(*args, **kwargs):
            held.append(self.busy())
            return [b"png-bytes"]

        with (
            mock.patch("services.imagegen.generate", draw),
            mock.patch("routes.images._BUSY_WAIT_SECONDS", 0.5),
        ):
            response = self.client.post(
                "/api/images/chat",
                json={
                    "session_id": self.sid,
                    "prompt": "a cat",
                    "model": "m",
                    "endpoint_id": self.endpoint,
                },
            )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], "turn_in_progress")
        self.assertIn("ask for the image again", response.json()["detail"])
        self.assertEqual(self.rows(), [])

    def test_a_stop_only_stops_the_turn_it_names(self):
        running = asyncio.Event()
        running.turn_token = "turn-b"
        self.assertTrue(chat.claim_turn(self.sid, running))
        # a late stop from a turn that already ended
        late = self.client.post(f"/api/chat/stop/{self.sid}", json={"turn_token": "turn-a"})
        # an expected outcome, not an error: no failed request in the page's console
        self.assertEqual(late.status_code, 200, late.text)
        self.assertEqual(late.json(), {"ok": False, "reason": "turn_changed"})
        self.assertFalse(running.is_set())
        mine = self.client.post(f"/api/chat/stop/{self.sid}", json={"turn_token": "turn-b"})
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertTrue(running.is_set())
        # without a token (background work's own stop buttons) it still stops what runs
        handoff = asyncio.Event()
        chat.release_turn(self.sid, running)
        self.assertTrue(chat.claim_turn(self.sid, handoff))
        self.assertEqual(self.client.post(f"/api/chat/stop/{self.sid}").status_code, 200)
        self.assertTrue(handoff.is_set())

    def test_a_held_call_line_survives_a_restart(self):
        with self.db() as db:
            call = AideCall(session_id=self.sid, state="connected", connected_at=datetime.now(UTC))
            db.add(call)
            db.commit()
            call_id = call.id
        self.busy()
        with self.db() as db:
            call = db.get(AideCall, call_id)
            event, _ = aide_calls.append_final_transcript(
                db, call, role="user", text="said mid-turn", provider_event_id="e1"
            )
            db.commit()
            # owed, and recorded as owed together with the event
            self.assertEqual(json.loads(event.data)["chat_line"], "held")
        # alles stops before the turn ends: memory is gone, the event says the line is owed
        chat._after_turn.clear()
        chat._streams.clear()
        aide_calls._held_lines.clear()
        self.assertEqual(self.rows(), [])
        with self.db() as db:
            self.assertEqual(aide_calls.restore_held_lines(db), 1)
        with self.db() as db:
            self.assertEqual(aide_calls.restore_held_lines(db), 0)
            event = db.query(AideCallEvent).filter_by(provider_event_id="e1").one()
            self.assertNotIn("chat_line", json.loads(event.data))
            self.assertEqual(db.get(Session, self.sid).message_count, 1)
        self.assertEqual(self.rows(), [("user", "said mid-turn")])

    def test_a_held_line_written_at_the_turns_end_clears_its_mark(self):
        with self.db() as db:
            call = AideCall(session_id=self.sid, state="connected", connected_at=datetime.now(UTC))
            db.add(call)
            db.commit()
            call_id = call.id
        stop = self.busy()
        with self.db() as db:
            call = db.get(AideCall, call_id)
            aide_calls.append_final_transcript(
                db, call, role="assistant", text="the reply line", provider_event_id="e2"
            )
            db.commit()
        chat.release_turn(self.sid, stop)
        self.assertEqual(self.rows(), [("assistant", "the reply line")])
        with self.db() as db:
            event = db.query(AideCallEvent).filter_by(provider_event_id="e2").one()
            self.assertNotIn("chat_line", json.loads(event.data))
            # nothing left for startup to redo
            self.assertEqual(aide_calls.restore_held_lines(db), 0)
        self.assertEqual(len(self.rows()), 1)
