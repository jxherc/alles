"""Pending DSH interactions use the documented mux and respond carriers."""

import asyncio
import json
import threading
import unittest
from unittest import mock

import httpx
from websockets.sync.server import serve

from core.database import AideCodingRun
from services.coding_backends.dsh import (
    DshBackend,
    DshProtocolError,
    DshTransportError,
    _answer_result,
)
from tests._client import ApiTest


def frame(kind, *, rpc_id="pending-1", session="owned-session", **payload):
    return {
        "type": "server-request",
        "rpcId": rpc_id,
        "method": kind,
        "payload": {"type": kind, "sessionId": session, **payload},
    }


APPROVAL = frame(
    "approval/requested", approvalId="approval-1", toolName="bash", reason="run the test"
)
QUESTION = frame(
    "question/requested",
    questions=[
        {
            "id": "choice",
            "question": "which change?",
            "options": [{"label": "small"}, {"label": "full"}],
        }
    ],
)


class MuxStub:
    def __init__(self, frames):
        self.requests = []
        self.frames = frames

        def handle(connection):
            self.requests.append(
                {
                    "path": connection.request.path,
                    "authorization": connection.request.headers.get("Authorization"),
                }
            )
            for item in self.frames:
                connection.send(json.dumps(item))

        self.server = serve(handle, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.socket.getsockname()[1]}"

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=2)


class DshResponseContractTests(unittest.TestCase):
    def backend(self, frames):
        stub = MuxStub(frames)
        self.addCleanup(stub.close)
        return DshBackend(base_url=stub.base, token="synthetic-token"), stub

    def test_mux_uses_authenticated_proxy_and_filters_other_sessions(self):
        backend, stub = self.backend(
            [frame("approval/requested", session="other", approvalId="other"), APPROVAL]
        )

        async def collect():
            return [item async for item in backend.live_events("owned-session")]

        self.assertEqual(asyncio.run(collect()), [APPROVAL])
        self.assertEqual(
            stub.requests,
            [{"path": "/mobile/api/proxy/events.mux", "authorization": "Bearer synthetic-token"}],
        )

    def test_approval_reuses_stable_rpc_and_host_owned_approval_id(self):
        backend, stub = self.backend([APPROVAL])
        with mock.patch(
            "services.coding_backends.dsh.httpx.AsyncClient.post",
            new=mock.AsyncMock(return_value=httpx.Response(200, json={"accepted": True})),
        ) as post:
            receipt = asyncio.run(
                backend.respond("owned-session", "pending-1", outcome="allowed-once")
            )
        self.assertEqual(receipt, {"accepted": True})
        self.assertEqual(post.call_args.args, (stub.base + "/mobile/api/proxy/respond",))
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "type": "client-response",
                "rpcId": "pending-1",
                "result": {
                    "ok": True,
                    "value": {
                        "sessionId": "owned-session",
                        "approvalId": "approval-1",
                        "outcome": "allowed-once",
                    },
                },
            },
        )

    def test_response_cannot_target_another_sessions_pending_request(self):
        backend, _ = self.backend(
            [frame("approval/requested", session="other", approvalId="other")]
        )
        with mock.patch(
            "services.coding_backends.dsh.httpx.AsyncClient.post", new_callable=mock.AsyncMock
        ) as post:
            with self.assertRaises(DshTransportError):
                asyncio.run(backend.respond("owned-session", "pending-1", outcome="allowed-once"))
        post.assert_not_awaited()

    def test_resolved_elsewhere_receipt_is_preserved_without_replaying(self):
        backend, _ = self.backend([APPROVAL])
        with mock.patch(
            "services.coding_backends.dsh.httpx.AsyncClient.post",
            new=mock.AsyncMock(
                return_value=httpx.Response(200, json={"accepted": False, "reason": "not-pending"})
            ),
        ) as post:
            receipt = asyncio.run(backend.respond("owned-session", "pending-1", outcome="rejected"))
        self.assertEqual(receipt, {"accepted": False, "reason": "not-pending"})
        post.assert_awaited_once()

    def test_question_selection_and_custom_answers_keep_question_order(self):
        result = _answer_result(QUESTION, answers=[{"id": "choice", "selected": ["small"]}])
        self.assertEqual(
            result["value"]["answer"]["answers"], [{"id": "choice", "selected": ["small"]}]
        )
        custom = _answer_result(
            QUESTION, answers=[{"id": "choice", "selected": [], "custom": "keep it as it is"}]
        )
        self.assertEqual(custom["value"]["answer"]["answers"][0]["custom"], "keep it as it is")
        multi = frame(
            "question/requested",
            questions=[
                {
                    "id": "choice",
                    "question": "which?",
                    "multiSelect": True,
                    "options": [{"label": "small"}, {"label": "full"}],
                }
            ],
        )
        self.assertEqual(
            _answer_result(multi, answers=[{"id": "choice", "selected": ["small", "full"]}])[
                "value"
            ]["sessionId"],
            "owned-session",
        )

    def test_question_rejects_wrong_ids_unknown_duplicate_and_mixed_answers(self):
        for answer in [
            {"id": "wrong", "selected": ["small"]},
            {"id": "choice", "selected": ["invented"]},
            {"id": "choice", "selected": ["small", "small"]},
            {"id": "choice", "selected": ["small", "full"]},
            {"id": "choice", "selected": ["small"], "custom": "mixed"},
            {"id": "choice", "selected": [], "custom": " "},
            {"id": "choice", "selected": []},
        ]:
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                _answer_result(QUESTION, answers=[answer])

    def test_question_cancel_uses_cancelled_error_and_cannot_approve(self):
        self.assertEqual(_answer_result(QUESTION, cancelled=True)["error"]["code"], "cancelled")
        with self.assertRaises(ValueError):
            _answer_result(APPROVAL, cancelled=True)
        with self.assertRaises(ValueError):
            _answer_result(QUESTION, outcome="allowed-once")

    def test_lost_answer_receipt_is_unknown_and_never_retried(self):
        backend, _ = self.backend([APPROVAL])
        with mock.patch(
            "services.coding_backends.dsh.httpx.AsyncClient.post",
            new=mock.AsyncMock(side_effect=httpx.ReadError("synthetic lost response")),
        ) as post:
            with self.assertRaisesRegex(DshTransportError, "outcome_unknown"):
                asyncio.run(backend.respond("owned-session", "pending-1", outcome="rejected"))
        post.assert_awaited_once()

    def test_malformed_mux_or_receipt_is_not_accepted(self):
        backend, _ = self.backend([{**APPROVAL, "method": "not-matching"}])

        async def read():
            return [item async for item in backend.live_events("owned-session")]

        with self.assertRaises(DshProtocolError):
            asyncio.run(read())
        backend, _ = self.backend([APPROVAL])
        with mock.patch(
            "services.coding_backends.dsh.httpx.AsyncClient.post",
            new=mock.AsyncMock(return_value=httpx.Response(200, json={"accepted": "true"})),
        ):
            with self.assertRaises(DshProtocolError):
                asyncio.run(backend.respond("owned-session", "pending-1", outcome="rejected"))


