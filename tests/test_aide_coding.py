import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from uuid import uuid4

from sqlalchemy import text

from core.database import AideCodingRun, DshConnection
from services import aide_coding
from tests._client import ApiTest


class ContractFaithfulDshStub:
    """Loopback stub for the bridge routes, envelopes, and durable side effects."""

    def __init__(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _json(self, status, body):
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _drop(self):
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()

            def do_GET(self):
                stub.paths.append(self.path)
                if self.path == "/mobile/api/pair/payload":
                    self._json(200, {"v": 2, "h": [stub.base_url], "sid": "pair-session"})
                    return
                self._json(404, {"error": "not-found"})

            def do_POST(self):
                stub.paths.append(self.path)
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/mobile/api/pair/claim":
                    if body == {"sid": "pair-session", "code": "12345678"}:
                        self._json(200, {"ok": True, "token": stub.token})
                    else:
                        self._json(403, {"error": "wrong code"})
                    return
                prefix = "/mobile/api/proxy/"
                if not self.path.startswith(prefix):
                    self._json(404, {"error": "not-found"})
                    return
                if self.headers.get("authorization") != f"Bearer {stub.token}":
                    self._json(401, {"error": "unauthorized"})
                    return
                method = self.path.removeprefix(prefix)
                stub.calls.append({"method": method, "payload": body.get("payload") or {}})
                value = stub.call(method, body.get("payload") or {})
                if value is stub.DROP:
                    self._drop()
                    return
                result = value if value.get("ok") is False else {"ok": True, "value": value}
                self._json(
                    200,
                    {
                        "type": "server-response",
                        "rpcId": body.get("rpcId"),
                        "result": result,
                    },
                )

        self.DROP = object()
        self.token = "synthetic-test-token"
        self.mode = "normal"
        self.paths = []
        self.calls = []
        self.sessions = {}
        self.prompt_count = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, method, payload):
        if method == "host.describe":
            return {
                "version": "stub-0.2.0",
                "cwd": "/tmp/stub",
                "attachedSessions": sum(1 for item in self.sessions.values() if item["running"]),
                "home": "/tmp",
                "canOpenPath": False,
            }
        if method == "workspace.list":
            return {
                "items": [
                    {
                        "workspaceId": "workspace-1",
                        "path": "/tmp/alles-stub",
                        "title": "Alles stub",
                        "sessionIds": list(self.sessions),
                    }
                ],
                "archivedSessionIds": [],
            }
        if method == "session.create":
            session_id = payload["sessionId"]
            self.sessions.setdefault(
                session_id,
                {
                    "running": False,
                    "blank": True,
                    "events": [],
                    "workspace": payload["workspaceId"],
                },
            )
            return {"sessionId": session_id, "agentPreset": "default"}
        if method == "session.prompt":
            if self.mode == "prompt_business_error":
                return {
                    "ok": False,
                    "error": {"code": "agent-busy", "message": "busy", "details": {}},
                }
            session = self.sessions[payload["sessionId"]]
            self.prompt_count += 1
            session["blank"] = False
            session["running"] = True
            session["events"].extend(
                [
                    {"event": {"type": "user/message", "seq": 0, "time": 1, "data": {}}},
                    {"event": {"type": "turn/start", "seq": 1, "time": 2, "data": {}}},
                ]
            )
            if self.mode == "prompt_drop":
                self.mode = "normal"
                return self.DROP
            return {"accepted": True}
        if method == "session.list":
            return {
                "items": [
                    {
                        "sessionId": session_id,
                        "updatedAt": 1,
                        "running": session["running"],
                        "blank": session["blank"],
                        "cwd": "/tmp/alles-stub",
                    }
                    for session_id, session in self.sessions.items()
                ]
            }
        if method == "session.history":
            return {"events": list(self.sessions[payload["sessionId"]]["events"]), "hasMore": False}
        if method == "session.cancel":
            session = self.sessions[payload["sessionId"]]
            if self.mode == "cancel_pending":
                return {"accepted": True}
            session["running"] = False
            sequence = len(session["events"])
            session["events"].append(
                {
                    "event": {
                        "type": "turn/end",
                        "seq": sequence,
                        "time": 3,
                        "data": {
                            "turn": 1,
                            "reason": {"kind": "aborted", "reason": {"kind": "user"}},
                        },
                    }
                }
            )
            if self.mode == "cancel_drop":
                self.mode = "normal"
                return self.DROP
            return {"accepted": True}
        raise AssertionError(f"unexpected DSH method {method}")

    def complete(self, session_id, reason="completed"):
        session = self.sessions[session_id]
        session["running"] = False
        session["events"].append(
            {
                "event": {
                    "type": "turn/end",
                    "seq": len(session["events"]),
                    "time": 4,
                    "data": {"turn": 1, "reason": {"kind": reason}},
                }
            }
        )


