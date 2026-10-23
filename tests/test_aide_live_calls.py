import asyncio
import os
import time
from unittest import mock
from uuid import uuid4

from core.database import AideCall, AideCallEvent, JarvisRun, Message, ModelEndpoint, Session
from services import jarvis_handoff
from tests._client import ApiTest


class AideLiveCallTest(ApiTest):
    def _realtime(self):
        db = self.db()
        endpoint = ModelEndpoint(
            name="OpenAI realtime",
            base_url="https://api.openai.com/v1",
            provider_id="openai",
            api_key="sk-test",
            enabled=True,
            cached_models='["gpt-realtime"]',
        )
        db.add(endpoint)
        db.commit()
        db.close()

    def _call(self):
        identity = str(uuid4())
        response = self.client.post("/api/aide/calls", json={"request_id": identity})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _negotiate(self, call):
        with mock.patch(
            "services.realtime.negotiate_offer", new=mock.AsyncMock(return_value="v=0\r\nanswer")
        ):
            response = self.client.post(
                f"/api/aide/calls/{call['id']}/offer", content="v=0\r\noffer"
            )
        self.assertEqual(response.status_code, 200)

    def test_authorized_call_transcripts_outlive_recent_auth_without_repeating_messages(self):
        from core import auth

        self._realtime()
        call = self._call()
        token = auth.create_session_token()
        auth.store_token(token)
        self.addCleanup(auth.revoke_token, token)
        self.client.cookies.set("aide_session", token)
        with mock.patch.dict(os.environ, {"AUTH_ENABLED": "true"}):
            self._negotiate(call)
            auth._recent_auth[token] -= auth.RECENT_AUTH_SECONDS + 1
            self.assertTrue(auth.verify_session(token))
            self.assertFalse(auth.verify_recent_session(token))
            body = {"provider_event_id": "after-601s", "role": "user", "text": "still here"}
            url = f"/api/aide/calls/{call['id']}/transcripts"
            first = self.client.post(url, json=body)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertTrue(first.json()["created"])
            self.client.post(f"/api/aide/calls/{call['id']}/hangup")
            again = self.client.post(url, json=body)
            self.assertEqual(again.status_code, 200)
            self.assertFalse(again.json()["created"])
            auth._tokens[token] = time.time() - 1
            expired = self.client.post(url, json={**body, "provider_event_id": "expired"})
            self.assertEqual(expired.status_code, 401)
            auth.store_token(token)
            auth.revoke_token(token)
            blocked = self.client.post(url, json={**body, "provider_event_id": "revoked"})
            self.assertEqual(blocked.status_code, 401)
        with self.db() as db:
            self.assertEqual(db.query(Message).filter_by(session_id=call["session_id"]).count(), 1)

    def test_stale_owner_offer_does_not_start_upstream_until_reconfirmed(self):
        from core import auth

        self._realtime()
        call = self._call()
        token = auth.create_session_token()
        auth.store_token(token)
        self.addCleanup(auth.revoke_token, token)
        self.client.cookies.set("aide_session", token)
        auth._recent_auth[token] -= auth.RECENT_AUTH_SECONDS + 1
        with (
            mock.patch.dict(os.environ, {"AUTH_ENABLED": "true"}),
            mock.patch(
                "services.realtime.negotiate_offer", new_callable=mock.AsyncMock
            ) as provider,
        ):
            response = self.client.post(
                f"/api/aide/calls/{call['id']}/offer", content="v=0\r\noffer"
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "recent_auth_required")
            provider.assert_not_awaited()
            with self.db() as db:
                self.assertEqual(
                    db.query(AideCallEvent)
                    .filter_by(call_id=call["id"], kind="offer_reserved")
                    .count(),
                    0,
                )
            auth.mark_session_recent(token)
            provider.return_value = "v=0\r\nanswer"
            confirmed = self.client.post(
                f"/api/aide/calls/{call['id']}/offer", content="v=0\r\noffer"
            )
            self.assertEqual(confirmed.status_code, 200)
            provider.assert_awaited_once()

    def test_unnegotiated_call_cannot_accept_transcripts(self):
        self._realtime()
        call = self._call()
        response = self.client.post(
            f"/api/aide/calls/{call['id']}/transcripts",
            json={"provider_event_id": "unoffered", "role": "user", "text": "not authorized"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "call_not_negotiated")

    def test_valid_admin_bearer_cannot_save_owner_call_transcripts(self):
        self._realtime()
        call = self._call()
        self._negotiate(call)
        raw = self.client.post(
            "/api/tokens", json={"name": "synthetic admin", "scopes": ["admin"]}
        ).json()["token"]
        with mock.patch.dict(os.environ, {"AUTH_ENABLED": "true"}):
            response = self.client.post(
                f"/api/aide/calls/{call['id']}/transcripts",
                headers={"Authorization": f"Bearer {raw}"},
                json={"provider_event_id": "bearer", "role": "user", "text": "blocked"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "owner_session_required")
        with self.db() as db:
            self.assertEqual(db.query(Message).filter_by(session_id=call["session_id"]).count(), 0)

    def test_transcript_cannot_be_submitted_to_other_call_provider(self):
        self._realtime()
        call = self._call()
        self._negotiate(call)
        with self.db() as db:
            db.get(AideCall, call["id"]).provider = "local"
            db.commit()
        response = self.client.post(
            f"/api/aide/calls/{call['id']}/transcripts",
            json={"provider_event_id": "wrong-provider", "role": "user", "text": "blocked"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "call_not_negotiated")

    def test_call_identity_transcripts_and_hangup_share_primary_thread(self):
        self._realtime()
        call = self._call()
        replay = self.client.post("/api/aide/calls", json={"request_id": call["id"]})
        self.assertEqual(replay.status_code, 200)
        self.assertFalse(replay.json()["created"])
        self._negotiate(call)

        body = {
            "provider_event_id": "input-final-1",
            "role": "user",
            "text": "continue the release check",
        }
        first = self.client.post(f"/api/aide/calls/{call['id']}/transcripts", json=body)
        repeated = self.client.post(f"/api/aide/calls/{call['id']}/transcripts", json=body)
        self.assertTrue(first.json()["created"])
        self.assertFalse(repeated.json()["created"])

        db = self.db()
        session = db.get(Session, call["session_id"])
        run = jarvis_handoff.create_handoff(db, session, "finish the release check")
        db.commit()
        run_id = run.id
        db.close()

        ended = self.client.post(f"/api/aide/calls/{call['id']}/hangup")
        self.assertEqual(ended.status_code, 200)
        self.assertFalse(ended.json()["tasks_cancelled"])

        async def agent(messages, _ep, _model, _stop, _settings, accumulated, *_args, **_kwargs):
            accumulated.append("release check complete")
            yield {"delta": "release check complete", "done": True}

        with (
            mock.patch.object(
                jarvis_handoff, "load_settings", return_value={"memory_policy": "off"}
            ),
            mock.patch("services.chat_turn.run_agent", agent),
        ):
            asyncio.run(jarvis_handoff._execute(run_id))

        db = self.db()
        self.assertEqual(db.get(AideCall, call["id"]).state, "ended")
        self.assertEqual(db.get(JarvisRun, run_id).state, "succeeded")
        messages = db.query(Message).filter_by(session_id=call["session_id"]).all()
        self.assertEqual(
            [(message.role, message.content) for message in messages],
            [
                ("user", "continue the release check"),
                ("user", "finish the release check"),
                ("assistant", "release check complete"),
            ],
        )
        self.assertEqual(
            db.query(AideCallEvent)
            .filter_by(call_id=call["id"], provider_event_id="input-final-1")
            .count(),
            1,
        )
        db.close()

    def test_provider_event_identity_cannot_be_reused_for_different_text(self):
        self._realtime()
        call = self._call()
        self._negotiate(call)
        url = f"/api/aide/calls/{call['id']}/transcripts"
        first = self.client.post(
            url,
            json={"provider_event_id": "same", "role": "assistant", "text": "first"},
        )
        conflict = self.client.post(
            url,
            json={"provider_event_id": "same", "role": "assistant", "text": "changed"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "call_event_identity_conflict")

    def test_final_transcript_racing_with_hangup_is_still_saved_once(self):
        self._realtime()
        call = self._call()
        self._negotiate(call)
        ended = self.client.post(f"/api/aide/calls/{call['id']}/hangup")
        self.assertEqual(ended.status_code, 200)

        body = {
            "provider_event_id": "late-final-1",
            "role": "assistant",
            "text": "The task is running in the background.",
        }
        saved = self.client.post(f"/api/aide/calls/{call['id']}/transcripts", json=body)
        replay = self.client.post(f"/api/aide/calls/{call['id']}/transcripts", json=body)
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["created"])
        self.assertFalse(replay.json()["created"])

        db = self.db()
        messages = db.query(Message).filter_by(session_id=call["session_id"]).all()
        self.assertEqual(
            [(message.role, message.content) for message in messages], [("assistant", body["text"])]
        )
        db.close()

    def test_offer_uses_server_negotiation_and_marks_call_connected(self):
        self._realtime()
        call = self._call()
        with mock.patch(
            "services.realtime.negotiate_offer",
            new=mock.AsyncMock(return_value="v=0\r\nanswer"),
        ) as negotiate:
            response = self.client.post(
                f"/api/aide/calls/{call['id']}/offer",
                content="v=0\r\noffer",
                headers={"content-type": "application/sdp"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "v=0\r\nanswer")
        negotiate.assert_awaited_once()
        db = self.db()
        self.assertEqual(db.get(AideCall, call["id"]).state, "connected")
        db.close()

    def test_ended_and_non_realtime_calls_reject_before_provider_work(self):
        self._realtime()
        for provider, ended, code in [
            ("openai-realtime", True, "call_already_ended"),
            ("local", False, "call_provider_mismatch"),
        ]:
            call = self._call()
            with self.db() as db:
                row = db.get(AideCall, call["id"])
                row.provider = provider
                if ended:
                    row.state = "ended"
                db.commit()
            with mock.patch(
                "services.realtime.negotiate_offer", new_callable=mock.AsyncMock
            ) as upstream:
                response = self.client.post(
                    f"/api/aide/calls/{call['id']}/offer", content="v=0\r\noffer"
                )
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["code"], code)
            upstream.assert_not_awaited()

    def test_duplicate_offer_is_rejected_before_another_provider_call(self):
        self._realtime()
        call = self._call()
        url = f"/api/aide/calls/{call['id']}/offer"
        with mock.patch(
            "services.realtime.negotiate_offer", new=mock.AsyncMock(return_value="v=0\r\nanswer")
        ) as upstream:
            self.assertEqual(self.client.post(url, content="v=0\r\noffer").status_code, 200)
            repeated = self.client.post(url, content="v=0\r\noffer")
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(repeated.json()["code"], "call_offer_already_submitted")
        upstream.assert_awaited_once()

    def test_offer_keeps_the_created_model_when_model_order_changes(self):
        self._realtime()
        call = self._call()
        with self.db() as db:
            endpoint = db.query(ModelEndpoint).one()
            endpoint.cached_models = '["different-realtime", "gpt-realtime"]'
            db.commit()
        with mock.patch(
            "services.realtime.negotiate_offer", new=mock.AsyncMock(return_value="v=0\r\nanswer")
        ) as upstream:
            response = self.client.post(
                f"/api/aide/calls/{call['id']}/offer", content="v=0\r\noffer"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(upstream.call_args.args[0].model, call["model"])

    def test_offer_does_not_switch_to_another_endpoint_when_original_is_disabled(self):
        self._realtime()
        call = self._call()
        with self.db() as db:
            db.query(ModelEndpoint).update({ModelEndpoint.enabled: False})
            db.commit()
        self._realtime()
        with mock.patch(
            "services.realtime.negotiate_offer", new_callable=mock.AsyncMock
        ) as upstream:
            response = self.client.post(
                f"/api/aide/calls/{call['id']}/offer", content="v=0\r\noffer"
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "realtime_unavailable")
        upstream.assert_not_awaited()

    def test_offer_reservation_commits_before_await_and_blocks_inflight_replay(self):
        self._realtime()
        call = self._call()
        from starlette.requests import Request

        from routes.aide import negotiate_call

        def request():
            async def receive():
                return {"type": "http.request", "body": b"v=0\r\noffer"}

            return Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/",
                    "headers": [],
                    "client": ("127.0.0.1", 1),
                },
                receive,
            )

        async def run():
            entered, finish = asyncio.Event(), asyncio.Event()

            async def upstream(_target, _offer):
                self.assertFalse(first_db.in_transaction())
                entered.set()
                await finish.wait()
                return "v=0\r\nanswer"

            with (
                self.db() as first_db,
                self.db() as second_db,
                mock.patch("services.realtime.negotiate_offer", upstream),
                mock.patch("routes.aide.require_recent_owner"),
            ):
                pending = asyncio.create_task(negotiate_call(call["id"], request(), first_db))
                await asyncio.wait_for(entered.wait(), timeout=2)
                try:
                    from core.api_errors import ApiError

                    with self.assertRaises(ApiError) as error:
                        await negotiate_call(call["id"], request(), second_db)
                    self.assertEqual(error.exception.code, "call_offer_already_submitted")
                finally:
                    second_db.rollback()
                    finish.set()
                    await pending

        asyncio.run(run())


class AideCapabilitiesTest(ApiTest):
    def test_capabilities_name_pi_as_the_coding_harness(self):
        db = self.db()
        db.add(
            ModelEndpoint(
                name="OpenAI realtime",
                base_url="https://api.openai.com/v1",
                provider_id="openai",
                api_key="sk-test",
                enabled=True,
                cached_models='["gpt-realtime"]',
            )
        )
        db.commit()
        db.close()
        response = self.client.get("/api/aide/capabilities")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["conversation"]["permanent"])
        self.assertTrue(body["voice"]["available"])
        self.assertEqual(body["coding"]["harness"], "pi")
        self.assertIn(
            body["coding"]["state"], {"ready", "missing", "needs_node", "failed", "installing"}
        )
        self.assertTrue(body["durable_tasks"]["available"])