class AideCodingResponseRouteTests(ApiTest):
    def setUp(self):
        super().setUp()
        with self.db() as db:
            db.add(
                AideCodingRun(
                    id="owned-run",
                    provider_session_id="owned-session",
                    workspace_id="owned-workspace",
                    prompt="synthetic request",
                    prompt_hash="fixture",
                    state="running",
                )
            )
            db.commit()
        self.backend = DshBackend(base_url="http://127.0.0.1:1", token="synthetic-token")
        self.patch = mock.patch("services.aide_coding.backend_for", return_value=self.backend)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_live_endpoint_streams_selected_run_frames(self):
        async def frames(session):
            self.assertEqual(session, "owned-session")
            yield APPROVAL

        with mock.patch.object(self.backend, "live_events", frames):
            response = self.client.get("/api/aide/coding/runs/owned-run/live")
        self.assertEqual(response.status_code, 200)
        self.assertIn('"rpcId":"pending-1"', response.text)
        self.assertNotIn("synthetic-token", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_response_route_binds_session_and_drops_no_user_answers(self):
        with mock.patch.object(
            self.backend, "respond", new=mock.AsyncMock(return_value={"accepted": True})
        ) as respond:
            response = self.client.post(
                "/api/aide/coding/runs/owned-run/respond",
                json={"rpc_id": "pending-1", "answers": [{"id": "choice", "selected": ["small"]}]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(respond.call_args.args, ("owned-session", "pending-1"))
        self.assertEqual(
            respond.call_args.kwargs["answers"], [{"id": "choice", "selected": ["small"]}]
        )
        injected = self.client.post(
            "/api/aide/coding/runs/owned-run/respond",
            json={"rpc_id": "pending-1", "session_id": "other", "outcome": "allowed-once"},
        )
        self.assertEqual(injected.status_code, 422)

    def test_stream_failure_exposes_recovery_event_and_safe_error(self):
        async def frames(_session):
            raise DshTransportError("dsh_bridge_stream_unavailable")
            yield

        with mock.patch.object(self.backend, "live_events", frames):
            response = self.client.get("/api/aide/coding/runs/owned-run/live")
        self.assertIn("event: bridge-error", response.text)
        self.assertIn("reconnect and refresh", response.text)
