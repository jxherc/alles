"""Local calls with synthetic audio, worker and text stubs; never live inference."""

import asyncio
import json
from unittest import mock
from uuid import uuid4

from core.database import AideCall, JarvisRun, Message, ModelEndpoint, Session
from routes import chat
from services import aide_voice, jarvis_handoff, local_voice
from tests._client import ApiTest


class AideVoiceTests(ApiTest):
    def setUp(self):
        super().setUp()
        aide_voice._active.clear()
        aide_voice._speech.clear()
        chat._streams.clear()
        self.addCleanup(aide_voice._active.clear)
        self.addCleanup(aide_voice._speech.clear)
        self.addCleanup(chat._streams.clear)
        self.settings = {
            "memory_policy": "off",
            "memory_auto_inject": False,
            "auto_compact": False,
            "agent_context_files": False,
            "default_chat_behavior": "answer_only",
        }
        for target, value in [
            ("services.local_voice.metadata_status", {"available": True, "reason": ""}),
            ("routes.chat.load_settings", self.settings),
            ("services.model_resolver.load_settings", self.settings),
            ("services.jarvis_handoff.load_settings", self.settings),
        ]:
            patch = mock.patch(target, side_effect=lambda v=value: dict(v))
            patch.start()
            self.addCleanup(patch.stop)
        self.transcription = mock.AsyncMock(
            return_value={"text": "hello there", "language": "en", "metrics": {"duration": 1}}
        )
        patch = mock.patch.object(local_voice, "transcribe", self.transcription)
        patch.start()
        self.addCleanup(patch.stop)
        self.outputs = []
        self.fail_model = False

        async def text_model(messages, base_url, key, model, **kwargs):
            self.outputs.append((messages, base_url, model))
            if self.fail_model:
                yield {"error": "synthetic failure"}
            else:
                yield {"delta": "Hello. "}
                yield {"delta": "This is synthetic."}
                yield {"done": True, "usage": {}}

        for target, value in [
            ("services.chat_turn.stream_chat", text_model),
            ("services.chat_turn._fire_message_hook", mock.AsyncMock()),
            ("httpx.AsyncClient", mock.Mock(side_effect=AssertionError("unexpected network"))),
        ]:
            patch = mock.patch(target, value)
            patch.start()
            self.addCleanup(patch.stop)
        with self.db() as db:
            ep = ModelEndpoint(
                name="local fixture",
                base_url="http://127.0.0.1:1/v1",
                cached_models='["voice-text"]',
            )
            db.add(ep)
            db.flush()
            primary = Session(
                name="Aide",
                aide_role="primary",
                endpoint_id=ep.id,
                model="voice-text",
                chat_behavior="answer_only",
            )
            db.add(primary)
            db.commit()
            self.sid, self.eid = primary.id, ep.id

    def call(self, **fields):
        response = self.client.post(
            "/api/aide/voice/calls", json={"request_id": str(uuid4()), **fields}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def turn(self, call, identity=None, audio=b"synthetic audio", **headers):
        identity = identity or str(uuid4())
        response = self.client.post(
            f"/api/aide/voice/calls/{call['id']}/turns?turn_id={identity}",
            content=audio,
            headers={"content-type": "audio/webm", **headers},
        )
        return identity, response

    def events(self, response):
        return [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: [DONE]"
        ]

    def rows(self):
        with self.db() as db:
            return [
                (m.id, m.role, m.content, m.meta_dict())
                for m in db.query(Message)
                .filter_by(session_id=self.sid)
                .order_by(Message.timestamp)
                .all()
            ]

    def test_status_metadata_has_no_writes_or_worker_start(self):
        with self.db() as db:
            db.query(Session).delete()
            db.commit()
        response = self.client.get("/api/aide/voice/status")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["available"])
        self.assertEqual(response.json()["audio"]["per_call_fee"], 0)
        self.assertEqual(response.json()["text_model"]["cost"], "unknown")
        self.transcription.assert_not_awaited()
        with self.db() as db:
            self.assertEqual(db.query(Session).count(), 0)
            self.assertEqual(db.query(AideCall).count(), 0)

    def test_turn_stream_uses_pinned_model_and_one_atomic_message_pair(self):
        call = self.call()
        tid, response = self.turn(call)
        self.assertEqual(response.status_code, 200, response.text)
        events = self.events(response)
        self.assertEqual(events[0]["transcript"]["text"], "hello there")
        receipt = events[-1]["voice_turn"]
        self.assertEqual(receipt["state"], "saved", response.text)
        rows = self.rows()
        self.assertEqual(
            [(r[1], r[2]) for r in rows],
            [("user", "hello there"), ("assistant", "Hello. This is synthetic.")],
        )
        self.assertEqual(receipt["user_message_id"], rows[0][0])
        self.assertEqual(receipt["assistant_message_id"], rows[1][0])
        self.assertTrue(all(r[3]["voice_turn_id"] == tid for r in rows))
        self.assertEqual(self.outputs[0][1:], ("http://127.0.0.1:1/v1", "voice-text"))
        self.assertFalse(chat._streams)

    def test_upload_retry_replays_receipt_without_reinvocation(self):
        call = self.call()
        tid, first = self.turn(call)
        _, second = self.turn(call, tid)
        self.assertEqual(second.status_code, 200, second.text)
        replay = self.events(second)[0]["voice_turn"]
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            replay["assistant_message_id"],
            self.events(first)[-1]["voice_turn"]["assistant_message_id"],
        )
        self.assertEqual(len(self.outputs), 1)
        self.assertEqual(self.transcription.await_count, 1)
        self.assertEqual(len(self.rows()), 2)
        _, conflict = self.turn(call, tid, b"different")
        self.assertEqual(conflict.status_code, 409)

    def test_repeated_identical_failed_utterances_are_distinct(self):
        self.fail_model = True
        call = self.call()
        first_id, first = self.turn(call)
        second_id, second = self.turn(call)
        self.assertEqual(self.events(first)[-1]["voice_turn"]["state"], "failed")
        self.assertEqual(self.events(second)[-1]["voice_turn"]["state"], "failed")
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r[3]["voice_turn_id"] for r in rows], [first_id, second_id])

    def test_no_speech_saves_no_empty_message_and_returns_final_receipt(self):
        self.transcription.return_value = {"text": "   "}
        call = self.call()
        _, response = self.turn(call)
        self.assertEqual(self.events(response)[-1]["voice_turn"]["state"], "failed")
        self.assertTrue(response.text.endswith("data: [DONE]\n\n"))
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.outputs, [])

    def test_remote_text_requires_exact_confirmation_not_paid_audio_fallback(self):
        with self.db() as db:
            db.get(ModelEndpoint, self.eid).base_url = "https://text.example.invalid/v1"
            db.commit()
        readiness = self.client.get("/api/aide/voice/status").json()
        self.assertFalse(readiness["available"])
        self.assertTrue(readiness["can_confirm"])
        response = self.client.post("/api/aide/voice/calls", json={"request_id": str(uuid4())})
        self.assertEqual(response.status_code, 409)
        call = self.call(confirmed_endpoint_id=self.eid, confirmed_model="voice-text")
        self.assertEqual(call["provider"], "local")
        self.assertEqual(self.outputs, [])

    def test_changed_endpoint_fails_without_stt_or_model_fallback(self):
        call = self.call()
        with self.db() as db:
            db.get(ModelEndpoint, self.eid).base_url = "https://changed.example.invalid/v1"
            db.commit()
        _, response = self.turn(call)
        self.assertIn("voice_model_changed", response.text)
        self.transcription.assert_not_awaited()
        self.assertEqual(self.outputs, [])

    def test_upload_limits_and_cross_origin_rejected_before_worker(self):
        call = self.call()
        for headers, status in [
            ({"content-length": str(8 * 1024 * 1024 + 1)}, 413),
            ({"x-audio-duration-seconds": "61"}, 413),
            ({"x-audio-duration-seconds": "NaN"}, 413),
            ({"origin": "https://evil.example"}, 403),
            ({"sec-fetch-site": "cross-site"}, 403),
            ({"authorization": "Bearer aide_fixture"}, 401),
        ]:
            with self.subTest(headers=headers):
                _, response = self.turn(call, **headers)
                self.assertEqual(response.status_code, status, response.text)
        self.transcription.assert_not_awaited()
        _, response = self.turn(call, audio=b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)

    def test_call_and_turn_replay_after_hangup_never_starts_new_work(self):
        call = self.call()
        tid, response = self.turn(call)
        ended = self.client.post(f"/api/aide/voice/calls/{call['id']}/hangup")
        self.assertFalse(ended.json()["tasks_cancelled"])
        _, repeated = self.turn(call, tid)
        self.assertEqual(repeated.status_code, 200)
        _, new = self.turn(call)
        self.assertEqual(new.status_code, 409)
        self.assertEqual(len(self.outputs), 1)

    def test_speech_is_bounded_pcm_and_cancel_blocks_late_clauses(self):
        call = self.call()
        tid, _ = self.turn(call)

        async def pcm(*args):
            yield b"\x00\x00" * 10
            yield b"\x01\x00" * 10

        url = f"/api/aide/voice/calls/{call['id']}/turns/{tid}"
        clause = {"clause_id": str(uuid4()), "text": "Hello."}
        with mock.patch.object(local_voice, "synthesize", pcm):
            spoken = self.client.post(url + "/speech", json=clause)
            self.assertEqual(spoken.status_code, 200, spoken.text)
            self.assertEqual(len(spoken.content), 40)
            self.assertEqual(spoken.headers["x-audio-sample-rate"], "24000")
            self.assertEqual(self.client.post(url + "/speech", json=clause).status_code, 409)
            self.client.post(url + "/cancel")
            clause["clause_id"] = str(uuid4())
            self.assertEqual(self.client.post(url + "/speech", json=clause).status_code, 409)

    def test_cancel_never_stops_unowned_typed_stream(self):
        async def check():
            typed = asyncio.Event()
            voice = asyncio.Event()
            chat._streams[self.sid] = typed
            active = aide_voice.ActiveTurn(asyncio.Event(), stop=voice)
            aide_voice._active[("call", "turn")] = active
            aide_voice.cancel_owned("call", "turn")
            self.assertTrue(voice.is_set())
            self.assertFalse(typed.is_set())

        asyncio.run(check())

    def test_background_handoff_is_pinned_idempotent_and_survives_hangup(self):
        self.transcription.return_value = {"text": "please check the release in the background"}
        call = self.call()
        with mock.patch.object(jarvis_handoff, "launch") as launch:
            tid, response = self.turn(call)
            events = self.events(response)
            result = events[-1]["voice_turn"]
            self.assertEqual(result["state"], "handoff", response.text)
            self.assertTrue(result["run_id"])
            self.assertEqual(self.outputs, [])
            self.assertEqual(self.rows(), [])
            self.turn(call, tid)
            launch.assert_called_once_with(result["run_id"])
        self.client.post(f"/api/aide/voice/calls/{call['id']}/hangup")

        async def agent(messages, _ep, _model, _stop, _settings, accumulated, *_args, **_kwargs):
            accumulated.append("finished synthetic work")
            yield {"delta": "finished synthetic work", "done": True}

        with mock.patch("services.chat_turn.run_agent", agent):
            asyncio.run(jarvis_handoff._execute(result["run_id"]))
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row[3]["voice_turn_id"] == tid for row in rows))
        with self.db() as db:
            self.assertEqual(db.get(JarvisRun, result["run_id"]).state, "succeeded")
        saved = self.client.get(f"/api/aide/voice/calls/{call['id']}/turns/{tid}").json()
        self.assertEqual(saved["assistant_message_id"], rows[1][0])

    def test_background_policy_does_not_promote_descriptions(self):
        self.assertTrue(aide_voice.wants_background("please work on the release in the background"))
        self.assertFalse(aide_voice.wants_background("explain background tasks"))
        self.assertFalse(aide_voice.wants_background("prepare a guide that runs in the background"))
