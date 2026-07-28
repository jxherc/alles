import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from core.database import (
    JarvisConnector,
    JarvisDeliveryAttempt,
    JarvisInboxEvent,
    JarvisRun,
    JarvisRunEvent,
    JarvisRunPrompt,
    JarvisWorkflow,
    Session,
)
from services import jarvis_discord, jarvis_handoff, jarvis_outbox, secretstore
from services.jarvis_store import (
    answer_choice,
    append_event,
    create_prompt,
    json_value,
    transition_run,
)
from tests._client import ApiTest


class JarvisDiscordTest(ApiTest):
    identity = {
        "id": "9001",
        "username": "jarvis-test",
        "global_name": "Jarvis",
        "bot": True,
    }

    def test_config_change_wakes_the_runtime_loop_thread_safely(self):
        loop = mock.Mock()
        loop.is_closed.return_value = False
        event = mock.Mock()
        with (
            mock.patch.object(jarvis_discord, "_runtime_loop", loop),
            mock.patch.object(jarvis_discord, "_restart_event", event),
        ):
            jarvis_discord.notify_config_changed()

        loop.call_soon_threadsafe.assert_called_once_with(event.set)
        event.set.assert_not_called()

    def test_gateway_does_not_checkpoint_a_message_that_failed_processing(self):
        connected = self._connect()
        connector_id = connected["id"]
        db = self.db()
        row = db.get(JarvisConnector, connector_id)
        config = json_value(row.config, dict)
        config["gateway_sequence"] = 7
        jarvis_discord._save_config(row, config)
        db.commit()
        db.close()

        class GatewayClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, *_args, **_kwargs):
                return mock.Mock(
                    status_code=200,
                    json=lambda: {"url": "wss://gateway.example.test"},
                    raise_for_status=lambda: None,
                )

        class GatewaySocket:
            def __init__(self):
                self.packets = iter(
                    (
                        {"op": 10, "d": {"heartbeat_interval": 60_000}},
                        {
                            "op": 0,
                            "s": 8,
                            "t": "MESSAGE_CREATE",
                            "d": {"id": "failed-message"},
                        },
                    )
                )

            async def recv(self):
                return json.dumps(next(self.packets))

            async def send(self, _payload):
                return None

        class GatewayConnection:
            def __init__(self):
                self.socket = GatewaySocket()

            async def __aenter__(self):
                return self.socket

            async def __aexit__(self, *_args):
                return None

        jarvis_discord._restart_event.clear()
        save_sequence = mock.AsyncMock()
        with (
            mock.patch.object(jarvis_discord.httpx, "AsyncClient", return_value=GatewayClient()),
            mock.patch("websockets.connect", return_value=GatewayConnection()),
            mock.patch.object(jarvis_discord, "_set_runtime_state", new=mock.AsyncMock()),
            mock.patch.object(jarvis_discord, "_notice_loop", new=mock.AsyncMock()),
            mock.patch.object(
                jarvis_discord,
                "process_message",
                new=mock.AsyncMock(side_effect=RuntimeError("transient handler failure")),
            ),
            mock.patch.object(jarvis_discord, "_save_gateway_sequence", new=save_sequence),
        ):
            with self.assertRaisesRegex(RuntimeError, "transient handler failure"):
                asyncio.run(jarvis_discord._gateway_session(connector_id))

        save_sequence.assert_awaited_once_with(connector_id, 7)

    def test_gateway_retries_reuse_enforced_nonces_for_each_message_reply(self):
        source = Path(jarvis_discord.__file__).read_text("utf-8")
        gateway = source[source.index('elif event_type == "MESSAGE_CREATE"') :]
        self.assertIn("discord-reply:{connector_id}:{message_id}:{index}:{channel_id}", gateway)
        self.assertIn("await _api_message(token, channel_id, text, nonce=nonce)", gateway)
        self.assertLess(gateway.index("nonce = hashlib.sha256"), gateway.index("handled_sequence"))

    def test_invalid_gateway_session_preserves_only_a_resumable_checkpoint(self):
        state = mock.AsyncMock()
        sleep = mock.AsyncMock()
        with (
            mock.patch.object(jarvis_discord, "_set_runtime_state", new=state),
            mock.patch.object(jarvis_discord.asyncio, "sleep", new=sleep),
            mock.patch.object(jarvis_discord.random, "uniform", return_value=3.25),
        ):
            resumable = asyncio.run(
                jarvis_discord._handle_invalid_gateway_session(
                    "connector-1", resumable=True, handled_sequence=41
                )
            )
            nonresumable = asyncio.run(
                jarvis_discord._handle_invalid_gateway_session(
                    "connector-1", resumable=False, handled_sequence=42
                )
            )

        self.assertEqual(resumable, 41)
        self.assertIsNone(nonresumable)
        self.assertEqual(
            state.await_args_list,
            [
                mock.call("connector-1", "reconnecting", gateway_sequence=41),
                mock.call(
                    "connector-1",
                    "reconnecting",
                    gateway_sequence=None,
                    gateway_session_id="",
                    resume_gateway_url="",
                ),
            ],
        )
        self.assertEqual(sleep.await_args_list, [mock.call(3.25), mock.call(3.25)])

    def _connect(self):
        with mock.patch.object(
            jarvis_discord, "validate_token", new=mock.AsyncMock(return_value=self.identity)
        ):
            response = self.client.post(
                "/api/jarvis/discord", json={"bot_token": "synthetic-discord-bot-token"}
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_discord_content_hides_internal_artifact_markup(self):
        wrapped = (
            '<aide-artifact type="markdown" title="answer" lang="text">\n'
            "the useful answer\n"
            "</aide-artifact>"
        )
        self.assertEqual(jarvis_discord._discord_content(wrapped), "the useful answer")
        self.assertEqual(jarvis_discord._discord_content('<aide-artifact type="markdown"'), "")

    def test_news_brief_retries_reuse_a_discord_enforced_nonce(self):
        connected = self._connect()
        self._message(
            connected["id"],
            message_id="pair-news",
            content=f"pair {connected['pairing_code']}",
        )
        with (
            mock.patch.object(jarvis_discord, "in_quiet_hours", return_value=False),
            mock.patch.object(
                jarvis_discord, "_api_message", new=mock.AsyncMock(return_value=True)
            ) as send,
        ):
            first = asyncio.run(
                jarvis_discord.deliver_news_brief(
                    "daily brief", idempotency_key="news-brief:brief-1"
                )
            )
            second = asyncio.run(
                jarvis_discord.deliver_news_brief(
                    "daily brief", idempotency_key="news-brief:brief-1"
                )
            )

        self.assertEqual((first, second), ("delivered", "delivered"))
        nonces = [call.kwargs["nonce"] for call in send.await_args_list]
        self.assertEqual(len(nonces[0]), 25)
        self.assertEqual(nonces, [nonces[0], nonces[0]])

    def _message(self, connector_id, *, message_id, user_id="42", content="status", **extra):
        return asyncio.run(
            jarvis_discord.process_message(
                connector_id,
                {
                    "id": message_id,
                    "channel_id": extra.pop("channel_id", "dm-1"),
                    "content": content,
                    "author": {
                        "id": user_id,
                        "username": f"user-{user_id}",
                        **extra.pop("author", {}),
                    },
                    **extra,
                },
            )
        )

    def test_connect_encrypts_token_and_returns_pairing_code_once(self):
        connected = self._connect()
        self.assertTrue(connected["configured"])
        self.assertTrue(connected["enabled"])
        self.assertFalse(connected["paired"])
        self.assertRegex(connected["pairing_code"], r"^\d{6}$")
        self.assertNotIn("pairing_code", self.client.get("/api/jarvis/discord").json())
        db = self.db()
        config = json_value(db.get(JarvisConnector, connected["id"]).config, dict)
        proof = config["pairing_proof"]
        self.assertTrue(secretstore.is_sealed(proof))
        self.assertNotIn(connected["pairing_code"], proof)
        self.assertNotIn("pairing_hash", config)
        db.close()

        db = self.db()
        row = db.get(JarvisConnector, connected["id"])
        self.assertEqual(row.secret, "synthetic-discord-bot-token")
        self.assertNotIn(connected["pairing_code"], row.config)
        db.close()

    def test_one_owner_pairing_filters_bots_webhooks_users_and_channels(self):
        connected = self._connect()
        connector_id = connected["id"]
        code = connected["pairing_code"]

        bot = self._message(
            connector_id,
            message_id="bot",
            content=f"pair {code}",
            author={"bot": True},
        )
        self.assertEqual(bot, [])
        webhook = self._message(
            connector_id, message_id="webhook", content=f"pair {code}", webhook_id="hook"
        )
        self.assertEqual(webhook, [])
        guild_pair = self._message(
            connector_id, message_id="guild-pair", content=f"pair {code}", guild_id="guild"
        )
        self.assertEqual(guild_pair, [])

        paired = self._message(connector_id, message_id="pair", content=f"pair {code}")
        self.assertIn("Paired", paired[0][1])
        self.assertEqual(self._message(connector_id, message_id="other", user_id="99"), [])
        self.assertEqual(
            self._message(
                connector_id,
                message_id="unknown-channel",
                channel_id="123",
                guild_id="guild",
            ),
            [],
        )
        db = self.db()
        self.assertEqual(
            [
                row.source_id
                for row in db.query(JarvisInboxEvent).order_by(JarvisInboxEvent.source_id)
            ],
            ["pair"],
        )
        db.close()
        updated = self.client.patch(
            "/api/jarvis/discord", json={"allowed_channel_ids": ["123", "bad", "123"]}
        ).json()
        self.assertEqual(updated["allowed_channel_ids"], ["123"])
        allowed = self._message(
            connector_id,
            message_id="approved-channel",
            channel_id="123",
            guild_id="guild",
        )
        self.assertIn("No recent", allowed[0][1])

    def test_invalid_pairing_attempts_lock_only_the_requester(self):
        connected = self._connect()
        connector_id = connected["id"]
        code = connected["pairing_code"]

        for attempt in range(jarvis_discord.PAIRING_MAX_FAILURES + 1):
            reply = self._message(
                connector_id,
                message_id=f"attacker-{attempt}",
                user_id="99",
                content="pair 000000",
            )
            self.assertIn("invalid or expired", reply[0][1])

        paired = self._message(
            connector_id,
            message_id="owner-pair",
            user_id="42",
            content=f"pair {code}",
        )
        self.assertIn("Paired", paired[0][1])

        db = self.db()
        config = json_value(db.get(JarvisConnector, connector_id).config, dict)
        self.assertEqual(config["owner_user_id"], "42")
        self.assertNotIn("pairing_hash", config)
        self.assertNotIn("pairing_proof", config)
        self.assertNotIn("pairing_failures", config)
        db.close()

    def test_rejected_pairing_events_are_bounded_without_creating_inbox_rows(self):
        connected = self._connect()
        connector_id = connected["id"]

        first = self._message(
            connector_id,
            message_id="rejected-replay",
            user_id="99",
            content="pair 000000",
        )
        replay = self._message(
            connector_id,
            message_id="rejected-replay",
            user_id="99",
            content="pair 000000",
        )
        self.assertIn("invalid or expired", first[0][1])
        self.assertEqual(replay, [])

        for attempt in range(jarvis_discord.PAIRING_REJECTED_EVENT_LIMIT + 10):
            self._message(
                connector_id,
                message_id=f"rejected-{attempt}",
                user_id="99",
                content="pair 000000",
            )

        db = self.db()
        config = json_value(db.get(JarvisConnector, connector_id).config, dict)
        self.assertEqual(db.query(JarvisInboxEvent).count(), 0)
        self.assertEqual(
            len(config["pairing_rejected_events"]),
            jarvis_discord.PAIRING_REJECTED_EVENT_LIMIT,
        )
        db.close()

    def test_dispatched_timestamp_uses_utc_clock(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-for-utc",
            content=f"pair {connected['pairing_code']}",
        )
        fixed = datetime(2026, 7, 22, 3, 4, 5, tzinfo=UTC)

        with mock.patch.object(jarvis_discord, "_utcnow", return_value=fixed):
            self._message(connector_id, message_id="utc-status")

        db = self.db()
        event = db.query(JarvisInboxEvent).filter_by(source_id="utc-status").one()
        self.assertEqual(event.dispatched_at, fixed.replace(tzinfo=None))
        db.close()

    def test_full_pairing_failure_map_requires_owner_to_reissue_the_code(self):
        connected = self._connect()
        connector_id = connected["id"]
        db = self.db()
        row = db.get(JarvisConnector, connector_id)
        config = json_value(row.config, dict)
        config["pairing_failures"] = {
            str(index): 1 for index in range(jarvis_discord.PAIRING_MAX_REQUESTERS)
        }
        jarvis_discord._save_config(row, config)
        db.commit()
        db.close()

        reply = self._message(
            connector_id,
            message_id="untracked-correct-code",
            user_id="new-requester",
            content=f"pair {connected['pairing_code']}",
        )

        self.assertIn("invalid or expired", reply[0][1])
        db = self.db()
        config = json_value(db.get(JarvisConnector, connector_id).config, dict)
        self.assertFalse(config.get("owner_user_id"))
        self.assertTrue(config.get("pairing_proof"))
        db.close()

    def test_global_pairing_failure_limit_requires_owner_to_reissue_the_code(self):
        connected = self._connect()
        connector_id = connected["id"]
        db = self.db()
        row = db.get(JarvisConnector, connector_id)
        config = json_value(row.config, dict)
        config["pairing_failure_count"] = jarvis_discord.PAIRING_GLOBAL_MAX_FAILURES
        jarvis_discord._save_config(row, config)
        db.commit()
        db.close()

        reply = self._message(
            connector_id,
            message_id="global-limit-correct-code",
            user_id="owner",
            content=f"pair {connected['pairing_code']}",
        )

        self.assertIn("invalid or expired", reply[0][1])
        db = self.db()
        config = json_value(db.get(JarvisConnector, connector_id).config, dict)
        self.assertFalse(config.get("owner_user_id"))
        self.assertTrue(config.get("pairing_proof"))
        db.close()

        regenerated = self.client.post(
            "/api/jarvis/discord/pairing-code", json={"revoke_owner": False}
        ).json()
        self.assertRegex(regenerated["pairing_code"], r"^\d{6}$")
        paired = self._message(
            connector_id,
            message_id="global-limit-correct-code-after-reissue",
            user_id="owner",
            content=f"pair {regenerated['pairing_code']}",
        )

        self.assertIn("Paired", paired[0][1])

    def test_multiline_discord_handoff_preserves_internal_formatting(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-formatting",
            content=f"pair {connected['pairing_code']}",
        )
        request = "review this code:\n```python\nvalue =  1\n```"
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(connector_id, message_id="formatted-work", content=request)

        db = self.db()
        workflow = db.query(JarvisWorkflow).order_by(JarvisWorkflow.created_at.desc()).first()
        self.assertEqual(workflow.prompt, request)
        db.close()

    def test_discord_starts_normal_aide_work_with_mutations_gated(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True) as launch:
            reply = self._message(
                connector_id,
                message_id="work-1",
                content="rename the report after checking it",
            )
        self.assertEqual(reply, [])
        launch.assert_called_once()

        db = self.db()
        run = db.query(JarvisRun).order_by(JarvisRun.created_at.desc()).first()
        event = db.query(JarvisRunEvent).filter_by(run_id=run.id, kind="handoff_requested").one()
        data = json_value(event.data, dict)
        self.assertEqual(data["permission_mode"], "approve")
        self.assertEqual(data["origin_kind"], "discord")
        self.assertEqual(data["origin_connector_id"], connector_id)
        self.assertTrue(data["origin_generation"])
        self.assertEqual(data["origin_channel_id"], "dm-1")
        inbox = db.query(JarvisInboxEvent).filter_by(source_id="work-1").one()
        self.assertEqual(inbox.entity_id, run.id)
        db.close()

        # The same Discord event never starts a second run.
        with mock.patch("services.jarvis_handoff.launch", return_value=True) as launch:
            self.assertEqual(
                self._message(
                    connector_id,
                    message_id="work-1",
                    content="rename the report after checking it",
                ),
                [],
            )
        launch.assert_not_called()

    def test_follow_up_messages_reuse_the_channel_conversation(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(connector_id, message_id="first", content="remember apples")
            self._message(connector_id, message_id="follow-up", content="what did I mention?")

        db = self.db()
        runs = db.query(JarvisRun).order_by(JarvisRun.created_at).all()
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0].session_id, runs[1].session_id)
        self.assertEqual(db.query(Session).count(), 1)
        self.assertEqual(db.get(Session, runs[0].session_id).name, "remember apples")
        db.close()

    def test_discord_shows_typing_then_streams_one_answer_message(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(connector_id, message_id="stream-work", content="explain this")

        db = self.db()
        run = db.query(JarvisRun).order_by(JarvisRun.created_at.desc()).first()
        run_id = run.id
        transition_run(db, run, "running")
        db.commit()
        db.close()
        jarvis_handoff._stream_text[run_id] = "the first part"

        typing = mock.AsyncMock(return_value=True)
        create = mock.AsyncMock(return_value="discord-message-1")
        edit_result = mock.AsyncMock(return_value="delivered")
        send = mock.AsyncMock(return_value=True)
        with (
            mock.patch.object(jarvis_discord, "_api_typing", new=typing),
            mock.patch.object(jarvis_discord, "_api_create_message", new=create),
            mock.patch.object(jarvis_discord, "_api_edit_message_result", new=edit_result),
            mock.patch.object(jarvis_discord, "_api_message", new=send),
        ):
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
            stream_nonce = jarvis_discord.hashlib.sha256(
                f"discord-stream:{run_id}".encode()
            ).hexdigest()[:25]
            create.assert_awaited_once_with(
                "synthetic-discord-bot-token",
                "dm-1",
                "the first part",
                nonce=stream_nonce,
            )
            typing.assert_awaited_once_with("synthetic-discord-bot-token", "dm-1")
            send.assert_not_awaited()

            # A restart during streaming must hydrate the durable provider id
            # before it decides whether a new message is needed.
            jarvis_discord._stream_messages.clear()
            jarvis_handoff._stream_text[run_id] = "the next part"
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
            create.assert_awaited_once()
            edit_result.assert_awaited_once_with(
                "synthetic-discord-bot-token",
                "dm-1",
                "discord-message-1",
                "the next part",
            )

            # Simulate a process restart: terminal delivery must recover the
            # provider message identity from the durable run event.
            jarvis_discord._stream_messages.clear()
            db = self.db()
            run = db.get(JarvisRun, run_id)
            transition_run(db, run, "succeeded", result_summary="the complete answer")
            db.commit()
            db.close()
            asyncio.run(jarvis_discord.deliver_notices(connector_id))

        edit_result.assert_has_awaits(
            [
                mock.call(
                    "synthetic-discord-bot-token",
                    "dm-1",
                    "discord-message-1",
                    "the next part",
                ),
                mock.call(
                    "synthetic-discord-bot-token",
                    "dm-1",
                    "discord-message-1",
                    "the complete answer",
                ),
            ]
        )
        send.assert_not_awaited()
        self.assertEqual(jarvis_handoff.stream_text(run_id), "")

        db = self.db()
        notice = db.query(JarvisRunEvent).filter_by(run_id=run_id, kind="discord_notice_sent").one()
        data = json_value(notice.data, dict)
        self.assertTrue(data["streamed"])
        self.assertEqual(data["message_id"], "discord-message-1")
        db.close()

    def test_live_stream_pauses_during_quiet_hours(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-quiet-stream",
            content=f"pair {connected['pairing_code']}",
        )
        db = self.db()
        connector = db.get(JarvisConnector, connector_id)
        owner_generation = jarvis_discord._owner_generation(json_value(connector.config, dict))
        db.close()
        jarvis_handoff._stream_text["quiet-run"] = "progress that must wait"

        create = mock.AsyncMock(return_value="message")
        typing = mock.AsyncMock(return_value=True)
        with (
            mock.patch.object(jarvis_discord, "in_quiet_hours", return_value=True),
            mock.patch.object(jarvis_discord, "_api_create_message", new=create),
            mock.patch.object(jarvis_discord, "_api_typing", new=typing),
        ):
            asyncio.run(
                jarvis_discord._deliver_stream(
                    "stale-token",
                    connector_id,
                    owner_generation,
                    "quiet-run",
                    "dm-1",
                )
            )

        create.assert_not_awaited()
        typing.assert_not_awaited()

    def test_live_and_terminal_delivery_stop_after_channel_access_is_revoked(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-revoked-channel",
            content=f"pair {connected['pairing_code']}",
        )
        db = self.db()
        connector = db.get(JarvisConnector, connector_id)
        config = json_value(connector.config, dict)
        owner_generation = jarvis_discord._owner_generation(config)
        connector.allowlist = json.dumps(["guild-channel"])
        db.commit()
        db.expunge(connector)
        db.close()

        db = self.db()
        current = db.get(JarvisConnector, connector_id)
        current.allowlist = "[]"
        db.commit()
        db.close()

        jarvis_handoff._stream_text["revoked-channel-run"] = "private progress"
        create_stream = mock.AsyncMock(return_value="message")
        typing = mock.AsyncMock(return_value=True)
        with (
            mock.patch.object(jarvis_discord, "_api_create_message", new=create_stream),
            mock.patch.object(jarvis_discord, "_api_typing", new=typing),
        ):
            asyncio.run(
                jarvis_discord._deliver_stream(
                    "stale-token",
                    connector_id,
                    owner_generation,
                    "revoked-channel-run",
                    "guild-channel",
                )
            )
        create_stream.assert_not_awaited()
        typing.assert_not_awaited()

        create_terminal = mock.AsyncMock(return_value=("delivered", "message"))
        payload = {
            "summary": "private result",
            "context": {
                "channel_id": "guild-channel",
                "owner_generation": owner_generation,
            },
        }
        with mock.patch.object(jarvis_discord, "_api_create_message_result", new=create_terminal):
            result = asyncio.run(
                jarvis_discord._discord_outbox_provider(
                    payload,
                    idempotency_key="revoked-channel",
                    connector=mock.Mock(id=connector_id),
                )
            )
        self.assertEqual(result["classification"], "permanent")
        create_terminal.assert_not_awaited()

    def test_deleted_live_stream_message_is_recreated_and_persisted(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-recreate-stream",
            content=f"pair {connected['pairing_code']}",
        )
        db = self.db()
        connector = db.get(JarvisConnector, connector_id)
        owner_generation = jarvis_discord._owner_generation(json_value(connector.config, dict))
        db.close()
        run_id = "deleted-live-run"
        jarvis_handoff._stream_text[run_id] = "new progress"
        jarvis_discord._stream_messages[run_id] = {
            "message_id": "deleted-message",
            "content": "old progress",
        }

        edit = mock.AsyncMock(return_value="missing")
        create = mock.AsyncMock(return_value="replacement-message")
        persist = mock.Mock()
        typing = mock.AsyncMock(return_value=True)
        with (
            mock.patch.object(jarvis_discord, "in_quiet_hours", return_value=False),
            mock.patch.object(jarvis_discord, "_api_edit_message_result", new=edit),
            mock.patch.object(jarvis_discord, "_api_create_message", new=create),
            mock.patch.object(jarvis_discord, "_persist_stream_message", new=persist),
            mock.patch.object(jarvis_discord, "_api_typing", new=typing),
        ):
            asyncio.run(
                jarvis_discord._deliver_stream(
                    "stale-token",
                    connector_id,
                    owner_generation,
                    run_id,
                    "dm-1",
                )
            )

        edit.assert_awaited_once_with(
            "synthetic-discord-bot-token", "dm-1", "deleted-message", "new progress"
        )
        create.assert_awaited_once_with(
            "synthetic-discord-bot-token",
            "dm-1",
            "new progress",
            nonce=jarvis_discord._stream_nonce(run_id),
        )
        persist.assert_called_once_with(
            connector_id,
            owner_generation,
            run_id,
            "dm-1",
            "replacement-message",
        )
        self.assertEqual(
            jarvis_discord._stream_messages[run_id]["message_id"], "replacement-message"
        )

    def test_deleted_stream_message_falls_back_to_a_new_terminal_notice(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-missing-stream",
            content=f"pair {connected['pairing_code']}",
        )
        db = self.db()
        connector = db.get(JarvisConnector, connector_id)
        payload = {
            "summary": "complete answer",
            "context": {
                "channel_id": "dm-1",
                "owner_generation": jarvis_discord._owner_generation(
                    json_value(connector.config, dict)
                ),
                "streamed_message_id": "deleted-message",
            },
        }
        db.expunge(connector)
        db.close()
        edit_result = mock.AsyncMock(return_value="missing")
        create = mock.AsyncMock(return_value=("delivered", "replacement-message"))
        with (
            mock.patch.object(jarvis_discord, "_api_edit_message_result", new=edit_result),
            mock.patch.object(jarvis_discord, "_api_create_message_result", new=create),
        ):
            result = asyncio.run(
                jarvis_discord._discord_outbox_provider(
                    payload,
                    idempotency_key="terminal-delivery-key",
                    connector=connector,
                )
            )
        self.assertEqual(
            result,
            {"classification": "delivered", "provider_message_id": "replacement-message"},
        )
        create.assert_awaited_once_with(
            "synthetic-discord-bot-token",
            "dm-1",
            "complete answer",
            nonce="terminal-delivery-key"[:25],
        )

        edit_result = mock.AsyncMock(return_value="permanent")
        with mock.patch.object(jarvis_discord, "_api_edit_message_result", new=edit_result):
            rejected = asyncio.run(
                jarvis_discord._discord_outbox_provider(
                    payload,
                    idempotency_key="terminal-delivery-key",
                    connector=connector,
                )
            )
        self.assertEqual(rejected["classification"], "permanent")

    def test_terminal_notice_create_preserves_permanent_failure_classification(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-permanent-create",
            content=f"pair {connected['pairing_code']}",
        )
        db = self.db()
        connector = db.get(JarvisConnector, connector_id)
        payload = {
            "summary": "complete answer",
            "context": {
                "channel_id": "dm-1",
                "owner_generation": jarvis_discord._owner_generation(
                    json_value(connector.config, dict)
                ),
            },
        }
        db.expunge(connector)
        db.close()
        create = mock.AsyncMock(return_value=("permanent", ""))
        with mock.patch.object(
            jarvis_discord,
            "_api_create_message_result",
            new=create,
        ):
            result = asyncio.run(
                jarvis_discord._discord_outbox_provider(
                    payload,
                    idempotency_key="terminal-delivery-key",
                    connector=connector,
                )
            )

        self.assertEqual(result, {"classification": "permanent", "provider_message_id": ""})

    def test_terminal_notice_rechecks_disabled_and_quiet_state_before_network_io(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-final-boundary",
            content=f"pair {connected['pairing_code']}",
        )
        db = self.db()
        connector = db.get(JarvisConnector, connector_id)
        generation = jarvis_discord._owner_generation(json_value(connector.config, dict))
        payload = {
            "summary": "complete answer",
            "context": {"channel_id": "dm-1", "owner_generation": generation},
        }
        db.expunge(connector)
        current = db.get(JarvisConnector, connector_id)
        current.enabled = False
        db.commit()
        db.close()
        send = mock.AsyncMock(return_value=("delivered", "message-1"))
        with mock.patch.object(jarvis_discord, "_api_create_message_result", new=send):
            disabled = asyncio.run(
                jarvis_discord._discord_outbox_provider(
                    payload, idempotency_key="delivery-key", connector=connector
                )
            )
        self.assertEqual(disabled["classification"], "permanent")
        send.assert_not_awaited()

        db = self.db()
        current = db.get(JarvisConnector, connector_id)
        current.enabled = True
        config = json_value(current.config, dict)
        config["quiet_hours"] = {
            "enabled": True,
            "start": "00:00",
            "end": "00:00",
            "timezone": "UTC",
        }
        jarvis_discord._save_config(current, config)
        db.commit()
        db.close()
        with mock.patch.object(jarvis_discord, "_api_create_message_result", new=send):
            quiet = asyncio.run(
                jarvis_discord._discord_outbox_provider(
                    payload, idempotency_key="delivery-key", connector=connector
                )
            )
        self.assertEqual(quiet["classification"], "transient")
        send.assert_not_awaited()

    def test_discord_can_answer_choices_but_never_approvals(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(connector_id, message_id="start", content="check two options")
        db = self.db()
        run = db.query(JarvisRun).order_by(JarvisRun.created_at.desc()).first()
        transition_run(db, run, "running")
        choice = create_prompt(db, run, kind="choice", question="pick", options=["a", "b"])
        db.commit()
        choice_id = choice.id
        run_id = run.id
        db.close()
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            reply = self._message(
                connector_id,
                message_id="answer",
                content=f"answer {choice_id} b",
            )
        self.assertIn("Choice saved", reply[0][1])

        db = self.db()
        run = db.get(JarvisRun, run_id)
        transition_run(db, run, "running")
        approval = create_prompt(db, run, kind="approval", question="write file?")
        db.commit()
        approval_id = approval.id
        db.close()
        denied = self._message(
            connector_id,
            message_id="approval",
            content=f"answer {approval_id} yes",
        )
        self.assertIn("Approvals must be handled inside Alles", denied[0][1])

    def test_discord_renders_and_answers_structured_questions(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-structured",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(connector_id, message_id="start-structured", content="ask about proof")
        db = self.db()
        run = db.query(JarvisRun).order_by(JarvisRun.created_at.desc()).first()
        transition_run(db, run, "running")
        prompt = create_prompt(
            db,
            run,
            kind="choice",
            title="Choose proof",
            questions=[
                {
                    "id": "surface",
                    "prompt": "Which surface?",
                    "choices": [
                        {"id": "files", "label": "Files"},
                        {"id": "aide", "label": "Aide"},
                    ],
                },
                {
                    "id": "proof",
                    "prompt": "Which proof?",
                    "selection": "multiple",
                    "choices": [
                        {"id": "browser", "label": "Browser"},
                        {"id": "tests", "label": "Tests"},
                    ],
                },
            ],
        )
        db.commit()
        prompt_id = prompt.id
        notice = jarvis_discord._notice_for(run, prompt)
        db.close()
        self.assertIn("surface=<choice>; proof=<choice>", notice)
        self.assertIn("browser: Browser", notice)

        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            reply = self._message(
                connector_id,
                message_id="answer-structured",
                content=f"answer {prompt_id} surface=files; proof=browser,tests",
            )
        self.assertIn("Choice saved", reply[0][1])
        db = self.db()
        saved = db.get(JarvisRunPrompt, prompt_id)
        self.assertEqual(
            json_value(saved.answer_data, dict)["answers"]["proof"]["selected"],
            ["browser", "tests"],
        )
        db.close()

    def test_terminal_notice_waits_through_quiet_hours_and_survives_restart(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(connector_id, message_id="work", content="check status")
        db = self.db()
        run = db.query(JarvisRun).order_by(JarvisRun.created_at.desc()).first()
        run_id = run.id
        transition_run(db, run, "running")
        transition_run(db, run, "succeeded", result_summary="all clear")
        row = db.get(JarvisConnector, connector_id)
        config = json_value(row.config, dict)
        current = datetime.now(UTC).strftime("%H:%M")
        config["quiet_hours"] = {
            "enabled": True,
            "start": current,
            "end": current,
            "timezone": "UTC",
        }
        row.config = json.dumps(config)
        db.commit()
        db.close()

        sender = mock.AsyncMock(return_value=("delivered", "discord-terminal"))
        with mock.patch.object(jarvis_discord, "_api_create_message_result", new=sender):
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
        sender.assert_not_awaited()

        self.client.patch("/api/jarvis/discord", json={"quiet_hours": {"enabled": False}})
        with mock.patch.object(jarvis_discord, "_api_create_message_result", new=sender):
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
        sender.assert_awaited_once()
        db = self.db()
        notice = db.query(JarvisRunEvent).filter_by(run_id=run_id, kind="discord_notice_sent").one()
        self.assertEqual(json_value(notice.data, dict)["state"], "succeeded")
        db.close()

    def test_each_choice_prompt_is_claimed_durably_and_delivered_once(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(connector_id, message_id="start", content="ask me twice")
        db = self.db()
        run = db.query(JarvisRun).order_by(JarvisRun.created_at.desc()).first()
        transition_run(db, run, "running")
        first = create_prompt(db, run, kind="choice", question="first?", options=["yes"])
        db.commit()
        run_id = run.id
        first_id = first.id
        db.close()

        claims = []

        async def create_message_result(_token, _channel, _content, *, nonce=""):
            check = self.db()
            attempt = (
                check.query(JarvisDeliveryAttempt)
                .filter_by(run_id=run_id, channel="discord")
                .order_by(JarvisDeliveryAttempt.created_at.desc())
                .first()
            )
            claims.append((attempt.state, attempt.lease_owner, nonce))
            check.close()
            return "delivered", f"discord-{len(claims)}"

        with mock.patch.object(
            jarvis_discord,
            "_api_create_message_result",
            new=create_message_result,
        ):
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
            db = self.db()
            first = db.get(type(first), first_id)
            answer_choice(db, first, "yes")
            run = db.get(JarvisRun, run_id)
            transition_run(db, run, "running")
            second = create_prompt(db, run, kind="choice", question="second?", options=["no"])
            second_id = second.id
            db.commit()
            db.close()
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
            asyncio.run(jarvis_discord.deliver_notices(connector_id))

        self.assertEqual(len(claims), 2)
        self.assertTrue(all(state == "delivering" and owner for state, owner, _nonce in claims))
        self.assertEqual(len({nonce for _state, _owner, nonce in claims}), 2)
        db = self.db()
        notices = (
            db.query(JarvisRunEvent).filter_by(run_id=run_id, kind="discord_notice_sent").all()
        )
        self.assertEqual(
            {json_value(event.data, dict)["notice_key"] for event in notices},
            {f"prompt:{first_id}", f"prompt:{second_id}"},
        )
        db.close()

    def test_notice_scan_reaches_an_older_unsent_run_after_two_hundred_sent_runs(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-notice-pagination",
            content=f"pair {connected['pairing_code']}",
        )
        db = self.db()
        connector = db.get(JarvisConnector, connector_id)
        generation = jarvis_discord._owner_generation(json_value(connector.config, dict))
        session = Session(name="notice pagination", mode="chat")
        db.add(session)
        db.flush()
        origin = {
            "kind": "discord",
            "connector_id": connector_id,
            "generation": generation,
            "channel_id": "dm-1",
            "message_id": "seed",
        }
        start = datetime(2026, 1, 1)
        for index in range(201):
            run = jarvis_handoff.create_handoff(
                db,
                session,
                f"work {index}",
                origin=origin,
            )
            run.created_at = start + timedelta(seconds=index)
            transition_run(db, run, "running")
            transition_run(db, run, "succeeded", result_summary=f"result {index}")
            if index:
                append_event(
                    db,
                    run,
                    "discord_notice_sent",
                    source="discord",
                    summary="Discord notice sent",
                    data={
                        "state": "succeeded",
                        "notice_key": "terminal:succeeded",
                        "owner_generation": generation,
                        "channel_id": "dm-1",
                    },
                )
        db.commit()
        db.close()

        sender = mock.AsyncMock(return_value=("delivered", "oldest-notice"))
        with mock.patch.object(jarvis_discord, "_api_create_message_result", new=sender):
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
        sender.assert_awaited_once()
        self.assertEqual(sender.await_args.args[2], "result 0")

    def test_owner_can_revoke_pairing_or_disconnect(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(connector_id, message_id="work", content="remember this")
        regenerated = self.client.post(
            "/api/jarvis/discord/pairing-code", json={"revoke_owner": True}
        ).json()
        self.assertFalse(regenerated["paired"])
        self.assertRegex(regenerated["pairing_code"], r"^\d{6}$")
        db = self.db()
        self.assertNotIn(
            "channel_sessions", json_value(db.get(JarvisConnector, connector_id).config, dict)
        )
        db.close()
        self.assertEqual(self.client.delete("/api/jarvis/discord").status_code, 200)
        self.assertFalse(self.client.get("/api/jarvis/discord").json()["configured"])

    def test_repaired_owner_cannot_inherit_previous_owner_work(self):
        connected = self._connect()
        connector_id = connected["id"]
        self._message(
            connector_id,
            message_id="pair-old-owner",
            user_id="old-owner",
            content=f"pair {connected['pairing_code']}",
        )
        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(
                connector_id,
                message_id="old-work",
                user_id="old-owner",
                content="remember the old owner's work",
            )

        db = self.db()
        old_run = db.query(JarvisRun).order_by(JarvisRun.created_at.desc()).first()
        old_session_id = old_run.session_id
        transition_run(db, old_run, "running")
        old_choice = create_prompt(db, old_run, kind="choice", question="old choice", options=["a"])
        connector = db.get(JarvisConnector, connector_id)
        old_generation = jarvis_discord._owner_generation(json_value(connector.config, dict))
        queued = append_event(
            db,
            old_run,
            "discord_notice_queued",
            source="discord",
            summary="old notice",
            data={
                "notice_key": f"prompt:{old_choice.id}",
                "owner_generation": old_generation,
                "channel_id": "dm-1",
            },
        )
        delivery, _created = jarvis_outbox.enqueue_delivery(
            db,
            old_run,
            channel="discord",
            privacy_level="summary",
            event_id=queued.id,
            connector_id=connector_id,
            idempotency_supported=True,
        )
        db.commit()
        old_choice_id = old_choice.id
        delivery_id = delivery.id
        db.close()

        regenerated = self.client.post(
            "/api/jarvis/discord/pairing-code", json={"revoke_owner": True}
        ).json()
        db = self.db()
        connector = db.get(JarvisConnector, connector_id)
        self.assertNotEqual(
            jarvis_discord._owner_generation(json_value(connector.config, dict)),
            old_generation,
        )
        self.assertEqual(db.get(JarvisDeliveryAttempt, delivery_id).state, "cancelled")
        db.close()

        self._message(
            connector_id,
            message_id="pair-new-owner",
            user_id="new-owner",
            content=f"pair {regenerated['pairing_code']}",
        )
        status = self._message(
            connector_id,
            message_id="new-owner-status",
            user_id="new-owner",
            content="status",
        )
        self.assertIn("No recent Aide work", status[0][1])
        answer = self._message(
            connector_id,
            message_id="new-owner-answer",
            user_id="new-owner",
            content=f"answer {old_choice_id} a",
        )
        self.assertIn("no longer available", answer[0][1])

        with mock.patch("services.jarvis_handoff.launch", return_value=True):
            self._message(
                connector_id,
                message_id="new-work",
                user_id="new-owner",
                content="start a separate conversation",
            )
        db = self.db()
        new_run = db.query(JarvisRun).order_by(JarvisRun.created_at.desc()).first()
        self.assertNotEqual(new_run.session_id, old_session_id)
        db.close()

        sender = mock.AsyncMock(return_value=("delivered", "unexpected-old-notice"))
        with mock.patch.object(jarvis_discord, "_api_create_message_result", new=sender):
            asyncio.run(jarvis_discord.deliver_notices(connector_id))
        sender.assert_not_awaited()

    def test_revoked_token_disables_reconnect_loop(self):
        connected = self._connect()
        asyncio.run(jarvis_discord._disable_revoked_token(connected["id"]))
        state = self.client.get("/api/jarvis/discord").json()
        self.assertFalse(state["enabled"])
        self.assertEqual(state["connection_state"], "token revoked")

    def test_notice_loop_retries_after_a_transient_failure(self):
        deliver = mock.AsyncMock(side_effect=[RuntimeError("temporary"), asyncio.CancelledError()])
        sleep = mock.AsyncMock()
        with (
            mock.patch.object(jarvis_discord, "deliver_notices", new=deliver),
            mock.patch.object(jarvis_discord.asyncio, "sleep", new=sleep),
            self.assertRaises(asyncio.CancelledError),
        ):
            asyncio.run(jarvis_discord._notice_loop("connector"))

        self.assertEqual(deliver.await_count, 2)
        sleep.assert_awaited_once_with(1.5)

    def test_heartbeat_fails_when_the_previous_send_is_not_acknowledged(self):
        websocket = mock.Mock()
        websocket.send = mock.AsyncMock()

        async def no_wait(_delay):
            return None

        with (
            mock.patch.object(jarvis_discord.random, "random", return_value=0),
            mock.patch.object(jarvis_discord.asyncio, "sleep", side_effect=no_wait),
            self.assertRaisesRegex(RuntimeError, "heartbeat_unacknowledged"),
        ):
            asyncio.run(
                jarvis_discord._heartbeat(
                    websocket,
                    0.0,
                    lambda: 42,
                    {
                        "acknowledged": True,
                        "deadline": 0.0,
                        "lock": asyncio.Lock(),
                    },
                )
            )

        websocket.send.assert_awaited_once()

    def test_immediate_heartbeat_resets_the_periodic_ack_deadline(self):
        websocket = mock.Mock()
        websocket.send = mock.AsyncMock()
        state = {
            "acknowledged": True,
            "deadline": 10.0,
            "lock": asyncio.Lock(),
        }
        with mock.patch.object(jarvis_discord, "monotonic", return_value=9.9):
            sent = asyncio.run(
                jarvis_discord._send_gateway_heartbeat(
                    websocket,
                    30.0,
                    lambda: 42,
                    state,
                    require_previous_ack=False,
                )
            )

        self.assertTrue(sent)
        self.assertFalse(state["acknowledged"])
        self.assertEqual(state["deadline"], 39.9)
        websocket.send.assert_awaited_once_with(json.dumps({"op": 1, "d": 42}))


class QuietHoursTest(ApiTest):
    def test_quiet_hours_are_saved_in_zero_padded_comparison_form(self):
        quiet = jarvis_discord._normalize_quiet_hours(
            {"enabled": True, "start": "7:00", "end": "8:00", "timezone": "UTC"}
        )
        self.assertEqual(quiet["start"], "07:00")
        self.assertEqual(quiet["end"], "08:00")
        self.assertTrue(
            jarvis_discord.in_quiet_hours(
                {"quiet_hours": quiet}, datetime(2026, 7, 14, 7, 30, tzinfo=UTC)
            )
        )

    def test_wraparound_quiet_hours(self):
        config = {
            "quiet_hours": {
                "enabled": True,
                "start": "23:00",
                "end": "07:00",
                "timezone": "UTC",
            }
        }
        self.assertTrue(
            jarvis_discord.in_quiet_hours(config, datetime(2026, 7, 14, 23, 30, tzinfo=UTC))
        )
        self.assertTrue(
            jarvis_discord.in_quiet_hours(config, datetime(2026, 7, 14, 6, 30, tzinfo=UTC))
        )
        self.assertFalse(
            jarvis_discord.in_quiet_hours(config, datetime(2026, 7, 14, 12, 0, tzinfo=UTC))
        )