class AideCodingLifecycleTest(ApiTest):
    def setUp(self):
        super().setUp()
        self.stub = ContractFaithfulDshStub()

    def tearDown(self):
        self.stub.close()
        super().tearDown()

    def pair(self):
        response = self.client.post(
            "/api/aide/coding/pair",
            json={"base_url": self.stub.base_url, "code": "12345678"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def start(self):
        run_id = str(uuid4())
        response = self.client.post(
            "/api/aide/coding/runs",
            json={
                "request_id": run_id,
                "workspace_id": "workspace-1",
                "workspace_path": "/tmp/alles-stub",
                "prompt": "Fix the lifecycle test and report the result.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return run_id, response.json()

    def test_pairing_and_rpc_use_actual_mobile_bridge_routes_and_encrypt_token(self):
        status = self.pair()
        self.assertTrue(status["available"])
        self.assertNotIn("token", status)
        workspaces = self.client.get("/api/aide/coding/workspaces")
        self.assertEqual(workspaces.status_code, 200, workspaces.text)
        self.assertEqual(workspaces.json()["items"][0]["workspace_id"], "workspace-1")
        self.assertIn("/mobile/api/pair/payload", self.stub.paths)
        self.assertIn("/mobile/api/pair/claim", self.stub.paths)
        self.assertIn("/mobile/api/proxy/host.describe", self.stub.paths)
        self.assertIn("/mobile/api/proxy/workspace.list", self.stub.paths)

        db = self.db()
        self.assertEqual(db.get(DshConnection, "default").token, self.stub.token)
        sealed = db.execute(
            text("SELECT token FROM dsh_connections WHERE id='default'")
        ).scalar_one()
        self.assertTrue(sealed.startswith("enc2:"))
        db.close()

    def test_successful_start_persists_intent_before_prompt_and_completes_on_refresh(self):
        self.pair()
        run_id, started = self.start()
        self.assertEqual(started["state"], "running")
        self.assertEqual(
            [call["method"] for call in self.stub.calls[-2:]],
            ["session.create", "session.prompt"],
        )
        self.assertEqual(self.stub.calls[-2]["payload"]["sessionId"], run_id)
        events = self.client.get(f"/api/aide/coding/runs/{run_id}/events").json()["items"]
        self.assertEqual(events[0]["kind"], "intent_saved")
        self.assertEqual(events[1]["kind"], "session_created")
        self.assertEqual(events[2]["kind"], "prompt_accepted")

        self.stub.complete(run_id)
        refreshed = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["state"], "succeeded")
        self.assertEqual(refreshed.json()["remote_events"][-1]["reason"], "completed")

    def test_ambiguous_prompt_is_never_retried_and_can_be_verified(self):
        self.pair()
        self.stub.mode = "prompt_drop"
        run_id, started = self.start()
        self.assertEqual(started["state"], "uncertain")
        self.assertEqual(self.stub.prompt_count, 1)

        refreshed = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["state"], "running")
        self.assertEqual(self.stub.prompt_count, 1)

    def test_rejected_prompt_stays_explicitly_recoverable(self):
        self.pair()
        self.stub.mode = "prompt_business_error"
        run_id, started = self.start()
        self.assertEqual(started["state"], "awaiting_prompt")
        self.assertIn("rejected", started["safe_error"].lower())
        self.stub.mode = "normal"
        resumed = self.client.post(f"/api/aide/coding/runs/{run_id}/resume")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["state"], "running")

    def test_ambiguous_cancel_requires_refresh_before_cancelled_receipt(self):
        self.pair()
        run_id, _started = self.start()
        self.stub.mode = "cancel_drop"
        cancelled = self.client.post(f"/api/aide/coding/runs/{run_id}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["state"], "uncertain")

        refreshed = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()["state"], "cancelled")

    def test_accepted_cancel_stays_pending_while_dsh_still_reports_active(self):
        self.pair()
        run_id, _started = self.start()
        self.stub.mode = "cancel_pending"
        cancelled = self.client.post(f"/api/aide/coding/runs/{run_id}/cancel")
        self.assertEqual(cancelled.json()["state"], "cancel_requested")
        refreshed = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(refreshed.json()["state"], "cancel_requested")
        self.assertNotEqual(refreshed.json()["state"], "cancelled")

    def test_disconnect_keeps_run_receipts(self):
        self.pair()
        run_id, _started = self.start()
        disconnected = self.client.delete("/api/aide/coding/connection")
        self.assertTrue(disconnected.json()["disconnected"])
        run = self.client.get(f"/api/aide/coding/runs/{run_id}")
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.json()["id"], run_id)

    def test_restart_marks_only_in_flight_outcomes_conservatively(self):
        db = self.db()
        rows = [
            AideCodingRun(
                id=str(uuid4()),
                workspace_id="workspace-1",
                provider_session_id=str(uuid4()),
                prompt="one",
                prompt_hash="one",
                state="running",
            ),
            AideCodingRun(
                id=str(uuid4()),
                workspace_id="workspace-1",
                provider_session_id=str(uuid4()),
                prompt="two",
                prompt_hash="two",
                state="cancel_requested",
            ),
            AideCodingRun(
                id=str(uuid4()),
                workspace_id="workspace-1",
                provider_session_id=str(uuid4()),
                prompt="three",
                prompt_hash="three",
                state="awaiting_prompt",
            ),
        ]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
        db.close()

        counts = aide_coding.reconcile_interrupted_runs()
        self.assertEqual(counts, {"interrupted": 1, "uncertain": 2})
        db = self.db()
        self.assertEqual(
            [db.get(AideCodingRun, rid).state for rid in ids],
            ["interrupted", "uncertain", "uncertain"],
        )
        db.close()

    def test_replay_rejects_a_different_workspace_path_or_conversation(self):
        self.pair()
        run_id, _ = self.start()
        response = self.client.post(
            "/api/aide/coding/runs",
            json={
                "request_id": run_id,
                "workspace_id": "workspace-1",
                "workspace_path": "/tmp/different",
                "prompt": "Fix the lifecycle test and report the result.",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stub.prompt_count, 1)

    def test_completed_receipt_survives_missing_session_and_transport_failure(self):
        self.pair()
        run_id, _ = self.start()
        self.stub.complete(run_id)
        response = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(response.json()["state"], "succeeded")
        self.stub.sessions.clear()
        response = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(response.json()["state"], "succeeded")
        from services.coding_backends.dsh import DshTransportError

        with mock.patch.object(
            aide_coding.DshBackend, "list_sessions", side_effect=DshTransportError("offline")
        ):
            response = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(response.json()["state"], "succeeded")
        self.assertEqual(response.json()["remote_events"][-1]["reason"], "completed")

    def test_older_running_refresh_cannot_replace_new_completion(self):
        self.pair()
        run_id, _ = self.start()

        async def scenario():
            first_waiting = asyncio.Event()
            release_first = asyncio.Event()
            count = 0

            async def history(_session_id):
                nonlocal count
                count += 1
                if count == 1:
                    first_waiting.set()
                    await release_first.wait()
                    return {"events": [{"event": {"type": "turn/start", "seq": 1, "data": {}}}]}
                return {
                    "events": [
                        {
                            "event": {
                                "type": "turn/end",
                                "seq": 2,
                                "data": {"reason": {"kind": "completed"}},
                            }
                        }
                    ]
                }

            backend = mock.Mock()
            backend.list_sessions = mock.AsyncMock(
                return_value={"items": [{"sessionId": run_id, "running": True}]}
            )
            backend.session_history = history
            first_db, second_db = self.db(), self.db()
            try:
                with mock.patch.object(aide_coding, "backend_for", return_value=backend):
                    first = asyncio.create_task(
                        aide_coding.refresh_run(first_db, first_db.get(AideCodingRun, run_id))
                    )
                    await first_waiting.wait()
                    self.assertFalse(first_db.in_transaction())
                    newer, _ = await aide_coding.refresh_run(
                        second_db, second_db.get(AideCodingRun, run_id)
                    )
                    self.assertEqual(newer.state, "succeeded")
                    release_first.set()
                    older, history_events = await first
                    self.assertEqual(older.state, "succeeded")
                    self.assertEqual(history_events[-1]["reason"], "completed")
            finally:
                first_db.close()
                second_db.close()

        asyncio.run(scenario())

    def test_output_and_diffs_survive_reload(self):
        self.pair()
        run_id, _ = self.start()
        self.stub.sessions[run_id]["events"].extend(
            [
                {
                    "event": {
                        "type": "assistant/message",
                        "seq": 2,
                        "data": {
                            "message": {
                                "content": [{"type": "text", "text": "fixed the synthetic test"}]
                            }
                        },
                    }
                },
                {
                    "event": {"type": "tool/result", "seq": 3, "data": {}},
                    "view": {
                        "for": "result",
                        "view": {
                            "card": "diff",
                            "title": "updated test",
                            "diffs": [{"path": "test.py", "oldText": "old", "newText": "new"}],
                        },
                    },
                },
            ]
        )
        self.stub.complete(run_id)
        self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        saved = self.client.get(f"/api/aide/coding/runs/{run_id}/events").json()["remote_events"]
        self.assertEqual(saved[2]["text"], "fixed the synthetic test")
        self.assertEqual(saved[3]["diffs"][0]["newText"], "new")

    def test_followup_reuses_session_once_and_ignores_previous_completion(self):
        self.pair()
        run_id, _ = self.start()
        self.stub.complete(run_id)
        self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        body = {"request_id": str(uuid4()), "prompt": "now check the edge case"}
        response = self.client.post(f"/api/aide/coding/runs/{run_id}/continue", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "running")
        self.assertEqual(len(self.stub.sessions), 1)
        self.assertEqual(self.stub.prompt_count, 2)
        self.assertEqual(self.stub.calls[-1]["payload"]["content"][0]["text"], body["prompt"])
        replay = self.client.post(f"/api/aide/coding/runs/{run_id}/continue", json=body)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(self.stub.prompt_count, 2)
        refreshed = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(refreshed.json()["state"], "running")
        self.stub.complete(run_id)
        refreshed = self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        self.assertEqual(refreshed.json()["state"], "succeeded")
        self.assertEqual(self.stub.prompt_count, 2)

    def test_followup_response_loss_is_replayed_without_another_prompt(self):
        self.pair()
        run_id, _ = self.start()
        self.stub.complete(run_id)
        self.client.post(f"/api/aide/coding/runs/{run_id}/refresh")
        body = {"request_id": str(uuid4()), "prompt": "continue exactly once"}
        self.stub.mode = "prompt_drop"
        response = self.client.post(f"/api/aide/coding/runs/{run_id}/continue", json=body)
        self.assertEqual(response.json()["state"], "uncertain")
        replay = self.client.post(f"/api/aide/coding/runs/{run_id}/continue", json=body)
        self.assertEqual(replay.json()["state"], "uncertain")
        self.assertEqual(self.stub.prompt_count, 2)
        conflict = self.client.post(
            f"/api/aide/coding/runs/{run_id}/continue", json={**body, "prompt": "different"}
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.stub.prompt_count, 2)

    def test_duplicate_insert_race_replays_the_committed_owner(self):
        self.pair()
        run_id, _ = self.start()
        db = self.db()
        get = db.get
        skipped = False

        def stale_once(model, identity, *args, **kwargs):
            nonlocal skipped
            if model is AideCodingRun and identity == run_id and not skipped:
                skipped = True
                return None
            return get(model, identity, *args, **kwargs)

        try:
            with mock.patch.object(db, "get", side_effect=stale_once):
                run, created = asyncio.run(
                    aide_coding.start_run(
                        db,
                        run_id=run_id,
                        aide_session_id=None,
                        workspace_id="workspace-1",
                        workspace_path="/tmp/alles-stub",
                        prompt="Fix the lifecycle test and report the result.",
                    )
                )
            self.assertEqual(run.id, run_id)
            self.assertFalse(created)
            self.assertEqual(self.stub.prompt_count, 1)
        finally:
            db.close()

    def test_unconfigured_start_gets_a_definite_failure_receipt(self):
        run_id = str(uuid4())
        response = self.client.post(
            "/api/aide/coding/runs",
            json={
                "request_id": run_id,
                "workspace_id": "workspace-1",
                "prompt": "no connection available",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "failed")
        self.assertEqual(response.json()["error_code"], "dsh_bridge_unconfigured")
